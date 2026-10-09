"""
Remove personal profile-location fields when a resume opts out of publishing them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from attrs import evolve

from resumeme.compiler.passes.header import is_pronouns
from resumeme.compiler.passes.locations import is_location_line

if TYPE_CHECKING:
    from resumeme.compiler.asts.profile import Profile

__all__ = ["without_profile_location"]

_ADDRESS_LABELS = {"address", "home address", "mailing address", "location"}


def without_profile_location(profile: Profile) -> Profile:
    """
    Remove the profile's standalone location and labeled contact-address entries.

    Employment locations remain intact because hiring managers may need them to understand each role.

    Args:
        profile (Profile): Captured or visible profile to sanitize.

    Returns:
        Profile: A copy without personal profile-location data.
    """
    intro = [line for line in profile.intro if is_pronouns(line) or not is_location_line(line)]
    headline = "" if is_location_line(profile.headline) else profile.headline
    sections = []

    for section in profile.sections:
        if section.key != "contact":
            sections.append(section)
            continue

        # Strip an entire labeled entry so its address cannot survive in a separate value or hyperlink.
        entries = [
            entry
            for entry in section.entries
            if not any(value.strip().rstrip(":").casefold() in _ADDRESS_LABELS for value in [entry.title, *entry.paragraphs])
        ]
        sections.append(evolve(section, entries=entries))

    return evolve(profile, intro=intro, headline=headline, sections=sections)
