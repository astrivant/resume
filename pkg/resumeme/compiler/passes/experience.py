"""
Select displayed employment before templates, assets, and skill scoring consume it.
"""

from __future__ import annotations

import calendar
from datetime import date
from typing import TYPE_CHECKING

from attrs import evolve

from resumeme.compiler.asts.dates import employment_period
from resumeme.compiler.constants.experience import ATTRIBUTION as _ATTRIBUTION
from resumeme.compiler.passes.selection import matches_fields
from resumeme.exceptions import ProfileError

if TYPE_CHECKING:
    from resumeme.compiler.asts.dates import EmploymentPeriod
    from resumeme.compiler.asts.profile import Entry
    from resumeme.config import Experience, JobSelector

__all__ = ["clean_experience", "filter_experience", "regroup_positions"]


def clean_experience(entry: Entry) -> Entry:
    """
    Remove LinkedIn's job-finding attribution from a display copy of an employment entry.

    Args:
        entry (Entry): Selected job or company group after exclusion rules have resolved role boundaries.

    Returns:
        Entry: Display content without attribution rows, retaining the original snapshot and substantive prose.
    """
    paragraphs: list[str] = []

    # Accessibility duplicates can appear as complete or shortened rows, including within a multiline paragraph.
    for paragraph in entry.paragraphs:
        original = paragraph.splitlines()
        lines = [line for line in original if not _ATTRIBUTION.fullmatch(_normalized(line))]

        if len(lines) == len(original):
            paragraphs.append(paragraph)
        elif lines:
            paragraphs.append("\n".join(lines))

    # Keep structured roles and flattened company text consistent for packaged and custom templates.
    return evolve(
        entry,
        paragraphs=paragraphs,
        links=[link for link in entry.links if not _ATTRIBUTION.fullmatch(_normalized(link.label))],
        positions=[clean_experience(position) for position in entry.positions],
    )


def _normalized(value: str) -> str:
    """
    Compare user-entered identities without case or whitespace differences.

    Args:
        value (str): Job title or employer name.

    Returns:
        str: Case-folded text with consecutive whitespace collapsed.
    """
    return " ".join(value.casefold().split())


def _disabled(title: str, company: str, selectors: list[JobSelector]) -> bool:
    """
    Match every field supplied by any one exclusion rule.

    Args:
        title (str): Role title, empty for a company group.
        company (str): Employer without LinkedIn's employment-type suffix.
        selectors (list[JobSelector]): Explicit exclusions.

    Returns:
        bool: Whether at least one rule matches this identity.
    """

    # A selector combines its fields with AND; separate selectors provide alternative ways to exclude a role.
    return any(
        matches_fields((selector.title, (title,), _normalized), (selector.company, (company,), _normalized)) for selector in selectors
    )


def _overlaps(period: EmploymentPeriod, cutoff: date | None, as_of: date) -> bool:
    """
    Include a job when any part of its employment interval intersects the window.

    Args:
        period (EmploymentPeriod): Observed date range.
        cutoff (date | None): Inclusive beginning, or None when date filtering is disabled.
        as_of (date): Inclusive window endpoint used for current roles.

    Returns:
        bool: Whether this period belongs in the displayed employment history.
    """

    # Test interval overlap rather than start-date recency so a long-running role is not lost at the cutoff.
    return cutoff is None or (period.start <= as_of and (period.end is None or period.end >= cutoff))


def regroup_positions(entry: Entry, selected: list[Entry | None]) -> Entry:
    """
    Rebuild a company's flattened presentation from retained or rewritten roles.

    Args:
        entry (Entry): Captured company group, including flattened text and role metadata.
        selected (list[Entry | None]): Replacement or exclusion for each captured role in its original order.

    Returns:
        Entry: Company context and selected descriptions, references, and skills.

    Raises:
        ProfileError: Recorded role boundaries cannot be reconciled with the captured company text.
    """

    # Splice each recorded role in order, preserving company context between roles and avoiding ambiguous title-only matches.
    paragraphs: list[str] = []
    cursor = 0

    for position, replacement in zip(entry.positions, selected, strict=True):
        lines = [position.title, *position.paragraphs]
        start = next(
            (index for index in range(cursor, len(entry.paragraphs)) if entry.paragraphs[index : index + len(lines)] == lines), None
        )

        if start is None:
            raise ProfileError(f"Cannot locate grouped role {position.title!r}. Run `resumeme capture` to refresh its role boundaries.")

        paragraphs.extend(entry.paragraphs[cursor:start])

        if replacement is not None:
            paragraphs.extend([replacement.title, *replacement.paragraphs])

        cursor = start + len(lines)

    paragraphs.extend(entry.paragraphs[cursor:])
    positions = [position for position in selected if position is not None]

    # Remove role-owned references from the parent first, then reintroduce only those belonging to retained roles.
    # This preserves shared logos and links while preventing excluded job content from leaking into the PDF or cloud.
    owned_links = {link.url for position in entry.positions for link in position.links}
    kept_links = {link.url for position in positions for link in position.links}
    owned_images = {(image.url, image.link) for position in entry.positions for image in position.images}
    owned_skills = {_normalized(skill.name) for position in entry.positions for skill in position.skills}
    links = [link for link in entry.links if link.url not in owned_links]
    links.extend(link for position in positions for link in position.links)
    images = [
        image
        for image in entry.images
        if (image.url, image.link) not in owned_images and (image.link not in owned_links or image.link in kept_links)
    ]
    images.extend(image for position in positions for image in position.images)
    skills = [skill for skill in entry.skills if _normalized(skill.name) not in owned_skills]
    skills.extend(skill for position in positions for skill in position.skills)

    # Keep the flattened presentation and structured role metadata consistent for packaged and custom templates.
    return evolve(
        entry,
        paragraphs=paragraphs,
        links=list({link.url: link for link in links}.values()),
        images=list({(image.url, image.link): image for image in images}.values()),
        skills=skills,
        positions=positions,
    )


