"""
Define typed intermediate structures consumed by document backends.
"""

from __future__ import annotations

from attrs import frozen

from resumeme.compiler.asts.names import company_key
from resumeme.compiler.asts.profile import Entry, Media

__all__ = ["TextBlock", "CompanyAffiliation", "ProjectLayout", "JobTarget"]


@frozen
class TextBlock:
    """
    Represent a paragraph or normalized bullet for presentation.

    Attributes:
        text (str): Unescaped content with any recognized marker removed.
        depth (int | None): Zero-based indentation level, or None for ordinary prose.
    """

    text: str
    depth: int | None = None


@frozen
class CompanyAffiliation:
    """
    Present a project's company once with its observed logo and associated roles.

    Attributes:
        company (str): Captured company name using the first observed spelling.
        roles (list[str]): Distinct associated role titles in source order.
        logo (Media): Staged company branding with its observed click destination.
    """

    company: str
    roles: list[str]
    logo: Media


@frozen
class ProjectLayout:
    """
    Own a project display copy and its inline company-logo placements.

    Attributes:
        entry (Entry): Project with moved logos and redundant reference rows removed.
        title_url (str): Observed destination for the project heading, or empty when absent.
        affiliations (dict[str, tuple[str, str, Media]]): Original association line mapped to prefix, company name, and logo.
        metadata (list[str]): Dates and affiliations displayed above the project media.
        description (list[str]): Project prose displayed below its image or logo.
    """

    entry: Entry
    title_url: str
    affiliations: dict[str, tuple[str, str, Media]]
    metadata: list[str]
    description: list[str]

    @property
    def companies(self) -> list[CompanyAffiliation]:
        """
        Group recognized affiliations without changing the source rows supplied to custom templates.

        Returns:
            list[CompanyAffiliation]: Company rows in first-seen order with unique roles and no inferred affiliations.
        """
        groups: dict[str, CompanyAffiliation] = {}

        for prefix, company, logo in self.affiliations.values():
            key = company_key(company)
            group = groups.setdefault(key, CompanyAffiliation(company, [], logo))

            # A company-only association has no role; retain each distinct role from the remaining observed prefixes.
            role = prefix.removeprefix("Associated with ").removesuffix(" at ").strip()

            if role and company_key(role) not in {company_key(value) for value in group.roles}:
                group.roles.append(role)

        return list(groups.values())


@frozen
class JobTarget:
    """
    Locate one visible company or role in document order.

    Attributes:
        anchor (str): Unique identifier generated from section and entry indices.
        company (str): Captured employer, or empty when unavailable.
        title (str): Role title, or empty for a grouped company heading.
    """

    anchor: str
    company: str
    title: str
