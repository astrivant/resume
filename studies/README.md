# Studies

Design assessments and validation plans for proposed resumeme capabilities.
Each study keeps its scope, evidence, assumptions, and evaluation protocol in
its own directory. Status distinguishes proposals from measured results.

<!-- toc:start -->
**Table of contents**

- [Study inventory](#study-inventory)
- [Evidence and publication](#evidence-and-publication)
<!-- toc:end -->

## Study inventory

| Study | Question | Status |
| --- | --- | --- |
| [Automated job applications](automated-job-applications/README.md) | Can supported application forms reuse profile facts, tailored PDFs, and approved answers reliably? | Design study; no application trials performed |
| [Capture convergence](capture-convergence/README.md) | Can feedback rebalance six capture shards faster without excessive reassignment under noise? | Reproducible synthetic comparisons; adaptive migration budget implemented, live speedup unmeasured |

## Evidence and publication

Keep a study's explanation, source references, and eventual aggregate results
under `studies/<name>/`. Record the date of external research and distinguish
engineering estimates from observed behavior.

Every generated figure must place a concise question below its title describing
what the plotted evidence can answer. Keep measurement details and caveats in
legends or captions. Use the shared
[question header](../scripts/studies/plotting.py) in study generators and regenerate
the figures from their recorded inputs; do not edit exported images by hand.
The study-figure tests check published SVG questions and header spacing.

Raw measurements, logs, and temporary fixtures belong under an ignored
`.cache/studies/<name>/<run-id>/` directory. Personal application data and browser
credentials stay in local user storage, outside published study artifacts.
Publish only reviewed, redacted evidence from actual runs. Failed or incomplete
trials must remain visible in reported outcomes.
