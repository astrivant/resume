"""
Filter academic entries before rendering, skill scoring, or summary generation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from resumeme.compiler.asts.dates import employment_period
from resumeme.compiler.passes.selection import matches_fields

if TYPE_CHECKING:
    from resumeme.compiler.asts.profile import Entry
    from resumeme.config import Education

__all__ = ["filter_education"]


def _normalized(value: str) -> str:
    """
    Compare literal education labels despite case, spacing, and typographic apostrophes.

    Args:
        value (str): Captured label or user-supplied selector.

    Returns:
        str: Case-folded label with collapsed whitespace and straight apostrophes.
    """
    return " ".join(value.casefold().split()).replace("\u2019", "'").replace("\u2018", "'")


def filter_education(entries: list[Entry], settings: Education) -> list[Entry]:
    """
    Exclude complete entries matching any school, degree, or major selector.

    Args:
        entries (list[Entry]): Captured schools with qualification metadata before dates and descriptive prose.
        settings (Education): Literal exclusions, combining fields within a selector with AND.

    Returns:
        list[Entry]: Retained entries in capture order, with their original text, links, images, and skills.
    """
    if not settings.disable:
        return list(entries)

    visible: list[Entry] = []

    for entry in entries:
        school = _normalized(entry.title)

        # LinkedIn renders degree and field of study together before dates; later descriptions must never become selectors.
        first = next((line.strip() for paragraph in entry.paragraphs for line in paragraph.splitlines() if line.strip()), "")
        qualification = "" if employment_period(first) is not None else _normalized(first)
        degree, separator, major = qualification.partition(",")
        degree, major = degree.strip(), major.strip()

        # A lone qualification has no reliable degree/major boundary, so either field may select that complete value.
        if not separator:
            major = degree

        disabled = any(
            matches_fields(
                (selector.school, (school,), _normalized),
                (selector.degree, (degree, qualification), _normalized),
                (selector.major, (major,), _normalized),
            )
            for selector in settings.disable
        )

        if not disabled:
            visible.append(entry)

    return visible
