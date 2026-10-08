"""
Represent proposed profile skills separately from captured skills and peer endorsements.
"""

from __future__ import annotations

import json
from importlib.resources import files

from attrs import frozen

from resumeme.compiler.constants.backend import AST_PACKAGE, SKILL_SUGGESTIONS_SCHEMA

__all__ = ["SkillSuggestion", "SkillSuggestions", "skill_suggestions_schema"]


@frozen
class SkillSuggestion:
    """
    Bind a proposed skill to a supporting quote from the visible captured profile.

    Attributes:
        name (str): Plain-text skill name, preserving observed spelling.
        evidence (str): Supporting captured text containing the skill name.
    """

    name: str
    evidence: str


@frozen
class SkillSuggestions:
    """
    Associate a bounded proposal with its owner, Git tag, and generation evidence.

    Attributes:
        username (str): Configured LinkedIn owner.
        source_tag (str): Tag whose captured profile was used.
        source_digest (str): SHA-256 of the tagged revision and filtered generation input.
        skills (list[SkillSuggestion]): Ordered suggestions, with no endorsement counts.
    """

    username: str
    source_tag: str
    source_digest: str
    skills: list[SkillSuggestion]


def skill_suggestions_schema() -> dict[str, object]:
    """
    Load a fresh copy of the proposal contract shared with the Codex action.

    Returns:
        dict[str, object]: JSON Schema for the complete response.
    """
    schema: dict[str, object] = json.loads(files(AST_PACKAGE).joinpath(SKILL_SUGGESTIONS_SCHEMA).read_text(encoding="utf-8"))
    return schema
