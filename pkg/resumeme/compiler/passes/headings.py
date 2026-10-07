"""
Suppress redundant child headings without changing captured content or hierarchy.
"""

from __future__ import annotations

from unicodedata import normalize

__all__ = ["distinct_heading"]


def distinct_heading(title: str, parent: str) -> str:
    """
    Keep a child heading only when its text differs from its immediate parent.

    Args:
        title (str): Captured child heading before LaTeX escaping.
        parent (str): Visible parent heading, not a section key or another entry's title.

    Returns:
        str: Original child text, or empty when normalized heading text matches its parent.
    """

    # Compare Unicode presentation forms, case, and whitespace; preserve punctuation and qualifiers that carry meaning.
    child_key = " ".join(normalize("NFKC", title).split()).casefold()
    parent_key = " ".join(normalize("NFKC", parent).split()).casefold()
    return "" if child_key == parent_key else title
