"""
Consolidate visible project references without changing the captured profile.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

from attrs import evolve

from resume.latex.media import image_role
from resume.linkedin.dates import employment_period
from resume.models import Entry, Link, Section

if TYPE_CHECKING:
    from resume.models import Media, Profile

__all__ = ["consolidate_projects"]


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
        company = entry.paragraphs[0].split("·", 1)[0].strip()

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


def _keys(entry: Entry) -> set[str]:
    """
    Collect observed external identities for one project.

    Args:
        entry (Entry): Explicit project or extracted attachment.

    Returns:
        set[str]: Canonical destinations, excluding shared LinkedIn viewers.
    """
    destinations = {link.url: link.resolved_url or link.url for link in entry.links}
    return {
        key
        for url in [*(destinations.values()), *(destinations.get(image.link, image.link) for image in entry.images)]
        if (key := _destination(url))
    }


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
            images[key] = image

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


def consolidate_projects(profile: Profile, *, enabled: bool) -> tuple[Profile, list[Link]]:
    """
    Move role and Featured project attachments into one deduplicated display section.

    Call after section and job exclusions so hidden content cannot be reintroduced.
    Inline prose stays in its source section; returned references retain its resolved links.

    Args:
        profile (Profile): Visible profile after employment and section filtering.
        enabled (bool): Whether the Projects section is enabled; false still removes relocated cards.

    Returns:
        tuple[Profile, list[Link]]: Display profile and moved source references for inline hyperlink resolution.
    """
    candidates = [entry for section in profile.sections if section.key == "projects" for entry in section.entries]
    references: list[Link] = []

    def extract(entry: Entry, association: str, *, keep_text: bool = False) -> Entry:
        """
        Move external references and attached previews while keeping role text and logos.

        Args:
            entry (Entry): Role, company group, or Featured post.
            association (str): Source context displayed with extracted projects.
            keep_text (bool): Preserve Featured post text, including standalone URL lines.

        Returns:
            Entry: Source content without the relocated attachment list.
        """
        owned_links = {link.url for position in entry.positions for link in position.links}
        owned_images = {(image.url, image.link) for position in entry.positions for image in position.images}
        moved = {link.url: link for link in entry.links if _destination(link.resolved_url or link.url)}
        references.extend(moved.values())
        captions = {link.label for link in moved.values() if link.label != link.url}
        captions.update(image.alt.removeprefix("Thumbnail for ") for image in entry.images if image.link in moved)

        # Grouped parents repeat their children's references; collect each role with its own employment context.
        positions = [extract(position, f"Associated with {position.title} at {entry.title}") for position in entry.positions]
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

            if (image.url, image.link) in owned_images:
                captions.add(image.alt.removeprefix("Thumbnail for "))
                continue

            key = image.link if image.link in moved or _destination(image.link) else image.url
            attachments.setdefault(key, []).append(image)

        for url in dict.fromkeys([*(url for url in moved if url not in owned_links), *attachments]):
            images = attachments.get(url, [])
            link = moved.get(url)

            if link is None:
                image = images[0]
                link = Link(image.alt.removeprefix("Thumbnail for ") or "Project attachment", image.link)
                references.append(link)

            destination = link.resolved_url or link.url
            label = link.title or link.label
            title = _name(label, destination)
            captions.update([link.label, title, *(image.alt.removeprefix("Thumbnail for ") for image in images)])
            candidates.append(
                Entry(
                    title=title,
                    paragraphs=[association],
                    links=[link],
                    images=[evolve(image, link=destination) for image in images],
                )
            )

        # Remove standalone attachment captions, retaining narrative paragraphs and embedded URLs verbatim.
        return evolve(
            entry,
            paragraphs=entry.paragraphs if keep_text else [line for line in entry.paragraphs if line not in captions],
            links=[link for link in entry.links if link.url not in moved],
            images=remaining,
            positions=positions,
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

    # Only an unambiguous title can connect a URL-less project to its observed attachment; conflicting URLs remain distinct.
    named: dict[str, set[str]] = {}

    for entry in candidates:
        named.setdefault(entry.title.casefold(), set()).update(_keys(entry))

    merged: list[tuple[set[str], Entry]] = []

    for entry in candidates:
        keys = _keys(entry)
        name = entry.title.casefold()

        if len(named[name]) <= 1:
            keys.add(f"name:{name}")

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

    projects = Section("projects", "Projects", [entry for _, entry in merged])
    result: list[Section] = []

    for section in sections:
        if section.key != "projects":
            result.append(section)
        elif enabled and not any(item.key == "projects" for item in result):
            result.append(projects)

    if enabled and projects.entries and not any(section.key == "projects" for section in result):
        result.append(projects)

    return evolve(profile, sections=result), references
