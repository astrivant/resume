"""
Replay identical synthetic workloads through production assignment and runtime feedback functions.
"""

from __future__ import annotations

import math
import random
from statistics import fmean, pstdev
from typing import Literal

from attrs import frozen

from resumeme.compiler.asts.profile import Profile
from resumeme.linkedin.capture.feedback import TimingFeedback, update_feedback
from resumeme.linkedin.capture.scheduling import balance_variance, migration_budget
from resumeme.linkedin.capture.shards import CaptureRoute, assign_routes, make_capture_plan

Policy = Literal["fixed_two", "adaptive", "fixed_six", "outer_pid", "gradient"]
Scenario = Literal["cold", "jitter", "step", "spike", "indivisible"]
POLICIES: tuple[Policy, ...] = ("fixed_two", "adaptive", "fixed_six", "outer_pid", "gradient")
SCENARIOS: tuple[Scenario, ...] = ("cold", "jitter", "step", "spike", "indivisible")


@frozen
class Sample:
    """
    Record one completed synthetic run, including failed balance targets.

    Attributes:
        scenario (str): Workload family.
        policy (str): Scheduling and prediction policy under comparison.
        seed (int): Reproducible workload realization shared by every policy.
        run (int): Zero-based capture number, with run zero using size weights only.
        cv (float): Observed population standard deviation divided by mean load.
        peak_ratio (float): Slowest observed shard divided by mean load.
        prediction_error (float): Sum of absolute prediction errors divided by total observed work; zero on the unmeasured run.
        migrations (int): Units whose final worker differs from the preceding run.
        budget (int): Allowed route migrations, zero on the cold run.
        loads (tuple[float, ...]): Observed seconds for all six workers.
        cv_floor (float): Lower bound imposed by a single indivisible unit larger than the mean.
    """

    scenario: str
    policy: str
    seed: int
    run: int
    cv: float
    peak_ratio: float
    prediction_error: float
    migrations: int
    budget: int
    loads: tuple[float, ...]
    cv_floor: float


@frozen
class Supervisor:
    """
    Retain experimental outer-controller state, separate from production timing metadata.

    Attributes:
        error (float): Previous normalized positive dispersion error.
        integral (float): Accumulated error limited to the unit interval.
    """

    error: float = 0.0
    integral: float = 0.0

    def advance(self, cv: float) -> tuple[int, Supervisor]:
        """
        Adjust the migration allowance with a bounded outer PID, leaving estimator gains unchanged.

        Args:
            cv (float): Current predicted shard coefficient of variation.

        Returns:
            tuple[int, Supervisor]: Two-to-six migration budget and next experimental controller state.
        """
        error = min(1.0, max(0.0, (cv - 0.15) / 0.45))

        if error == 0:
            return 2, Supervisor()

        integral = min(1.0, self.integral + error)
        effort = error + 0.2 * integral + 0.1 * (error - self.error)

        # Conditional integration prevents accumulated pressure while the migration actuator is saturated.
        if effort > 1:
            integral = self.integral
            effort = error + 0.2 * integral + 0.1 * (error - self.error)

        budget = 2 + math.ceil(4 * min(1.0, max(0.0, effort)))
        return budget, Supervisor(error, integral)


def gradient_feedback(previous: TimingFeedback | None, observed: float, shard: int) -> TimingFeedback:
    """
    Compare projected online gradient descent on half-squared prediction error against PID.

    Args:
        previous (TimingFeedback | None): Prior positive runtime estimate, absent for the first observation.
        observed (float): Positive synthetic traversal seconds.
        shard (int): Worker that completed this route.

    Returns:
        TimingFeedback: Gradient update with learning rate 0.5, retaining production deadband and 25 percent slew limits.
    """
    if previous is None:
        return update_feedback(None, observed, shard)

    error = observed - previous.estimate

    if abs(error) <= 0.05 * previous.estimate:
        return TimingFeedback(previous.estimate, 0.0, 0.0, shard)

    limit = 0.25 * previous.estimate
    estimate = previous.estimate + min(limit, max(-limit, 0.5 * error))
    return TimingFeedback(estimate, error, 0.0, shard)


