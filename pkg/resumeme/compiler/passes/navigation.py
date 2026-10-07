"""
Resolve project affiliations to visible employment destinations inside the PDF.
"""

from __future__ import annotations

import unicodedata
from typing import TYPE_CHECKING

from attrs import frozen

from resumeme.compiler.asts.dates import employment_period
from resumeme.compiler.asts.presentation import JobTarget
from resumeme.compiler.passes.media import employer_badge
from resumeme.compiler.passes.progression import experience_layout

if TYPE_CHECKING:
    from resumeme.compiler.asts.profile import Entry, Section

__all__ = ["ExperienceNavigation", "JobTarget", "experience_navigation"]


def _key(value: str) -> str:
    """
    Compare captured names without case, whitespace, or trailing-period differences.

    Args:
        value (str): Company or role display name.

    Returns:
        str: Normalized matching key; never used as a PDF destination identifier.
    """
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split()).rstrip(".")


@frozen
class ExperienceNavigation:
    """
    Match affiliations against filtered employment without inventing missing destinations.

    Attributes:
        targets (list[JobTarget]): Visible destinations in document order, including nested roles.
    """

    targets: list[JobTarget]

    def destination(self, company: str, roles: list[str] | None = None) -> str:
        """
        Resolve an employer and optional associated roles to their first visible match.

        Args:
            company (str): Observed employer name.
            roles (list[str] | None): Associated role titles; None or empty selects the company entry.

        Returns:
            str: Matching anchor, or empty when the referenced employment is absent.
        """
        titles = {_key(role) for role in roles or []}

        # Explicit roles must match a retained position; a hidden role must not fall back to a different job at that company.
        return next(
            (
                target.anchor
                for target in self.targets
                if _key(target.company) == _key(company) and (not titles or _key(target.title) in titles)
            ),
            "",
        )

    def association(self, line: str) -> tuple[str, str, str] | None:
        """
        Link an unbranded association while retaining its original wording.

        Args:
            line (str): Captured metadata line, with or without a known employer logo.

        Returns:
            tuple[str, str, str] | None: Original prefix, linked label, and anchor, or None without a safe match.
        """
        if not line.startswith("Associated with "):
            return None

        label = line.removeprefix("Associated with ")
        role, separator, company = label.rpartition(" at ")
        anchor = self.destination(company, [role]) if separator else self.destination(label)

        # Some attachments identify only a role. Resolve those only when the title occurs once among visible positions.
        if not separator and not anchor:
            matches = [target.anchor for target in self.targets if _key(target.title) == _key(label)]
            anchor = matches[0] if len(matches) == 1 else ""

        label = company if separator else label
        return (line[: -len(label)], label, anchor) if anchor and label else None


def experience_navigation(sections: list[tuple[str, Section]]) -> ExperienceNavigation:
    """
    Index the same employment hierarchy that the template renders after filtering and consolidation.

    Args:
        sections (list[tuple[str, Section]]): Section anchors and staged, visible content in document order.

    Returns:
        ExperienceNavigation: Destinations using section/entry paths, independent of logos and potentially repeated titles.
    """
    targets: list[JobTarget] = []

    def collect(entry: Entry, anchor: str, company: str = "") -> None:
        """
        Index a company group or standalone job and recurse through visible roles.

        Args:
            entry (Entry): Employment content before its presentation split.
            anchor (str): Unique section and entry path.
            company (str): Inherited employer for nested roles, empty for a root entry.

        Returns:
            None: Append destinations in the template's render order.
        """
        entry = experience_layout(entry)

        if entry.positions:
            company = entry.title
        elif not company:
            badge = employer_badge(entry)
            dated = next((index for index, line in enumerate(entry.paragraphs) if employment_period(line)), None)

            # A logo is optional. A company row immediately before the first date also establishes employer identity.
            if badge and badge[0] == -1:
                company = entry.title
            elif entry.paragraphs and (dated == 1 or (badge and badge[0] == 0)):
                company = entry.paragraphs[0].split("\u00b7", 1)[0].strip()

        targets.append(JobTarget(anchor, company, "" if entry.positions else entry.title))

        for index, position in enumerate(entry.positions):
            collect(position, f"{anchor}-{index}", company)

    for anchor, section in sections:
        if section.key == "experience":
            for index, entry in enumerate(section.entries):
                collect(entry, f"{anchor}-job-{index}")

    return ExperienceNavigation(targets)
