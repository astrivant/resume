"""
Static links rules shared by compiler stages.
"""

from __future__ import annotations

import re

__all__ = ["WEB_URL"]

WEB_URL = re.compile(r"(?<![\w@])(?:https?://|www\.)[^\s<>\"'`]+", re.IGNORECASE)