def workload(seed: int, scenario: Scenario, runs: int) -> tuple[list[CaptureRoute], list[dict[str, float]]]:
    """
    Generate common random numbers so every policy faces exactly the same traversal observations.

    Args:
        seed (int): Local random generator seed, independent of global random state.
        scenario (Scenario): Hidden initial costs, jitter, sustained change, isolated retry, or an indivisible bottleneck.
        runs (int): Number of completed captures to simulate.

    Returns:
        tuple[list[CaptureRoute], list[dict[str, float]]]: Stable route catalog and seconds per route per capture.
    """
    generator = random.Random(seed)
    routes = [
        CaptureRoute(
            f"unit-{index:02}", "Synthetic", f"https://www.linkedin.com/in/synthetic/details/{index}/", "detail", generator.randint(1, 5)
        )
        for index in range(36)
    ]
    initial = assign_routes(make_capture_plan(Profile("synthetic", "Synthetic"), "firefox", routes))
    first_worker = {route.unit_key for route in initial[1]}
    base = {route.unit_key: 10.0 * route.weight for route in routes}

    # Size weights conceal a concentration of slow traversals; no policy sees these durations before run zero completes.
    if scenario == "cold":
        base = {route.unit_key: generator.uniform(10, 20) * (8 if route.unit_key in first_worker else 1) for route in routes}
    elif scenario == "indivisible":
        base = {route.unit_key: 900.0 if index == 0 else 10.0 for index, route in enumerate(routes)}

    observations: list[dict[str, float]] = []

    for run in range(runs):
        values = dict(base)

        if scenario == "step" and run >= 8:
            values = {key: seconds * (4 if key in first_worker else 1) for key, seconds in values.items()}
        elif scenario == "spike" and run == 8:
            values[routes[0].unit_key] *= 8

        if scenario in {"jitter", "spike"}:
            values = {key: seconds * generator.lognormvariate(-(0.12**2) / 2, 0.12) for key, seconds in values.items()}

        observations.append(values)

    return routes, observations


def simulate(seed: int, scenario: Scenario, policy: Policy, runs: int = 24) -> list[Sample]:
    """
    Execute causal consecutive captures, retaining the production PID and move acceptance rules.

    Args:
        seed (int): Shared workload realization for paired policy comparisons.
        scenario (Scenario): Synthetic timing behavior.
        policy (Policy): Budget/estimator combination under comparison.
        runs (int): Number of captures, including the unmeasured first run.

    Returns:
        list[Sample]: Per-run evidence without profile content, credentials, or live browser requests.
    """
    routes, observations = workload(seed, scenario, runs)
    buckets = assign_routes(make_capture_plan(Profile("synthetic", "Synthetic"), "firefox", routes))
    feedback: dict[str, TimingFeedback] = {}
    supervisor = Supervisor()
    samples: list[Sample] = []

    for run, observed in enumerate(observations):
        before = {route.unit_key: worker for worker, assigned in buckets.items() for route in assigned}
        costs = {key: state.estimate for key, state in feedback.items()}
        budget = 0

        # Planning reads only preceding observations. Current run measurements are revealed after assignment freezes.
        if feedback:
            predicted = [sum(costs[route.unit_key] for route in assigned) for assigned in buckets.values()]

            if policy == "outer_pid":
                budget, supervisor = supervisor.advance(pstdev(predicted) / fmean(predicted))
            elif policy in {"adaptive", "gradient"}:
                budget = migration_budget(predicted)
            else:
                budget = 2 if policy == "fixed_two" else 6

            buckets = balance_variance(buckets, costs, max_migrations=budget, limit_churn=policy not in {"fixed_two", "fixed_six"})

        owners = {route.unit_key: worker for worker, assigned in buckets.items() for route in assigned}
        loads = tuple(sum(observed[route.unit_key] for route in assigned) for assigned in buckets.values())
        mean = fmean(loads)
        prediction_error = sum(abs(observed[key] - costs[key]) for key in costs) / sum(observed.values())
        samples.append(
            Sample(
                scenario,
                policy,
                seed,
                run,
                pstdev(loads) / mean,
                max(loads) / mean,
                prediction_error,
                sum(before[key] != worker for key, worker in owners.items()),
                budget,
                loads,
                max(0.0, (max(observed.values()) - mean) / (mean * math.sqrt(5))),
            )
        )

        # Every unit is observed exactly once; the real pipeline accepts feedback only after validated fan-in.
        update = gradient_feedback if policy == "gradient" else update_feedback
        feedback = {key: update(feedback.get(key), seconds, owners[key]) for key, seconds in observed.items()}

    return samples
