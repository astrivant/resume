"""
Select the same visible profile evidence for document compilation and summary generation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from attrs import evolve

from resumeme.compiler.asts.sections import section_key
from resumeme.compiler.passes.education import filter_education
from resumeme.compiler.passes.experience import clean_experience, filter_experience

if TYPE_CHECKING:
    from datetime import date

    from resumeme.compiler.asts.profile import Profile
    from resumeme.config import Config

__all__ = ["visible_profile"]


def visible_profile(profile: Profile, config: Config, *, today: date | None = None) -> Profile:
    """
    Apply section, employment, and education exclusions without modifying the captured snapshot.

    Args:
        profile (Profile): Validated profile snapshot.
        config (Config): Enabled sections, job and education exclusions, and inclusive employment window.
        today (date | None): Explicit date for an unpinned employment window; unused without date filtering.

    Returns:
        Profile: Retained sections and entries in capture order.
    """
    enabled = {section_key(key) for key in config.section_order}

    # Filter before any consumer can score, summarize, or stage excluded content.
    return evolve(
        profile,
        sections=[
            evolve(
                section,
                key=section_key(section.key),
                entries=[clean_experience(entry) for entry in filter_experience(section.entries, config.experience, today=today)]
                if section_key(section.key) == "experience"
                else filter_education(section.entries, config.education)
                if section_key(section.key) == "education"
                else section.entries,
            )
            for section in profile.sections
            if section_key(section.key) in enabled
        ],
    )
