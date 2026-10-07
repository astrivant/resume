"""
Static skills rules shared by compiler stages.
"""

from __future__ import annotations

import re

__all__ = ["ENDORSEMENTS"]

ENDORSEMENTS = re.compile(r"(?<![\w.])([\d,]+)(\+)?\s+endorsements?\b", re.IGNORECASE)
