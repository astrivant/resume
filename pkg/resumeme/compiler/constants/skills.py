"""
Static skills rules shared by compiler stages.
"""

from __future__ import annotations

import re

__all__ = ["COLLAPSED_SKILLS", "ENDORSEMENTS", "SKILL_COUNT", "SKILL_PREFIX"]

ENDORSEMENTS = re.compile(r"(?<![\w.])([\d,]+)(\+)?\s+endorsements?\b", re.IGNORECASE)
COLLAPSED_SKILLS = re.compile(r"(?<!\w)(?:and\s+)?[+\uff0b]\s*(?P<count>\d+)\s+(?:more\s+)?skills?\s*$", re.IGNORECASE)
SKILL_PREFIX = re.compile(r"^skills:\s*", re.IGNORECASE)
SKILL_COUNT = re.compile(r"\d+\s+skills?", re.IGNORECASE)
