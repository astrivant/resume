"""
Discover web references in profile prose without changing its text or performing requests.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlsplit

from attrs import evolve

from resumeme.compiler.asts.profile import Link
from resumeme.compiler.constants.links import WEB_URL as _WEB_URL

if TYPE_CHECKING:
    from collections.abc import Iterable

    from resumeme.compiler.asts.profile import Entry, Profile

__all__ = ["discover_profile_links", "merge_text_links", "safe_url", "text_links"]


def safe_url(value: str, base: str = "https://www.linkedin.com") -> str:
    """
    Normalize navigable web links and discard scripts, credentials, and standalone fragments.

    Args:
        value (str): Raw link or image source.
        base (str): Base used to resolve relative URLs.

    Returns:
        str: Absolute HTTP URL, or an empty string when unsuitable.
    """

    if not value or value.startswith("#"):
        return ""

    # Validate before any consumer fetches or embeds the URL; preserve anchors belonging to complete destinations.
    absolute = urljoin(base, value)

    try:
        parsed = urlsplit(absolute)

        if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
            return ""
    except ValueError:
        return ""

    if re.search(r"[\s{}\\]", absolute):
        return ""

    return absolute


def text_links(value: str) -> list[tuple[int, int, Link]]:
    """
    Locate explicit HTTP(S) and www references while retaining surrounding prose punctuation.

    Args:
        value (str): Unmodified profile text.

    Returns:
        list[tuple[int, int, Link]]: Start offset, exclusive end offset, and normalized reference for each occurrence.
    """
    result: list[tuple[int, int, Link]] = []

    for match in _WEB_URL.finditer(value):
        label = match.group().rstrip(".,;:!?")

        # Remove sentence delimiters while preserving balanced parentheses inside destinations such as wiki page names.
        while label and label[-1] in ")]":
            closing = label[-1]
            opening = {")": "(", "]": "["}[closing]

            if label.count(closing) <= label.count(opening):
                break

            label = label[:-1].rstrip(".,;:!?")

        url = safe_url("https://" + label if label.lower().startswith("www.") else label)

        if url:
            result.append((match.start(), match.start() + len(label), Link(label, url)))

    return result


def merge_text_links(links: list[Link], lines: Iterable[str]) -> list[Link]:
    """
    Add prose references once without replacing captured labels or resolved metadata.

    Args:
        links (list[Link]): Explicit references in capture order.
        lines (Iterable[str]): Text belonging to the same profile block.

    Returns:
        list[Link]: Existing references followed by previously unrecorded text destinations.
    """
    result = {link.url: link for link in links}

    for line in lines:
        for _, _, link in text_links(line):
            result.setdefault(link.url, link)

    return list(result.values())


def discover_profile_links(profile: Profile) -> Profile:
    """
    Discover prose URLs in headers, sections, and grouped roles, including older saved snapshots.

    Args:
        profile (Profile): Snapshot whose original text and captured references must be retained.

    Returns:
        Profile: Independent snapshot with additional structured links and no network side effects.
    """

    def entry_links(entry: Entry) -> Entry:
        """
        Preserve role ownership while collecting URLs from an entry's full text.

        Args:
            entry (Entry): Section entry or nested role.

        Returns:
            Entry: Entry with deduplicated references and recursively updated roles.
        """
        return evolve(
            entry,
            links=merge_text_links(entry.links, [entry.title, *entry.paragraphs]),
            positions=[entry_links(position) for position in entry.positions],
        )

    return evolve(
        profile,
        links=merge_text_links(profile.links, profile.intro),
        sections=[evolve(section, entries=[entry_links(entry) for entry in section.entries]) for section in profile.sections],
    )
