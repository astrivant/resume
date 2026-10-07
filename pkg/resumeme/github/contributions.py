"""
Fetch the public calendar displayed on GitHub profiles without tokens or browser state.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING
from urllib.parse import urlencode, urlsplit

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter

from resumeme.compiler.asts.contributions import ContributionCalendar, ContributionDay, calendar_window, validate_calendar
from resumeme.compiler.constants.contributions import CONTRIBUTION_COUNT
from resumeme.linkedin.media import _ExponentialRetry, fetch_public

if TYPE_CHECKING:
    from resumeme.config import Config

__all__ = ["fetch_calendar", "parse_calendar"]


def parse_calendar(html: bytes, start: date, end: date) -> list[ContributionDay]:
    """
    Read public calendar cells and English accessibility counts for a requested date interval.

    Args:
        html (bytes): GitHub's public contribution-calendar response.
        start (date): Inclusive first day to retain.
        end (date): Inclusive final day to retain.

    Returns:
        list[ContributionDay]: Sorted observed days, without filling gaps or estimating activity levels.

    Raises:
        ValueError: GitHub omitted an activity count or supplied malformed calendar metadata.
    """
    soup = BeautifulSoup(html, "html.parser")
    labels = {str(label.get("for")): label.get_text(" ", strip=True) for label in soup.select("tool-tip[for]")}
    days: list[ContributionDay] = []

    for cell in soup.select("[data-date][data-level]"):
        current = date.fromisoformat(str(cell["data-date"]))

        if not start <= current <= end:
            continue

        # GitHub's intensity is relative to its full calendar, not just the cropped period requested for the resume.
        count = CONTRIBUTION_COUNT.match(labels.get(str(cell.get("id")), ""))

        if count is None:
            raise ValueError("GitHub changed its public contribution-calendar markup; no activity counts were guessed.")

        days.append(
            ContributionDay(current.isoformat(), 0 if count[1] == "No" else int(count[1].replace(",", "")), int(str(cell["data-level"])))
        )

    return sorted(days, key=lambda day: day.date)


def fetch_calendar(config: Config) -> ContributionCalendar:
    """
    Acquire every requested day with the project's bounded exponential HTTP retries.

    Args:
        config (Config): Public account, calendar window, and existing capture retry policy.

    Returns:
        ContributionCalendar: Complete validated public observations for the configured interval.

    Raises:
        ValueError: No username is configured or GitHub did not return the requested public calendar.
        requests.RequestException: Transient HTTP retries are exhausted or a permanent response fails.
    """
    username = config.github.username

    if username is None:
        raise ValueError("Set github.username before fetching contributions.")

    start, end = calendar_window(config.github.contributions)
    days: list[ContributionDay] = []

    with requests.Session() as session:
        # Read only what hiring managers can see publicly; never inherit tokens, netrc credentials, proxies, or browser cookies.
        session.trust_env = False
        session.headers.update({"User-Agent": "resumeme/0.1 (public contribution calendar)", "Accept-Language": "en-US"})
        policy = _ExponentialRetry(
            total=config.capture.retry_attempts - 1,
            backoff_factor=config.capture.retry_backoff_seconds,
            backoff_max=config.capture.retry_max_backoff_seconds,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            respect_retry_after_header=True,
            retry_after_max=config.capture.retry_max_backoff_seconds,
        )
        session.mount("https://", HTTPAdapter(max_retries=policy))

        # GitHub returns year-sized grids; split cross-year windows so January builds also include the previous December.
        for year in range(start.year, end.year + 1):
            first, last = max(start, date(year, 1, 1)), min(end, date(year, 12, 31))
            query = urlencode({"from": first.isoformat(), "to": last.isoformat()})
            destination = f"https://github.com/users/{username}/contributions"
            html, final_url = fetch_public(session, f"{destination}?{query}", config.capture.page_timeout_seconds)
            location = urlsplit(final_url)

            if location.hostname != "github.com" or location.path.casefold() != f"/users/{username}/contributions".casefold():
                raise ValueError("GitHub redirected away from the configured account's public contribution calendar.")

            days.extend(parse_calendar(html, first, last))

    calendar = ContributionCalendar(username, start.isoformat(), end.isoformat(), days)
    validate_calendar(calendar, username, start, end)
    return calendar
