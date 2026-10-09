"""
Generate the bounded capture-convergence study from the installed project environment.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from scripts.studies.capture_convergence.report import render
from scripts.studies.capture_convergence.resizing import render_capacity
from scripts.studies.capture_convergence.simulation import POLICIES, SCENARIOS, simulate


def main() -> None:
    """
    Run the documented paired experiment and publish only synthetic aggregate evidence.

    Returns:
        None: Study figures/tables and ignored detailed trajectories are regenerated.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("studies/capture-convergence"))
    parser.add_argument("--raw-output", type=Path, default=Path(".cache/studies/capture-convergence"))
    args = parser.parse_args()
    samples = [
        sample
        for scenario in SCENARIOS
        for seed in range(12)
        for policy in POLICIES
        for sample in simulate(seed, scenario, policy, runs=24)
    ]
    render(samples, args.output, args.raw_output, seeds=12)
    render_capacity(args.output, args.raw_output)

    # Matplotlib leaves padding at line ends in SVG paths; normalize it so generated diagrams satisfy repository whitespace checks.
    for path in args.output.glob("*.svg"):
        path.write_text("\n".join(line.rstrip() for line in path.read_text(encoding="utf-8").splitlines()) + "\n", encoding="utf-8")

    print(f"Generated {len(samples)} synthetic run observations under {args.output}")


if __name__ == "__main__":
    main()
