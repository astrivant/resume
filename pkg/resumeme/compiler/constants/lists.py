"""
Static lists rules shared by compiler stages.
"""

from __future__ import annotations

import re

__all__ = ["GLYPHS", "MARKER"]

GLYPHS = (
    "\u2022\u2023\u2043\u204c\u204d\u2219\u00b7\u25a0-\u25a3\u25aa\u25ab"
    "\u25b6\u25b8\u25ba\u25c6\u25c7\u25cb\u25cf\u25e6\u2610-\u2612"
    "\u2713\u2714\u2717\u2718\u2705\u2726\u2727\u2605\u2606\u2192\u21d2"
    "\u2794\u27a2\u27a4\u27a5\u27a7\u27ab\u27b2\u27bd"
    "\u2460-\u2473\u2474-\u2487\u2488-\u249b\u2776-\u277f"
    "\U0001f539\U0001f538\U0001f537\U0001f536\U0001f534\U0001f535\U0001f7e0-\U0001f7e3"
)

# Ambiguous ASCII markers and dashes require separation, keeping dates, negative numbers, and versions as ordinary prose.
MARKER = re.compile(
    r"^(?P<indent>[^\S\r\n]*)(?P<marker>"
    r"(?:[-*+][^\S\r\n]+)?\[[ xX]\]"
    rf"|(?P<glyph>[{GLYPHS}]|[0-9]\ufe0f?\u20e3)"
    r"|[-*+\u2010-\u2015\u2212]|(?:->|=>|--|---)"
    r"|(?:\d{1,3}|[a-zA-Z]|[ivxlcdmIVXLCDM]{1,8})[.)]"
    r"|\((?:\d{1,3}|[a-zA-Z]|[ivxlcdmIVXLCDM]{1,8})\)"
    r"|o)(?:\ufe0f)?(?(glyph)[^\S\r\n]*|[^\S\r\n]+)(?P<text>\S.*)$"
)
