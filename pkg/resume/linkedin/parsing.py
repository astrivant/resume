"""
Extract profile content from rendered LinkedIn HTML without relying on private APIs.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

from resume.models import Entry, Link, Media, Profile, Section

__all__ = ["detail_links", "merge_profile_html", "parse_contact", "parse_detail", "parse_profile", "safe_url"]

_IGNORED_SECTIONS = {"analytics", "resources", "activity", "suggested-for-you"}
_UI_TEXT = re.compile(
    r"^(?:show all\b|show more\b|see more$|see less$|show less$|\.\.\.more$|…more$|…see more$|add section$|add profile section$)",
    re.IGNORECASE,
)


def safe_url(value: str, base: str = "https://www.linkedin.com") -> str:
    """
    Normalize navigable web links and discard scripts, credentials, and fragments.

    Args:
        value (str): Raw link or image source.
        base (str): Base used to resolve relative URLs.

    Returns:
        str: Absolute HTTP URL, or an empty string when unsuitable.
    """
    if not value or value.startswith("#"):
        return ""
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


def _clean(node: Tag) -> Tag:
    """
    Copy a content node and remove duplicated accessibility text and UI controls.

    Args:
        node (Tag): Rendered content node.

    Returns:
        Tag: Independent, cleaned HTML fragment.
    """
    cleaned = BeautifulSoup(str(node), "html.parser")
    for item in cleaned.select(
        "script, style, button, nav, label, input, [role='tab'], .visually-hidden, [hidden], [inert], [style*='display: none']"
    ):
        item.decompose()
    return cleaned


def _lines(node: Tag) -> list[str]:
    """
    Preserve text lines and paragraphs while discarding expansion labels.

    Args:
        node (Tag): Cleaned content node.

    Returns:
        list[str]: Full nonempty text in source order.
    """
    return [line for raw in node.get_text("\n").splitlines() if (line := raw.strip()) and not _UI_TEXT.match(line)]


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
        if parsed.hostname == "www.linkedin.com" and parsed.path == "/safety/go/":
            url = safe_url(parse_qs(parsed.query).get("url", [""])[0])
        if not url or re.search(r"/(?:edit|add|details|overlay)/|[?&]controlName=", url):
            continue
        label = " ".join(anchor.stripped_strings) or str(anchor.get("aria-label", ""))
        if _UI_TEXT.match(label):
            continue
        result.setdefault(url, Link(label=label or url, url=url))
    return list(result.values())


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


def _entry(node: Tag) -> Entry:
    """
    Preserve a whole entry, including nested positions and associated projects.

    Args:
        node (Tag): Top-level entry or prose block.

    Returns:
        Entry: Complete text and all associated references.
    """
    cleaned = _clean(node)
    lines = _lines(cleaned)
    return Entry(title=lines[0] if lines else "", paragraphs=lines[1:], links=_links(cleaned), images=_images(cleaned))


def _entries(node: Tag, *, strip_skills: bool = False) -> list[Entry]:
    """
    Split top-level list entries while keeping grouped experience intact.

    Args:
        node (Tag): Section or detail page content.
        strip_skills (bool): Remove attached LinkedIn skill summaries from job records.

    Returns:
        list[Entry]: Entries or a single full-text block when no list exists.
    """
    if strip_skills:
        node = _clean(node)
        for summary in node.select("a[href*='/skill-associations-details/']"):
            summary.decompose()
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
        ]
    if not candidates:
        candidates = node.select("ul > li")
    identities = {id(item) for item in candidates}
    roots = [item for item in candidates if not any(id(parent) in identities for parent in item.parents)]
    if roots:
        entries = [entry for item in roots if (entry := _entry(item)).title or entry.images]
        if entries:
            return entries
    cleaned = _clean(node)
    for heading in cleaned.select("h2"):
        heading.decompose()
    entry = _entry(cleaned)
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
    pattern = re.compile(rf"^/in/{re.escape(username)}/details/([^/]+)/?$", re.IGNORECASE)
    soup = BeautifulSoup(html, "html.parser")
    for anchor in soup.select("main a[href]"):
        url = safe_url(str(anchor.get("href", "")))
        parsed = urlsplit(url)
        match = pattern.match(unquote(parsed.path))
        if parsed.hostname == "www.linkedin.com" and match:
            result[match[1]] = url
    return result


def merge_profile_html(snapshots: list[str]) -> str:
    """
    Preserve cards removed from LinkedIn's virtualized DOM while scrolling downward.

    Args:
        snapshots (list[str]): Consecutive rendered pages from top to bottom.

    Returns:
        str: Synthetic primary-content HTML containing every observed card.
    """
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
        ValueError: Profile identity or content is missing.
    """
    soup = BeautifulSoup(html, "html.parser")
    main = soup.select_one('section[aria-label="Primary content"]') or soup.select_one("main")
    heading = main.select_one("h1, h2") if main else None
    if main is None or heading is None:
        raise ValueError("No profile heading found. Finish login and open your profile; LinkedIn may also have changed its markup.")
    name = heading.get_text(" ", strip=True)
    intro_node = heading.find_parent("section") or heading.parent
    if not isinstance(intro_node, Tag) or not name:
        raise ValueError("The profile intro is missing.")
    intro = _clean(intro_node)
    for item in intro.select("h1, h2, [data-testid='carousel']"):
        item.decompose()
    sections: list[Section] = []
    for node in main.select("section"):
        title_node = node.select_one("h2")
        if title_node is None or node is intro_node or title_node.find_parent("section") is not node:
            continue
        title = re.sub(r"\s+\(?[\d,]+\)?$", "", " ".join(_clean(title_node).stripped_strings))
        anchor = node.select_one("[id].pv-profile-card__anchor, [data-resume-section]")
        key = str(anchor.get("id", "")) if anchor else ""
        for link in node.select("a[href]"):
            match = re.match(rf"/in/{re.escape(username)}/details/([^/]+)/", urlsplit(safe_url(str(link.get("href", "")))).path)
            if match:
                key = match[1]
                break
        key = key or re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        if key and key not in _IGNORED_SECTIONS:
            sections.append(Section(key=key, title=title, entries=_entries(node, strip_skills=key == "experience")))
    if not sections:
        raise ValueError("No profile sections found; refusing to save an empty or unsupported profile page.")
    return Profile(username=username, name=name, intro=_lines(intro), images=_images(intro), links=_links(intro), sections=sections)


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
        ValueError: The page has no supported content list.
    """
    soup = BeautifulSoup(html, "html.parser")
    main = soup.select_one('section[aria-label="Primary content"]') or soup.select_one("main")
    if main is None:
        raise ValueError(f"No detail entries found for {title}; refusing to discard its preview.")
    entries = _entries(main, strip_skills=key == "experience")
    entries = [entry for entry in entries if entry.title.casefold() != title.casefold() or entry.paragraphs or entry.images]
    if not entries:
        raise ValueError(f"No detail entries found for {title}; refusing to discard its preview.")
    return Section(key=key, title=title, entries=entries)


def parse_contact(html: str) -> Section:
    """
    Read contact fields from the owner-opened dialog without including the surrounding page.

    Args:
        html (str): Profile page with the contact information dialog open.

    Returns:
        Section: Contact fields and website links in their displayed order.

    Raises:
        ValueError: The contact dialog is missing or empty.
    """
    soup = BeautifulSoup(html, "html.parser")
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
    raise ValueError("The profile contact information dialog did not load.")
