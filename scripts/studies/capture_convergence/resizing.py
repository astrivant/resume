"""
Compare fixed and adaptive worker counts including browser overhead and runner consumption.
"""

from __future__ import annotations

import json
from statistics import fmean, median, pstdev
from typing import TYPE_CHECKING

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from attrs import evolve

from resumeme.compiler.asts.profile import Profile
from resumeme.config import CaptureSharding
from resumeme.linkedin.capture.capacity import resize_capture_plan
from resumeme.linkedin.capture.feedback import update_feedback
from resumeme.linkedin.capture.shards import assign_routes, make_capture_plan
from resumeme.linkedin.capture.timings import CaptureTimings
from scripts.studies.capture_convergence.simulation import workload

if TYPE_CHECKING:
    from pathlib import Path

    from resumeme.linkedin.capture.feedback import TimingFeedback


def capacity_trial(seed: int, scenario: str, adaptive: bool) -> list[dict[str, float]]:
    """
    Simulate one capacity trial using the production resize policy and immutable assignment logic.

    Args:
        seed (int): Common random workload seed shared by both policies.
        scenario (str): Heavy traversal, small work with expensive startup, or one indivisible bottleneck.
        adaptive (bool): Enable bounded resizing instead of retaining six workers.

    Returns:
        list[dict[str, float]]: Completed-run counts, wall time, browser-seconds, dispersion, and migration evidence.
    """
    routes, observations = workload(seed, "indivisible" if scenario == "indivisible" else "jitter", 24)
    overhead = 90.0 if scenario == "small" else 20.0
    multiplier = 10.0 if scenario == "heavy" else 0.05 if scenario == "small" else 1.0
    settings = CaptureSharding(enabled=adaptive)
    plan = make_capture_plan(Profile("synthetic", "Synthetic"), "firefox", routes)
    history: CaptureTimings | None = None
    feedback: dict[str, TimingFeedback] = {}
    results: list[dict[str, float]] = []
    previous: dict[str, int] = {}

    for run, raw in enumerate(observations):
        observed = {key: seconds * multiplier for key, seconds in raw.items()}

        if history is not None:
            plan = evolve(
                plan,
                routes=[
                    evolve(route, estimated_seconds=feedback[route.unit_key].estimate, feedback=feedback[route.unit_key])
                    for route in routes
                ],
                resize_age=history.resize_age,
                placements={},
            )
            plan = resize_capture_plan(plan, history, settings)

        assigned = assign_routes(plan)
        owners = {route.unit_key: worker for worker, units in assigned.items() for route in units}
        loads = [sum(observed[route.unit_key] for route in units) for units in assigned.values()]
        results.append(
            {
                "run": float(run),
                "workers": float(plan.shard_count),
                "seconds": max(loads) + overhead,
                "runner_seconds": sum(loads) + sum(load > 0 for load in loads) * overhead,
                "cv": pstdev(loads) / fmean(loads),
                "migrations": float(sum(key in previous and previous[key] != worker for key, worker in owners.items())),
            }
        )
        previous = owners
        feedback = {key: update_feedback(feedback.get(key), seconds, owners[key]) for key, seconds in observed.items()}
        history = CaptureTimings(
            "synthetic",
            "firefox",
            {f"detail:{key}": value for key, value in observed.items()},
            feedback={f"detail:{key}": state for key, state in feedback.items()},
            shard_count=plan.shard_count,
            resize_age=plan.resize_age + 1,
            worker_overhead_seconds=overhead,
        )

    return results


def render_capacity(output: Path, raw: Path) -> None:
    """
    Plot capacity, runtime, and cost for paired fixed/adaptive scheduling trials.

    Args:
        output (Path): Study artifact directory.
        raw (Path): Ignored trace and raster preview directory.

    Returns:
        None: Published capacity figure and summaries include all trials and overhead assumptions.
    """
    figure, axes = plt.subplots(3, 3, figsize=(14, 10), constrained_layout=True)
    summaries: list[dict[str, str | float | bool]] = []
    traces: dict[str, list[list[dict[str, float]]]] = {}

    for row, scenario in enumerate(("heavy", "small", "indivisible")):
        for adaptive in (False, True):
            trials = [capacity_trial(seed, scenario, adaptive) for seed in range(12)]
            traces[f"{scenario}:{adaptive}"] = trials
            summaries.append(
                {
                    "scenario": scenario,
                    "adaptive": adaptive,
                    "median_final_workers": median(trial[-1]["workers"] for trial in trials),
                    "median_wall_seconds_sum": round(median(sum(item["seconds"] for item in trial) for trial in trials), 3),
                    "median_runner_seconds_sum": round(median(sum(item["runner_seconds"] for item in trial) for trial in trials), 3),
                    "median_final_cv": round(median(trial[-1]["cv"] for trial in trials), 5),
                }
            )

            for column, metric in enumerate(("workers", "seconds", "runner_seconds")):
                values = [median(trial[run][metric] for trial in trials) for run in range(24)]
                axes[row, column].plot(
                    range(24),
                    values,
                    label="Adaptive 2-8" if adaptive else "Fixed 6",
                    color="#C35C24" if adaptive else "#797979",
                    linewidth=2,
                )
                axes[row, column].set_xlabel("Completed capture run")
                axes[row, column].grid(alpha=0.18)

        axes[row, 0].set_ylabel(
            {"heavy": "Heavy traversal", "small": "Small work, 90s startup", "indivisible": "Indivisible bottleneck"}[scenario]
        )

    for column, title in enumerate(("Worker count", "Slowest browser lifetime (seconds)", "Total browser-seconds per run")):
        axes[0, column].set_title(title)

    handles, labels = axes[0, 0].get_legend_handles_labels()
    figure.legend(handles, labels, loc="outside lower center", ncol=2, frameon=False)
    figure.suptitle("Capacity adaptation: 12 paired synthetic seeds, cooldown and startup overhead included", fontsize=14)
    figure.savefig(output / "capacity.svg", metadata={"Date": None})
    figure.savefig(raw / "capacity.png", dpi=150)
    plt.close(figure)
    (output / "capacity-results.json").write_text(json.dumps(summaries, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (raw / "capacity-traces.json").write_text(json.dumps(traces, indent=2, sort_keys=True) + "\n", encoding="utf-8")
