"""
Normalize known profile section aliases while preserving unfamiliar sections.
"""

from __future__ import annotations

import re

from resumeme.compiler.constants.sections import ALIASES as _ALIASES
from resumeme.compiler.constants.sections import SECTION_TITLES

__all__ = ["SECTION_TITLES", "section_key"]


def section_key(value: str) -> str:
    """
    Give route identifiers and display headings the same stable exclusion key.

    Args:
        value (str): Section heading, anchor, route key, or configured exclusion.

    Returns:
        str: Canonical key for a known section, or the normalized unfamiliar key.
    """

    # Normalize known aliases without treating the catalog as a whitelist; unfamiliar LinkedIn sections remain representable.
    key = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return _ALIASES.get(key, key)
