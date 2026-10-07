"""
Static locations rules shared by compiler stages.
"""

from __future__ import annotations

import re

__all__ = ["WORK_MODES", "HEADINGS", "DURATION", "PLACE", "CONNECTORS"]

WORK_MODES = {"remote", "hybrid", "on-site", "on site", "onsite"}
HEADINGS = {"responsibilities", "projects", "technologies", "skills", "achievements", "description", "summary", "highlights"}
DURATION = re.compile(r"(?:\d+\s+(?:yrs?|years?|mos?|months?)\s*)+", re.IGNORECASE)
PLACE = re.compile(r"[^\W_][\w\s,.'\u2019()&/\u2013-]*")
CONNECTORS = {"de", "del", "da", "do", "du", "des", "of", "the", "and", "am", "an", "der", "den"}
