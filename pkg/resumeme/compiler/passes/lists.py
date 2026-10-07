"""
Recognize list markers in captured prose without rewriting the saved snapshot.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from attrs import evolve

from resumeme.compiler.asts.dates import employment_period
from resumeme.compiler.asts.presentation import TextBlock
from resumeme.compiler.constants.lists import BODY_HEADINGS
from resumeme.compiler.constants.lists import MARKER as _MARKER
from resumeme.compiler.passes.headings import is_body_heading

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["TextBlock", "text_blocks"]


def text_blocks(paragraphs: list[str], *, reflow_soft_breaks: bool = True, subheadings: Sequence[str] = BODY_HEADINGS) -> list[TextBlock]:
    """
    Normalize common ASCII, Unicode, checkbox, and ordered markers into bullet blocks.

    Args:
        paragraphs (list[str]): Original paragraphs, possibly containing embedded newlines and indentation.
        reflow_soft_breaks (bool): Join continuation lines; False retains every captured line boundary.
        subheadings (Sequence[str]): Standalone labels that delimit body subsections even when highlighting is disabled.

    Returns:
        list[TextBlock]: Prose and bullets with soft breaks reflowed; blank lines, headings, and list boundaries remain distinct.
    """
    lines = [(line, owner) for owner, paragraph in enumerate(paragraphs) for line in (paragraph.splitlines() or [""])]
    result: list[TextBlock] = []
    levels: list[int] = []

    for index, (line, owner) in enumerate(lines):
        text = " ".join(line.split())

        if not text:
            levels.clear()
            continue

        match = _MARKER.fullmatch(line)

        # An isolated initial such as "A. Smith" or the ASCII circle "o" is ambiguous without adjacent list items.
        if match and re.fullmatch(r"(?:[a-zA-Z]+\.|o)", match["marker"]):
            adjacent = bool(levels) or (index + 1 < len(lines) and _MARKER.fullmatch(lines[index + 1][0]) is not None)

            if not adjacent:
                match = None

        if match:
            indent = len(match["indent"].expandtabs(4))

            # Relative indentation defines nesting; the first item's leading whitespace is not an extra list level.
            while levels and indent < levels[-1]:
                levels.pop()

            if not levels or indent > levels[-1]:
                levels.append(indent)

            result.append(TextBlock(" ".join(match["text"].split()), len(levels) - 1))
        else:
            indent = len(line.expandtabs(4)) - len(line.expandtabs(4).lstrip())

            # A single break within one captured block is a soft wrap, regardless of punctuation or capitalization.
            # Blank lines and metadata still delimit content; separate captured blocks retain their own ownership.
            same_paragraph = bool(index and lines[index - 1][1] == owner and lines[index - 1][0].strip())
            boundary = bool(result) and any(
                value.endswith(":") or is_body_heading(value, labels=subheadings) or employment_period(value) is not None
                for value in (result[-1].text, text)
            )

            # Older snapshots flattened <br> tags into separate rows. Keep their conservative punctuation heuristic,
            # since row ownership is unavailable and a following attachment caption must not become job prose.
            sentence_continuation = (
                bool(levels)
                and result[-1].text.endswith((",", ";"))
                and text[0].islower()
                and not text.endswith(":")
                and not re.match(r"(?:https?://|www\.)", text)
            )

            if (
                reflow_soft_breaks
                and not boundary
                and (same_paragraph or (levels and result[-1].depth is not None and (indent > levels[-1] or sentence_continuation)))
            ):
                # Joining at the presentation boundary retains bullet nesting and the normal link/TeX escaping path.
                result[-1] = evolve(result[-1], text=result[-1].text + " " + text)
            else:
                levels.clear()
                result.append(TextBlock(text))

    return result
