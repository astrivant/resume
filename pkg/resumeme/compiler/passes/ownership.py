"""
Remove release-ownership metadata from printable profile text.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from attrs import evolve

from resumeme.compiler.asts.links import text_links
from resumeme.compiler.asts.sections import section_key
from resumeme.compiler.constants.ownership import OWNERSHIP_FIELD

if TYPE_CHECKING:
    from collections.abc import Iterator

    from resumeme.compiler.asts.profile import Entry, Link, Profile

__all__ = ["without_ownership_metadata"]


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
        match = OWNERSHIP_FIELD.match(line)

        if match:
            removed_labels.add(" ".join(match[1].casefold().split()))
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


def _walk_entries(entries: list[Entry]) -> Iterator[Entry]:
    """
    Visit all About records in source order, including nested captures.

    Args:
        entries (list[Entry]): Finite captured About tree.

    Yields:
        Entry: Each parent followed by its nested records.
    """
    for entry in entries:
        yield entry
        yield from _walk_entries(entry.positions)


def _linked_destinations(urls: set[str], links: list[Link]) -> set[str]:
    """
    Resolve equivalent destinations using only observed original/resolved link pairs.

    Args:
        urls (set[str]): Initial destinations owned by removed or retained prose.
        links (list[Link]): Captured redirect evidence; no network requests are performed.

    Returns:
        set[str]: Finite closure of known aliases, including the original destinations.
    """
    result = set(urls)

    # The set grows monotonically over captured URL pairs; redirect cycles cannot prolong traversal indefinitely.
    while True:
        before = len(result)

        for link in links:
            pair = {url for url in (link.url, link.resolved_url) if url}

            if pair & result:
                result.update(pair)

        if len(result) == before:
            return result


def _removed_destinations(entries: list[Entry]) -> set[str]:
    """
    Classify managed links across an entire About tree before filtering any record.

    Args:
        entries (list[Entry]): Records whose footer prose and preview can be stored in separate entries.

    Returns:
        set[str]: Removed destinations and their captured aliases, excluding references still used by personal prose.
    """
    removed: set[str] = set()
    kept: set[str] = set()
    labels: set[str] = set()
    links: list[Link] = []

    for entry in _walk_entries(entries):
        links.extend(entry.links)

        for value in (entry.title, *entry.paragraphs):
            text, urls, fields = _clean_text(value)
            removed.update(urls)
            labels.update(fields)
            kept.update(link.url for _, _, link in text_links(text))

    # A captured field label can identify a link even when LinkedIn puts its destination outside the prose node.
    for link in links:
        if " ".join(link.label.casefold().split()).rstrip(":") in labels:
            removed.update(url for url in (link.url, link.resolved_url) if url)

    return _linked_destinations(removed, links) - _linked_destinations(kept, links)


def _clean_entry(entry: Entry, removed: set[str]) -> Entry | None:
    """
    Filter managed lines from one About entry and discard their links and preview images.

    Args:
        entry (Entry): Captured About entry.
        removed (set[str]): Destinations owned exclusively by managed fields across the About tree.

    Returns:
        Entry | None: Clean entry, or None when it contained no printable content.
    """
    title = _clean_text(entry.title)[0]
    paragraphs: list[str] = []

    for paragraph in entry.paragraphs:
        cleaned = _clean_text(paragraph)[0]

        if cleaned:
            paragraphs.append(cleaned)

    links = [link for link in entry.links if not {link.url, link.resolved_url} & removed]
    images = [image for image in entry.images if image.link not in removed]

    # Recursively handle unusually nested entries without discarding their unrelated content.
    positions = [cleaned_position for position in entry.positions if (cleaned_position := _clean_entry(position, removed)) is not None]
    result = evolve(entry, title=title, paragraphs=paragraphs, links=links, images=images, positions=positions)

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

    # Classify the complete section first: capture markup can separate managed prose, links, and previews into siblings.
    removed = {
        index: _removed_destinations(section.entries)
        for index, section in enumerate(profile.sections)
        if section_key(section.key) == "about"
    }

    # Restrict entry cleanup to About so identically labeled text in other sections remains source-owned.
    sections = [
        evolve(
            section,
            entries=[cleaned for entry in section.entries if (cleaned := _clean_entry(entry, removed[index])) is not None],
        )
        if index in removed
        else section
        for index, section in enumerate(profile.sections)
    ]

    return evolve(profile, intro=intro, sections=sections)
