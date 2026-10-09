"""
Verify consecutive-run feedback, variance descent, and complete timing publication.
"""

from __future__ import annotations

import json
from contextlib import nullcontext
from statistics import fmean, pvariance
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from attrs import evolve
from hypothesis import given, settings
from hypothesis import strategies as st

from resumeme.compiler.asts.profile import Profile, Section
from resumeme.config import Config, LinkedIn
from resumeme.linkedin.capture.feedback import TimingFeedback, update_feedback
from resumeme.linkedin.capture.profile import capture_profile_shard
from resumeme.linkedin.capture.refinement import refine_capture_plan
from resumeme.linkedin.capture.scheduling import balance_variance, migration_budget
from resumeme.linkedin.capture.shards import (
    CaptureRoute,
    CaptureShard,
    aggregate_capture,
    assign_routes,
    load_capture_plan,
    make_capture_plan,
    save_capture_plan,
)
from resumeme.linkedin.capture.timings import CaptureTimings, apply_timings, decode_timings, encode_timings, learn_timings, save_timings

if TYPE_CHECKING:
    from pathlib import Path


def test_consecutive_captures_rebalance_using_measured_times(tmp_path: Path) -> None:
    """
    Replace inaccurate size weights with validated feedback while preserving deterministic fan-in.

    Args:
        tmp_path (Path): Isolated ignored history and serialized worker plan.

    Returns:
        None: A slower first capture trains a lower-variance second plan without changing its mean workload.
    """
    routes = [CaptureRoute(f"section-{i}", f"Section {i}", f"https://www.linkedin.com/in/person/details/{i}/", "detail") for i in range(12)]
    plan = make_capture_plan(Profile("person", "Person"), "firefox", routes)
    history = tmp_path / "timings.json"
    assert apply_timings(plan, history) == plan
    first = assign_routes(plan)

    # A skew the size estimate cannot see: two very slow routes land together on the first shard.
    seconds = {route.key: 100.0 if route in first[1] else 10.0 for route in routes}
    shards = [
        CaptureShard(
            plan.capture_id,
            plan.browser,
            index,
            6,
            [Section(route.key, route.title) for route in assigned],
            {route.key: seconds[route.key] for route in assigned},
        )
        for index, assigned in first.items()
    ]
    timings = learn_timings(plan, shards)
    assert timings is not None
    save_timings(timings, history)
    learned = apply_timings(plan, history)
    second = assign_routes(learned)
    before = [sum(seconds[route.key] for route in assigned) for assigned in first.values()]
    after = [sum(seconds[route.key] for route in assigned) for assigned in second.values()]
    assert pvariance(after) < pvariance(before)
    assert fmean(after) == fmean(before)

    # Workers consume frozen estimates, so changing the local history later cannot change this run's assignment.
    save_capture_plan(learned, tmp_path / "plan.json")
    history.unlink()
    assert assign_routes(load_capture_plan(tmp_path / "plan.json")) == second
    outputs = [
        CaptureShard(learned.capture_id, learned.browser, index, 6, [Section(route.key, route.title) for route in assigned])
        for index, assigned in second.items()
    ]
    assert len(aggregate_capture(learned, outputs).sections) == 12


@pytest.mark.parametrize("history_kind", ["missing", "corrupt", "owner", "browser", "route_kind", "version"])
def test_unusable_history_keeps_original_algorithm(tmp_path: Path, history_kind: str) -> None:
    """
    Preserve cold-start behavior when old observations do not apply.

    Args:
        tmp_path (Path): Local history file directory.
        history_kind (str): Absent, invalid, or incompatible timing input.

    Returns:
        None: The fresh plan retains its original weights and assignments.
    """
    route = CaptureRoute("experience", "Experience", "https://www.linkedin.com/in/person/details/experience/", "detail", 4)
    plan = make_capture_plan(Profile("person", "Person"), "firefox", [route])
    timings = CaptureTimings(
        "other" if history_kind == "owner" else "person",
        "chrome" if history_kind == "browser" else "firefox",
        {
            ("inline:experience" if history_kind == "route_kind" else "detail:experience"): 17.0,
        },
    )
    path = tmp_path / "timings.json"

    if history_kind != "missing":
        path.write_bytes(encode_timings(timings))

    if history_kind == "corrupt":
        path.write_text("broken")
    elif history_kind == "version":
        path.write_text(json.dumps({**json.loads(encode_timings(timings)), "version": 2}))

    assert apply_timings(plan, path) == plan


