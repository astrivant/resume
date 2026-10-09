"""
Represent captured public GitHub calendar days and validate reproducible inputs.
"""

from __future__ import annotations

import calendar
import json
from datetime import date, timedelta
from importlib.resources import files
from typing import TYPE_CHECKING
from urllib.parse import urlencode

import cattrs
from attrs import asdict, frozen
from jsonschema import Draft202012Validator, FormatChecker

from resumeme.compiler.constants.backend import AST_PACKAGE
from resumeme.compiler.constants.contributions import CALENDAR_SCHEMA
from resumeme.exceptions import ContributionError

if TYPE_CHECKING:
    from pathlib import Path

    from resumeme.config import GitHubContributions

__all__ = ["ContributionDay", "ContributionCalendar", "calendar_window", "load_calendar", "save_calendar", "validate_calendar"]


@frozen
class ContributionDay:
    """
    Retain GitHub's own intensity classification rather than recomputing thresholds.

    Attributes:
        date (str): ISO calendar date.
        count (int): Publicly displayed contribution count.
        level (int): GitHub intensity from zero through four.
    """

    date: str
    count: int
    level: int


@frozen
class ContributionCalendar:
    """
    Bind complete day observations to a public account and inclusive date range.

    Attributes:
        username (str): GitHub account whose public calendar was read.
        start (str): First included ISO date.
        end (str): Last included ISO date.
        days (list[ContributionDay]): Every date in the interval, sorted ascending.
    """

    username: str
    start: str
    end: str
    days: list[ContributionDay]

    @property
    def weeks(self) -> int:
        """
        Count Sunday-first week columns, retaining partial weeks at both ends.

        Returns:
            int: Positive calendar width in weeks.
        """
        start = date.fromisoformat(self.start)
        offset = (start.weekday() + 1) % 7
        return ((date.fromisoformat(self.end) - start).days + offset) // 7 + 1

    @property
    def total(self) -> int:
        """
        Sum only the displayed period's observed activity.

        Returns:
            int: Contribution count across retained days.
        """
        return sum(day.count for day in self.days)

    def cell(self, day: ContributionDay) -> tuple[int, int, str]:
        """
        Locate a day and link to GitHub's corresponding contribution activity view.

        Args:
            day (ContributionDay): Day belonging to this calendar.

        Returns:
            tuple[int, int, str]: Zero-based week, Sunday-first weekday, and HTTPS profile activity URL.
        """
        start = date.fromisoformat(self.start)
        current = date.fromisoformat(day.date)
        week = ((current - start).days + (start.weekday() + 1) % 7) // 7
        query = urlencode({"from": day.date, "to": day.date, "tab": "overview"})
        return week, (current.weekday() + 1) % 7, f"https://github.com/{self.username}?{query}"


def calendar_window(settings: GitHubContributions, *, today: date | None = None) -> tuple[date, date]:
    """
    Select trailing calendar months with an inclusive, optionally pinned endpoint.

    Args:
        settings (GitHubContributions): Month count and optional ISO endpoint.
        today (date | None): Explicit reference date when settings.as_of is unset.

    Returns:
        tuple[date, date]: Inclusive start and end dates, clipping the start day to its month's last valid day.

    Raises:
        ContributionError: No reference date is supplied or the requested window precedes the supported calendar.
    """
    end = date.fromisoformat(settings.as_of) if settings.as_of else today

    if end is None:
        raise ContributionError("GitHub calendar filtering requires profile.github.contributions.as_of or an explicit reference date.")

    year, month = divmod(end.year * 12 + end.month - 1 - settings.months, 12)

    if year < 1:
        raise ContributionError("The GitHub contribution window starts before year 1; choose a later endpoint or fewer months.")

    start = date(year, month + 1, min(end.day, calendar.monthrange(year, month + 1)[1]))
    return start, end


def validate_calendar(calendar: ContributionCalendar, username: str, start: date, end: date) -> None:
    """
    Reject foreign, stale, incomplete, or contradictory calendar evidence.

    Args:
        calendar (ContributionCalendar): Loaded or newly captured observations.
        username (str): Explicitly configured public account.
        start (date): Requested inclusive first day.
        end (date): Requested inclusive last day.

    Returns:
        None: Every requested date appears exactly once under the configured identity.

    Raises:
        ContributionError: The account, date window, day coverage, or activity levels are inconsistent.
    """
    if calendar.username.casefold() != username.casefold() or (calendar.start, calendar.end) != (start.isoformat(), end.isoformat()):
        raise ContributionError("GitHub calendar owner or date range does not match the configured username, months, and as_of.")

    expected = [(start + timedelta(days=offset)).isoformat() for offset in range((end - start).days + 1)]

    # Missing dates indicate a changed or restricted response; never fill them with fabricated zero-contribution days.
    if not expected or [day.date for day in calendar.days] != expected:
        raise ContributionError("GitHub calendar is incomplete or contains duplicated/out-of-order dates.")

    if any(day.count < 0 or day.level not in range(5) or (day.count == 0) != (day.level == 0) for day in calendar.days):
        raise ContributionError("GitHub calendar has inconsistent activity counts or intensity levels.")


def load_calendar(path: Path) -> ContributionCalendar:
    """
    Load a saved public calendar through its packaged schema.

    Args:
        path (Path): Previously generated GitHub calendar JSON.

    Returns:
        ContributionCalendar: Typed observations; the caller validates account and date-window ownership.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    schema = json.loads(files(AST_PACKAGE).joinpath(CALENDAR_SCHEMA).read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(raw)
    return cattrs.Converter(forbid_extra_keys=True).structure(raw, ContributionCalendar)


def save_calendar(calendar: ContributionCalendar, path: Path) -> None:
    """
    Save the exact public observations used to build a resume without credentials or HTML.

    Args:
        calendar (ContributionCalendar): Validated public day counts and intensity levels.
        path (Path): Generated-source artifact destination.

    Returns:
        None: The calendar is available for reproducible offline rendering.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(calendar), indent=2) + "\n", encoding="utf-8")
