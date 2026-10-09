"""
Learn section costs from complete captures for history-based adaptive scheduling.
"""

from __future__ import annotations

import json
import logging
import math
from statistics import fmean, median, pstdev
from typing import TYPE_CHECKING

import cattrs
from attrs import evolve, field, frozen

from resumeme.linkedin.capture.feedback import TimingFeedback, update_feedback
from resumeme.linkedin.capture.shards import aggregate_capture, assign_routes

if TYPE_CHECKING:
    from pathlib import Path

    from resumeme.linkedin.capture.shards import CapturePlan, CaptureShard

__all__ = ["CaptureTimings", "apply_timings", "decode_timings", "encode_timings", "learn_timings", "read_timings", "save_timings"]
_LOGGER = logging.getLogger(__name__)
_CONVERTER = cattrs.Converter(forbid_extra_keys=True)


@frozen
class CaptureTimings:
    """
    Retain only the most recent complete capture's traversal measurements.

    Attributes:
        username (str): Profile owner whose section costs were measured.
        browser (str): Browser engine used for these observations.
        route_seconds (dict[str, float]): Durations keyed by route kind and canonical section key.
        version (int): Timing format version, independent of package releases.
        feedback (dict[str, TimingFeedback]): PID state and assignment for each completed unit.
    """

    username: str
    browser: str
    route_seconds: dict[str, float]
    version: int = 1
    feedback: dict[str, TimingFeedback] = field(factory=dict)


def decode_timings(data: bytes) -> CaptureTimings:
    """
    Validate timing metadata before it can influence route assignment.

    Args:
        data (bytes): JSON from local storage or an authenticated CI artifact.

    Returns:
        CaptureTimings: Supported timing metadata with finite, positive route durations.

    Raises:
        ValueError: Metadata is malformed, unsupported, or contains invalid durations.
    """
    timings = _CONVERTER.structure(json.loads(data), CaptureTimings)

    if (
        timings.version != 1
        or not timings.username
        or timings.browser not in {"firefox", "chrome"}
        or any(
            key.partition(":")[0] not in {"detail", "inline", "contact"}
            or not key.partition(":")[2]
            or not math.isfinite(seconds)
            or seconds <= 0
            for key, seconds in timings.route_seconds.items()
        )
    ):
        raise ValueError("Capture timings must identify an owner, browser, and finite positive traversal durations.")

    if timings.feedback and (
        timings.feedback.keys() != timings.route_seconds.keys()
        or any(
            not 1 <= item.shard <= 6
            or item.estimate <= 0
            or not all(math.isfinite(value) for value in (item.estimate, item.error, item.integral))
            for item in timings.feedback.values()
        )
    ):
        raise ValueError("Capture feedback must cover every unit with finite PID state and a valid shard.")

    return timings


