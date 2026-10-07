"""
Static contact rules shared by compiler stages.
"""

from __future__ import annotations

import re

__all__ = ["BIRTHDAY", "CONTACT_FIELD"]

BIRTHDAY = re.compile(r"^(?:birthday|date of birth)(?:\s*[:\uff1a]\s*|\s+|$)", re.IGNORECASE)
CONTACT_FIELD = re.compile(
    r"^(?:your profile|profile|websites?|email|phone(?: number)?|address|im|instant messaging"
    r"|twitter|connected(?: since)?|edit contact info)"
    r"(?:\s*[:\uff1a]|\s*$)",
    re.IGNORECASE,
)
