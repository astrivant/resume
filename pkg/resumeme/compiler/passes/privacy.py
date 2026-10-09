"""
Remove personal profile-location fields when a resume opts out of publishing them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from attrs import evolve

from resumeme.compiler.constants.contact import ADDRESS_FIELDS, CONTACT_FIELD
from resumeme.compiler.passes.header import is_pronouns
from resumeme.compiler.passes.locations import is_location_line

if TYPE_CHECKING:
    from resumeme.compiler.asts.profile import Entry, Profile

__all__ = ["without_profile_location"]


def _without_contact_address(entry: Entry) -> Entry | None:
    """
    Remove address fields within a captured dialog while retaining neighboring contact fields.

    Args:
        entry (Entry): Standalone contact field or flattened dialog with labeled field boundaries.

    Returns:
        Entry | None: Sanitized copy, the original when no address exists, or None when nothing remains.
    """
    retained: list[str] = []
    removed: list[str] = []
    hiding = False

    # A recognized label ends the previous field; inline values and multiline DOM text use the same boundary rule.
    for paragraph in [entry.title, *entry.paragraphs]:
        for line in paragraph.splitlines():
            field = CONTACT_FIELD.fullmatch(" ".join(line.split()))

            if field:
                hiding = field["label"].casefold() in ADDRESS_FIELDS

            (removed if hiding else retained).append(line)

    if not removed:
        return entry

    if not any(line.strip() for line in retained):
        return None

    # Flattened captures do not retain DOM ownership for references. Keep only those evidenced by surviving fields,
    # so an orphaned Maps link or address image cannot publish a value removed from the text.
    visible = " ".join(" ".join(retained).split()).casefold()
    hidden = " ".join(" ".join(removed).split()).casefold()

    def owned(value: str) -> bool:
        """
        Match a reference to surviving text without accepting ambiguous address-owned labels.

        Args:
            value (str): Observed label, URL, or image alternative text.

        Returns:
            bool: Whether nonempty normalized text belongs only to the retained contact fields.
        """
        normalized = " ".join(value.split()).casefold()
        return bool(normalized and normalized in visible and normalized not in hidden)

    links = [link for link in entry.links if any(owned(value) for value in (link.label, link.url, link.resolved_url))]
    destinations = {value for link in links for value in (link.url, link.resolved_url) if value}
    images = [image for image in entry.images if owned(image.alt) or image.link in destinations]
    return evolve(entry, title=retained[0], paragraphs=retained[1:], links=links, images=images)


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

        # LinkedIn may flatten every contact field into one entry; redact field boundaries instead of the whole dialog.
        entries = [cleaned for entry in section.entries if (cleaned := _without_contact_address(entry)) is not None]
        sections.append(evolve(section, entries=entries))

    return evolve(profile, intro=intro, headline=headline, sections=sections)
