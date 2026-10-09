"""
Damp per-route runtime predictions with bounded PID feedback between complete captures.
"""

from __future__ import annotations

from attrs import frozen

__all__ = ["TimingFeedback", "update_feedback"]
_KP = 0.5
_KI = 0.05
_KD = 0.1
_DEADBAND = 0.05
_MAX_CHANGE = 0.25


@frozen
class TimingFeedback:
    """
    Carry one traversal unit's controller state and accepted shard assignment.

    Attributes:
        estimate (float): Predicted seconds for the next run.
        error (float): Last observed minus predicted duration, in seconds.
        integral (float): Bounded accumulated error in seconds over normalized unit run intervals.
        shard (int): Last accepted worker assignment, within the previous plan.
    """

    estimate: float
    error: float
    integral: float
    shard: int


def update_feedback(previous: TimingFeedback | None, observed: float, shard: int) -> TimingFeedback:
    """
    Apply one PID update per successful capture with deadband, slew limiting, and anti-windup.

    Args:
        previous (TimingFeedback | None): State used for this run, absent for a newly measured unit.
        observed (float): Positive, validated traversal duration including in-process retries.
        shard (int): Worker that completed this unit.

    Returns:
        TimingFeedback: Updated estimate bounded to a 25 percent change for established units.
    """
    if previous is None:
        return TimingFeedback(observed, 0.0, 0.0, shard)

    error = observed - previous.estimate

    # Ignore timing jitter and clear accumulated pressure once the prediction is sufficiently close.
    if abs(error) <= _DEADBAND * previous.estimate:
        return TimingFeedback(previous.estimate, 0.0, 0.0, shard)

    integral = max(-previous.estimate, min(previous.estimate, previous.integral + error))
    delta = _KP * error + _KI * integral + _KD * (error - previous.error)
    limit = _MAX_CHANGE * previous.estimate

    # Conditional integration prevents an unusually slow run from accumulating error behind the output clamp.
    if abs(delta) > limit and delta * error > 0:
        integral = previous.integral
        delta = _KP * error + _KI * integral + _KD * (error - previous.error)

    estimate = previous.estimate + max(-limit, min(limit, delta))
    return TimingFeedback(estimate, error, max(-estimate, min(estimate, integral)), shard)
