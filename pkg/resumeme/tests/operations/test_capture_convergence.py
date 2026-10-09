"""
Check the study's causal comparisons and bounded control alternatives against production scheduling.
"""

from __future__ import annotations

from statistics import fmean

import pytest
from scripts.studies.capture_convergence.simulation import POLICIES, Supervisor, gradient_feedback, simulate, workload

from resumeme.linkedin.capture.feedback import TimingFeedback


def test_study_uses_paired_workloads_and_deterministic_causal_feedback() -> None:
    """
    Require all policy variants to start with the same unmeasured schedule and total work.

    Returns:
        None: Feedback is causal, all work is conserved, migration budgets hold, and repeat simulations agree.
    """
    _, observed = workload(0, "cold", 8)
    trials = [simulate(0, "cold", policy, runs=8) for policy in POLICIES]
    assert all(trial[0].loads == trials[0][0].loads and trial[0].budget == 0 for trial in trials)

    for trial in trials:
        for sample, seconds in zip(trial, observed, strict=True):
            assert sum(sample.loads) == pytest.approx(sum(seconds.values()))
            assert sample.migrations <= sample.budget
            assert sample.peak_ratio == pytest.approx(max(sample.loads) / fmean(sample.loads))

    assert simulate(0, "cold", "adaptive", runs=8) == trials[1]
    assert trials[1][1].cv < trials[0][1].cv
    prefix = simulate(0, "cold", "adaptive", runs=3)
    assert prefix == trials[1][:3]


def test_experimental_controllers_respect_saturation_and_reset() -> None:
    """
    Keep exploratory PID and gradient baselines bounded even under extreme disturbances.

    Returns:
        None: The outer controller avoids windup and gradient descent preserves the existing predictor limits.
    """
    controller = Supervisor()

    for _ in range(10):
        budget, controller = controller.advance(10.0)
        assert budget == 6 and controller.integral == 0

    assert controller.advance(0.1) == (2, Supervisor())
    initial = TimingFeedback(100.0, 0.0, 0.0, 1)
    assert gradient_feedback(initial, 10000.0, 1).estimate == 125.0
    assert gradient_feedback(initial, 1.0, 1).estimate == 75.0
    assert gradient_feedback(initial, 104.0, 1).estimate == 100.0


def test_indivisible_workload_reports_unreachable_target() -> None:
    """
    Prevent the study from implying that a migration controller can split an atomic traversal.

    Returns:
        None: Every policy remains above the analytically necessary dispersion floor.
    """
    for policy in POLICIES:
        samples = simulate(0, "indivisible", policy, runs=4)
        assert all(sample.cv >= sample.cv_floor > 0.15 for sample in samples)
