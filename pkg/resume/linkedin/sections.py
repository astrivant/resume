"""
Normalize known profile section aliases while preserving unfamiliar sections.
"""

from __future__ import annotations

import re

__all__ = ["SECTION_TITLES", "section_key"]

SECTION_TITLES: dict[str, str] = {
    "contact": "Contact info",
    "about": "About",
    "featured": "Featured",
    "activity": "Activity",
    "experience": "Experience",
    "education": "Education",
    "services": "Services",
    "career-breaks": "Career breaks",
    "certifications": "Licenses & certifications",
    "volunteering-experiences": "Volunteer experience",
    "projects": "Projects",
    "publications": "Publications",
    "patents": "Patents",
    "courses": "Courses",
    "honors": "Honors & awards",
    "test-scores": "Test scores",
    "skills": "Skills",
    "recommendations": "Recommendations",
    "languages": "Languages",
    "organizations": "Organizations",
    "interests": "Interests",
    "causes": "Causes",
}
_ALIASES = {
    "contact-info": "contact",
    "licenses-certifications": "certifications",
    "licenses-and-certifications": "certifications",
    "volunteer-experience": "volunteering-experiences",
    "volunteering": "volunteering-experiences",
    "honors-awards": "honors",
    "honors-and-awards": "honors",
    "test-scores": "test-scores",
    "skills-endorsements": "skills",
    "skills-and-endorsements": "skills",
    "career-break": "career-breaks",
}


def section_key(value: str) -> str:
    """
    Give route identifiers and display headings the same stable exclusion key.

    Args:
        value (str): Section heading, anchor, route key, or configured exclusion.

    Returns:
        str: Canonical key for a known section, or the normalized unfamiliar key.
    """
    # Normalize known aliases without treating the catalog as a whitelist; unfamiliar LinkedIn sections remain representable.
    key = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return _ALIASES.get(key, key)
