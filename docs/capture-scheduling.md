# Capture scheduling

The six capture workers use **history-based adaptive scheduling**: one complete
capture measures work, and later runs use that feedback to rebalance it. This is
the same broad pattern as [timing-based test splitting](https://circleci.com/docs/guides/optimize/parallelism-faster-jobs/).
The planner combines a bounded PID runtime predictor with discrete local search
on the variance of predicted shard loads.

## Contents

- [Pipeline and artifact flow](#pipeline-and-artifact-flow)
- [Objective](#objective)
- [First run and feedback](#first-run-and-feedback)
- [Bounded PID feedback](#bounded-pid-feedback)
- [Progressive granularity](#progressive-granularity)
- [Cross-run storage](#cross-run-storage)
- [Worked examples and validation](#worked-examples-and-validation)

## Pipeline and artifact flow

The [entry workflow](../.github/workflows/ci.yml) resolves one source SHA, then
starts source-only tests, security scans, documentation checks, browser fixture
tests, package/container builds, and eligible live capture independently.
Ordinary non-refresh builds use committed profile inputs. Requested refreshes
must succeed; they cannot silently fall back to an older profile.

| Stage | Inputs and responsibility | Output and failure behavior |
| --- | --- | --- |
| Bootstrap | Restore compatible encrypted timing feedback and the configured browser's encrypted session; authenticate and discover the current overview/routes. | One immutable plan with capture ID, unit ownership, cost predictions, and controller state. Missing feedback starts cold; missing profile data fails capture. |
| Six parallel workers | Restore independent copies of that browser session and execute only assigned units. | One shard artifact each, including empty workers, with captured sections/tab units and measured durations. Workers never update the shared session cache. |
| Fan-in | Validate capture ID, browser, worker indices, and exact unit coverage; merge tabs, preserve source order, cache media, and validate the fresh profile. | Accepted profile artifact. No incomplete worker output trains the next run or replaces the accepted profile. |
| Feedback publication | Update runtime estimates and bounded controller state from the accepted capture, then encrypt it. | A timing artifact for a later run. It becomes usable after successful capture even if a downstream PDF or release stage later fails. |
| Build and publish | Consume that run's accepted profile, optional summaries, and immutable source revision. | Validation gates publication; tags sign/release the fresh PDF. PDF, main-branch, and Pages publication follow their existing gates. |

Feedback is a dependency between successive runs, not a dependency cycle within
one workflow. See the [complete pipeline graph](automation.md#linkedin-capture-sharding-algorithm)
for build, test, release, and publication branches.

## Objective

Let `m = 6`, let `c_j` be unit `j`'s predicted traversal time in seconds, and let
`S_i` be the units assigned to shard `i`. Every unit belongs to exactly one shard.
Empty shards have load zero. These are population statistics over all six shards:

```math
L_i = \sum_{j\in S_i} c_j,\qquad
\mu = \frac{1}{m}\sum_{i=1}^{m} L_i,\qquad
D = \sum_{i=1}^{m}(L_i-\mu)^2,\qquad
V = \frac{D}{m},\qquad \sigma = \sqrt{V}.
```

The objective is to reduce `V`, equivalently `D` or `sigma`. Moving fixed work
between shards preserves the mean within that planning pass. The mean may change
between runs as observations, profiles, or traversal granularity change. No
Gaussian distribution is assumed, and the scheduler adds no artificial delay.

For a move or swap from shard `a` to shard `b`, let `x` be the net transferred
cost: the departing unit's cost minus the returning unit's cost, with a missing
unit contributing zero. Only two loads change. Expanding their squares gives:

```math
\begin{aligned}
L_a' &= L_a-x, & L_b' &= L_b+x,\\
G &= (L_a^2+L_b^2)-\bigl((L_a-x)^2+(L_b+x)^2\bigr)\\
  &= 2x(L_a-L_b-x),\\
D' &= D-G, & V' &= V-\frac{G}{m}.
\end{aligned}
```

`G` is a reduction in the **sum of squared deviations**, not in standard
deviation directly. For a fractional standard-deviation improvement `h = 0.05`,
the acceptance test is derived by squaring both nonnegative sides:

```math
\sigma' < (1-h)\sigma
\quad\Longleftrightarrow\quad
G > \bigl(1-(1-h)^2\bigr)D = 0.0975D.
```

The implementation requires `G > max(epsilon, 0.0975 * D)`, where `epsilon` is
`1e-12 * max(1, sum(L_i**2))` using numeric values expressed in seconds. This
numerical tolerance has the same squared-second scale as `G`. It also requires
that the largest predicted shard load does not increase. Thus a 5% decrease in
variance alone would be insufficient: the threshold concerns standard deviation.

This is a [multi-way number partitioning](https://research.google/pubs/optimal-multi-way-number-partitioning/)
problem with a variance objective. We use bounded move/swap local search rather
than claim a globally optimal partition. Each accepted change reduces predicted
standard deviation by more than 5% and cannot increase the slowest predicted
shard. At most two units migrate per run; a swap counts as two migrations.

## First run and feedback

Without compatible history, keep the original size-based distribution. Each
whole section receives `max(1, 2 * entry_count + text_characters // 500 + 1)` from
its overview. Sections without previews use `max(1, title_length // 80 + 1)`;
contact uses `1`. [Longest Processing Time first (LPT)](https://doi.org/10.1137/0117039)
orders these estimates from largest to smallest and assigns each to the least
loaded shard. Route-key and shard-number ties are deterministic.

Workers measure each traversal with a monotonic clock, including navigation,
expansion, pagination, parsing, and in-process retries. Browser startup, initial
session checks, and cleanup are reported separately in total worker duration.
GitHub queue time and dependency installation are outside the scheduler's cost
model. A failed worker attempt does not supply partial training data.

After all six results pass aggregation and profile validation, the latest
measurements replace local `.cache/capture/timings.json`. Established units retain
their previous shard as the starting assignment. New units go to the least-loaded
worker. Local search then makes only worthwhile, bounded changes. The resulting
estimates and controller state are frozen in the shared plan, so workers and
fan-in compute exactly the same assignment even if another run completes.

Aggregation logs predicted and observed seconds per shard, prediction error,
mean, population standard deviation, and maximum traversal time. These are
measurements and predictions, not a guarantee of equal wall-clock completion.

## Bounded PID feedback

Each completed run is one discrete controller step, with a normalized interval
of one run. This is a PID-based predictor correction, not a continuous-time plant
controller or a claim of tuned closed-loop stability. State is per unit: positive
prediction `p_t`, previous stored error `E_(t-1)`, integral `I_(t-1)`, and previous
worker assignment. Let `y_t` be this run's observed traversal seconds, and define:

```math
\operatorname{clip}(z,a,b)=\min(b,\max(a,z)),\qquad e_t=y_t-p_t.
```

All errors, predictions, and corrections below are in seconds; the normalized
run interval makes the gains dimensionless. A new unit is seeded from its first
observation with stored error and integral zero. Existing units inside the 5%
deadband keep their estimate and clear error state:

```math
|e_t|\le 0.05p_t
\quad\Longrightarrow\quad
(p_{t+1},E_t,I_t)=(p_t,0,0).
```

Otherwise, first compute a trial integral and correction:

```math
\begin{aligned}
K_P &= 0.5, & K_I &= 0.05, & K_D &= 0.1, & \alpha &= 0.25,\\
I_t^* &= \operatorname{clip}(I_{t-1}+e_t,-p_t,p_t),\\
u_t^* &= K_P e_t + K_I I_t^* + K_D(e_t-E_{t-1}).
\end{aligned}
```

Conditional integration prevents windup: if the trial correction is saturated
and points in the same direction as the error, reuse the previous integral.
Then recompute the correction and bound its effect on the estimate:

```math
\begin{aligned}
J_t &= \begin{cases}
I_{t-1}, & |u_t^*|>\alpha p_t\ \text{and}\ u_t^*e_t>0,\\
I_t^*, & \text{otherwise},
\end{cases}\\
u_t &= K_P e_t + K_I J_t + K_D(e_t-E_{t-1}),\\
p_{t+1} &= p_t + \operatorname{clip}(u_t,-\alpha p_t,\alpha p_t),\\
E_t &= e_t,\qquad I_t=\operatorname{clip}(J_t,-p_{t+1},p_{t+1}).
\end{aligned}
```

For established units this guarantees a positive, bounded next estimate:

```math
0.75p_t\le p_{t+1}\le1.25p_t.
```

Assignment hysteresis and the two-migration budget are separate from this
controller. If the previous assignments remain balanced, updated predictions
need not move any work.

These conservative constants live in [`capture/feedback.py`](../pkg/resumeme/linkedin/capture/feedback.py) and
[`capture/scheduling.py`](../pkg/resumeme/linkedin/capture/scheduling.py). They are initial engineering defaults, not gains tuned
against a live production benchmark. The controller estimates runtime; it does
not delay a fast worker to manufacture a lower variance.

## Progressive granularity

Start with whole sections. If the rebalanced plan still has a coefficient of
variation (`stddev / mean`) above 15%, inspect at most one additional supported
bottleneck section per run. It must exceed both 30 estimated seconds and 125% of
the mean shard load. Refinement stops at 36 traversal units.

```math
\mu>0,\qquad \frac{\sigma}{\mu}>0.15,\qquad
c_j>\max(30\,\mathrm{s},1.25\mu).
```

The ratio is evaluated only when the mean is positive. These conditions select
a candidate for supported, bounded discovery; they do not make arbitrary browser
states independently replayable.

The first supported refinement is a dedicated Recommendations or Interests
page's independently selectable tabs. Bootstrap discovers their labels; workers
reopen the same owner-scoped page, select their assigned tab, and fully traverse
it. Labels are rediscovered on later runs. Stable unit IDs include a digest of
the label and are independent of the chosen worker. Previously split sections
remain split when those tabs still exist.

For a newly split section, divide the parent's prediction among its tabs until
individual timings arrive. For other unseen units, use the median observed
seconds per size-weight to estimate a cost in seconds. Removed units and their
controller state disappear from the next complete timing snapshot.

Fan-in requires every planned unit exactly once, including all empty workers.
It reassembles tabs in discovery order into one parent section and restores the
profile's source order. Missing tabs fail collection rather than drop content.

| Traversal unit | Current scheduling support | Requirement for finer partitioning |
| --- | --- | --- |
| Whole detail section or contact overlay | Implemented | Already independently navigable. |
| Recommendations/Interests detail tab | Implemented, incremental | Live tab discovery and complete per-tab output. |
| Inline profile-card tab | Cataloged | A tab can reveal a dedicated detail route; ownership must be reconciled before splitting. |
| Numbered detail page | Cataloged | Require a stable, independently replayable page URL or cursor and proof of complete coverage. Current Next-button traversal stays sequential. |
| Skill category or endorsement detail | Cataloged | Verify disjoint content and stable IDs before separating overlapping filters or dialogs. |
| Company, role, or project card | Cataloged | Require independent navigation; slicing rendered cards duplicates scrolling and may lose virtualized content. |
| Infinite-scroll batch | Sequential | Browser state and dynamically discovered boundaries prevent safe independent replay. |

## Cross-run storage

Ordinary [Actions caches cannot cross sibling tags](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching#restrictions-for-accessing-a-cache).
CI therefore restores the latest nonexpired matching **encrypted timing
artifact** from another run, using the GitHub artifact API with `actions: read`.
Feedback is uploaded only after capture succeeds; an unrelated later build
failure does not invalidate it. Each artifact expires after 90 days, subject to
repository limits. The consumer reads only the latest compatible artifact;
GitHub may retain older encrypted artifacts until their retention expires.

The artifact is scoped to the repository, profile owner, browser/capture settings,
runner selection, and dedicated cache-key fingerprint. It contains durations,
unit identifiers, and bounded controller state, not profile prose or browser
credentials. Encryption and authentication reuse the dedicated session-cache
keys; rotating them starts a new timing history. Invalid or unavailable feedback
falls back to the original algorithm. No additional secret is required.

See [data handling](data-handling.md) for storage boundaries and
[CLI reference](CLI.md#ci-capture-fan-out-and-fan-in) for local timing paths.

## Worked examples and validation

These Python examples run in pre-commit through `doctest`. In the move example,
shifting a ten-second unit from a 120-second shard to an 80-second shard preserves
the 100-second mean and halves standard deviation:

```pycon
>>> from fractions import Fraction
>>> from statistics import mean, pvariance
>>> before = [120, 80, 100, 100, 100, 100]
>>> after = [110, 90, 100, 100, 100, 100]
>>> mean(before), mean(after)
(100, 100)
>>> gain = 2 * 10 * (120 - 80 - 10)
>>> gain
600
>>> Fraction(gain, 6) == pvariance(map(Fraction, before)) - pvariance(map(Fraction, after))
True
>>> Fraction(1) - (Fraction(1) - Fraction(5, 100)) ** 2
Fraction(39, 400)
>>> pvariance(after) / pvariance(before)
0.25

```

The predictor examples exercise the production function, including deadband,
PID correction, and saturation without integral windup:

```pycon
>>> from resumeme.linkedin.capture.feedback import TimingFeedback, update_feedback
>>> initial = TimingFeedback(100.0, 0.0, 0.0, 2)
>>> update_feedback(initial, 104.0, 2)
TimingFeedback(estimate=100.0, error=0.0, integral=0.0, shard=2)
>>> update_feedback(initial, 120.0, 2)
TimingFeedback(estimate=113.0, error=20.0, integral=20.0, shard=2)
>>> update_feedback(initial, 10000.0, 2)
TimingFeedback(estimate=125.0, error=9900.0, integral=0.0, shard=2)

```

The `document-math` pre-commit hook parses Markdown math with remark and validates
each expression with KaTeX in strict mode. It covers inline dollar math, display
math, and GitHub `math` fences while ignoring ordinary code examples. It also
rejects unclosed display/fenced blocks and executes the examples above. CI runs
the same hook in its existing checks job. Property tests separately cover work
conservation, nonincreasing variance/makespan, and migration limits.

Syntax validation cannot prove arbitrary mathematical claims. Review changes to
definitions and derivations, and update executable examples and property tests
when changing the objective or controller. See [development checks](development.md#document-checks).