def _select(entry: Entry, settings: Experience, cutoff: date | None, as_of: date, company: str = "") -> Entry | None:
    """
    Apply explicit exclusions and inclusive dates to one role or company group.

    Args:
        entry (Entry): Captured employment entry.
        settings (Experience): Exclusion rules and window settings.
        cutoff (date | None): Inclusive start, or None for unrestricted dates.
        as_of (date): Inclusive end of the window.
        company (str): Inherited employer for a grouped role, otherwise inferred from the entry.

    Returns:
        Entry | None: Selected entry, or None when all of its roles are excluded.

    Raises:
        ProfileError: An old flattened group needs recapture to safely separate individual roles.
    """
    dated = [(index, period) for index, line in enumerate(entry.paragraphs) if (period := employment_period(line)) is not None]

    if entry.positions:
        # Company-wide exclusions short-circuit the group; otherwise each child inherits its employer for exact matching.
        company = entry.title

        if _disabled("", company, settings.disable):
            return None

        selected = [_select(position, settings, cutoff, as_of, company) for position in entry.positions]

        if all(position is None for position in selected):
            return None

        return entry if selected == entry.positions else regroup_positions(entry, selected)

    if len(dated) > 1:
        # Legacy snapshots flattened grouped jobs, losing per-role media and skill ownership.
        if _disabled(entry.title, entry.title, settings.disable):
            return None

        retained = [
            not _disabled(entry.paragraphs[index - 1] if index else "", entry.title, settings.disable) and _overlaps(period, cutoff, as_of)
            for index, period in dated
        ]

        if not any(retained):
            return None

        # Old snapshots cannot attribute media or tags to individual roles; require recapture instead of guessing ownership.
        if not all(retained):
            raise ProfileError(
                f"Filtering individual roles at {entry.title!r} needs role boundaries. Run `resumeme capture` once to refresh."
            )

        return entry

    # Standalone jobs usually put the employer before the date row, with employment type after a middle-dot separator.
    if not company and entry.paragraphs and (not dated or dated[0][0] > 0):
        company = entry.paragraphs[0].split("\u00b7", 1)[0].strip()

    if _disabled(entry.title, company, settings.disable):
        return None

    # Missing or unreadable dates are insufficient evidence for removal; explicit identity exclusions still apply above.
    if dated and not _overlaps(dated[0][1], cutoff, as_of):
        return None

    return entry


def filter_experience(entries: list[Entry], settings: Experience, *, today: date | None = None) -> list[Entry]:
    """
    Filter employment using only captured inputs, settings, and an explicit reference date.

    Missing and unrecognized dates are retained. Partial dates include their entire
    displayed month or year. February 29 maps to February 28 in a non-leap cutoff year.

    Args:
        entries (list[Entry]): Experience entries in display order.
        settings (Experience): Job exclusions and an optional fixed or trailing calendar-year window.
        today (date | None): Reference date when settings.as_of is unset; required for unpinned date windows.

    Returns:
        list[Entry]: Selected jobs with original descriptions and dates intact.

    Raises:
        ProfileError: A date window lacks an endpoint, its start exceeds its end, or a legacy group cannot be safely separated.
    """

    # Preserve the original records when filtering is disabled, including legacy groups without role boundaries.
    if not settings.disable and settings.last_years is None and settings.since is None:
        return entries

    # Relative windows require context; identity-only exclusions must not invent a clock-dependent date restriction.
    date_filter = settings.last_years is not None or settings.since is not None

    if settings.as_of is None and today is None and date_filter:
        raise ProfileError("Employment date filtering requires experience.as_of or an explicit compilation reference date.")

    as_of = date.fromisoformat(settings.as_of) if settings.as_of else today or date.max

    if not date_filter:
        as_of = date.max
    cutoff = date.fromisoformat(settings.since) if settings.since else None

    # A fixed start stays put as the endpoint advances; users need not clear last_years when switching to it.
    if cutoff is None and settings.last_years is not None:
        # Subtract calendar years, not 365-day intervals, and clamp leap-day anniversaries to an existing date.
        year = as_of.year - settings.last_years
        cutoff = date(year, as_of.month, min(as_of.day, calendar.monthrange(year, as_of.month)[1])) if year > 0 else date.min

    if cutoff is not None and cutoff > as_of:
        raise ProfileError(f"experience.since must be on or before the effective experience.as_of ({as_of.isoformat()}).")

    return [selected for entry in entries if (selected := _select(entry, settings, cutoff, as_of)) is not None]