def test_new_routes_use_seconds_calibrated_from_known_weights(tmp_path: Path) -> None:
    """
    Keep new section costs in seconds instead of mixing them with profile-size weights.

    Args:
        tmp_path (Path): Timing history destination.

    Returns:
        None: Known costs are retained and unseen routes scale by median observed seconds per weight.
    """
    routes = [
        CaptureRoute(str(i), str(i), f"https://www.linkedin.com/in/person/details/{i}/", "detail", weight)
        for i, weight in enumerate([2, 4, 6])
    ]
    plan = make_capture_plan(Profile("person", "Person"), "firefox", routes)
    path = tmp_path / "timings.json"
    save_timings(CaptureTimings("person", "firefox", {"detail:0": 10, "detail:1": 28, "detail:deleted": 9999}), path)
    assert [route.estimated_seconds for route in apply_timings(plan, path).routes] == [10, 28, 36]


@settings(max_examples=50, deadline=None)
@given(st.lists(st.integers(min_value=1, max_value=500), min_size=1, max_size=36), st.sampled_from([None, 1, 2, 6, 12]))
def test_variance_descent_preserves_work_and_never_worsens_loads(values: list[int], budget: int | None) -> None:
    """
    Protect the objective and ownership invariants for arbitrary section workloads.

    Args:
        values (list[int]): Synthetic positive traversal durations.
        budget (int | None): Fixed experimental budget, or production adaptive selection.

    Returns:
        None: Local search conserves work and mean, reduces variance, and never increases the slowest shard.
    """
    routes = [CaptureRoute(str(i), str(i), "", "detail") for i in range(len(values))]
    buckets = {index: routes[index - 1 :: 6] for index in range(1, 7)}
    costs = {route.key: float(value) for route, value in zip(routes, values, strict=True)}
    before = [sum(costs[route.key] for route in assigned) for assigned in buckets.values()]
    result = balance_variance(buckets, costs, max_migrations=budget)
    after = [sum(costs[route.key] for route in assigned) for assigned in result.values()]
    assert sorted(route.key for assigned in result.values() for route in assigned) == sorted(costs)
    assert fmean(before) == fmean(after)
    assert pvariance(after) <= pvariance(before)
    assert max(after) <= max(before)
    assert result == balance_variance(buckets, costs, max_migrations=budget)
    assert buckets == {index: routes[index - 1 :: 6] for index in range(1, 7)}
    before_owner = {route.unit_key: index for index, assigned in buckets.items() for route in assigned}
    allowed = migration_budget(before) if budget is None else budget
    assert sum(before_owner[route.unit_key] != index for index, assigned in result.items() for route in assigned) <= allowed


@pytest.mark.parametrize("loads", [[], [0.0] * 6, [100.0] * 6, [110.0, 90.0, 100.0, 100.0, 100.0, 100.0]])
def test_migration_budget_stays_conservative_near_balance(loads: list[float]) -> None:
    """
    Keep the existing two-migration allowance for empty, balanced, and mildly noisy plans.

    Args:
        loads (list[float]): Predicted shard loads within the dispersion target.

    Returns:
        None: Small errors cannot activate the startup acceleration.
    """
    assert migration_budget(loads) == 2


@given(st.lists(st.integers(min_value=0, max_value=1000), min_size=1, max_size=6), st.integers(min_value=1, max_value=100))
def test_migration_budget_is_bounded_and_scale_invariant(loads: list[int], scale: int) -> None:
    """
    Preserve scheduling decisions when seconds are uniformly rescaled.

    Args:
        loads (list[int]): Nonnegative synthetic shard durations.
        scale (int): Positive multiplier for every worker duration.

    Returns:
        None: Dispersion yields the same two-to-six migration budget regardless of workload scale.
    """
    assert 2 <= migration_budget(loads) <= 6
    assert migration_budget(loads) == migration_budget([load * scale for load in loads])


def test_large_initial_imbalance_moves_more_work_without_relaxing_acceptance() -> None:
    """
    Correct an uneven initial placement faster, then stop moving an exactly balanced assignment.

    Returns:
        None: Six safe moves outperform two moves while maintaining deterministic ownership and immutability.
    """
    routes = [CaptureRoute(str(index), "Synthetic", "", "detail") for index in range(18)]
    buckets = {index: routes.copy() if index == 1 else [] for index in range(1, 7)}
    costs = {route.unit_key: 10.0 for route in routes}
    fast = balance_variance(buckets, costs)
    slow = balance_variance(buckets, costs, max_migrations=2)
    assert sum(len(assigned) for index, assigned in fast.items() if index != 1) == 6
    assert max(map(len, fast.values())) < max(map(len, slow.values()))
    balanced = {index: routes[index - 1 :: 6] for index in range(1, 7)}
    assert balance_variance(balanced, costs) == balanced
    assert buckets[1] == routes


