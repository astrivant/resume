"""
Static header rules shared by compiler stages.
"""

from __future__ import annotations

import re

__all__ = ["COUNT", "PRONOUN", "PRONOUNS", "LEGACY_HEADLINE"]

COUNT = re.compile(r"^[\d][\d,.\s]*[km]?\+?\s+connections?$", re.IGNORECASE)
PRONOUN = r"(?:she|her|hers|he|him|his|they|them|their|theirs|it|its|xe|xem|xyr|xyrs|ze|zir|zirs|hir|hirs|ey|em|eir|eirs)"
PRONOUNS = re.compile(rf"{PRONOUN}(?:\s*/\s*{PRONOUN})+", re.IGNORECASE)
LEGACY_HEADLINE = re.compile(r"\S\s+(?:@|at)\s+\S")
