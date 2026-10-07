"""
Normalize captured company identities for presentation matching.
"""

from __future__ import annotations

__all__ = ["company_key"]


def company_key(value: str) -> str:
    """
    Compare company names while preserving their captured display spelling.

    Args:
        value (str): Company name from an employment or project association.

    Returns:
        str: Whitespace-normalized, case-folded name without a trailing period.
    """
    return " ".join(value.split()).casefold().rstrip(".")
