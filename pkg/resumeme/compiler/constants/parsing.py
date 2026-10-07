"""
Static parsing rules shared by compiler stages.
"""

from __future__ import annotations

import re

__all__ = ["IGNORED_SECTIONS", "UI_TEXT"]

IGNORED_SECTIONS = {"analytics", "resources", "suggested-for-you"}
UI_TEXT = re.compile(
    r"^(?:show all\b|show more\b|see more$|see less$|show less$|\.\.\.more$|…more$|…see more$|add section$|add profile section$)",
    re.IGNORECASE,
)
