"""
Refine a measured capture schedule through discrete descent on shard load variance.
"""

from __future__ import annotations

from itertools import combinations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from resumeme.linkedin.capture.shards import CaptureRoute

__all__ = ["balance_variance"]
_MAX_MIGRATIONS = 2
_MIN_STDDEV_IMPROVEMENT = 0.05


def balance_variance(buckets: dict[int, list[CaptureRoute]], costs: dict[str, float]) -> dict[int, list[CaptureRoute]]:
    """
    Move or swap whole routes to reduce variance without increasing the slowest predicted shard.

    Args:
        buckets (dict[int, list[CaptureRoute]]): Initial LPT assignment, left unchanged.
        costs (dict[str, float]): Positive traversal estimates in seconds for every route.

    Returns:
        dict[int, list[CaptureRoute]]: Deterministically improved assignment, limited to two route migrations per run.
    """
    result = {index: list(routes) for index, routes in buckets.items()}
    loads = {index: sum(costs[route.unit_key] for route in routes) for index, routes in result.items()}

    # The mean is fixed by total work / worker count, so lowering sum(load**2) also lowers variance and standard deviation.
    migrations = 0

    while migrations < _MAX_MIGRATIONS:
        tolerance = 1e-12 * max(1.0, sum(load * load for load in loads.values()))
        mean = sum(loads.values()) / len(loads)
        deviation = sum((load - mean) ** 2 for load in loads.values())
        improvement = max(tolerance, deviation * (1 - (1 - _MIN_STDDEV_IMPROVEMENT) ** 2))
        choice: tuple[int, int, CaptureRoute | None, CaptureRoute | None] | None = None
        ceiling = max(loads.values())

        # None represents an empty exchange slot, allowing both one-route moves and two-route swaps in the same neighborhood.
        for first, second in combinations(sorted(result), 2):
            left_options = [None, *sorted(result[first], key=lambda route: route.unit_key)]
            right_options = [None, *sorted(result[second], key=lambda route: route.unit_key)]

            for left in left_options:
                for right in right_options:
                    changes = int(left is not None) + int(right is not None)

                    if migrations + changes > _MAX_MIGRATIONS:
                        continue

                    transfer = (costs[left.unit_key] if left else 0.0) - (costs[right.unit_key] if right else 0.0)
                    left_load, right_load = loads[first] - transfer, loads[second] + transfer
                    gain = 2 * transfer * (loads[first] - loads[second] - transfer)

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
