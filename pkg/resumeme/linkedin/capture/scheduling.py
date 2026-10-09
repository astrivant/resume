"""
Refine a measured capture schedule through discrete descent on shard load variance.
"""

from __future__ import annotations

import math
from itertools import combinations
from statistics import fmean, pstdev
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from resumeme.linkedin.capture.shards import CaptureRoute

__all__ = ["balance_variance", "migration_budget"]
_MIN_MIGRATIONS = 2
_MAX_MIGRATIONS = 6
_TARGET_CV = 0.15
_FULL_BUDGET_CV = 0.60
_MIN_STDDEV_IMPROVEMENT = 0.05
_MIN_SETTLED_MAKESPAN_GAIN = 0.03
_MIN_SETTLED_SECONDS = 2.0


def migration_budget(loads: Sequence[float]) -> int:
    """
    Allow faster correction of large imbalance, returning to two migrations near the target.

    Args:
        loads (Sequence[float]): Nonnegative predicted seconds for every shard, including empty workers.

    Returns:
        int: Budget between two and six route migrations; empty or zero work uses two.

    Raises:
        ValueError: A shard load is negative or nonfinite.
    """
    if any(not math.isfinite(load) or load < 0 for load in loads):
        raise ValueError("Migration planning requires finite, nonnegative shard loads.")

    if not loads or not (mean := fmean(loads)):
        return _MIN_MIGRATIONS

    # Dimensionless dispersion makes the same policy apply to short and long profiles without persisted controller state.
    cv = pstdev(loads) / mean
    severity = min(1.0, max(0.0, (cv - _TARGET_CV) / (_FULL_BUDGET_CV - _TARGET_CV)))
    return _MIN_MIGRATIONS + math.ceil((_MAX_MIGRATIONS - _MIN_MIGRATIONS) * severity)


def balance_variance(
    buckets: dict[int, list[CaptureRoute]],
    costs: dict[str, float],
    *,
    max_migrations: int | None = None,
    limit_churn: bool = True,
) -> dict[int, list[CaptureRoute]]:
    """
    Move or swap whole routes to reduce variance without increasing the slowest predicted shard.

    Args:
        buckets (dict[int, list[CaptureRoute]]): Initial LPT or retained assignment, left unchanged.
        costs (dict[str, float]): Positive traversal estimates in seconds for every route.
        max_migrations (int | None): Explicit positive budget for controlled comparisons, or adaptive default when None.
        limit_churn (bool): Within the dispersion target, require a useful predicted makespan reduction before moving work.

    Returns:
        dict[int, list[CaptureRoute]]: Deterministically improved assignment within the selected migration budget.

    Raises:
        ValueError: An explicit migration budget is not a positive integer.
    """
    if max_migrations is not None and (type(max_migrations) is not int or max_migrations < 1):
        raise ValueError("The migration budget must be a positive integer.")

    result = {index: list(routes) for index, routes in buckets.items()}
    loads = {index: sum(costs[route.unit_key] for route in routes) for index, routes in result.items()}
    budget = migration_budget(list(loads.values())) if max_migrations is None else max_migrations

    if not result:
        return result

    # The mean is fixed by total work / worker count, so lowering sum(load**2) also lowers variance and standard deviation.
    migrations = 0

    while migrations < budget:
        tolerance = 1e-12 * max(1.0, sum(load * load for load in loads.values()))
        mean = sum(loads.values()) / len(loads)
        deviation = sum((load - mean) ** 2 for load in loads.values())
        improvement = max(tolerance, deviation * (1 - (1 - _MIN_STDDEV_IMPROVEMENT) ** 2))
        choice: tuple[int, int, CaptureRoute | None, CaptureRoute | None] | None = None
        ceiling = max(loads.values())
        settled = limit_churn and (not mean or math.sqrt(deviation / len(loads)) / mean <= _TARGET_CV)

        # None represents an empty exchange slot, allowing both one-route moves and two-route swaps in the same neighborhood.
        for first, second in combinations(sorted(result), 2):
            left_options = [None, *sorted(result[first], key=lambda route: route.unit_key)]
            right_options = [None, *sorted(result[second], key=lambda route: route.unit_key)]

            for left in left_options:
                for right in right_options:
                    changes = int(left is not None) + int(right is not None)

                    if migrations + changes > budget:
                        continue

                    transfer = (costs[left.unit_key] if left else 0.0) - (costs[right.unit_key] if right else 0.0)
                    left_load, right_load = loads[first] - transfer, loads[second] + transfer
                    gain = 2 * transfer * (loads[first] - loads[second] - transfer)

                    # Near balance, variance-only polishing is not worth ownership churn without a material time saving.
                    after_peak = max(left_load, right_load, *(load for index, load in loads.items() if index not in {first, second}))

                    if settled and ceiling - after_peak < max(_MIN_SETTLED_SECONDS, _MIN_SETTLED_MAKESPAN_GAIN * ceiling):
                        continue

                    if gain > improvement and max(left_load, right_load) <= ceiling:
                        improvement = gain
                        choice = first, second, left, right

        if choice is None:
            break

        first, second, left, right = choice
        migrations += int(left is not None) + int(right is not None)

        # Accept only strict improvement; stable iteration order resolves ties and avoids assignment churn on identical feedback.
        if left is not None:
            result[first].remove(left)
            result[second].append(left)

        if right is not None:
            result[second].remove(right)
            result[first].append(right)

        loads[first] = sum(costs[route.unit_key] for route in result[first])
        loads[second] = sum(costs[route.unit_key] for route in result[second])

    return result
