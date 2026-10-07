"""
Recognize list markers in captured prose without rewriting the saved snapshot.
"""

from __future__ import annotations

import re

from attrs import evolve

from resumeme.compiler.asts.presentation import TextBlock
from resumeme.compiler.constants.lists import MARKER as _MARKER

__all__ = ["TextBlock", "text_blocks"]


def text_blocks(paragraphs: list[str]) -> list[TextBlock]:
    """
    Normalize common ASCII, Unicode, checkbox, and ordered markers into bullet blocks.

    Args:
        paragraphs (list[str]): Original paragraphs, possibly containing embedded newlines and indentation.

    Returns:
        list[TextBlock]: Ordered prose and bullets with indented continuations and comma/semicolon-led sentence fragments joined.
    """
    lines = [line for paragraph in paragraphs for line in (paragraph.splitlines() or [""])]
    result: list[TextBlock] = []
    levels: list[int] = []

    for index, line in enumerate(lines):
        text = line.strip()

        if not text:
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

            # Captured <br> tags can split a sentence into unindented rows. Require punctuation and a lowercase continuation
            # to avoid absorbing unmarked headings, metadata, or attachment titles after ordinary, unpunctuated list items.
            sentence_continuation = (
                bool(levels)
                and result[-1].text.endswith((",", ";"))
                and text[0].islower()
                and not text.endswith(":")
                and not re.match(r"(?:https?://|www\.)", text)
            )

            if levels and result[-1].depth is not None and (indent > levels[-1] or sentence_continuation):
                # Both continuation forms retain the original bullet's nesting and pass through normal link/TeX escaping.
                result[-1] = evolve(result[-1], text=result[-1].text + " " + text)
            else:
                levels.clear()
                result.append(TextBlock(text))

    return result
