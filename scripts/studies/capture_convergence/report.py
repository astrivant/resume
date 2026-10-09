"""
Render reproducible convergence figures and aggregate tables from synthetic scheduling runs.
"""

from __future__ import annotations

import csv
import json
from hashlib import sha256
from pathlib import Path
from statistics import median, quantiles
from typing import TYPE_CHECKING

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from scripts.studies.capture_convergence.simulation import POLICIES, SCENARIOS

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from scripts.studies.capture_convergence.simulation import Sample

LABELS = {
    "fixed_two": "Fixed 2 + PID",
    "adaptive": "Adaptive 2-6 + PID",
    "fixed_six": "Fixed 6 + PID",
    "outer_pid": "Outer PID budget",
    "gradient": "Adaptive 2-6 + gradient",
}
COLORS = {"fixed_two": "#797979", "adaptive": "#C35C24", "fixed_six": "#38654B", "outer_pid": "#8063A5", "gradient": "#24688A"}
TITLES = {
    "cold": "Hidden initial costs",
    "jitter": "12% timing jitter",
    "step": "Sustained 4x change at run 8",
    "spike": "One 8x retry spike at run 8",
    "indivisible": "One indivisible 900s unit",
}


def target_run(samples: list[Sample], start: int) -> int | None:
    """
    Locate the first three consecutive captures meeting the operational dispersion target.

    Args:
        samples (list[Sample]): Ordered observations for one policy, scenario, and seed.
        start (int): Earliest eligible run, after a sustained workload change where applicable.

    Returns:
        int | None: First run of a qualifying window, or None when the target is not reached within the horizon.
    """
    for index in range(start, len(samples) - 2):
        if all(sample.cv <= 0.15 for sample in samples[index : index + 3]):
            return samples[index].run

    return None


def summarize(samples: list[Sample], seeds: int) -> list[dict[str, str | int | float | None]]:
    """
    Report successful and censored trials without hiding unattainable balance targets.

    Args:
        samples (list[Sample]): All paired policy trajectories.
        seeds (int): Number of independent workload realizations per scenario.

    Returns:
        list[dict[str, str | int | float | None]]: Per-policy convergence, migration, and traversal makespan summaries.
    """
    results: list[dict[str, str | int | float | None]] = []

    for scenario in SCENARIOS:
        for policy in POLICIES:
            trials = [
                [sample for sample in samples if sample.scenario == scenario and sample.policy == policy and sample.seed == seed]
                for seed in range(seeds)
            ]
            reached = [run for trial in trials if (run := target_run(trial, 8 if scenario == "step" else 1)) is not None]
            results.append(
                {
                    "scenario": scenario,
                    "policy": policy,
                    "trials": seeds,
                    "reached": len(reached),
                    "median_target_run": median(reached) if reached else None,
                    "median_total_migrations": median(sum(sample.migrations for sample in trial) for trial in trials),
                    "median_peak_seconds_sum": round(median(sum(max(sample.loads) for sample in trial) for trial in trials), 3),
                    "median_final_cv": round(median(trial[-1].cv for trial in trials), 5),
                }
            )

    return results


def curves(axis: Axes, samples: list[Sample], metric: str) -> None:
    """
    Draw paired-policy medians with interquartile bands, preserving the run axis.

    Args:
        axis (Axes): Figure panel receiving the curves.
        samples (list[Sample]): Evidence for a single workload family.
        metric (str): Numeric Sample attribute to plot.

    Returns:
        None: The panel displays deterministic medians and 25th-to-75th percentile bands across seeds.
    """
    runs = sorted({sample.run for sample in samples})

    for policy in POLICIES:
        values = [[float(getattr(sample, metric)) for sample in samples if sample.policy == policy and sample.run == run] for run in runs]
        quarters = [quantiles(value, n=4, method="inclusive") for value in values]
        axis.plot(
            runs,
            [median(value) for value in values],
            label=LABELS[policy],
            color=COLORS[policy],
            linestyle="--" if policy in {"outer_pid", "gradient"} else "-",
            linewidth=1.8,
        )
        axis.fill_between(runs, [value[0] for value in quarters], [value[2] for value in quarters], color=COLORS[policy], alpha=0.08)

    axis.set_xlabel("Completed capture run (0 = first observation)")
    axis.grid(alpha=0.18)
    axis.spines[["top", "right"]].set_visible(False)


