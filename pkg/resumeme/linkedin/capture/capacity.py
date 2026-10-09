"""
Resize future capture matrices only when predicted time or runner savings justify a count change.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from attrs import evolve

from resumeme.linkedin.capture.shards import assign_routes

if TYPE_CHECKING:
    from resumeme.config import CaptureSharding
    from resumeme.linkedin.capture.shards import CapturePlan
    from resumeme.linkedin.capture.timings import CaptureTimings

__all__ = ["capacity_metrics", "resize_capture_plan"]
_MIN_TIME_GAIN = 0.10
_MIN_SECONDS_SAVED = 15.0
_MAX_RUNNER_GROWTH = 0.25
_MAX_DOWNSIZE_SLOWDOWN = 0.05
_MIN_RUNNER_SAVING = 0.10
_LOGGER = logging.getLogger(__name__)


def capacity_metrics(plan: CapturePlan, overhead: float) -> tuple[float, float]:
    """
    Predict completion time and total active browser-seconds for one frozen assignment.

    Args:
        plan (CapturePlan): Plan whose route estimates are all in seconds.
        overhead (float): Nonnegative per-worker browser startup and teardown estimate.

    Returns:
        tuple[float, float]: Predicted makespan and total browser-seconds, excluding GitHub queues and installation.
    """
    loads = [sum(route.estimated_seconds or 0.0 for route in routes) for routes in assign_routes(plan).values()]
    active = [load for load in loads if load > 0]
    return (max(active) + overhead, sum(active) + len(active) * overhead) if active else (0.0, 0.0)


def resize_capture_plan(plan: CapturePlan, history: CaptureTimings | None, settings: CaptureSharding) -> CapturePlan:
    """
    Evaluate adjacent worker counts after a cooldown using only the latest compatible complete capture.

    Args:
        plan (CapturePlan): Current measured plan, retaining established unit ownership and predictor state.
        history (CaptureTimings | None): Prior measurements, including independently measured worker overhead.
        settings (CaptureSharding): Enabled flag, initial count, user limits, and completed-run cooldown.

    Returns:
        CapturePlan: Same plan or one-count resize with a reset cooldown; explicit configuration bounds take precedence.
    """
    if (
        not settings.enabled
        or history is None
        or history.username.casefold() != plan.profile.username.casefold()
        or history.browser != plan.browser
    ):
        return evolve(plan, shard_count=settings.initial, resize_age=0, placements={})

    # Respect newly narrowed operator limits immediately; ordinary automatic decisions change only one worker per interval.
    count = max(settings.minimum, min(settings.maximum, plan.shard_count))

    if count != plan.shard_count:
        return evolve(plan, shard_count=count, resize_age=0, placements={})

    if (
        plan.resize_age < settings.cooldown_runs
        or history.worker_overhead_seconds is None
        or not plan.routes
        or any(route.estimated_seconds is None for route in plan.routes)
    ):
        return plan

    before_time, before_runner = capacity_metrics(plan, history.worker_overhead_seconds)
    candidates: list[tuple[float, float, CapturePlan]] = []

    for count in (plan.shard_count - 1, plan.shard_count + 1):
        if not settings.minimum <= count <= settings.maximum or count > len(plan.routes):
            continue

        # Compare an actual feasible repartition, not a fractional division of total work that ignores atomic traversals.
        trial = evolve(plan, shard_count=count, placements={}, routes=[evolve(route, feedback=None) for route in plan.routes])
        placements = {route.unit_key: worker for worker, routes in assign_routes(trial).items() for route in routes}
        candidate = evolve(plan, shard_count=count, resize_age=0, placements=placements)
        after_time, after_runner = capacity_metrics(candidate, history.worker_overhead_seconds)

        # More workers must materially accelerate useful traversal without an excessive increase in active browser time.
        grows = count > plan.shard_count
        worthwhile = (
            (
                before_time - after_time >= max(_MIN_SECONDS_SAVED, _MIN_TIME_GAIN * before_time)
                and after_runner <= before_runner * (1 + _MAX_RUNNER_GROWTH)
            )
            if grows
            else (after_time <= before_time * (1 + _MAX_DOWNSIZE_SLOWDOWN) and after_runner <= before_runner * (1 - _MIN_RUNNER_SAVING))
        )

        if worthwhile:
            candidates.append((after_time, after_runner, candidate))

    if not candidates:
        return plan

    after_time, after_runner, selected = min(candidates, key=lambda item: (item[0], item[1], item[2].shard_count))
    _LOGGER.info(
        "Resized capture worker matrix",
        extra={
            "capture.previous_shards": plan.shard_count,
            "capture.shards": selected.shard_count,
            "capture.predicted_seconds_before": before_time,
            "capture.predicted_seconds_after": after_time,
            "capture.browser_seconds_before": before_runner,
            "capture.browser_seconds_after": after_runner,
        },
    )
    return selected
