"""
Suppress redundant child headings without changing captured content or hierarchy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unicodedata import normalize

from resumeme.compiler.constants.lists import BODY_HEADINGS

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["distinct_heading", "is_body_heading"]


def is_body_heading(text: str, *, labels: Sequence[str] = BODY_HEADINGS) -> bool:
    """
    Identify standalone subsection labels inside job descriptions without classifying sentences as headings.

    Args:
        text (str): Unmarked captured text block before LaTeX escaping.
        labels (Sequence[str]): Complete labels eligible for subsection treatment; an empty sequence disables recognition.

    Returns:
        bool: Whether the complete block is a recognized job subsection label, with an optional trailing colon.
    """
    key = " ".join(normalize("NFKC", text).split()).rstrip(":").rstrip().casefold()
    return bool(key) and any(key == " ".join(normalize("NFKC", label).split()).rstrip(":").rstrip().casefold() for label in labels)


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
