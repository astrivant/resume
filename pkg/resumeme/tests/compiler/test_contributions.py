"""
Verify public contribution capture, date windows, rendering placement, and offline reuse.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit

import pytest
import requests
from attrs import evolve
from jsonschema import ValidationError
from requests.adapters import HTTPAdapter

from resumeme.cli import main
from resumeme.compiler.asts.contributions import (
    ContributionCalendar,
    calendar_window,
    load_calendar,
    save_calendar,
    validate_calendar,
)
from resumeme.compiler.asts.profile import Entry, Link, Profile, Section, save_profile
from resumeme.compiler.constants.contributions import CONTRIBUTION_COLORS
from resumeme.compiler.pipeline import render_profile
from resumeme.config import Config, GitHub, GitHubContributions, LinkedIn, load_config
from resumeme.github.contributions import fetch_calendar, parse_calendar

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch


def _html(start: date, end: date, *, count: int = 3, level: int = 1) -> bytes:
    """
    Model public calendar markup with accessibility counts and deliberately reversed dates.

    Args:
        start (date): Inclusive first fixture day.
        end (date): Inclusive last fixture day.
        count (int): Same publicly displayed count for each fixture cell.
        level (int): GitHub-assigned intensity level.

    Returns:
        bytes: Minimal GitHub-shaped HTML without a browser or network dependency.
    """
    cells = []

    for offset in reversed(range((end - start).days + 1)):
        current = start + timedelta(days=offset)
        label = f"{count:,} contributions" if count else "No contributions"
        cells.append(
            f'<td id="day-{offset}" data-date="{current}" data-level="{level}"></td>'
            f'<tool-tip for="day-{offset}">{label} on January 1st.</tool-tip>'
        )

    return "".join(cells).encode("utf-8")


def _calendar(settings: GitHubContributions) -> ContributionCalendar:
    """
    Prepare complete deterministic observations for a pinned configuration.

    Args:
        settings (GitHubContributions): Month window with an explicit endpoint.

    Returns:
        ContributionCalendar: Public fixture account and one record per requested day.
    """
    start, end = calendar_window(settings)
    return ContributionCalendar("example-person", start.isoformat(), end.isoformat(), parse_calendar(_html(start, end), start, end))


@pytest.mark.parametrize(
    "end,months,start",
    [
        ("2026-10-07", 1, "2026-09-07"),
        ("2026-01-07", 1, "2025-12-07"),
        ("2024-03-31", 1, "2024-02-29"),
        ("2025-03-31", 1, "2025-02-28"),
        ("2024-02-29", 12, "2023-02-28"),
        ("2026-10-07", 6, "2026-04-07"),
    ],
)
def test_trailing_calendar_months(end: str, months: int, start: str) -> None:
    """
    Clip short-month boundaries without treating a calendar month as thirty days.

    Args:
        end (str): Inclusive endpoint.
        months (int): Trailing month count.
        start (str): Expected inclusive start.

    Returns:
        None: Both explicit endpoints and injected current dates select the same window.
    """
    expected = (date.fromisoformat(start), date.fromisoformat(end))
    assert calendar_window(GitHubContributions(months=months, as_of=end)) == expected
    assert calendar_window(GitHubContributions(months=months), today=date.fromisoformat(end)) == expected


def test_parse_counts_intensities_and_day_links() -> None:
    """
    Preserve GitHub's own count and intensity independently of the selected interval.

    Returns:
        None: Cropped days are sorted, comma-separated counts parse, and links select precisely one day.
    """
    start, end = date(2026, 9, 7), date(2026, 10, 7)
    days = parse_calendar(_html(start - timedelta(days=1), end + timedelta(days=1), count=1234, level=4), start, end)
    calendar = ContributionCalendar("example-person", str(start), str(end), days)
    validate_calendar(calendar, "EXAMPLE-PERSON", start, end)
    assert len(days) == 31
    assert calendar.total == 31 * 1234
    assert calendar.weeks == 5
    assert {day.level for day in days} == {4}
    assert calendar.cell(days[0])[:2] == (0, 1)
    assert calendar.cell(days[-1])[:2] == (4, 3)

    for day in days:
        destination = urlsplit(calendar.cell(day)[2])
        assert destination.netloc == "github.com"
        assert destination.path == "/example-person"
        assert parse_qs(destination.query) == {"from": [day.date], "to": [day.date], "tab": ["overview"]}


def test_zero_activity_is_observed_not_assumed() -> None:
    """
    Accept explicitly empty activity while rejecting missing, duplicate, and inconsistent observations.

    Returns:
        None: A real zero calendar is valid; malformed responses never become invented zeros.
    """
    start, end = date(2026, 9, 7), date(2026, 9, 8)
    days = parse_calendar(_html(start, end, count=0, level=0), start, end)
    calendar = ContributionCalendar("example-person", str(start), str(end), days)
    validate_calendar(calendar, calendar.username, start, end)
    assert calendar.total == 0

    for invalid in [[], days[:1], days + days[:1], list(reversed(days)), [evolve(days[0], level=1), days[1]]]:
        with pytest.raises(ValueError):
            validate_calendar(evolve(calendar, days=invalid), calendar.username, start, end)

    with pytest.raises(ValueError, match="owner or date range"):
        validate_calendar(calendar, "different-owner", start, end)

    with pytest.raises(ValueError, match="owner or date range"):
        validate_calendar(calendar, calendar.username, start - timedelta(days=1), end)

    with pytest.raises(ValueError, match="markup"):
        parse_calendar(b'<td data-date="2026-09-07" data-level="0"></td>', start, end)


def test_fetch_handles_year_boundaries_without_credentials(monkeypatch: MonkeyPatch) -> None:
    """
    Request both calendar years and configure bounded retries without inheriting authentication.

    Args:
        monkeypatch (MonkeyPatch): Replace the HTTP boundary with recorded public responses.

    Returns:
        None: One request per year covers the configured window with the expected retry and credential policy.
    """
    settings = GitHubContributions(enabled=True, as_of="2026-01-07")
    config = Config(LinkedIn("linkedin-owner"), github=GitHub("example-person", settings))
    calls: list[str] = []

    def fetch(session: requests.Session, url: str, timeout: int) -> tuple[bytes, str]:
        """
        Return one year segment and assert the public client contract.

        Args:
            session (requests.Session): Unauthenticated HTTP client.
            url (str): Account calendar and explicit year-segment dates.
            timeout (int): Configured request timeout.

        Returns:
            tuple[bytes, str]: Fixture calendar and unchanged destination.
        """
        assert session.trust_env is False
        assert session.auth is None
        assert "Authorization" not in session.headers
        assert session.headers["Accept-Language"] == "en-US"
        assert timeout == config.capture.page_timeout_seconds
        adapter = session.get_adapter(url)
        assert isinstance(adapter, HTTPAdapter)
        assert adapter.max_retries.total == config.capture.retry_attempts - 1
        assert adapter.max_retries.backoff_factor == config.capture.retry_backoff_seconds
        assert adapter.max_retries.backoff_max == config.capture.retry_max_backoff_seconds
        assert 429 in adapter.max_retries.status_forcelist
        assert 403 not in adapter.max_retries.status_forcelist
        calls.append(url)
        query = parse_qs(urlsplit(url).query)
        return _html(date.fromisoformat(query["from"][0]), date.fromisoformat(query["to"][0])), url

    monkeypatch.setattr("resumeme.github.contributions.fetch_public", fetch)
    calendar = fetch_calendar(config)
    assert len(calls) == 2
    assert "from=2025-12-07&to=2025-12-31" in calls[0]
    assert "from=2026-01-01&to=2026-01-07" in calls[1]
    assert len(calendar.days) == 32


@pytest.mark.parametrize("response", ["login", "missing", "failure"])
def test_unavailable_calendar_fails_visibly(monkeypatch: MonkeyPatch, response: str) -> None:
    """
    Reject changed markup, redirects, and transport failures without silently removing enabled graphs.

    Args:
        monkeypatch (MonkeyPatch): Scoped HTTP boundary replacement.
        response (str): Failure condition returned by GitHub.

    Returns:
        None: The failure propagates before a PDF can be published.
    """
    config = Config(LinkedIn("example"), github=GitHub("example-person", GitHubContributions(enabled=True, as_of="2026-10-07")))

    def fetch(session: requests.Session, url: str, timeout: int) -> tuple[bytes, str]:
        """
        Simulate a failed public read without making HTTP requests.

        Args:
            session (requests.Session): Unused public client.
            url (str): Requested destination.
            timeout (int): Unused request timeout.

        Returns:
            tuple[bytes, str]: Incomplete HTML or a redirect destination.

        Raises:
            requests.HTTPError: The failure case simulates exhausted transport retries.
        """
        if response == "failure":
            raise requests.HTTPError("GitHub unavailable")

        return b"<html>No public calendar</html>", "https://github.com/login" if response == "login" else url

    monkeypatch.setattr("resumeme.github.contributions.fetch_public", fetch)

    with pytest.raises(requests.HTTPError if response == "failure" else ValueError):
        fetch_calendar(config)


@pytest.mark.parametrize("side", ["left", "right"])
@pytest.mark.parametrize("placement", ["profile", "appendix"])
def test_template_places_linked_cells_in_configured_location(tmp_path: Path, side: str, placement: str) -> None:
    """
    Emit one day link per observation and keep appendix output separate from first-page profile content.

    Args:
        tmp_path (Path): Temporary config and generated source root.
        side (str): Profile column placement.
        placement (str): Calendar's configured destination.

    Returns:
        None: Both profile sides and appendix layouts preserve data, exact day links, and GitHub colors.
    """
    path = tmp_path / "resumeme.config.yaml"
    path.write_text(
        "linkedin: {username: example-person}\n"
        f"style: {{profile_column_side: {side}}}\n"
        "github:\n  username: example-person\n  contributions:\n"
        f"    enabled: true\n    placement: {placement}\n    as_of: '2026-10-07'\n",
        encoding="utf-8",
    )
    config = load_config(path)
    calendar = _calendar(config.github.contributions)
    source = render_profile(Profile("example-person", "Alex"), config, tmp_path, contributions=calendar).read_text()
    assert source.count("tab=overview") == len(calendar.days)

    for color in CONTRIBUTION_COLORS:
        assert "{HTML}{" + color + "}" in source

    graph = source.index("tab=overview")
    assert graph > source.index("GitHub: example-person")
    assert ("\\finishthispage" in source) == (placement == "appendix")

    if placement == "appendix":
        assert graph > source.index("\\finishthispage")
        assert "\\hyperlink{github-contributions}" in source
    else:
        assert graph < source.index("\\sbox{\\profileidentitybox}") if side == "right" else True

    assert load_calendar(tmp_path / "tex/github-contributions.json") == calendar


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("placement", ["profile", "appendix"])
def test_contact_owns_profile_graph_but_not_appendix(tmp_path: Path, enabled: bool, placement: str) -> None:
    """
    Keep social links and the sidebar graph together above Contents, with independent appendix visibility.

    Args:
        tmp_path (Path): Isolated configuration and rendering directory.
        enabled (bool): Whether Contact is included in section_order.
        placement (str): Requested contribution placement.

    Returns:
        None: Graph cells occur once in their requested visible location and Contact and Contents share heading styling.
    """
    path = tmp_path / "resumeme.config.yaml"
    path.write_text(
        "linkedin: {username: example-person}\n"
        "style: {show_connection_link: true, display_websites: true}\n"
        f"section_order: {['about', 'contact'] if enabled else ['about']}\n"
        "github:\n  username: example-person\n  contributions:\n"
        f"    enabled: true\n    placement: {placement}\n    as_of: '2026-10-07'\n"
    )
    config = load_config(path)
    calendar = _calendar(config.github.contributions)
    connections = "https://www.linkedin.com/mynetwork/invite-connect/connections/"
    website = Link("Portfolio", "https://example.org/alex")
    profile = Profile(
        "example-person",
        "Alex",
        links=[Link("Connections", connections)],
        sections=[
            Section("about", "About", [Entry("Build systems")]),
            Section("contact", "Contact info", [Entry("Website", ["Portfolio"], links=[website]), Entry("Email", ["alex@example.org"])]),
        ],
    )
    source = render_profile(profile, config, tmp_path, contributions=calendar).read_text()
    body = source.split(r"\begin{document}", 1)[1]
    assert (r"\identityheading{Contact}" in body) is enabled
    assert r"\identityheading{Contents}" in body
    assert body.count("tab=overview") == (len(calendar.days) if enabled or placement == "appendix" else 0)

    if enabled:
        assert body.index(r"\identityheading{Contact}") < body.index("LinkedIn profile") < body.index("GitHub: example-person")
        assert body.index("LinkedIn profile") < body.index("https://example.org/alex") < body.index("mailto:alex@example.org")
        assert body.index("mailto:alex@example.org") < body.index(connections) < body.index("GitHub: example-person")
        assert body.index("GitHub: example-person") < body.index(r"\identityheading{Contents}")

        if placement == "profile":
            assert body.index("GitHub: example-person") < body.index("tab=overview") < body.index(r"\identityheading{Contents}")


def test_cli_disabled_and_offline_calendar_paths_do_not_fetch(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Keep default builds offline and permit enabled graphs to reuse an explicitly owned snapshot.

    Args:
        tmp_path (Path): Complete synthetic project with saved profile and calendar.
        monkeypatch (MonkeyPatch): Deny HTTP acquisition for both CLI scenarios.

    Returns:
        None: Rendering succeeds without networking, while stale calendar ownership is rejected.
    """

    def forbidden(config: Config) -> ContributionCalendar:
        """
        Fail if an offline CLI path attempts to fetch activity.

        Args:
            config (Config): Unused render configuration.

        Returns:
            ContributionCalendar: Never returned because this boundary is forbidden.
        """
        raise AssertionError("Unexpected GitHub request")

    monkeypatch.setattr("resumeme.cli.fetch_calendar", forbidden)
    config = tmp_path / "resumeme.config.yaml"
    config.write_text("linkedin: {username: example-person}\n", encoding="utf-8")
    save_profile(Profile("example-person", "Alex"), tmp_path / "data/profile.json")
    assert main(["--config", str(config), "render"]) == 0
    assert "tab=overview" not in (tmp_path / "tex/resume.tex").read_text()
    settings = GitHubContributions(enabled=True, as_of="2026-10-07")
    save_calendar(_calendar(settings), tmp_path / "calendar.json")

    with config.open("a") as stream:
        stream.write("github:\n  username: example-person\n  contributions: {enabled: true, as_of: '2026-10-07'}\n")

    assert main(["--config", str(config), "render", "--github-calendar", "calendar.json"]) == 0
    raw = json.loads((tmp_path / "calendar.json").read_text())
    raw["username"] = "someone-else"
    (tmp_path / "calendar.json").write_text(json.dumps(raw))
    assert main(["--config", str(config), "render", "--github-calendar", "calendar.json"]) == 2