def encode_timings(timings: CaptureTimings) -> bytes:
    """
    Serialize the timing model without profile text, URLs, or browser state.

    Args:
        timings (CaptureTimings): Complete measurements for the most recent capture.

    Returns:
        bytes: Validated UTF-8 JSON suitable for local storage or encryption.
    """
    data = (json.dumps(_CONVERTER.unstructure(timings), indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    decode_timings(data)
    return data


def read_timings(path: Path) -> CaptureTimings | None:
    """
    Read optional feedback without making fresh capture depend on historical metadata.

    Args:
        path (Path): Previous complete observations, when available.

    Returns:
        CaptureTimings | None: Valid observations or None for absent or invalid history.
    """
    if path.exists():
        try:
            return decode_timings(path.read_bytes())
        except (OSError, ValueError, cattrs.BaseValidationError):
            _LOGGER.warning("Ignoring unreadable capture timings; using profile-size estimates")

    return None


def apply_timings(plan: CapturePlan, path: Path) -> CapturePlan:
    """
    Freeze known durations and calibrated fallback estimates into a new plan.

    Args:
        plan (CapturePlan): Newly discovered routes using the original size weights.
        path (Path): Optional observations from a previous complete capture.

    Returns:
        CapturePlan: Plan with all-second estimates, or unchanged size weights on a cold start.
    """
    timings = read_timings(path)
    known: dict[str, float] = {}
    feedback: dict[str, TimingFeedback] = {}

    if timings is not None and timings.username.casefold() == plan.profile.username.casefold() and timings.browser == plan.browser:
        known = {
            route.unit_key: timings.route_seconds[f"{route.kind}:{route.unit_key}"]
            for route in plan.routes
            if f"{route.kind}:{route.unit_key}" in timings.route_seconds
        }
        feedback = {
            route.unit_key: timings.feedback[f"{route.kind}:{route.unit_key}"]
            for route in plan.routes
            if f"{route.kind}:{route.unit_key}" in timings.feedback
        }
        known.update({key: state.estimate for key, state in feedback.items()})

        # A newly split parent's cost seeds its children until each has its own independent measurement.
        for route in plan.routes:
            parent = timings.feedback.get(f"{route.kind}:{route.key}")
            parent_seconds = parent.estimate if parent else timings.route_seconds.get(f"{route.kind}:{route.key}")

            if route.tab is not None and route.unit_key not in known and parent_seconds is not None:
                siblings = sum(item.key == route.key for item in plan.routes)
                known[route.unit_key] = parent_seconds / siblings

    # New routes use a robust observed seconds-per-weight ratio so their estimates share units with measured routes.
    if known:
        seconds_per_weight = median(known[route.unit_key] / route.weight for route in plan.routes if route.unit_key in known)
        plan = evolve(
            plan,
            routes=[
                evolve(
                    route,
                    estimated_seconds=known.get(route.unit_key, seconds_per_weight * route.weight),
                    feedback=feedback.get(route.unit_key),
                )
                for route in plan.routes
            ],
        )

    for index, routes in assign_routes(plan).items():
        _LOGGER.info(
            "Planned capture shard using history-based variance balancing" if known else "Planned capture shard using profile-size LPT",
            extra={
                "capture.shard": index,
                "capture.routes": [route.unit_key for route in routes],
                "capture.estimated_cost": sum(route.estimated_seconds or route.weight for route in routes),
                "capture.cost_unit": "seconds" if known else "size_weight",
                "capture.measured_routes": sum(route.unit_key in known for route in routes),
            },
        )

    return plan


def learn_timings(plan: CapturePlan, shards: list[CaptureShard]) -> CaptureTimings | None:
    """
    Accept timing feedback only from a complete, correctly assigned capture.

    Args:
        plan (CapturePlan): Immutable plan shared by all workers.
        shards (list[CaptureShard]): All six completed worker outputs.

    Returns:
        CaptureTimings | None: Latest route durations, or None for legacy outputs without measurements.

    Raises:
        ValueError: Workers are incomplete, mismatched, or misrouted.
    """
    aggregate_capture(plan, shards)
    seconds = {key: value for shard in shards for key, value in shard.route_seconds.items()}

    if seconds.keys() != {route.unit_key for route in plan.routes}:
        return None

    # Report the prediction residual per shard so later runs can distinguish inaccurate cost estimates from poor placement.
    observed = {shard.shard_index: sum(shard.route_seconds.values()) for shard in shards}
    assignments = assign_routes(plan)
    predicted = {index: sum(route.estimated_seconds or 0 for route in routes) for index, routes in assignments.items()}
    measured_plan = any(route.estimated_seconds is not None for route in plan.routes)

    for shard in shards:
        _LOGGER.info(
            "Observed capture shard load",
            extra={
                "capture.shard": shard.shard_index,
                "capture.observed_seconds": observed[shard.shard_index],
                "capture.predicted_seconds": predicted[shard.shard_index] if measured_plan else None,
                "capture.prediction_error_seconds": observed[shard.shard_index] - predicted[shard.shard_index] if measured_plan else None,
                "capture.worker_seconds": shard.elapsed_seconds,
            },
        )

    _LOGGER.info(
        "Capture shard timing distribution",
        extra={
            "capture.mean_seconds": fmean(observed.values()),
            "capture.stddev_seconds": pstdev(observed.values()),
            "capture.max_seconds": max(observed.values()),
            "capture.predicted_mean_seconds": fmean(predicted.values()) if measured_plan else None,
            "capture.predicted_stddev_seconds": pstdev(predicted.values()) if measured_plan else None,
        },
    )

    return CaptureTimings(
        plan.profile.username,
        plan.browser,
        {f"{route.kind}:{route.unit_key}": seconds[route.unit_key] for route in plan.routes},
        feedback={
            f"{route.kind}:{route.unit_key}": update_feedback(route.feedback, seconds[route.unit_key], index)
            for index, routes in assignments.items()
            for route in routes
        },
    )


def save_timings(timings: CaptureTimings, path: Path) -> None:
    """
    Replace local history atomically without retaining older profile measurements.

    Args:
        timings (CaptureTimings): Accepted observations from a complete capture.
        path (Path): Ignored local JSON destination.

    Returns:
        None: Only the latest complete measurements remain at the destination.
    """
    data = encode_timings(timings)
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(".pending")
    pending.write_bytes(data)
    pending.replace(path)
