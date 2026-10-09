"""
Extract profile content from rendered LinkedIn HTML without relying on private APIs.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, unquote, urlsplit

from bs4 import BeautifulSoup, Tag
from bs4.element import NavigableString

from resumeme.compiler.asts.dates import employment_period
from resumeme.compiler.asts.links import merge_text_links, safe_url
from resumeme.compiler.asts.profile import Entry, Link, Media, Profile, Section, Skill
from resumeme.compiler.asts.sections import section_key
from resumeme.compiler.asts.skills.parsing import endorsement_count, skill_labels
from resumeme.compiler.constants.parsing import BLOCK_TAGS, PARAGRAPH_BREAK
from resumeme.compiler.constants.parsing import IGNORED_SECTIONS as _IGNORED_SECTIONS
from resumeme.compiler.constants.parsing import UI_TEXT as _UI_TEXT
from resumeme.exceptions import ProfileError

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ["detail_links", "merge_profile_html", "parse_contact", "parse_detail", "parse_profile", "safe_url"]


def _clean(node: Tag) -> Tag:
    """
    Copy a content node and remove duplicated accessibility text and UI controls.

    Args:
        node (Tag): Rendered content node.

    Returns:
        Tag: Independent, cleaned HTML fragment.
    """

    # Work on a copy: parsing one entry must not remove nodes needed by its parent group or neighboring sections.
    cleaned = BeautifulSoup(str(node), "html.parser")

    for control in cleaned.select("input[type='checkbox'], input[type='radio']"):
        wrapper = control.find_parent(attrs={"componentkey": re.compile(r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")})

        if wrapper is not None and wrapper.select_one("p, h1, h2, h3, img") is None:
            wrapper.decompose()

    # LinkedIn often duplicates visible text for accessibility; keep one display copy and remove interactive chrome.
    for item in cleaned.select(
        "script, style, button, nav, label, input, [role='tab'], .visually-hidden, [hidden], [inert], [style*='display: none']"
    ):
        item.decompose()

    return cleaned


def _text_fragments(node: Tag) -> Iterator[str]:
    """
    Retain HTML block boundaries without inserting breaks around inline text.

    Args:
        node (Tag): Cleaned content node.

    Yields:
        str: Literal text, soft line breaks, or semantic paragraph separators in document order.
    """
    if node.name == "br":
        yield "\n"
        return

    block = node.name in BLOCK_TAGS or node.get("role") in {"heading", "listitem"}

    if block:
        yield PARAGRAPH_BREAK

    # Preserve source whitespace between inline nodes, including punctuation immediately after a link or emphasis.
    for child in node.children:
        if isinstance(child, Tag):
            yield from _text_fragments(child)
        elif type(child) is NavigableString and not _UI_TEXT.match(str(child).strip()):
            yield str(child)

    if block:
        yield PARAGRAPH_BREAK


def _lines(node: Tag) -> list[str]:
    """
    Extract semantic text blocks while retaining explicit line breaks inside body paragraphs.

    Args:
        node (Tag): Cleaned content node.

    Returns:
        list[str]: Nonempty blocks in source order, with inline links and formatting joined to their surrounding prose.
    """
    return [text for fragment in "".join(_text_fragments(node)).split(PARAGRAPH_BREAK) if (text := fragment.strip())]


def _links(node: Tag) -> list[Link]:
    """
    Collect unique content links without profile editing or expansion controls.

    Args:
        node (Tag): Content scope.

    Returns:
        list[Link]: Labeled destinations in source order.
    """
    result: dict[str, Link] = {}

    for anchor in node.select("a[href]"):
        url = safe_url(str(anchor.get("href", "")))
        parsed = urlsplit(url)

        # Store the final external destination rather than LinkedIn's redirect wrapper or profile-editing controls.
        if parsed.hostname == "www.linkedin.com" and parsed.path == "/safety/go/":
            url = safe_url(parse_qs(parsed.query).get("url", [""])[0])

        if not url or re.search(r"/(?:edit|add|details|overlay)/|[?&]controlName=", url):
            continue

        label = " ".join(anchor.stripped_strings) or str(anchor.get("aria-label", ""))

        if _UI_TEXT.match(label):
            continue

        result.setdefault(url, Link(label=label or url, url=url))

    return merge_text_links(list(result.values()), node.stripped_strings)


def _images(node: Tag) -> list[Media]:
    """
    Preserve images and their enclosing link, including company and project logos.

    Args:
        node (Tag): Content scope.

    Returns:
        list[Media]: Remote references awaiting local downloads.
    """
    result: dict[str, Media] = {}

    for image in node.select("img"):
        # Lazy-loaded images may still expose a placeholder in src while keeping the real URL in a data attribute.
        source = str(image.get("src", ""))

        if not source or source.startswith("data:"):
            source = str(image.get("data-delayed-url", ""))

        url = safe_url(source)

        if not url:
            continue

        parent = image.find_parent("a")
        link = safe_url(str(parent.get("href", ""))) if parent else ""
        result.setdefault(url, Media(url=url, alt=str(image.get("alt", "")), link=link))

    return list(result.values())


def _entry(node: Tag, *, strip_skills: bool = False, skills_section: bool = False) -> Entry:
    """
    Preserve a whole entry, including nested positions and associated projects.

    Args:
        node (Tag): Top-level entry or prose block.
        strip_skills (bool): Hide job association text while retaining structured tags.
        skills_section (bool): Interpret the entry title as a skill with endorsements.

    Returns:
        Entry: Complete text and all associated references.
    """
    cleaned = _clean(node)
    skills = []

    # Strip association rows from job prose only after retaining their labels for the aggregate skill cloud.
    for association in cleaned.select("a[href*='/skill-associations-details/'], a[href*='/skill-associations/']"):
        skills.extend(skill_labels(" ".join(association.stripped_strings)))

        if strip_skills:
            association.decompose()

    lines = _lines(cleaned)

    if skills_section and lines:
        # Endorsement totals can live on controls removed by cleanup, so read counts from the original node.
        labels = [*node.stripped_strings, *(str(item.get("aria-label", "")) for item in node.select("[aria-label]"))]
        skills = [Skill(lines[0], endorsements=endorsement_count(labels))]

    return Entry(
        title=lines[0] if lines else "",
        paragraphs=lines[1:],
        links=_links(cleaned),
        images=_images(cleaned),
        skills=skills,
        positions=_positions(node) if strip_skills else [],
    )


def _positions(node: Tag) -> list[Entry]:
    """
    Retain role boundaries inside company groups for independent job filtering.

    Args:
        node (Tag): Employment entry whose full flattened content is retained separately.

    Returns:
        list[Entry]: Nested roles with their own descriptions, links, images, and skill associations.
    """

    # Date-bearing nested list items identify role containers; ordinary responsibility bullets should stay in the prose.
    candidates = [
        item
        for item in node.select("li, [role='listitem'], [data-resume-entry], [componentkey^='entity-collection-item-']")
        if any(employment_period(line) for line in _lines(_clean(item))[1:4])
    ]

    # Choose outer role containers so nested markup cannot duplicate the same job in the structured metadata.
    identities = {id(item) for item in candidates}
    roots = [item for item in candidates if not any(id(parent) in identities for parent in item.parents)]

    # Keep undated siblings selectable instead of treating them as company context.
    parents = {id(item.parent) for item in roots}
    return [
        _entry(item, strip_skills=True)
        for item in node.select("li, [role='listitem'], [data-resume-entry], [componentkey^='entity-collection-item-']")
        if id(item.parent) in parents
    ]


def _entries(node: Tag, *, strip_skills: bool = False, skills_section: bool = False) -> list[Entry]:
    """
    Split top-level list entries while keeping grouped experience intact.

    Args:
        node (Tag): Section or detail page content.
        strip_skills (bool): Remove attached LinkedIn skill summaries from job records.
        skills_section (bool): Preserve skill names and endorsement totals as structured data.

    Returns:
        list[Entry]: Entries or a single full-text block when no list exists.
    """

    # Prefer known entity containers, then fall back to generated identifiers and ordinary lists for layout variants.
    candidates: list[Tag] = node.select(
        "[componentkey^='entity-collection-item-'], [componentkey^='FeFeaturedItemUrn('], "
        "[componentkey^='com.linkedin.sdui.profile.skill('], "
        "li.artdeco-list__item, li.pvs-list__paged-list-item, "
        "[data-resume-entry], [role='listitem']"
    )

    if not candidates:
        candidates = [
            item
            for item in node.select("div[componentkey]")
            if re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", str(item.get("componentkey", "")))
            and item.select_one("p, h3, img") is not None
        ]

    if not candidates:
        candidates = node.select("ul > li")

    # Keep the company card intact here; _positions separately records the boundaries needed for role-level filtering.
    identities = {id(item) for item in candidates}
    roots = [item for item in candidates if not any(id(parent) in identities for parent in item.parents)]

    if roots:
        entries = [
            entry
            for item in roots
            if (entry := _entry(item, strip_skills=strip_skills, skills_section=skills_section)).title or entry.images
        ]

        if entries:
            return entries

    # Prose-only sections have no list items; remove their heading before treating the remaining content as one entry.
    cleaned = _clean(node)

    for heading in cleaned.select("h2"):
        heading.decompose()

    entry = _entry(cleaned, strip_skills=strip_skills, skills_section=skills_section)
    return [entry] if entry.title or entry.images else []


def detail_links(html: str, username: str) -> dict[str, str]:
    """
    Discover section detail routes restricted to the configured profile owner.

    Args:
        html (str): Expanded profile HTML.
        username (str): Profile slug.

    Returns:
        dict[str, str]: Section keys and their detail URLs.
    """
    result: dict[str, str] = {}

    # Only owner-scoped detail routes are eligible; links to suggested profiles must never extend the capture.
    pattern = re.compile(rf"^/in/{re.escape(username)}/details/([^/]+)/?$", re.IGNORECASE)
    soup = BeautifulSoup(html, "html.parser")

    for anchor in soup.select("main a[href]"):
        url = safe_url(str(anchor.get("href", "")))
        parsed = urlsplit(url)
        match = pattern.match(unquote(parsed.path))

        if parsed.hostname == "www.linkedin.com" and match:
            result[section_key(match[1])] = url

    return result


def merge_profile_html(snapshots: list[str]) -> str:
    """
    Preserve cards removed from LinkedIn's virtualized DOM while scrolling downward.

    Args:
        snapshots (list[str]): Consecutive rendered pages from top to bottom.

    Returns:
        str: Synthetic primary-content HTML containing every observed card.
    """

    # Keep the fullest observed version of each card while preserving the order in which cards first appeared.
    cards: dict[str, tuple[int, str]] = {}

    for html in snapshots:
        soup = BeautifulSoup(html, "html.parser")
        main = soup.select_one('section[aria-label="Primary content"]') or soup.select_one("main")

        if main is None:
            continue

        for node in main.select("section"):
            heading = node.select_one("h1, h2")

            if heading is None or heading.find_parent("section") is not node:
                continue

            title = " ".join(_clean(heading).stripped_strings)
            length = len(_clean(node).get_text())

            if title not in cards or length >= cards[title][0]:
                cards[title] = (length, str(node))

        heading = main.select_one("h1, h2")

        if heading is not None and heading.find_parent("section") in (main, None):
            # Some layouts leave the intro unwrapped; remove child sections so hidden content cannot leak into the header.
            intro = _clean(main)

            for section in intro.select("section"):
                section.decompose()

            title = " ".join(_clean(heading).stripped_strings)

            if title and intro.select_one("h1, h2"):
                cards[title] = (len(intro.get_text()), f"<section>{intro}</section>")

    return '<main><section aria-label="Primary content">' + "".join(value[1] for value in cards.values()) + "</section></main>"


def parse_profile(html: str, username: str) -> Profile:
    """
    Parse an authenticated profile page and fail on login or unsupported markup.

    Args:
        html (str): Rendered and expanded browser page.
        username (str): Owner used to bind the snapshot.

    Returns:
        Profile: Ordered sections and intro content.

    Raises:
        ProfileError: Profile identity is missing or the page is an authentication form.
    """
    soup = BeautifulSoup(html, "html.parser")
    main = soup.select_one('section[aria-label="Primary content"]') or soup.select_one("main")

    # Accept minimal profiles, but require an identity and reject authentication pages before extracting any content.
    heading = main.select_one("h1, h2") if main else None

    if main is None or heading is None or soup.select_one("input[type='password']"):
        raise ProfileError("No profile heading found. Finish login and open your profile; LinkedIn may also have changed its markup.")

    name = heading.get_text(" ", strip=True)
    intro_node = heading.find_parent("section") or heading.parent

    if not isinstance(intro_node, Tag) or not name or name.casefold() in {"sign in", "join linkedin", "security verification"}:
        raise ProfileError("The profile intro is missing.")

    intro = _clean(intro_node)

    if intro_node is main:
        for section in intro.select("main section, section section"):
            section.decompose()

    for item in intro.select("h1, h2, [data-testid='carousel']"):
        item.decompose()

    # Prefer stable anchors or detail routes over display headings so YAML exclusions survive presentation changes.
    sections: list[Section] = []

    for node in main.select("section"):
        title_node = node.select_one("h2")

        if title_node is None or node is intro_node or title_node.find_parent("section") is not node:
            continue

        title = re.sub(r"\s+\(?[\d,]+\)?$", "", " ".join(_clean(title_node).stripped_strings))
        anchor = node.select_one("[id].pv-profile-card__anchor, [data-resume-section]")
        key = str(anchor.get("data-resume-section") or anchor.get("id", "")) if anchor else ""

        for link in node.select("a[href]"):
            match = re.match(rf"/in/{re.escape(username)}/details/([^/]+)/", urlsplit(safe_url(str(link.get("href", "")))).path)

            if match:
                key = match[1]
                break

        key = section_key(key or title)

        if key and key not in _IGNORED_SECTIONS:
            sections.append(
                Section(key=key, title=title, entries=_entries(node, strip_skills=key == "experience", skills_section=key == "skills"))
            )

    headline = intro.select_one("[data-resume-headline], [data-testid='profile-headline'], .text-body-medium.break-words")
    return Profile(
        username=username,
        name=name,
        intro=_lines(intro),
        images=_images(intro),
        links=_links(intro),
        sections=sections,
        headline=" ".join(headline.stripped_strings) if headline else "",
    )


def parse_detail(html: str, key: str, title: str) -> Section:
    """
    Extract all loaded entries from a dedicated profile section page.

    Args:
        html (str): Expanded detail-page HTML.
        key (str): Stable section route key.
        title (str): Human-readable section heading.

    Returns:
        Section: Complete loaded entries for replacement of the profile preview.

    Raises:
        ProfileError: The page has no supported content list.
    """
    soup = BeautifulSoup(html, "html.parser")
    main = soup.select_one('section[aria-label="Primary content"]') or soup.select_one("main")

    if main is None:
        raise ProfileError(f"No detail entries found for {title}; refusing to discard its preview.")

    key = section_key(key)

    # An explicit empty state is valid profile data; a bare heading may indicate failed loading or unsupported markup.
    if _clean(main).select_one(".artdeco-empty-state, [data-view-name*='empty-state'], [data-test-empty-state]"):
        return Section(key=key, title=title)

    heading = main.find(["h1", "h2", "p"])

    if heading is not None and heading.get_text(" ", strip=True).casefold() == title.casefold():
        heading.decompose()

    entries = _entries(main, strip_skills=key == "experience", skills_section=key == "skills")

    # Do not let a section heading masquerade as a complete detail result and overwrite a useful preview.
    entries = [entry for entry in entries if entry.title.casefold() != title.casefold() or entry.paragraphs or entry.images]

    if not entries:
        raise ProfileError(f"No detail entries found for {title}; refusing to discard its preview.")

    return Section(key=key, title=title, entries=entries)


def parse_contact(html: str) -> Section:
    """
    Read contact fields from the owner-opened dialog without including the surrounding page.

    Args:
        html (str): Profile page with the contact information dialog open.

    Returns:
        Section: Contact fields and website links in their displayed order.

    Raises:
        ProfileError: The contact dialog is missing or empty.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Scope extraction to the named contact dialog; the surrounding profile and premium promotions are not contact fields.
    for dialog in soup.select('dialog[open], [role="dialog"]'):
        heading = dialog.select_one("h1, h2")

        if heading and "contact info" in heading.get_text(" ", strip=True).casefold():
            content = dialog.select_one('[data-testid="dialog-content"]') or dialog
            cleaned = _clean(content)

            for link in cleaned.select("a[href*='/premium/']"):
                promotion = link.find_parent(attrs={"componentkey": re.compile(r"^auto-component")})
                (promotion or link).decompose()

            for node in cleaned.select("h1, h2"):
                node.decompose()

            entry = _entry(cleaned)

            if entry.title:
                return Section("contact", "Contact info", [entry])

    raise ProfileError("The profile contact information dialog did not load.")
