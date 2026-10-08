"""
Static sections rules shared by compiler stages.
"""

from __future__ import annotations

__all__ = ["SECTION_TITLES", "DEFAULT_SECTION_ORDER", "ALIASES"]

SECTION_TITLES: dict[str, str] = {
    "contact": "Contact",
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

# The catalog's declared sequence is the default presentation order; users can replace it in configuration.
DEFAULT_SECTION_ORDER = tuple(SECTION_TITLES)

ALIASES = {
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
