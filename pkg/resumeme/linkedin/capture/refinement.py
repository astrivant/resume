"""
Refine persistent capture bottlenecks into independently replayable detail tabs.
"""

from __future__ import annotations

import logging
from statistics import fmean, pstdev
from typing import TYPE_CHECKING

from attrs import evolve

from resumeme.linkedin.capture.shards import assign_routes

if TYPE_CHECKING:
    from collections.abc import Callable

    from resumeme.linkedin.capture.shards import CapturePlan, CaptureRoute
    from resumeme.linkedin.capture.timings import CaptureTimings

__all__ = ["refine_capture_plan"]
_TARGET_CV = 0.15
_MIN_SPLIT_SECONDS = 30
_MAX_UNITS = 36
_TAB_SECTIONS = frozenset({"recommendations", "interests"})
_LOGGER = logging.getLogger(__name__)


def refine_capture_plan(
    plan: CapturePlan,
    history: CaptureTimings | None,
    discover: Callable[[CaptureRoute], list[str]],
) -> CapturePlan:
    """
    Retain existing tab units and split at most one additional costly section per run.

    Args:
        plan (CapturePlan): Current whole-section plan with historical cost estimates when available.
        history (CaptureTimings | None): Previous complete capture's observations and controller state.
        discover (Callable[[CaptureRoute], list[str]]): Browser callback returning independently selectable tab labels.

    Returns:
        CapturePlan: Whole sections or stable tab units, with a maximum of 36 units after refinement.
    """
    if history is None or history.username.casefold() != plan.profile.username.casefold() or history.browser != plan.browser:
        return plan

    eligible = [route for route in plan.routes if route.kind == "detail" and route.key in _TAB_SECTIONS]
    retained = {route.key for route in eligible if any(key.startswith(f"{route.kind}:{route.key}/tab/") for key in history.route_seconds)}
    loads = [sum(route.estimated_seconds or 0 for route in routes) for routes in assign_routes(plan).values()]
    mean = fmean(loads)
    candidates = [
        route for route in eligible if route.key not in retained and (route.estimated_seconds or 0) > max(_MIN_SPLIT_SECONDS, mean * 1.25)
    ]

    # Use relative dispersion rather than assuming normally distributed browser times; leave balanced plans coarse.
    if mean and pstdev(loads) / mean > _TARGET_CV and candidates:
        retained.add(max(candidates, key=lambda route: (route.estimated_seconds or 0, route.key)).key)

    routes: list[CaptureRoute] = []
    extra_units = 0

    for route in plan.routes:
        if route.key not in retained:
            routes.append(route)
            continue

        labels = list(dict.fromkeys(discover(route)))

        # Rediscover labels in the live DOM on every run; disappeared or newly added tabs must not retain stale content.
        if len(labels) < 2 or len(plan.routes) + extra_units + len(labels) - 1 > _MAX_UNITS:
            routes.append(route)
            continue

        extra_units += len(labels) - 1
        routes.extend(evolve(route, tab=label, feedback=None, estimated_seconds=None) for label in labels)
        _LOGGER.info(
            "Refined capture section into independently selectable tabs", extra={"profile.section": route.key, "capture.units": len(labels)}
        )

    # Estimates are reapplied by the caller after discovery; preserve the original input and avoid mixed units in serialized plans.
    return evolve(plan, routes=[evolve(route, estimated_seconds=None, feedback=None) for route in routes])
