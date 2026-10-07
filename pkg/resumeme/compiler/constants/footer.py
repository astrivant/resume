"""
Place compact release provenance to the right of the existing centered page number.
"""

from __future__ import annotations

__all__ = ["FOOTER_BASELINE", "FOOTER_FONT_SIZE", "FOOTER_GRAY", "FOOTER_LEADING", "FOOTER_MARGIN", "FOOTER_NAME"]

# Align the block's center with the page number and its right edge with the template's 19mm paper margin.
FOOTER_BASELINE = 26
FOOTER_LEADING = 9
FOOTER_MARGIN = 19 * 72 / 25.4
FOOTER_FONT_SIZE = 7
FOOTER_GRAY = 0.6
FOOTER_NAME = "/ResumemeReleaseFooter"
