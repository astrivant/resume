"""
Static contact rules shared by compiler stages.
"""

from __future__ import annotations

import re

__all__ = ["BIRTHDAY", "CONTACT_FIELD", "CONTACT_CONTROL", "PROFILE_FIELD", "PROFILE_URL", "EMAIL_ADDRESS", "WEBSITE_FIELDS"]

BIRTHDAY = re.compile(r"^(?:birthday|date of birth)(?:\s*[:\uff1a]\s*|\s+|$)", re.IGNORECASE)
CONTACT_FIELD = re.compile(
    r"^(?P<label>(?:your |linkedin )?profile(?: link)?|linkedin|websites?|email|phone(?: number)?|address|im|instant messaging"
    r"|twitter|birthday|date of birth|connected(?: since)?|edit contact info)"
    r"(?:\s*[:\uff1a]\s*(?P<value>.*)|\s*$)",
    re.IGNORECASE,
)
CONTACT_CONTROL = re.compile(r"^(?:edit(?: contact info(?:rmation)?)?|contact info(?:rmation)?|close|dismiss|done)$", re.IGNORECASE)
PROFILE_FIELD = re.compile(r"^(?:(?:your |linkedin )?profile(?: link)?|linkedin)$", re.IGNORECASE)
PROFILE_URL = re.compile(r"^(?:https?://)?(?:[a-z0-9-]+\.)*linkedin\.com/(?:in|pub)/", re.IGNORECASE)
EMAIL_ADDRESS = re.compile(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+")
WEBSITE_FIELDS = frozenset({"website", "websites"})
