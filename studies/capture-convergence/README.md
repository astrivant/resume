# Faster capture convergence

The production scheduler now permits **two to six migrations per capture**,
depending on predicted imbalance. It keeps the existing PID runtime estimator
and returns to the two-migration limit near balance. In the paired synthetic
startup experiment, the median number of correction runs to reach the 15% CV
target falls from four to two. This is a simulation result, not a measured CI
speedup. No LinkedIn account or live capture is used by this study.

## Contents

- [Reproduce](#reproduce)
- [Why not a PID controlling PID gains?](#why-not-a-pid-controlling-pid-gains)
- [Scheduling rule and guarantees](#scheduling-rule-and-guarantees)
- [Gradient descent and machine learning](#gradient-descent-and-machine-learning)
- [Experiment](#experiment)
- [Results and interpretation](#results-and-interpretation)
- [Automatic capacity and useful turnover](#automatic-capacity-and-useful-turnover)
- [Executable mathematics](#executable-mathematics)
- [Sources and next evidence](#sources-and-next-evidence)

## Reproduce

Use the project's installed Poetry environment and committed lockfile. Matplotlib
is already installed through the word-cloud dependency; no new ML dependency is
needed. From the repository root:

```bash
MPLCONFIGDIR=.cache/matplotlib poetry run python -m scripts.studies.capture_convergence
```

The command regenerates `convergence.svg`, `tradeoffs.svg`, `capacity.svg`, JSON summaries, and
`RESULTS.md` here. Detailed synthetic traces and PNG previews go to the ignored
`.cache/studies/capture-convergence/` directory. `--output` and `--raw-output`
override those destinations. The fixed experiment covers seeds 0 through 11,
five scenarios, five policies, and 24 runs per trial: 7,200 fixed-count run observations. A second comparison covers three capacity
scenarios, two policies, 12 seeds, and 24 captures: another 1,728 observations.
The JSON records source hashes and the Matplotlib version for reproduction.

Source: [simulation](../../scripts/studies/capture_convergence/simulation.py),
[reporting](../../scripts/studies/capture_convergence/report.py), and
[production scheduler](../../pkg/resumeme/linkedin/capture/scheduling.py).
The simulator calls the production move/swap search and PID update. It retains
assignments between runs, just as the real scheduler does. All simulated routes
are independently traversable; this experiment holds their granularity fixed.

## Why not a PID controlling PID gains?

The existing pipeline has two different constraints:

1. The predictor estimates seconds per traversal unit. New units take their first
   measurement directly. Established predictions have a 5% deadband, bounded
   integral, and a 25% change limit per completed run.
2. The scheduler previously allowed only two unit migrations per run, even when
   its predictions were accurate and the initial placement was badly imbalanced.

Increasing predictor gains cannot bypass either an explicit output clamp or a
separate assignment budget. A secondary controller might help tune a measured
system, but here there is no identified response model linking three predictor
gains to discrete assignment changes. Both loops would receive just one new
sample per capture. Conventional cascade tuning depends on a faster inner loop;
that assumption is absent here. This is a design judgment, not a proof that every
adaptive controller would fail.

We compare a bounded **outer PID controlling the migration budget** as an
experimental alternative. It does not retune the inner PID's gains. It adds
integral/derivative state but shows no median startup-target advantage over the
stateless adaptive budget in this experiment. A literal online gain tuner is
therefore deferred, rather than presented as an implemented feature.

```mermaid
flowchart LR
    timings[Last complete traversal timings] --> predictor[Bounded per-unit PID]
    predictor --> loads[Predicted loads on previous assignment]
    loads --> dispersion[Coefficient of variation]
    dispersion --> budget[Adaptive budget: 2 to 6]
    loads --> search[Deterministic move / swap search]
    budget --> search
    search --> freeze[Freeze plan]
    freeze --> workers[Six parallel capture workers]
    workers --> validate[Validate complete fan-in]
    validate --> timings
```

That feedback edge connects successive pipeline runs. No running browser is
migrated, and incomplete captures never train the next plan.

## Scheduling rule and guarantees

Let `L_i` be predicted seconds on worker `i`, with all `m = 6` workers included.
Use population statistics, not a sample standard deviation:

```math
\mu=\frac{1}{m}\sum_i L_i,\qquad
V=\frac{1}{m}\sum_i(L_i-\mu)^2,\qquad
c=\begin{cases}\sqrt{V}/\mu,&\mu>0,\\0,&\mu=0.\end{cases}
```

Normalize dispersion above the target and choose the migration allowance:

```math
a=\operatorname{clip}\left(\frac{c-0.15}{0.60-0.15},0,1\right),\qquad
B=2+\lceil4a\rceil,\qquad 2\le B\le6.
```

The 15% threshold matches the existing refinement target. The 60% full-budget
threshold and six-unit cap are engineering choices, not statistically fitted
optima. They make the correction stronger during large errors while preserving
the prior allowance near balance. Uniform scaling of all durations leaves this
policy unchanged. The budget is chosen once per planning pass and is not a quota:
the planner stops when no qualifying move remains. A swap consumes two units.
Within the 15% target, a change must also save at least 3% of the predicted
makespan and at least two seconds. Thus useful time savings remain possible,
while small variance-only improvements no longer cause continuous reassignment.

Every accepted exchange still satisfies the existing acceptance tests. For a net
transfer `x` from worker `a` to worker `b`, define the squared-deviation reduction:

```math
G=2x(L_a-L_b-x),\qquad
V'=V-\frac{G}{m},\qquad
G>\max(\epsilon,0.0975mV),\qquad
\max_i L_i'\le\max_i L_i.
```

Here `epsilon = 1e-12 * max(1, sum(L_i**2))`, with durations in seconds. Total
work and the mean are conserved within the pass. The factor 0.0975 comes from
requiring a reduction of more than 5% in standard deviation, not in variance:

```math
0.0975=1-0.95^2,\qquad
\sigma_k<0.95^k\sigma_0
\quad\text{after }k\text{ accepted exchanges, for }k\ge1.
```

With fixed costs, strict descent and finitely many assignments prevent a cycle.
This is not a guarantee of a global optimum or a fixed number of pipeline runs.
An indivisible unit, the improvement threshold, or a local minimum may stop
progress. With noisy or changing costs, predicted improvement need not be an
observed improvement, so the plots report actual simulated observations too.

The experimental outer PID uses the same normalized `a`, previous error `a_prev`,
and an integral clamped to `[0, 1]`. Its trial effort is
`a + 0.2 * integral + 0.1 * (a - a_prev)`. If that effort exceeds one, integration
is held and effort recomputed. The resulting budget is `2 + ceil(4 * clip(effort,
0, 1))`; reaching the target resets both states. These gains are an illustrative
bounded candidate, not a search over optimal controllers.

## Gradient descent and machine learning

For one unit's prediction `p` and observed duration `y`, squared-error learning
needs no external training framework:

```math
\ell(p;y)=\frac12(p-y)^2,\qquad
\nabla_p\ell=p-y,\qquad
p'=p-\eta(p-y)=p+\eta(y-p).
```

With `eta = 0.5`, this is exponential smoothing, or a stochastic gradient update
on a noisy observation. The comparison keeps the PID's 5% deadband and 25% slew
limits, making the update projected onto `[0.75p, 1.25p]`. For a constant target
outside those nonlinear limits, unconstrained error contracts by `1 - eta`.
No claim of that rate is made for clipped updates or changing observations.

Simply importing an optimizer would not remove the migration cap or discover
independent traversal units. A learned predictor using section type, entry count,
and retry history could help when sufficient representative timing data exists.
That requires a dataset and evaluation against this simple baseline first.

The slew limit itself supplies a lower bound for sustained growth in an
established unit's runtime:

```math
p_k\le1.25^k p_0,\qquad
k\ge\left\lceil\frac{\log r}{\log1.25}\right\rceil
\quad\text{to reach }p_k\ge r p_0,\quad r>1.
```

For a fourfold change, reaching the full new level requires at least seven
updates, irrespective of larger PID gains. New units are seeded directly and
do not have this startup penalty. A future change detector could distinguish
persistent growth from isolated retries before temporarily relaxing the clamp;
this study does not implement one.

## Experiment

Every policy receives identical route costs for a given scenario, seed, and run.
Planning uses only previous observations. Run zero uses size-based LPT, and its
measurements become available to the next plan. There are 36 units and six workers.
Size weights are uniform integers from one to five. The fixed random seeds are
not selected based on outcomes.

| Scenario | Synthetic observations |
| --- | --- |
| Hidden initial costs | Durations are uniform from 10 to 20 seconds; units initially on worker 1 cost eight times that. Size weights conceal this concentration. |
| Timing jitter | Base duration is ten seconds times size weight, multiplied independently by mean-one lognormal noise with log standard deviation 0.12. |
| Sustained change | Base costs are initially exact; at run 8, units initially assigned to worker 1 become four times slower permanently. |
| Retry spike | Same jitter as above; at run 8 only, one unit becomes eight times slower. |
| Indivisible bottleneck | One unit costs 900 seconds; the remaining 35 units cost ten seconds each. |

Policies are fixed two migrations with PID (previous default), adaptive two-to-six
with PID (new default), fixed six with PID, experimental outer-PID budget with
PID prediction, and adaptive budget with projected gradient prediction.

The target metric is the first run of three consecutive observed CV values at
or below 15%. Search starts at run 1, or at run 8 for the sustained change.
Non-reaching trials are reported explicitly. For the spike scenario, this target
metric describes initial balance; inspect its full curve for disturbance recovery.
Migrations count changed final worker ownership, which can be less than the search
budget if a unit participates in multiple exchanges. Traversal makespan is the
largest worker sum. It excludes browser startup, queueing, installation, and
shared-service contention. The interquartile bands describe variability across
these synthetic seeds; they are not confidence intervals.

## Results and interpretation

![Observed imbalance over successive captures](https://raw.githubusercontent.com/astrivant/resumeme/main/studies/capture-convergence/convergence.svg)

![Traversal time, reassignment, and estimator tradeoffs](https://raw.githubusercontent.com/astrivant/resumeme/main/studies/capture-convergence/tradeoffs.svg)

See the [complete results](RESULTS.md), [machine-readable metadata](results.json),
and the local [convergence](convergence.svg) and [tradeoff](tradeoffs.svg) figures.

| Finding | Median across 12 paired seeds |
| --- | --- |
| Startup target reached | Fixed two: run 4; adaptive: run 2; outer PID: run 2. All 12 trials reach the target. |
| Startup sum of traversal makespans over 24 runs | Fixed two: 5729.862 seconds; adaptive: 5812.488 seconds, about 1.4% higher. Faster initial balancing does not guarantee lower long-horizon time after we stop polishing small gains. |
| Jitter reassignment over 24 runs | Fixed two: 43 units; adaptive: 13.5 units; fixed six: 129 units. |
| Sustained change target reached | Fixed two and adaptive: run 13; fixed six: run 12. Adaptive makespan sum is 7265 seconds versus 7000 for fixed two, a 3.8% cost for limiting low-value reassignment. |
| Indivisible target reached | Zero of 12 for every policy. Larger budgets cannot split this unit. |

Reaching the operational target is different from exhausting small improvements.
For constant startup costs, the first quiet run after the final observed migration
has median 10.5 for fixed two, 3 for adaptive, and 5 for fixed six. The adaptive
rule deliberately stops before all small improvements disappear. This means
settling within the operational target, not solving the partition to a global optimum.
The fixed-budget baselines retain the former acceptance rules; adaptive and outer
controller variants include the new makespan threshold near the target.

The indivisible case has an analytic lower bound. For total work `W`, mean
`mu = W/m`, and largest atomic cost `c_max > mu`, the best continuous relaxation
puts all other worker loads equally below the mean:

```math
\delta=c_{\max}-\mu,\qquad
D\ge\delta^2+(m-1)\left(\frac{\delta}{m-1}\right)^2,
\qquad c\ge\frac{\delta}{\mu\sqrt{m-1}}.
```

Here `W = 1250`, giving a CV lower bound of approximately 1.485, far above 0.15.
The observed planner also retains a gap above that bound because no available
single move/swap clears its 5% improvement threshold. Budget tuning cannot fix
that local stall. Progressive refinement, where the browser genuinely supports
independent traversal, is the appropriate separate mechanism.

## Automatic capacity and useful turnover

Assignment churn and worker capacity are separate decisions. Moving the same work
between workers preserves total work and mean at fixed count. Changing the count
changes the mean, so comparing raw standard deviations across counts can reward
the wrong behavior. The production capacity selector therefore uses feasible
predicted completion time and browser-seconds, not CV alone.

```yaml
capture:
  sharding:
    enabled: true
    initial: 6
    minimum: 2
    maximum: 8
    cooldown_runs: 3
```

The configurable hard ceiling is twelve; eight is the conservative default used
in both repository configs and this experiment. Disabling the feature fixes the
count at `initial`. After three completed captures since the last change, compare
the current count with one fewer and one more. A candidate uses an actual LPT
assignment followed by local search. Its exact placement is frozen in the plan,
with PID state retained and exact unit/worker coverage enforced by fan-in. A
resize can reassign more units than the ordinary fixed-count migration budget.

Let `o` be median observed browser startup/session-check/cleanup time, obtained
by subtracting traversal seconds from nonempty workers' elapsed seconds. For each
feasible candidate assignment, let `a` be its number of nonempty workers:

```math
T=\max_i L_i+o,\qquad R=\sum_i L_i+ao.
```

An empty plan has `T = R = 0`. An extra worker is accepted only if

```math
T-T'\ge\max(15\,\mathrm{s},0.10T),\qquad R'\le1.25R.
```

A reduction is accepted only if

```math
T'\le1.05T,\qquad R'\le0.90R.
```

These criteria use browser-seconds as a cost proxy, not billed Actions time.
They exclude installation, queueing, and contention. The 5% slowdown bound applies
to each reduction and can compound over several reductions. Missing overhead
observations prevent automatic resizing. New explicit limits take precedence over
the cooldown. Count and cooldown age are stored only in the existing encrypted
timing feedback; the current run's matrix always comes from its own frozen plan.

![Adaptive capacity, latency, and browser consumption](https://raw.githubusercontent.com/astrivant/resumeme/main/studies/capture-convergence/capacity.svg)

The [local figure](capacity.svg) and [capacity results](capacity-results.json)
compare fixed six with adaptive two-to-eight. Both use the production migration
and churn rules, so this comparison isolates capacity changes. Twelve paired
seeds run for 24 captures. Heavy work scales the jitter workload's durations by
ten and uses 20-second startup. Small work scales them by 0.05 and uses 90-second
startup. The indivisible case uses the 900-second unit and 20-second startup.
Overhead is deterministic and visible only after the first completed capture.

| Workload | Final count (median) | Sum of completion times, fixed -> adaptive | Sum of browser-seconds, fixed -> adaptive |
| --- | --- | --- | --- |
| Heavy traversal | 6 -> 8 | 46462.405 -> 37889.026 seconds, 18.5% lower | 258317.724 -> 259097.724, 0.3% higher |
| Small work with startup overhead | 6 -> 3 | 2388.801 -> 2541.551 seconds, 6.4% higher | 14237.189 -> 9377.189, 34.1% lower |
| Indivisible bottleneck | 6 -> 6 | Unchanged | Unchanged |

The heavy case finishes sooner even though final observed CV increases slightly,
from about 0.056 to 0.061. That is why smaller standard deviation alone is not the
capacity objective. Adjacent-count search and bounded local search can miss a
better count that needs several workers added at once; the policy deliberately
avoids speculative jumps. These synthetic results establish behavior and
tradeoffs, not live LinkedIn scaling or rate-limit safety.

## Executable mathematics

These examples run through the existing Markdown-math pre-commit hook. KaTeX
checks expression syntax; doctest and property tests check concrete calculations
and scheduler invariants. Syntax lint alone is not a mathematical proof.

```pycon
>>> from math import ceil, log, sqrt
>>> from resumeme.linkedin.capture.scheduling import migration_budget
>>> [migration_budget(loads) for loads in ([100] * 6, [200, 80, 80, 80, 80, 80], [400, 40, 40, 40, 40, 40])]
[2, 5, 6]
>>> migration_budget([4000, 400, 400, 400, 400, 400])
6
>>> ceil(log(4) / log(1.25))
7
>>> round((900 - 1250 / 6) / ((1250 / 6) * sqrt(5)), 3)
1.485
>>> from scripts.studies.capture_convergence.simulation import gradient_feedback
>>> from resumeme.linkedin.capture.feedback import TimingFeedback
>>> gradient_feedback(TimingFeedback(100.0, 0.0, 0.0, 1), 120.0, 1).estimate
110.0

```

## Sources and next evidence

Source review: 2026-10-09. The production change is a proportional, bounded budget
schedule. It is analogous to adapting control effort by operating region, but it
does not implement classical gain scheduling of PID coefficients.

- [MathWorks: cascade PI design](https://www.mathworks.com/help/control/ug/designing-cascade-control-system-with-pi-controllers.html) explains the faster-inner-loop assumption behind classical cascade tuning.
- [MathWorks: gain-scheduled PID implementation](https://www.mathworks.com/help/slcontrol/ug/implement-gain-scheduled-pid-controllers.html) distinguishes operating-point gain selection from adding a second PID.
- [Astrom and Murray: PID control](https://www.cds.caltech.edu/~murray/books/AM05/pdf/fbs-pid_01Jan19.pdf) discusses derivative filtering, saturation, and anti-windup.
- [Production scheduling design](../../docs/capture-scheduling.md) documents the existing predictor, exact objective, encrypted feedback lifecycle, and progressive refinement.

Next evidence should be paired replay of redacted real timing traces, including
runtime prediction error, CV, slowest worker, and assignment churn. Check whether
the limiting factor is prediction lag, placement, indivisible work, or startup
and queue overhead before adding another controller or a learning dependency.
The fixed simulated costs are independent of placement; real rate limiting and
parallel LinkedIn traffic can violate that assumption.
