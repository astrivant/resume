"""
Select displayed employment before templates, assets, and skill scoring consume it.
"""

from __future__ import annotations

import calendar
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from attrs import evolve

from resume.linkedin.dates import employment_period

if TYPE_CHECKING:
    from resume.config import Experience, JobSelector
    from resume.linkedin.dates import EmploymentPeriod
    from resume.models import Entry

__all__ = ["filter_experience"]


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
        (selector.title is None or _normalized(selector.title) == _normalized(title))
        and (selector.company is None or _normalized(selector.company) == _normalized(company))
        for selector in selectors
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


def _regroup(entry: Entry, selected: list[Entry | None]) -> Entry:
    """
    Rebuild a company's flattened presentation using only its selected roles.

    Args:
        entry (Entry): Captured company group, including flattened text and role metadata.
        selected (list[Entry | None]): Selection result for each captured role in its original order.

    Returns:
        Entry: Company context and selected descriptions, references, and skills.

    Raises:
        ValueError: Recorded role boundaries cannot be reconciled with the captured company text.
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
            raise ValueError(f"Cannot locate grouped role {position.title!r}. Run `resume capture` to refresh its role boundaries.")

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
        ValueError: An old flattened group needs recapture to safely separate individual roles.
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

        return entry if selected == entry.positions else _regroup(entry, selected)

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
            raise ValueError(f"Filtering individual roles at {entry.title!r} needs role boundaries. Run `resume capture` once to refresh.")

        return entry

    # Standalone jobs usually put the employer before the date row, with employment type after a middle-dot separator.
    if not company and entry.paragraphs and (not dated or dated[0][0] > 0):
        company = entry.paragraphs[0].split("·", 1)[0].strip()

    if _disabled(entry.title, company, settings.disable):
        return None

    # Missing or unreadable dates are insufficient evidence for removal; explicit identity exclusions still apply above.
    if dated and not _overlaps(dated[0][1], cutoff, as_of):
        return None

    return entry


def filter_experience(entries: list[Entry], settings: Experience, *, today: date | None = None) -> list[Entry]:
    """
    Filter employment without mutating captured inputs or using the machine's local timezone.

    Missing and unrecognized dates are retained. Partial dates include their entire
    displayed month or year. February 29 maps to February 28 in a non-leap cutoff year.

    Args:
        entries (list[Entry]): Experience entries in display order.
        settings (Experience): Job exclusions and optional trailing calendar-year window.
        today (date | None): Explicit current UTC date for deterministic callers; defaults to the clock.

    Returns:
        list[Entry]: Selected jobs with original descriptions and dates intact.
    """

    # Preserve the original records when filtering is disabled, including legacy groups without role boundaries.
    if not settings.disable and settings.last_years is None:
        return entries

    # A pinned endpoint makes rebuilds repeatable; otherwise use one UTC date consistently for every job in this call.
    as_of = date.fromisoformat(settings.as_of) if settings.as_of else today or datetime.now(UTC).date()
    cutoff = None

    if settings.last_years is not None:
        # Subtract calendar years, not 365-day intervals, and clamp leap-day anniversaries to an existing date.
        year = as_of.year - settings.last_years
        cutoff = date(year, as_of.month, min(as_of.day, calendar.monthrange(year, as_of.month)[1])) if year > 0 else date.min

    return [selected for entry in entries if (selected := _select(entry, settings, cutoff, as_of)) is not None]
