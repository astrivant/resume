"""
Exercise real Firefox and Chrome capture against a deterministic LinkedIn-shaped page.
"""

from __future__ import annotations

import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import pytest
from attrs import evolve

from resumeme.compiler.asts.profile import load_profile, save_profile
from resumeme.config import Capture, Config, LinkedIn
from resumeme.linkedin.browser import _navigate, capture_profile
from resumeme.tests.paths import TEST_FIXTURES

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import Literal

    from pytest import MonkeyPatch
    from selenium.webdriver.remote.webdriver import WebDriver

_FIXTURE = TEST_FIXTURES / "browser-e2e-profile.html"
_USERNAME = "e2e-fixture"


class _FixtureHandler(BaseHTTPRequestHandler):
    """
    Serve one local profile document for every navigation in the browser capture.
    """

    def do_GET(self) -> None:
        """
        Return the fixed profile fixture without making a network request outside the runner.

        Returns:
            None: The fixture page and content type are written to the local response.
        """
        body = _FIXTURE.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        """
        Keep routine HTTP server access logs out of the test output.

        Args:
            format (str): Standard-library access log format, intentionally unused.
            *args (object): Standard-library access log values, intentionally unused.

        Returns:
            None: The local fixture server does not emit access logs.
        """


@pytest.fixture
def profile_server() -> Iterator[str]:
    """
    Start a loopback-only HTTP server for the real browser session.

    Yields:
        str: Local origin serving the LinkedIn-shaped fixture.
    """
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        # Close the listener and join the worker so parallel pytest shards do not leak local services.
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.browser_e2e
def test_real_browser_capture_is_validated_and_exported(tmp_path: Path, monkeypatch: MonkeyPatch, profile_server: str) -> None:
    """
    Capture the same dynamic profile through the selected real browser and validate the serialized payload.

    Args:
        tmp_path (Path): Isolated browser state and fallback output directory.
        monkeypatch (MonkeyPatch): Redirects only LinkedIn routes and disables external media downloads.
        profile_server (str): Loopback fixture origin.

    Returns:
        None: Selenium expands the fixture, the profile schema accepts it, and validated data is written for parity checks.
    """
    browser_setting = os.environ.get("RESUMEME_E2E_BROWSER", "firefox").casefold()

    if browser_setting == "firefox":
        browser: Literal["firefox", "chrome"] = "firefox"
    elif browser_setting == "chrome":
        browser = "chrome"
    else:
        pytest.fail("RESUMEME_E2E_BROWSER must be either 'firefox' or 'chrome'.")

    # Keep LinkedIn login and its remote network outside the test while exercising the production browser lifecycle and capture path.
    monkeypatch.setenv("LINKEDIN_USERNAME", "browser-e2e@example.invalid")
    monkeypatch.setenv("LINKEDIN_PASSWORD", "fixture-only-password")
    monkeypatch.setattr("resumeme.linkedin.browser._login", lambda driver, settings, *, headless: None)
    monkeypatch.setattr("resumeme.linkedin.browser.cache_media", lambda profile, config, root: profile)
    navigate = _navigate
    visited: list[str] = []

    def fixture_navigation(driver: WebDriver, url: str, settings: Capture) -> None:
        """
        Preserve requested LinkedIn paths while routing navigation to the loopback fixture.

        Args:
            driver (WebDriver): Live Selenium driver supplied by the capture module.
            url (str): Production LinkedIn route requested by capture.
            settings (Capture): Configured page and retry bounds.

        Returns:
            None: The browser loads the local fixture at the requested route path.
        """
        path = urlsplit(url).path
        visited.append(path)
        navigate(driver, f"{profile_server}{path}", settings)

    monkeypatch.setattr("resumeme.linkedin.browser._navigate", fixture_navigation)
    monkeypatch.setenv("RESUMEME_BROWSER_STATE_DIR", str(tmp_path / "browser-state"))
    settings = Capture(browser=browser, page_timeout_seconds=10, max_scrolls=12, retry_attempts=2, retry_backoff_seconds=0)
    config = Config(LinkedIn(_USERNAME), capture=settings)

    # Include browser startup and cleanup in the comparison because users experience the complete capture command.
    capture_started = time.perf_counter()
    profile = capture_profile(config, tmp_path, headless=True)
    capture_duration = time.perf_counter() - capture_started
    experience = next(section for section in profile.sections if section.key == "experience")
    job = next(entry for entry in experience.entries if entry.title == "Lead Platform Engineer")
    skills = next(section for section in profile.sections if section.key == "skills")
    output_value = os.environ.get("RESUMEME_E2E_OUTPUT")
    output = Path(output_value) if output_value else tmp_path / "validated-profile.json"
    assert profile.warnings == []
    normalized = evolve(profile, captured_at="")

    # Schema validation on reload checks the same portable payload the release pipeline consumes.
    output.parent.mkdir(parents=True, exist_ok=True)
    save_profile(normalized, output)

    # Keep timing metadata separate so browser speed never affects payload parity.
    timing_value = os.environ.get("RESUMEME_E2E_TIMING_OUTPUT")
    timing_output = Path(timing_value) if timing_value else output.with_suffix(".duration_seconds")
    timing_output.write_text(f"{capture_duration:.6f}\n", encoding="utf-8")

    assert float(timing_output.read_text(encoding="utf-8")) > 0
    assert load_profile(output, _USERNAME) == normalized
    assert visited == ["/login", f"/in/{_USERNAME}/"]
    assert profile.name == "Alex Example"
    assert profile.headline == "Senior Platform Engineer"
    assert [section.key for section in profile.sections] == ["experience", "skills"]
    assert "Builds reliable platforms for product teams." in profile.intro
    assert [(link.label, link.url) for link in profile.links] == [("GitHub", "https://github.com/alex-example")]
    assert profile.images[0].alt == "Alex Example profile photo"
    assert "Reduced deployment time by 60 percent across 40 services." in job.paragraphs
    assert [(link.label, link.url) for link in job.links] == [("Platform source", "https://github.com/acme/platform")]
    assert job.images[0].alt == "Acme Systems logo"
    assert skills.entries[0].skills[0].name == "Python"
    assert skills.entries[0].skills[0].endorsements == 5
