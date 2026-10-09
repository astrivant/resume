"""
Provide stable repository and fixture paths to categorized tests.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["REPOSITORY_ROOT", "TEST_FIXTURES"]

# Resolve repository inputs from this stable module, not from a test's category depth.
REPOSITORY_ROOT: Path = Path(__file__).resolve().parents[3]
TEST_FIXTURES: Path = Path(__file__).resolve().parent / "fixtures"