@pytest.mark.parametrize(
    "settings",
    [
        "{months: 0}",
        "{months: 13}",
        "{months: true}",
        "{months: 1.5}",
        "{placement: footer}",
        "{enabled: yesplease}",
        "{as_of: '2026-02-30'}",
    ],
)
def test_invalid_graph_config_is_rejected(tmp_path: Path, settings: str) -> None:
    """
    Validate month bounds, placement, dates, and booleans before any network request.

    Args:
        tmp_path (Path): Temporary config root.
        settings (str): Invalid contribution settings.

    Returns:
        None: Invalid configuration fails strict schema validation.
    """
    path = tmp_path / "resumeme.config.yaml"
    path.write_text(f"linkedin: {{username: example}}\ngithub:\n  username: example\n  contributions: {settings}\n")

    with pytest.raises(ValidationError):
        load_config(path)


def test_graph_defaults_and_missing_username(tmp_path: Path) -> None:
    """
    Keep the feature optional and require explicit GitHub ownership when enabled.

    Args:
        tmp_path (Path): Temporary configuration root.

    Returns:
        None: Username-only LinkedIn configuration stays compatible and enabled graphs cannot infer an owner.
    """
    path = tmp_path / "resumeme.config.yaml"
    path.write_text("linkedin: {username: example}\n")
    assert load_config(path).github.contributions == GitHubContributions()
    path.write_text("linkedin: {username: example}\ngithub: {contributions: {enabled: true}}\n")

    with pytest.raises(ValueError, match="github.username"):
        load_config(path)
