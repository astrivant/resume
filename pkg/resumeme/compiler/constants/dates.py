"""
Static dates rules shared by compiler stages.
"""

from __future__ import annotations

import re

__all__ = ["MONTH_NAMES", "MONTHS", "DATE", "PERIOD"]

MONTH_NAMES = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december")
MONTHS = {name: index for index, name in enumerate(MONTH_NAMES, 1)}
MONTHS.update({name[:3]: index for index, name in enumerate(MONTH_NAMES, 1)})
MONTHS["sept"] = 9
DATE = r"(?:[A-Za-z]+\.?\s+)?\d{4}(?:-\d{2}(?:-\d{2})?)?"
PERIOD = re.compile(rf"^({DATE})\s*[-\u2013\u2014]\s*({DATE}|present|current|now)$", re.IGNORECASE)
