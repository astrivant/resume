"""
Remove release-ownership metadata from printable profile text.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from attrs import evolve

from resumeme.compiler.asts.links import text_links

if TYPE_CHECKING:
    from resumeme.compiler.asts.profile import Entry, Profile

__all__ = ["without_ownership_metadata"]
_OWNERSHIP_FIELD = re.compile(r"^\s*(resume signature|releases)\s*:", re.IGNORECASE)


def _clean_text(value: str) -> tuple[str, set[str], set[str]]:
    """
    Remove a managed About line while retaining any adjacent personal prose.

    Args:
        value (str): One profile text field.

    Returns:
        tuple[str, set[str], set[str]]: Clean text, removed release URLs, and removed field labels.
    """
    kept: list[str] = []
    removed_urls: set[str] = set()
    removed_labels: set[str] = set()

    for line in value.splitlines():
        match = _OWNERSHIP_FIELD.match(line)

        if match:
            removed_labels.add(match[1].casefold())
            removed_urls.update(link.url for _, _, link in text_links(line))
        else:
            kept.append(line)

    # Preserve the source exactly when no managed field was present, including spaces that encode nested list depth.
    if not removed_labels:
        return value, removed_urls, removed_labels

    # Trim blank boundary lines after filtering without stripping meaningful indentation from retained prose.
    while kept and not kept[0].strip():
        kept.pop(0)

    while kept and not kept[-1].strip():
        kept.pop()

    return "\n".join(kept), removed_urls, removed_labels


def _clean_entry(entry: Entry) -> Entry | None:
    """
    Filter managed lines from one About entry and discard only links owned by those lines.

    Args:
        entry (Entry): Captured About entry.

    Returns:
        Entry | None: Clean entry, or None when it contained no printable content.
    """
    title, removed_urls, removed_labels = _clean_text(entry.title)
    paragraphs: list[str] = []

    for paragraph in entry.paragraphs:
        cleaned, urls, labels = _clean_text(paragraph)
        removed_urls.update(urls)
        removed_labels.update(labels)

        if cleaned:
            paragraphs.append(cleaned)

    kept_urls = {link.url for value in [title, *paragraphs] for _, _, link in text_links(value)}
    links = [
        link
        for link in entry.links
        if link.url not in removed_urls and not (link.label.strip().casefold() in removed_labels and link.url not in kept_urls)
    ]

    # Recursively handle unusually nested entries without discarding their unrelated content.
    positions = [cleaned_position for position in entry.positions if (cleaned_position := _clean_entry(position)) is not None]
    result = evolve(entry, title=title, paragraphs=paragraphs, links=links, positions=positions)

    return result if title or paragraphs or links or result.images or result.skills or positions else None


def without_ownership_metadata(profile: Profile) -> Profile:
    """
    Exclude managed signature and release lines from the PDF view of About.

    Captured profile data remains intact, so local snapshots and future capture
    validation still contain the complete LinkedIn profile.

    Args:
        profile (Profile): Filtered display copy passed to the selected renderer.

    Returns:
        Profile: Independent copy with ownership lines absent from its intro and About entries.
    """
    intro = [_clean_text(line)[0] for line in profile.intro]
    intro = [line for line in intro if line]

    # Restrict entry cleanup to About so identically labeled text in other sections remains source-owned.
    sections = [
        evolve(
            section,
            entries=[cleaned for entry in section.entries if (cleaned := _clean_entry(entry)) is not None],
        )
        if section.key.casefold() == "about"
        else section
        for section in profile.sections
    ]

    return evolve(profile, intro=intro, sections=sections)