@pytest.mark.parametrize("value", [-1.0, float("inf"), float("nan")])
def test_invalid_loads_cannot_select_a_migration_budget(value: float) -> None:
    """
    Reject invalid costs before they influence feedback policy.

    Args:
        value (float): Negative or nonfinite shard load.

    Returns:
        None: Malformed costs raise an actionable validation error.
    """
    with pytest.raises(ValueError, match="finite, nonnegative"):
        migration_budget([value])


def test_pid_limits_outliers_and_ignores_jitter() -> None:
    """
    Bound controller movement while preventing noise and saturated errors from accumulating pressure.

    Returns:
        None: Outliers are slew-limited, the integral does not wind up, and small errors leave estimates unchanged.
    """
    initial = update_feedback(None, 100.0, 2)
    assert initial == TimingFeedback(100.0, 0.0, 0.0, 2)
    noisy = update_feedback(TimingFeedback(100.0, 20.0, 40.0, 2), 104.0, 2)
    assert noisy == initial
    spike = update_feedback(initial, 10000.0, 2)
    assert spike.estimate == 125.0
    assert spike.integral == 0.0
    changed = update_feedback(initial, 120.0, 2)
    assert changed.estimate == 113.0
    assert changed.integral == 20.0


def test_refinement_splits_only_one_new_bottleneck_and_reassembles_tabs(tmp_path: Path) -> None:
    """
    Progress from sections to bounded, independently selectable units without dropping parent content.

    Args:
        tmp_path (Path): Serialized timing history and refined plan.

    Returns:
        None: One bottleneck refines, tabs remain stable, and fan-in restores the parent and discovery order.
    """
    routes = [
        CaptureRoute(key, key.title(), f"https://www.linkedin.com/in/person/details/{key}/", "detail", estimated_seconds=seconds)
        for key, seconds in [("recommendations", 800.0), ("interests", 600.0), ("skills", 10.0)]
    ]
    plan = make_capture_plan(Profile("person", "Person"), "firefox", routes)
    history = CaptureTimings("person", "firefox", {f"detail:{route.key}": route.estimated_seconds or 1.0 for route in routes})
    visited: list[str] = []

    def discover(route: CaptureRoute) -> list[str]:
        """
        Catalog stable, disjoint tabs in source order.

        Args:
            route (CaptureRoute): Section selected for refinement.

        Returns:
            list[str]: Visible tab labels.
        """
        visited.append(route.key)
        return ["Received", "Given"]

    refined = refine_capture_plan(plan, history, discover)
    assert visited == ["recommendations"]
    assert [route.tab for route in refined.routes] == ["Received", "Given", None, None]
    save_timings(history, tmp_path / "timings.json")
    refined = apply_timings(refined, tmp_path / "timings.json")
    assert [route.estimated_seconds for route in refined.routes] == [400.0, 400.0, 600.0, 10.0]
    save_capture_plan(refined, tmp_path / "plan.json")
    restored = load_capture_plan(tmp_path / "plan.json")
    shards = [
        CaptureShard(
            restored.capture_id,
            restored.browser,
            index,
            6,
            [Section(route.unit_key, route.title) for route in assigned],
            {route.unit_key: 10.0 for route in assigned},
        )
        for index, assigned in assign_routes(restored).items()
    ]
    assert [section.key for section in aggregate_capture(restored, shards).sections] == ["recommendations", "interests", "skills"]
    learned = learn_timings(restored, shards)
    assert learned is not None
    assert "detail:recommendations" not in learned.route_seconds
    quiet_plan = evolve(plan, routes=[evolve(route, estimated_seconds=10.0) for route in routes])
    visited.clear()
    repeated = refine_capture_plan(quiet_plan, learned, discover)
    assert visited == ["recommendations"]
    assert [route.unit_key for route in repeated.routes] == [route.unit_key for route in restored.routes]


def test_balanced_feedback_does_not_probe_finer_units() -> None:
    """
    Stop refinement once section-level balancing meets the dispersion target.

    Returns:
        None: Six balanced sections cause no additional browser traversal.
    """
    routes = [
        CaptureRoute(key, key.title(), f"https://www.linkedin.com/in/person/details/{key}/", "detail", estimated_seconds=100.0)
        for key in ["recommendations", "interests", "skills", "experience", "education", "projects"]
    ]
    plan = make_capture_plan(Profile("person", "Person"), "firefox", routes)
    history = CaptureTimings("person", "firefox", {f"detail:{route.key}": 100.0 for route in routes})
    discovery = MagicMock()
    refine_capture_plan(plan, history, discovery)
    discovery.assert_not_called()


