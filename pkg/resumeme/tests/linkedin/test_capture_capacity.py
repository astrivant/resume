"""
Verify bounded worker resizing, exact fan-in, and configuration/CI matrix contracts.
"""

from __future__ import annotations

import json
import runpy
from typing import TYPE_CHECKING

import pytest
import yaml
from attrs import evolve
from scripts.studies.capture_convergence.resizing import capacity_trial
from scripts.studies.capture_convergence.simulation import workload

from resumeme.compiler.asts.profile import Profile, Section
from resumeme.config import CaptureSharding, load_config
from resumeme.exceptions import ConfigurationError
from resumeme.linkedin.capture.capacity import capacity_metrics, resize_capture_plan
from resumeme.linkedin.capture.feedback import TimingFeedback
from resumeme.linkedin.capture.shards import (
    CaptureShard,
    aggregate_capture,
    assign_routes,
    load_capture_plan,
    make_capture_plan,
    save_capture_plan,
)
from resumeme.linkedin.capture.timings import CaptureTimings, decode_timings, encode_timings, learn_timings
from resumeme.tests.paths import REPOSITORY_ROOT

if TYPE_CHECKING:
    from pathlib import Path


def test_capacity_scales_for_useful_work_and_holds_indivisible_bottlenecks() -> None:
    """
    Exercise the real capacity selector against growth, overhead-heavy work, and atomic traversal limits.

    Returns:
        None: Counts stay bounded, cooldown prevents rapid resizing, and ineffective scale-out is rejected.
    """
    for scenario, expected in (("heavy", 8), ("small", 3), ("indivisible", 6)):
        trial = capacity_trial(0, scenario, True)
        assert trial[-1]["workers"] == expected
        changes = [index for index in range(1, len(trial)) if trial[index]["workers"] != trial[index - 1]["workers"]]
        assert all(2 <= item["workers"] <= 8 for item in trial)
        assert all(abs(trial[index]["workers"] - trial[index - 1]["workers"]) == 1 for index in changes)
        assert all(second - first >= 3 for first, second in zip(changes, changes[1:], strict=False))


@pytest.mark.parametrize("count", [1, 2, 6, 8, 12])
def test_variable_counts_round_trip_and_require_every_planned_worker(tmp_path: Path, count: int) -> None:
    """
    Preserve the complete-profile contract across every permitted matrix size, including empty shards.

    Args:
        tmp_path (Path): Isolated plan serialization directory.
        count (int): Supported matrix size.

    Returns:
        None: Fan-in requires exact worker coverage and timing metadata preserves the selected count.
    """
    routes, _ = workload(0, "cold", 1)
    plan = make_capture_plan(Profile("synthetic", "Synthetic"), "firefox", routes[:3], shard_count=count)
    save_capture_plan(plan, tmp_path / "plan.json")
    assert load_capture_plan(tmp_path / "plan.json") == plan
    shards = [
        CaptureShard(
            plan.capture_id,
            plan.browser,
            index,
            count,
            [Section(route.unit_key, route.title) for route in assigned],
            {route.unit_key: 10.0 for route in assigned},
            20.0 + 10 * len(assigned),
        )
        for index, assigned in assign_routes(plan).items()
    ]
    assert len(aggregate_capture(plan, shards).sections) == 3

    with pytest.raises(ValueError, match="do not cover the plan"):
        aggregate_capture(plan, shards[:-1])

    timings = learn_timings(plan, shards)
    assert timings is not None and timings.shard_count == count and timings.worker_overhead_seconds == 20.0
    assert timings.resize_age == 1
    assert decode_timings(encode_timings(timings)) == timings