def render(samples: list[Sample], output: Path, raw: Path, seeds: int) -> None:
    """
    Write reviewable aggregate evidence while keeping detailed synthetic traces in ignored storage.

    Args:
        samples (list[Sample]): All simulation observations.
        output (Path): Study directory for committed figures, metadata, and summary tables.
        raw (Path): Ignored destination for CSV traces and raster previews used for visual checks.
        seeds (int): Workload realizations per scenario.

    Returns:
        None: Published SVG figures, JSON summaries, and Markdown results correspond to the saved raw CSV.
    """
    output.mkdir(parents=True, exist_ok=True)
    raw.mkdir(parents=True, exist_ok=True)
    matplotlib.rcParams.update({"svg.hashsalt": "resumeme-capture-convergence", "font.size": 10, "axes.titlesize": 12})
    results = summarize(samples, seeds)
    sources = [
        Path(__file__),
        Path(__file__).with_name("simulation.py"),
        Path(__file__).with_name("__main__.py"),
        Path(__file__).with_name("resizing.py"),
        Path("pkg/resumeme/linkedin/capture/scheduling.py"),
        Path("pkg/resumeme/linkedin/capture/feedback.py"),
        Path("pkg/resumeme/linkedin/capture/shards.py"),
        Path("pkg/resumeme/linkedin/capture/capacity.py"),
        Path("pkg/resumeme/config/models.py"),
    ]
    metadata = {
        "seeds": list(range(seeds)),
        "runs": max(sample.run for sample in samples) + 1,
        "units": 36,
        "shards": 6,
        "matplotlib": matplotlib.__version__,
        "source_sha256": {
            str(path.relative_to(Path.cwd()) if path.is_absolute() else path): sha256(path.read_bytes()).hexdigest() for path in sources
        },
        "results": results,
    }
    (output / "results.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # Keep full trajectories reproducible without filling the published study with thousands of raw rows.
    with (raw / "samples.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "scenario",
                "policy",
                "seed",
                "run",
                "cv",
                "peak_ratio",
                "prediction_error",
                "migrations",
                "budget",
                "cv_floor",
                *[f"shard_{index}_seconds" for index in range(1, 7)],
            ]
        )

        for sample in samples:
            writer.writerow(
                [
                    sample.scenario,
                    sample.policy,
                    sample.seed,
                    sample.run,
                    sample.cv,
                    sample.peak_ratio,
                    sample.prediction_error,
                    sample.migrations,
                    sample.budget,
                    sample.cv_floor,
                    *sample.loads,
                ]
            )

    table = [
        "# Simulation results",
        "",
        "Synthetic data only. Runs are zero-based; target requires three consecutive runs at CV <= 15%.",
        "Target search starts at run 1, or run 8 for sustained change. Medians for target runs include successful trials only;",
        "the reached column reports censored trials explicitly. Makespan sums cover the full 24-run horizon.",
        "",
        "| Scenario | Policy | Reached | Median target run | Total migrations (median) | Sum of traversal makespans (median seconds) |",
        "| --- | --- | --- | --- | --- | --- |",
    ]

    for row in results:
        reached = row["median_target_run"] if row["median_target_run"] is not None else "not reached"
        table.append(
            f"| {row['scenario']} | {row['policy']} | {row['reached']}/{seeds} | {reached} | "
            f"{row['median_total_migrations']} | {row['median_peak_seconds_sum']} |"
        )

    (output / "RESULTS.md").write_text("\n".join(table) + "\n", encoding="utf-8")

    # These are empirical envelopes over synthetic seeds, not confidence intervals or a stability proof.
    figure, axes = plt.subplots(2, 3, figsize=(15, 8), constrained_layout=True)

    for axis, scenario in zip(axes.flat, SCENARIOS, strict=False):
        selected = [sample for sample in samples if sample.scenario == scenario]
        curves(axis, selected, "cv")
        axis.axhline(0.15, color="#333333", linewidth=1, linestyle=":")
        axis.set_title(TITLES[scenario])
        axis.set_ylabel("Observed stddev / mean")

        if scenario in {"step", "spike"}:
            axis.axvline(8, color="#333333", linewidth=0.8, linestyle=":")
        elif scenario == "indivisible":
            axis.axhline(selected[0].cv_floor, color="#AD3434", linestyle="--", linewidth=1)

    axes[1, 2].axis("off")
    handles, labels = axes[0, 0].get_legend_handles_labels()
    axes[1, 2].legend(handles, labels, loc="upper left", frameon=False)
    axes[1, 2].text(
        0,
        0.02,
        f"{seeds} paired seeds; 36 units; 6 workers\nMedian with interquartile bands\n"
        "Dotted horizontal: 15% CV target\nRed dashed: indivisible-unit lower bound\nNo network, queue, or install costs",
        transform=axes[1, 2].transAxes,
        linespacing=1.8,
    )
    figure.suptitle("Capture convergence on synthetic workloads", fontsize=16)
    figure.savefig(output / "convergence.svg", metadata={"Date": None})
    figure.savefig(raw / "convergence.png", dpi=150)
    plt.close(figure)

    figure, axes = plt.subplots(2, 2, figsize=(12, 8), constrained_layout=True)

    for axis, scenario, metric, title, label in (
        (axes[0, 0], "cold", "peak_ratio", "Initial balancing: slowest worker", "Slowest / mean traversal seconds"),
        (axes[0, 1], "cold", "migrations", "Initial balancing: assignment churn", "Units changing workers"),
        (axes[1, 0], "step", "prediction_error", "Persistent change: estimator response", "Absolute prediction error / total work"),
        (axes[1, 1], "jitter", "migrations", "Jitter: assignment churn", "Units changing workers"),
    ):
        curves(axis, [sample for sample in samples if sample.scenario == scenario], metric)
        axis.set_title(title)
        axis.set_ylabel(label)

    figure.legend(handles, labels, loc="outside lower center", ncol=3, frameon=False)
    figure.savefig(output / "tradeoffs.svg", metadata={"Date": None})
    figure.savefig(raw / "tradeoffs.png", dpi=150)
    plt.close(figure)
