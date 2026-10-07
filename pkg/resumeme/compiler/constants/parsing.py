"""
Static parsing rules shared by compiler stages.
"""

from __future__ import annotations

import re

__all__ = ["BLOCK_TAGS", "IGNORED_SECTIONS", "PARAGRAPH_BREAK", "UI_TEXT"]

# HTML blocks delimit profile rows; inline spans, emphasis, and links must not introduce paragraph breaks.
BLOCK_TAGS = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "dd",
        "div",
        "dl",
        "dt",
        "figcaption",
        "figure",
        "footer",
        "header",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "li",
        "main",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }
)
PARAGRAPH_BREAK = "\u2029"

IGNORED_SECTIONS = {"analytics", "resources", "suggested-for-you"}
UI_TEXT = re.compile(
    r"^(?:show all\b|show more\b|see more$|see less$|show less$|\.\.\.more$|…more$|…see more$|add section$|add profile section$)",
    re.IGNORECASE,
)
