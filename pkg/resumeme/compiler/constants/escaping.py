"""
Static escaping rules shared by compiler stages.
"""

from __future__ import annotations

import re

__all__ = ["ESCAPES", "EMOJI", "PUNCTUATION"]

# Normalize editorial typography at presentation time while keeping captured text and accented names intact.
PUNCTUATION = {
    "\u2010": "-",
    "\u2011": "-",
    "\u2012": "-",
    "\u2013": "-",
    "\u2014": "-",
    "\u2015": "-",
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2026": "...",
}

ESCAPES = {
    **PUNCTUATION,
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}
EMOJI = re.compile(
    "[\U0001f1e6-\U0001f1ff]{2}|[#*0-9]\ufe0f?\u20e3|"
    "[\U0001f300-\U0001faff\u2600-\u27bf](?:\ufe0f|[\U0001f3fb-\U0001f3ff])?"
    "(?:\u200d[\U0001f300-\U0001faff\u2600-\u27bf](?:\ufe0f|[\U0001f3fb-\U0001f3ff])?)*"
)
