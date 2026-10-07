"""
Prepare compact project affiliations and linked headings for the PDF template.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from attrs import evolve, frozen

from resumeme.latex.media import employer_badge, image_role
from resumeme.linkedin.dates import employment_period
from resumeme.models import Entry, Media

if TYPE_CHECKING:
    from resumeme.models import Profile

__all__ = ["ProjectLayout", "company_logos", "project_layout"]


@frozen
class ProjectLayout:
    """
    Own a project display copy and its inline company-logo placements.

    Attributes:
        entry (Entry): Project with moved logos and redundant reference rows removed.
        title_url (str): Observed destination for the project heading, or empty when absent.
        affiliations (dict[str, tuple[str, str, Media]]): Original association line mapped to prefix, company name, and logo.
        metadata (list[str]): Dates and affiliations displayed above the project media.
        description (list[str]): Project prose displayed below its image or logo.
    """

    entry: Entry
    title_url: str
    affiliations: dict[str, tuple[str, str, Media]]
    metadata: list[str]
    description: list[str]


def _company_key(value: str) -> str:
    """
    Compare company names while preserving their captured display spelling.

    Args:
        value (str): Company name from an employment or project association.

    Returns:
        str: Whitespace-normalized, case-folded name without a trailing period.
    """
    return " ".join(value.split()).casefold().rstrip(".")


def company_logos(profile: Profile) -> dict[str, Media]:
    """
    Index staged employer logos from visible employment for reuse by associated projects.

    Args:
        profile (Profile): Display profile after section/job exclusions and asset staging.

    Returns:
        dict[str, Media]: Normalized employer names mapped to their captured, staged branding.
    """
    result: dict[str, Media] = {}

    for section in profile.sections:
        if section.key != "experience":
            continue

        for entry in section.entries:
            badge = employer_badge(entry)

            if badge:
                index, logo = badge
                company = entry.title if index == -1 else entry.paragraphs[index].split("·", 1)[0]
                result.setdefault(_company_key(company), logo)

    return result


def project_layout(entry: Entry, *, companies: dict[str, Media], show_title: bool = True) -> ProjectLayout:
    """
    Place known company logos beside affiliations and replace duplicate links with linked project titles.

    Args:
        entry (Entry): Consolidated project with staged assets and resolved image destinations.
        companies (dict[str, Media]): Logos belonging to visible employers, indexed by normalized company name.
        show_title (bool): Whether the project heading will render and can carry its destination.

    Returns:
        ProjectLayout: Template-only presentation retaining source descriptions and otherwise unrepresented destinations.
    """
    associations = {
        line: line.removeprefix("Associated with ").rsplit(" at ", 1)[-1]
        for line in entry.paragraphs
        if line.startswith("Associated with ")
    }
    names = {_company_key(company) for company in associations.values()}
    logos = dict(companies)

    # A blank image label is common in LinkedIn project captures; use it only when the project names one unambiguous employer.
    for image in entry.images:
        if image_role(image) != "logo":
            continue

        name = _company_key(re.sub(r"\s+logo$", "", image.alt, flags=re.IGNORECASE))

        if name in {"", "logo"} and len(names) == 1:
            name = next(iter(names))

        if name in names:
            known = logos.get(name)
            logos[name] = evolve(image, link=image.link or (known.link if known else ""))

    affiliations = {
        line: (line[: -len(company)], company, logos[key])
        for line, company in associations.items()
        if (key := _company_key(company)) in logos
    }
    placed = {logo.url for _, _, logo in affiliations.values()}
    images = [image for image in entry.images if image.url not in placed]
    company_urls = {logo.link for _, _, logo in affiliations.values() if logo.link}
    candidates = [link for link in entry.links if (link.resolved_url or link.url) not in company_urls]
    # A suppressed duplicate heading cannot replace a reference link; its destination still needs an image or text row.
    title_url = (candidates[0].resolved_url or candidates[0].url) if candidates and show_title else ""
    covered = {title_url, *company_urls, *(image.link for image in images if image.link)} - {""}

    # Standalone URL rows duplicate the clickable heading or illustration; inline prose retains its wording and references.
    redundant = covered | {link.url for link in entry.links if (link.resolved_url or link.url) in covered}
    paragraphs = [line for line in entry.paragraphs if line.strip() not in redundant]
    displayed = {_company_key(text) for text in [entry.title, *paragraphs]}

    # Keep useful descriptions as body text, even when their destination is already supplied by the title or a preview.
    for link in candidates:
        if (link.resolved_url or link.url) not in covered:
            continue

        caption = link.title if link.label == link.url else link.label
        caption = re.sub(r"^GitHub - [^/\s]+/[^:\s]+:\s*", "", caption)

        if caption and _company_key(caption) not in displayed:
            paragraphs.append(caption)
            displayed.add(_company_key(caption))

    links = [link for link in entry.links if (link.resolved_url or link.url) not in covered]

    # Keep identity and role associations beside the heading; descriptions follow the image they explain.
    metadata = [line for line in paragraphs if line.startswith("Associated with ") or line == "Featured project" or employment_period(line)]
    description = [line for line in paragraphs if line not in metadata]
    return ProjectLayout(evolve(entry, paragraphs=paragraphs, images=images, links=links), title_url, affiliations, metadata, description)
