"""
Interpret displayed employment periods without guessing dates from descriptive prose.
"""

from __future__ import annotations

import calendar
from datetime import date

from attrs import frozen

from resumeme.compiler.constants.dates import MONTHS as _MONTHS
from resumeme.compiler.constants.dates import PERIOD as _PERIOD

__all__ = ["EmploymentPeriod", "employment_period"]


@frozen
class EmploymentPeriod:
    """
    Represent the widest interval justified by a displayed employment date range.

    Attributes:
        start (date): Earliest possible start date at the displayed precision.
        end (date | None): Latest possible end date, or None for an explicitly ongoing role.
    """

    start: date
    end: date | None


def _boundary(value: str, *, end: bool) -> date:
    """
    Expand year-only and month-only dates to inclusive interval boundaries.

    Args:
        value (str): English month/year, year-only, or ISO date text.
        end (bool): Whether to take the latest possible day instead of the earliest.

    Returns:
        date: Calendar boundary without locale-dependent parsing.

    Raises:
        ValueError: The text contains an invalid date or unsupported month.
    """

    # Use an explicit English month map so build hosts with different locales interpret captured dates identically.
    parts = value.casefold().replace(".", "").split()

    if len(parts) == 2:
        month = _MONTHS.get(parts[0])

        if month is None:
            raise ValueError("Unknown employment month.")

        year = int(parts[1])
    else:
        components = value.split("-")

        if len(components) == 3:
            return date.fromisoformat(value)

        year = int(components[0])
        month = int(components[1]) if len(components) == 2 else (12 if end else 1)

    # Missing day precision represents the whole month, not an invented first-of-month employment end.
    return date(year, month, calendar.monthrange(year, month)[1] if end else 1)


def employment_period(line: str) -> EmploymentPeriod | None:
    """
    Read a complete date-range line, optionally followed by LinkedIn's duration suffix.

    Args:
        line (str): Captured text such as January 2020 - Present.

    Returns:
        EmploymentPeriod | None: Inclusive bounds, or None for absent, unsupported, or inconsistent dates.
    """

    # Match a complete metadata line after removing the duration suffix, never a year range buried in job prose.
    match = _PERIOD.fullmatch(line.split("\u00b7", 1)[0].strip())

    if match is None:
        return None

    try:
        start = _boundary(match[1], end=False)
        end = None if match[2].casefold() in {"present", "current", "now"} else _boundary(match[2], end=True)
    except ValueError:
        # Unknown dates keep a role visible downstream; failed parsing must not silently remove employment history.
        return None

    return EmploymentPeriod(start, end) if end is None or start <= end else None