def test_capacity_freezes_evaluated_placement_and_preserves_pid_state(tmp_path: Path) -> None:
    """
    Keep the chosen schedule identical on workers and fan-in without erasing learned runtime state.

    Args:
        tmp_path (Path): Cross-process plan serialization boundary.

    Returns:
        None: A justified resize retains predictor values and exactly reproduces its scored makespan after serialization.
    """
    routes, observed = workload(0, "jitter", 1)
    plan = make_capture_plan(Profile("synthetic", "Synthetic"), "firefox", routes)
    owners = {route.unit_key: worker for worker, assigned in assign_routes(plan).items() for route in assigned}
    plan = evolve(
        plan,
        resize_age=3,
        routes=[
            evolve(
                route,
                estimated_seconds=observed[0][route.unit_key] * 10,
                feedback=TimingFeedback(observed[0][route.unit_key] * 10, 2.0, 3.0, owners[route.unit_key]),
            )
            for route in routes
        ],
    )
    history = CaptureTimings("synthetic", "firefox", {}, worker_overhead_seconds=20.0)
    resized = resize_capture_plan(plan, history, CaptureSharding())
    assert resized.shard_count == 7 and resized.resize_age == 0 and resized.placements
    assert resized.routes == plan.routes
    assert capacity_metrics(resized, 20.0)[0] <= 0.9 * capacity_metrics(plan, 20.0)[0]
    save_capture_plan(resized, tmp_path / "plan.json")
    assert assign_routes(resized) == assign_routes(load_capture_plan(tmp_path / "plan.json"))

    # The same cost signal cannot resize before enough complete captures, or without reliable overhead observations.
    assert resize_capture_plan(evolve(plan, resize_age=2), history, CaptureSharding()).shard_count == 6
    assert resize_capture_plan(plan, evolve(history, worker_overhead_seconds=None), CaptureSharding()) == plan

    with pytest.raises(ValueError, match="Frozen placements"):
        save_capture_plan(evolve(resized, placements={"missing": 1}), tmp_path / "invalid.json")


def test_config_bounds_and_matrix_use_the_validated_plan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Tie schema validation, local opt-out, and the Actions matrix to one authoritative count.

    Args:
        tmp_path (Path): Local configuration and plan fixtures.
        monkeypatch (pytest.MonkeyPatch): Isolated working directory and Actions outputs.

    Returns:
        None: Invalid bounds fail; every emitted worker belongs to the saved plan and CI consumes the emitted count.
    """
    config = tmp_path / "resumeme.config.yaml"
    config.write_text("profile: {linkedin: {username: synthetic}}\ncapture: {sharding: {minimum: 8, initial: 6}}\n")

    with pytest.raises(ConfigurationError, match="minimum <= initial"):
        load_config(config)

    config.write_text("profile: {linkedin: {username: synthetic}}\ncapture: {sharding: {enabled: false, initial: 4}}\n")
    routes, _ = workload(0, "cold", 1)
    plan = make_capture_plan(Profile("synthetic", "Synthetic"), "firefox", routes, shard_count=8)
    fixed = resize_capture_plan(plan, None, load_config(config).capture.sharding)
    assert fixed.shard_count == 4
    save_capture_plan(plan, tmp_path / ".cache/capture/plan.json")
    output = tmp_path / "outputs"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.chdir(tmp_path)
    runpy.run_path(str(REPOSITORY_ROOT / "scripts/ci/linkedin/capture-matrix.py"), run_name="__main__")
    values = dict(line.split("=", 1) for line in output.read_text().splitlines())
    assert values["count"] == "8" and json.loads(values["shards"]) == list(range(1, 9))
    job = yaml.safe_load((REPOSITORY_ROOT / ".github/workflows/ci.yml").read_text())["jobs"]["capture-shards"]
    assert job["strategy"]["matrix"]["shard"] == "${{ fromJSON(needs.capture-bootstrap.outputs.shards) }}"
    worker = next(step for step in job["steps"] if step.get("uses") == "./.github/actions/linkedin-session")
    assert worker["with"]["shard-count"] == "${{ needs.capture-bootstrap.outputs.count }}"
