"""
Recognize list markers in captured prose without rewriting the saved snapshot.
"""

from __future__ import annotations

import re

from attrs import evolve, frozen

__all__ = ["TextBlock", "text_blocks"]

# Typographic and emoji bullets are explicit markers even without a separating space.
_GLYPHS = (
    "\u2022\u2023\u2043\u204c\u204d\u2219\u00b7\u25a0-\u25a3\u25aa\u25ab"
    "\u25b6\u25b8\u25ba\u25c6\u25c7\u25cb\u25cf\u25e6\u2610-\u2612"
    "\u2713\u2714\u2717\u2718\u2705\u2726\u2727\u2605\u2606\u2192\u21d2"
    "\u2794\u27a2\u27a4\u27a5\u27a7\u27ab\u27b2\u27bd"
    "\u2460-\u2473\u2474-\u2487\u2488-\u249b\u2776-\u277f"
    "\U0001f539\U0001f538\U0001f537\U0001f536\U0001f534\U0001f535\U0001f7e0-\U0001f7e3"
)

# Ambiguous ASCII markers and dashes require separation, keeping dates, negative numbers, and versions as ordinary prose.
_MARKER = re.compile(
    r"^(?P<indent>[^\S\r\n]*)(?P<marker>"
    r"(?:[-*+][^\S\r\n]+)?\[[ xX]\]"
    rf"|(?P<glyph>[{_GLYPHS}]|[0-9]\ufe0f?\u20e3)"
    r"|[-*+\u2010-\u2015\u2212]|(?:->|=>|--|---)"
    r"|(?:\d{1,3}|[a-zA-Z]|[ivxlcdmIVXLCDM]{1,8})[.)]"
    r"|\((?:\d{1,3}|[a-zA-Z]|[ivxlcdmIVXLCDM]{1,8})\)"
    r"|o)(?:\ufe0f)?(?(glyph)[^\S\r\n]*|[^\S\r\n]+)(?P<text>\S.*)$"
)


@frozen
class TextBlock:
    """
    Represent a paragraph or normalized bullet for presentation.

    Attributes:
        text (str): Unescaped content with any recognized marker removed.
        depth (int | None): Zero-based indentation level, or None for ordinary prose.
    """

    text: str
    depth: int | None = None


def text_blocks(paragraphs: list[str]) -> list[TextBlock]:
    """
    Normalize common ASCII, Unicode, checkbox, and ordered markers into bullet blocks.

    Args:
        paragraphs (list[str]): Original paragraphs, possibly containing embedded newlines and indentation.

    Returns:
        list[TextBlock]: Ordered prose and bullet blocks, preserving nested indentation and indented continuations.
    """
    lines = [line for paragraph in paragraphs for line in (paragraph.splitlines() or [""])]
    result: list[TextBlock] = []
    levels: list[int] = []

    for index, line in enumerate(lines):
        if not line.strip():
            levels.clear()
            continue

        match = _MARKER.fullmatch(line)

        # An isolated initial such as "A. Smith" or the ASCII circle "o" is ambiguous without adjacent list items.
        if match and re.fullmatch(r"(?:[a-zA-Z]+\.|o)", match["marker"]):
            adjacent = bool(levels) or (index + 1 < len(lines) and _MARKER.fullmatch(lines[index + 1]) is not None)

            if not adjacent:
                match = None

        if match:
            indent = len(match["indent"].expandtabs(4))

            # Relative indentation defines nesting; the first item's leading whitespace is not an extra list level.
            while levels and indent < levels[-1]:
                levels.pop()

            if not levels or indent > levels[-1]:
                levels.append(indent)

            result.append(TextBlock(match["text"], len(levels) - 1))
        else:
            indent = len(line.expandtabs(4)) - len(line.expandtabs(4).lstrip())

            if levels and indent > levels[-1] and result[-1].depth is not None:
                # Explicitly indented continuation lines belong to the preceding item; unmarked headings remain paragraphs.
                result[-1] = evolve(result[-1], text=result[-1].text + " " + line.strip())
            else:
                levels.clear()
                result.append(TextBlock(line.strip()))

    return result
