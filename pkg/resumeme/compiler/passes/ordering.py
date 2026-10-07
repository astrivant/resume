"""
Select and order enabled sections for templates and navigation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from resumeme.compiler.asts.sections import section_key

if TYPE_CHECKING:
    from resumeme.compiler.asts.profile import Section

__all__ = ["order_sections"]


def order_sections(sections: list[Section], order: list[str]) -> list[Section]:
    """
    Apply configured priorities after filtering and synthesis while preserving ties.

    Args:
        sections (list[Section]): Visible sections, including generated Projects and Skills.
        order (list[str]): Enabled keys, accepting known section aliases.

    Returns:
        list[Section]: New ordered list containing only enabled keys; repeated sections retain their relative source order.
    """
    priorities: dict[str, int] = {}

    # Aliases can name the same section; the first occurrence owns its requested position.
    for key in order:
        priorities.setdefault(section_key(key), len(priorities))

    return sorted(
        (section for section in sections if section_key(section.key) in priorities),
        key=lambda section: priorities[section_key(section.key)],
    )
