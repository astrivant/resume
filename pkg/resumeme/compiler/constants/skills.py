"""
Static skills rules shared by compiler stages.
"""

from __future__ import annotations

import re

__all__ = [
    "COLLAPSED_SKILLS",
    "ENDORSEMENTS",
    "SKILL_ASSOCIATION_PATH",
    "SKILL_COUNT",
    "SKILL_PREFIX",
    "SKILL_ROW_SEPARATOR",
    "TAG_PREFIX",
    "TAG_ROW",
]

ENDORSEMENTS = re.compile(r"(?<![\w.])([\d,]+)(\+)?\s+endorsements?\b", re.IGNORECASE)
COLLAPSED_SKILLS = re.compile(r"(?<!\w)(?:and\s+)?[+\uff0b]\s*(?P<count>\d+)\s+(?:more\s+)?skills?\s*$", re.IGNORECASE)
SKILL_PREFIX = re.compile(r"^skills:\s*", re.IGNORECASE)
SKILL_COUNT = re.compile(r"\d+\s+skills?", re.IGNORECASE)
SKILL_ASSOCIATION_PATH = re.compile(r"/skill-associations(?:-details)?(?:/|$)")
SKILL_ROW_SEPARATOR = r"(?:\s*[,;\u00b7]\s*(?:and\s+)?|\s+(?:and|&)\s+)"
TAG_PREFIX = re.compile(r"^(?:skills|tags):\s*", re.IGNORECASE)
TAG_ROW = re.compile(r"(?:#[^\W\d]\w*(?:[\s,;]+|$))+")
