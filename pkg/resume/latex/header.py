"""
Separate profile identity text from optional LinkedIn connection metadata.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from attrs import evolve

if TYPE_CHECKING:
    from resume.config import Style
    from resume.models import Profile

__all__ = ["prepare_header"]

_COUNT = re.compile(r"^[\d][\d,.\s]*[km]?\+?\s+connections?$", re.IGNORECASE)


def prepare_header(profile: Profile, style: Style) -> tuple[Profile, str, str]:
    """
    Remove repeated navigation and expose observed connection details only when enabled.

    Args:
        profile (Profile): Visible snapshot whose original header remains available to the caller.
        style (Style): Effective style after inline theme overrides.

    Returns:
        tuple[Profile, str, str]: Clean header view, optional count label, and optional captured connections URL.
    """
    intro: list[str] = []
    count = ""
    destination = ""
    index = 0

    # Counts may be one text node or split between a number and the word "connections" in older captures.
    while index < len(profile.intro):
        line = " ".join(profile.intro[index].split())
        combined = " ".join([line, profile.intro[index + 1]]) if index + 1 < len(profile.intro) else ""

        if _COUNT.fullmatch(line):
            count = count or line
        elif _COUNT.fullmatch(combined):
            count = count or combined
            index += 1
        elif line.casefold() not in {"contact info", "edit contact info", "connections", "·"}:
            intro.append(profile.intro[index])

        index += 1

    # Use only the owner's observed LinkedIn navigation; never invent a count or substitute an external lookalike URL.
    for link in profile.links:
        parsed = urlsplit(link.resolved_url or link.url)
        host = parsed.hostname or ""
        label = " ".join(link.label.split())

        if host != "linkedin.com" and not host.endswith(".linkedin.com"):
            continue

        if "connections" in parsed.path.strip("/").split("/") or _COUNT.fullmatch(label):
            destination = destination or link.resolved_url or link.url

            if _COUNT.fullmatch(label):
                count = count or label

    # Standalone header links repeat the canonical profile link; inline prose links are resolved separately by the renderer.
    return (
        evolve(profile, intro=intro, links=[]),
        count if style.show_connection_count else "",
        destination if style.show_connection_link else "",
    )
