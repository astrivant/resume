"""
Escape profile text, emoji, and URLs for LaTeX template expressions.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from resumeme.compiler.asts.links import text_links
from resumeme.compiler.constants.escaping import EMOJI as _EMOJI
from resumeme.compiler.constants.escaping import ESCAPES as _ESCAPES

if TYPE_CHECKING:
    from resumeme.compiler.asts.profile import Link

__all__ = ["latex_contact_text", "latex_escape", "latex_linked_text", "latex_url"]


def latex_contact_text(value: str, links: list[Link]) -> str:
    """
    Attach captured contact destinations to their labels without printing a separate URL list.

    Args:
        value (str): Untrusted contact label or value.
        links (list[Link]): References owned by this contact field.

    Returns:
        str: Escaped text with unambiguous captured captions linked inline; explicit URLs remain clickable.
    """
    labels: dict[str, set[str]] = {}

    for link in links:
        if link.label.strip():
            labels.setdefault(link.label, set()).add(link.resolved_url or link.url)

    # A shared caption cannot identify two destinations. Leave that caption plain instead of inventing an association.
    destinations = {label: next(iter(urls)) for label, urls in labels.items() if len(urls) == 1}

    if not destinations:
        return latex_linked_text(value, links)

    pattern = re.compile(
        r"(?<![\w@./])(?:" + "|".join(re.escape(label) for label in sorted(destinations, key=len, reverse=True)) + r")(?![\w./])"
    )
    urls = text_links(value)
    parts: list[str] = []
    offset = 0

    for match in pattern.finditer(value):
        # Explicit URLs own their full span; a domain caption must not split a longer URL into mismatched pieces.
        if any(start < match.end() and match.start() < end for start, end, _ in urls):
            continue

        parts.append(latex_linked_text(value[offset : match.start()], links))
        label = match.group()
        parts.append(r"\href{" + latex_url(destinations[label]) + "}{" + latex_escape(label) + "}")
        offset = match.end()

    parts.append(latex_linked_text(value[offset:], links))
    return "".join(parts)


def latex_escape(value: str) -> str:
    """
    Escape each input character once so profile text cannot become TeX commands.

    Args:
        value (str): Untrusted display text.

    Returns:
        str: Text suitable for a LaTeX argument.
    """

    # Split emoji sequences from ordinary text so generated TeX commands are never escaped a second time.
    parts: list[str] = []
    offset = 0

    for match in _EMOJI.finditer(value):
        parts.append("".join(_ESCAPES.get(character, character) for character in value[offset : match.start()]))
        emoji = match.group()

        # Twemoji filenames omit presentation selectors on simple emoji but retain them inside joined sequences.
        if "\u200d" not in emoji:
            emoji = emoji.replace("\ufe0f", "")

        code = "-".join(f"{ord(character):x}" for character in emoji)
        parts.append(r"\texttwemoji{" + code + "}")
        offset = match.end()

    parts.append("".join(_ESCAPES.get(character, character) for character in value[offset:]))
    return "".join(parts)


def latex_url(value: str) -> str:
    """
    Quote special URL characters for hyperref while retaining the destination.

    Args:
        value (str): Validated HTTP URL.

    Returns:
        str: Escaped hyperlink argument.
    """

    # URL validation already rejected structural TeX characters; escape remaining hyperref-sensitive characters without rewriting the URL.
    return "".join({"%": r"\%", "#": r"\#", "&": r"\&", "_": r"\_"}.get(character, character) for character in value)


def latex_linked_text(value: str, links: list[Link]) -> str:
    """
    Preserve prose while making explicit web URLs clickable using captured redirect destinations.

    Args:
        value (str): Untrusted profile text containing optional web references.
        links (list[Link]): References associated with this text, including previously resolved destinations.

    Returns:
        str: Escaped prose with safe hyperlinks and URL line-break opportunities, without network requests.
    """
    destinations = {link.url: link.resolved_url or link.url for link in links}
    parts: list[str] = []
    offset = 0

    for start, end, link in text_links(value):
        parts.append(latex_escape(value[offset:start]))

        # Escape all display text and allow long URL paths to wrap without treating prose as raw TeX.
        label = r"\allowbreak{}".join(latex_escape(part) for part in re.split(r"(?<=[/.?&=_#-])", link.label) if part)
        destination = latex_url(destinations.get(link.url, link.url))
        parts.append(r"\href{" + destination + "}{" + label + "}")
        offset = end

    parts.append(latex_escape(value[offset:]))
    return "".join(parts)
