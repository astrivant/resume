"""
Separate profile identity text from optional LinkedIn connection metadata.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from attrs import evolve

from resumeme.compiler.constants.header import COUNT as _COUNT
from resumeme.compiler.constants.header import LEGACY_HEADLINE
from resumeme.compiler.constants.header import PRONOUNS as _PRONOUNS
from resumeme.compiler.passes.media import image_role

if TYPE_CHECKING:
    from resumeme.compiler.asts.profile import Media, Profile
    from resumeme.config import Style

__all__ = ["is_pronouns", "prepare_header", "prepare_header_logos"]


def is_pronouns(value: str) -> bool:
    """
    Identify captured pronoun lines without inferring pronouns from other identity fields.

    Args:
        value (str): One captured introductory line.

    Returns:
        bool: Whether the line explicitly labels pronouns or contains a recognized slash-separated pronoun set.
    """
    normalized = " ".join(value.split()).strip("() ")

    # Explicit labels also support custom pronouns; technical slash-separated text such as CI/CD stays in the ordinary intro.
    return (
        normalized.casefold().startswith("pronouns:")
        or normalized.casefold() in {"any pronouns", "all pronouns", "any/all"}
        or _PRONOUNS.fullmatch(normalized) is not None
    )


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
        elif line.casefold() not in {"contact info", "edit contact info", "connections", "\u00b7"}:
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

    # Omit the standalone header reference list; inline prose links are resolved separately by the renderer.
    if not style.show_headline:
        headline = profile.headline

        # Older snapshots lack an explicit headline field. Only recognize an initial role-at-company phrase;
        # removing the first arbitrary row could discard a minimal profile's employer or location.
        if not headline:
            first = next((line for line in intro if not is_pronouns(line)), "")
            headline = first if LEGACY_HEADLINE.search(first) else ""

        intro = [line for line in intro if not headline or " ".join(line.split()) != " ".join(headline.split())]

    return (
        evolve(profile, intro=intro, links=[], headline=profile.headline if style.show_headline else ""),
        count if style.show_connection_count else "",
        destination if style.show_connection_link else "",
    )


def prepare_header_logos(profile: Profile, *, companies: dict[str, Media]) -> tuple[Profile, dict[str, Media]]:
    """
    Pair header logos with observed company names without guessing an unlabeled image's owner.

    Args:
        profile (Profile): Staged display profile whose identity fields remain available to the caller.
        companies (dict[str, Media]): Normalized employer names and staged logos from visible Experience entries.

    Returns:
        tuple[Profile, dict[str, Media]]: Header copy with matched logos moved into badges and repeated company names removed.
    """
    names: dict[str, str] = {}

    for line in profile.intro:
        names.setdefault(" ".join(line.split()).casefold().rstrip("."), line.strip())

    badges: dict[str, Media] = {}
    remaining: list[Media] = []

    for image in profile.images:
        if image_role(image, header=True) != "logo":
            remaining.append(image)
            continue

        # A staged path identifies identical image bytes, including unlabeled header logos in older snapshots.
        matches = {
            company: logo
            for company, logo in companies.items()
            if company in names and ((image.path and image.path == logo.path) or image.url == logo.url)
        }
        label = " ".join(image.alt.split()).casefold().removesuffix(" logo").rstrip(".")
        candidates = ({label} if label and label in names else set()) | set(matches)

        # Keep ambiguous or unmatched imagery in its original position rather than attaching it to unrelated intro prose.
        if len(candidates) != 1:
            remaining.append(image)
            continue

        company = candidates.pop()
        observed = matches.get(company)
        destination = image.link or (observed.link if observed else "")
        badges.setdefault(names[company], evolve(image, link=destination))

    # Repeated company text is common in LinkedIn's header; display each matched organization once alongside its logo.
    intro: list[str] = []
    displayed: set[str] = set()

    for line in profile.intro:
        normalized = " ".join(line.split()).casefold().rstrip(".")
        canonical = names[normalized]

        if canonical in badges:
            if normalized in displayed:
                continue

            displayed.add(normalized)

        intro.append(line)

    return evolve(profile, intro=intro, images=remaining), badges