def test_tab_unit_identity_ignores_counts_and_fanin_rejects_missing_units() -> None:
    """
    Preserve feedback across counter updates while requiring every planned subsection at fan-in.

    Returns:
        None: Presentation counters do not change identity and absent tab output cannot truncate a parent section.
    """
    received = CaptureRoute(
        "recommendations", "Recommendations", "https://www.linkedin.com/in/person/details/recommendations/", "detail", tab="Received (2)"
    )
    assert received.unit_key == evolve(received, tab="Received (3)").unit_key
    given = evolve(received, tab="Given (1)")
    plan = make_capture_plan(Profile("person", "Person"), "firefox", [received, given])
    shards = [
        CaptureShard(
            plan.capture_id, plan.browser, index, 6, [Section(route.unit_key, route.title) for route in assigned if route != given]
        )
        for index, assigned in assign_routes(plan).items()
    ]

    with pytest.raises(ValueError, match="incomplete route set"):
        aggregate_capture(plan, shards)

    with pytest.raises(ValueError, match="both a whole section"):
        make_capture_plan(plan.profile, "firefox", [received, evolve(received, tab=None)])


def test_local_search_improves_lpt_variance() -> None:
    """
    Preserve the search's ability to improve LPT, while production stops polishing an already balanced placement.

    Returns:
        None: Unrestricted polishing improves variance; the production target guard avoids this low-value reassignment.
    """
    values = [41, 47, 28, 23, 50, 4, 14, 51, 3, 38, 24, 43, 12, 40, 14]
    routes = [
        CaptureRoute(str(i), str(i), f"https://www.linkedin.com/in/person/details/{i}/", "detail", value) for i, value in enumerate(values)
    ]
    cold = make_capture_plan(Profile("person", "Person"), "firefox", routes)
    learned = evolve(cold, routes=[evolve(route, estimated_seconds=0.01 * route.weight) for route in routes])
    before = [sum(route.weight for route in assigned) for assigned in assign_routes(cold).values()]
    assert {index: [route.key for route in assigned] for index, assigned in assign_routes(learned).items()} == {
        index: [route.key for route in assigned] for index, assigned in assign_routes(cold).items()
    }
    polished = balance_variance(assign_routes(cold), {route.unit_key: float(route.weight) for route in routes}, limit_churn=False)
    after = [sum(route.weight for route in assigned) for assigned in polished.values()]
    assert pvariance(after) < pvariance(before)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 0])
def test_timing_model_rejects_invalid_durations(value: float) -> None:
    """
    Reject costs that could invalidate ordering or variance arithmetic.

    Args:
        value (float): Nonfinite or nonpositive duration.

    Returns:
        None: Invalid observations are never accepted as timing history.
    """
    data = json.dumps({"username": "person", "browser": "firefox", "route_seconds": {"detail:skills": value}}).encode()

    with pytest.raises(ValueError, match="finite positive"):
        decode_timings(data)


def test_worker_times_traversal_separately_from_browser_lifetime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Measure retries inside a route without attributing shared startup and cleanup costs to its content.

    Args:
        tmp_path (Path): Isolated browser root.
        monkeypatch (pytest.MonkeyPatch): Replaces browser navigation and the monotonic clock deterministically.

    Returns:
        None: Shards report route cost and complete browser lifetime separately.
    """
    config = Config(linkedin=LinkedIn("person"))
    route = CaptureRoute("skills", "Skills", "https://www.linkedin.com/in/person/details/skills/", "detail")
    plan = make_capture_plan(Profile("person", "Person"), config.capture.browser, [route])
    monkeypatch.setattr("resumeme.linkedin.capture.profile._browser", lambda *args, **kwargs: nullcontext(MagicMock()))
    monkeypatch.setattr("resumeme.linkedin.capture.profile._navigate", lambda *args: None)
    monkeypatch.setattr("resumeme.linkedin.capture.profile._authenticated", lambda *args: True)
    monkeypatch.setattr("resumeme.linkedin.capture.profile._details", lambda *args: Section("skills", "Skills"))
    clock = iter([100.0, 110.0, 140.0, 150.0])
    monkeypatch.setattr("resumeme.linkedin.capture.profile.time.monotonic", lambda: next(clock))
    shard = capture_profile_shard(config, tmp_path, plan, 1, 6)
    assert shard.route_seconds == {"skills": 30.0}
    assert shard.elapsed_seconds == 50.0
