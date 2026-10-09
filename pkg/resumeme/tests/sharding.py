"""
Register CI sharding before pytest parses arguments, without changing ordinary local runs.
"""

from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    """
    Register optional one-based shard selection for local reproduction and CI.

    Args:
        parser (pytest.Parser): Shared pytest command-line parser.

    Returns:
        None: Unspecified options select the entire suite as one shard.
    """
    group = parser.getgroup("sharding")
    group.addoption("--shard-count", type=int, default=1, help="Total number of disjoint test partitions (default: 1).")
    group.addoption("--shard-index", type=int, default=1, help="One-based partition to execute (default: 1).")


def pytest_configure(config: pytest.Config) -> None:
    """
    Reject invalid shard settings before starting collection or xdist workers.

    Args:
        config (pytest.Config): Parsed pytest options.

    Returns:
        None: Every requested shard has a positive count and an index within that count.

    Raises:
        pytest.UsageError: The partition count or index is invalid.
    """
    count: int = config.getoption("--shard-count")
    index: int = config.getoption("--shard-index")

    if count < 1 or not 1 <= index <= count:
        raise pytest.UsageError("Sharding requires --shard-count >= 1 and 1 <= --shard-index <= --shard-count.")


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """
    Select a balanced round-robin partition of sorted node IDs after other collection filters.

    Args:
        config (pytest.Config): Validated shard options shared by every xdist worker.
        items (list[pytest.Item]): Collected cases, including individual parameter combinations; modified in place.

    Returns:
        None: Each collected case belongs to exactly one shard and deselections remain visible in pytest reporting.
    """
    count: int = config.getoption("--shard-count")
    index: int = config.getoption("--shard-index")

    # Preserve pytest's ordinary ordering when sharding is not requested.
    if count == 1:
        return

    ordered = sorted(items, key=lambda item: item.nodeid)
    selected = ordered[index - 1 :: count]
    deselected = [item for position, item in enumerate(ordered) if position % count != index - 1]
    items[:] = selected
    config.hook.pytest_deselected(items=deselected)
