"""
Static experience rules shared by compiler stages.
"""

from __future__ import annotations

import re

__all__ = ["ATTRIBUTION"]

# LinkedIn can repeat full and shortened accessibility labels in the same row, in either order.
ATTRIBUTION = re.compile(r"(?:(?:linkedin\s+)?helped\s+me\s+get\s+this\s+job[.!]*\s*)+", re.IGNORECASE)
