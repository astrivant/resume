"""
Keep GitHub calendar parsing and light-theme color conventions explicit.
"""

from __future__ import annotations

import re

__all__ = ["CONTRIBUTION_COLORS", "CONTRIBUTION_COUNT", "CALENDAR_SCHEMA"]

# GitHub's default light theme, excluding seasonal palettes. Source: github.githubassets.com/assets/light-5c4e9fc574bf49f3.css.
CONTRIBUTION_COLORS = ("eff2f5", "aceebb", "4ac26b", "2da44e", "116329")
CONTRIBUTION_COUNT = re.compile(r"^(No|[\d,]+) contributions? on\b")
CALENDAR_SCHEMA = "resources/github-calendar.schema.json"
