"""
Read displayed skill labels and endorsement totals without inferring hidden counts.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from resumeme.compiler.asts.profile import Skill
from resumeme.compiler.constants.skills import ENDORSEMENTS as _ENDORSEMENTS

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = ["endorsement_count", "skill_labels"]


def endorsement_count(lines: Iterable[str]) -> int:
    """
    Use the largest displayed total rather than summing duplicate endorsement rows.

    Args:
        lines (Iterable[str]): Skill text or accessible labels from the captured browser.

    Returns:
        int: Observed total, or zero when absent. A displayed 99+ contributes the known lower bound 99.
    """

    # Visible text and accessibility labels often repeat the same total; summing them would inflate the cloud's weights.
    return max((int(match[1].replace(",", "")) for line in lines for match in _ENDORSEMENTS.finditer(line)), default=0)


def skill_labels(value: str) -> list[Skill]:
    """
    Extract visible association labels without treating a collapsed remainder as a skill.

    Args:
        value (str): LinkedIn association text, such as Python, Leadership and +3 skills.

    Returns:
        list[Skill]: Named associations only; undisplayed skills are never invented.
    """

    # A collapsed remainder describes undisplayed skills, not another label or evidence for their individual names.
    value = re.sub(r"\s*(?:and\s+)?\+\d+\s+skills?\s*$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^skills:\s*", "", value, flags=re.IGNORECASE)
    return [Skill(name=name) for part in value.split(",") if (name := part.strip()) and not re.fullmatch(r"\d+\s+skills?", name)]
