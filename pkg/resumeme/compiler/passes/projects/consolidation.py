"""
Consolidate visible project references without changing the captured profile.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

from attrs import evolve

from resumeme.compiler.asts.dates import employment_period
from resumeme.compiler.asts.names import company_key
from resumeme.compiler.asts.profile import Entry, Link, Section
from resumeme.compiler.passes.experience import regroup_positions
from resumeme.compiler.passes.media import image_role
from resumeme.compiler.passes.projects.descriptions import partition_descriptions
from resumeme.compiler.passes.selection import matches_fields

if TYPE_CHECKING:
    from collections.abc import Sequence

    from resumeme.compiler.asts.profile import Media, Profile
    from resumeme.config import ProjectSelector

__all__ = ["consolidate_projects"]

type _ProjectKey = str | tuple[str, str]


def _name_key(value: str) -> str:
    """
    Compare literal project names independently of display case and spacing.

    Args:
        value (str): Displayed name or configured selector.

    Returns:
        str: Case-folded name with collapsed whitespace.
    """
    return " ".join(value.split()).casefold()


def _affiliations(entry: Entry) -> set[str]:
    """
    Read organizations from explicit associations and extracted role provenance.

    Args:
        entry (Entry): Project containing captured or generated association rows.

    Returns:
        set[str]: Normalized affiliations, excluding arbitrary description mentions.
    """
    result: set[str] = set()

    for paragraph in entry.paragraphs:
        for line in paragraph.splitlines():
            label = " ".join(line.split())

            # Extracted roles use 'Associated with ROLE at COMPANY'; native projects name their organization directly.
            if label.casefold().startswith("associated with "):
                association = label[len("Associated with ") :]
                company = re.split(r" at ", association, flags=re.IGNORECASE)[-1]

                if company_key(company):
                    result.add(company_key(company))

    return result


def _matches(entry: Entry, selector: ProjectSelector) -> bool:
    """
    Apply the same literal name and affiliation rules to inclusion and exclusion selectors.

    Args:
        entry (Entry): Consolidated project with all captured associations.
        selector (ProjectSelector): Optional name and affiliation, combined when both are supplied.

    Returns:
        bool: Whether every supplied field matches the project.
    """
    return matches_fields(
        (selector.name, (entry.title,), _name_key),
        (selector.affiliation, _affiliations(entry), company_key),
    )


def _association(entry: Entry) -> str:
    """
    Retain the employer alongside a standalone role when captured employment rows identify it.

    Args:
        entry (Entry): Visible employment entry or grouped company.

    Returns:
        str: Source attribution without mistaking an employment type or narrative for an employer.
    """
    association = f"Associated with {entry.title}"
    dated = next((index for index, line in enumerate(entry.paragraphs) if employment_period(line)), None)

    # Standalone roles place the employer before their date; legacy company groups start with an employment type.
    if not entry.positions and dated is not None and dated > 0:
        company = entry.paragraphs[0].split("\u00b7", 1)[0].strip()

        if company.casefold() not in {
            "full-time",
            "part-time",
            "self-employed",
            "freelance",
            "contract",
            "internship",
            "apprenticeship",
            "seasonal",
        }:
            association += f" at {company}"

    return association


def _destination(url: str) -> str:
    """
    Identify external destinations without conflating LinkedIn's shared viewers.

    Args:
        url (str): Observed destination or original reference.

    Returns:
        str: Comparable external URL, or empty for LinkedIn navigation and missing references.
    """
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()

    if not host or host == "linkedin.com" or host.endswith(".linkedin.com"):
        return ""

    # Keep meaningful paths and queries; fragments and a trailing slash do not create a second project page.
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), parsed.query, ""))


def _name(label: str, url: str = "") -> str:
    """
    Prefer a concise repository name while retaining other attachment labels.

    Args:
        label (str): Captured title, label, or image description.
        url (str): Observed external destination, empty for unresolved attachments.

    Returns:
        str: Human-readable project heading without an inferred destination.
    """
    label = label.removeprefix("Thumbnail for ").strip()
    parsed = urlsplit(url)
    parts = parsed.path.strip("/").split("/")

    if parsed.hostname == "github.com" and len(parts) == 2:
        return parts[-1]

    # A captured GitHub title can identify an unlinked project, but never authorizes inventing its URL.
    match = re.match(r"GitHub - [^/\s]+/([^:\s]+)(?::|$)", label)
    return match.group(1) if match else label or url or "Project attachment"


def _sources(entry: Entry) -> set[str]:
    """
    Select observed project destinations without treating downloaded image assets as source pages.

    Args:
        entry (Entry): Explicit project or extracted attachment.

    Returns:
        set[str]: Resolved destinations where available, otherwise original links including image click targets.
    """
    destinations = {link.url: link.resolved_url or link.url for link in entry.links}
    return {url for url in [*destinations.values(), *(destinations.get(image.link, image.link) for image in entry.images)] if url}


def _keys(entry: Entry) -> set[str]:
    """
    Collect observed external identities for one project.

    Args:
        entry (Entry): Explicit project or extracted attachment.

    Returns:
        set[str]: Canonical destinations, excluding shared LinkedIn viewers.
    """
    return {key for url in _sources(entry) if (key := _destination(url))}


def _merge(left: Entry, right: Entry) -> Entry:
    """
    Preserve project descriptions and role associations while removing repeated references.

    Args:
        left (Entry): Preferred explicit project or first occurrence.
        right (Entry): Another observation of the same project.

    Returns:
        Entry: Combined text with one link and preview per destination.
    """
    links: dict[str, Link] = {}
    images: dict[str, Media] = {}
    destinations = {link.url: link.resolved_url or link.url for link in [*left.links, *right.links]}

    for link in [*left.links, *right.links]:
        key = _destination(link.resolved_url or link.url) or link.url

        if key not in links or (not links[key].resolved_url and link.resolved_url):
            links[key] = link

    for image in [*left.images, *right.images]:
        key = _destination(destinations.get(image.link, image.link)) if image_role(image) == "preview" else ""
        key = key or image.path or image.url

        if key not in images or (not images[key].path and image.path):
            # Preserve redirect resolution even if deduplication retains a different link alias for this image.
            images[key] = evolve(image, link=destinations.get(image.link, image.link))

    # Deduplicating a destination must not discard different descriptions captured beside it in different roles.
    displayed = {left.title.casefold(), *(link.label.casefold() for link in links.values())}
    descriptions = [link.label for link in [*left.links, *right.links] if link.label != link.url and link.label.casefold() not in displayed]

    return evolve(
        left,
        paragraphs=list(dict.fromkeys([*left.paragraphs, *right.paragraphs, *descriptions])),
        links=list(links.values()),
        images=list(images.values()),
        skills=list(dict.fromkeys([*left.skills, *right.skills])),
    )


def consolidate_projects(
    profile: Profile,
    *,
    enabled: bool,
    project_filter: str | None = None,
    include: list[ProjectSelector] | None = None,
    exclude: Sequence[ProjectSelector] = (),
) -> tuple[Profile, list[Link]]:
    """
    Move role and Featured project attachments into one deduplicated display section.

    Call after section and job exclusions so hidden content cannot be reintroduced.
    Attachment descriptions follow their cards; ordinary role prose and Featured post text stay in their source section.

    Args:
        profile (Profile): Visible profile after employment and section filtering.
        enabled (bool): Whether the Projects section is enabled; false still removes relocated cards.
        project_filter (str | None): Python regex searched against source URLs after deduplication; None includes unlinked projects too.
        include (list[ProjectSelector] | None): Alternative name/affiliation selectors applied after consolidation; None keeps all projects.
        exclude (Sequence[ProjectSelector]): Matching selectors remove consolidated tiles even when include also matches.

    Returns:
        tuple[Profile, list[Link]]: Display profile and moved source references for inline hyperlink resolution.

    Raises:
        re.PatternError: The source URL filter is not a valid Python regular expression.
    """
    pattern = re.compile(project_filter) if project_filter is not None else None
    candidates = [entry for section in profile.sections if section.key == "projects" for entry in section.entries]
    references: list[Link] = []

    def extract(entry: Entry, association: str, *, keep_text: bool = False) -> Entry:
        """
        Move attachment descriptions and previews while keeping role narrative and company logos.

        Args:
            entry (Entry): Role, company group, or Featured post.
            association (str): Source context displayed with extracted projects.
            keep_text (bool): Preserve Featured post text, including standalone URL lines.

        Returns:
            Entry: Source content without the relocated attachment list.
        """
        # Rewrite children first, then splice their retained prose into the parent without duplicating their project cards.
        if entry.positions:
            positions = [extract(position, f"Associated with {position.title} at {entry.title}") for position in entry.positions]
            entry = regroup_positions(entry, list(positions))

        moved = {link.url: link for link in entry.links if _destination(link.resolved_url or link.url)}
        references.extend(moved.values())
        captions = {link.label for link in moved.values() if link.label != link.url}
        captions.update(image.alt.removeprefix("Thumbnail for ") for image in entry.images if image.link in moved)

        remaining: list[Media] = []
        attachments: dict[str, list[Media]] = {}

        for image in entry.images:
            if image_role(image) not in {"preview", "icon"} or not image.link:
                remaining.append(image)
                continue

            # LinkedIn's native preview opens the post; attach it to the first observed project without moving unrelated post images.
            if keep_text and moved and image_role(image) == "preview" and image.link in {link.url for link in entry.links}:
                if not _destination(image.link):
                    primary = next(iter(moved))
                    attachments.setdefault(primary, []).append(evolve(image, link=primary))
                    continue

            # Other LinkedIn navigation is not a project destination.
            if image.link not in moved and "/overlay/" not in urlsplit(image.link).path and not _destination(image.link):
                remaining.append(image)
                continue

            key = image.link if image.link in moved or _destination(image.link) else image.url
            attachments.setdefault(key, []).append(image)

        cards: dict[str, Entry] = {}
        labels: dict[str, set[str]] = {}

        for url in dict.fromkeys([*moved, *attachments]):
            images = attachments.get(url, [])
            link = moved.get(url)

            if link is None:
                image = images[0]
                link = Link(image.alt.removeprefix("Thumbnail for ") or "Project attachment", image.link)
                references.append(link)

            destination = link.resolved_url or link.url
            label = link.title or link.label
            title = _name(label, destination)
            labels[url] = {link.label, link.title, title, *(image.alt.removeprefix("Thumbnail for ") for image in images)} - {""}
            captions.update(labels[url])
            cards[url] = Entry(
                title=title,
                paragraphs=[association],
                links=[link],
                images=[evolve(image, link=destination) for image in images],
            )

        # Featured captions remain part of the post; employment attachment descriptions belong to the relocated cards.
        paragraphs, descriptions = (entry.paragraphs, {}) if keep_text else partition_descriptions(entry, labels)
        candidates.extend(evolve(card, paragraphs=[*card.paragraphs, *descriptions.get(url, [])]) for url, card in cards.items())

        # Remove standalone attachment labels while preserving ordinary role prose and its embedded hyperlinks.
        return evolve(
            entry,
            paragraphs=paragraphs if keep_text else [line for line in paragraphs if line not in captions],
            links=[link for link in entry.links if link.url not in moved],
            images=remaining,
        )

    sections: list[Section] = []

    for section in profile.sections:
        if section.key in {"experience", "featured"}:
            entries = [
                extract(
                    entry,
                    _association(entry) if section.key == "experience" else "Featured project",
                    keep_text=section.key == "featured",
                )
                for entry in section.entries
            ]
            section = evolve(section, entries=entries)

        sections.append(section)

    # Associate URL-less descriptions only with unambiguous names within their captured organization.
    # An unknown affiliation cannot bridge same-named projects at different companies.
    named: dict[str, set[str]] = {}
    affiliated: dict[tuple[str, str], set[str]] = {}
    companies: dict[str, set[str]] = {}

    for entry in candidates:
        name = _name_key(entry.title)
        named.setdefault(name, set()).update(_keys(entry))
        affiliations = _affiliations(entry)
        companies.setdefault(name, set()).update(affiliations)

        for affiliation in affiliations:
            affiliated.setdefault((name, affiliation), set()).update(_keys(entry))

    merged: list[tuple[set[_ProjectKey], Entry]] = []

    for entry in candidates:
        keys: set[_ProjectKey] = set(_keys(entry))
        name = _name_key(entry.title)
        affiliations = _affiliations(entry)

        if len(named[name]) <= 1 and len(companies[name]) <= 1:
            keys.add((name, ""))

        # A multi-affiliation record is not evidence that two different URLs identify the same project.
        destinations = {url for affiliation in affiliations for url in affiliated[(name, affiliation)]}

        if len(destinations) <= 1:
            keys.update((name, affiliation) for affiliation in affiliations)

        matches = [index for index, (existing, _) in enumerate(merged) if keys & existing]

        if not matches:
            merged.append((keys, _merge(entry, Entry())))
            continue

        first = matches[0]
        combined = merged[first][1]

        for index in matches:
            keys.update(merged[index][0])

            if index != first:
                combined = _merge(combined, merged[index][1])

        merged[first] = (keys, _merge(combined, entry))

        for index in reversed(matches[1:]):
            del merged[index]

    # Merge first so an unlinked explicit entry can inherit its observed attachment's destination before filtering.
    # Exclusions win over inclusion and apply to the whole tile, including any deduplicated role or Featured references.
    # Keep moved references available for hyperlinks in retained role narrative and Featured post text.
    entries = [
        entry
        for _, entry in merged
        if (pattern is None or any(pattern.search(url) for url in _sources(entry)))
        and (include is None or any(_matches(entry, selector) for selector in include))
        and not any(_matches(entry, selector) for selector in exclude)
    ]
    projects = Section("projects", "Projects", entries)
    result: list[Section] = []

    for section in sections:
        if section.key != "projects":
            result.append(section)
        elif enabled and projects.entries and not any(item.key == "projects" for item in result):
            result.append(projects)

    if enabled and projects.entries and not any(section.key == "projects" for section in result):
        result.append(projects)

    return evolve(profile, sections=result), references
