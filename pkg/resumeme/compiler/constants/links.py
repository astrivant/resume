"""
Static links rules shared by compiler stages.
"""

from __future__ import annotations

import re

__all__ = ["WEB_URL", "DEFAULT_PROJECT_FILTER"]

WEB_URL = re.compile(r"(?<![\w@])(?:https?://|www\.)[^\s<>\"'`]+", re.IGNORECASE)

# Match the GitHub host rather than mentions of its name in another site's path or query.
DEFAULT_PROJECT_FILTER = r"(?i)^https?://(?:www\.)?github\.com(?:[/?#]|$)"
