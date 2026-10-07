"""
Verify macOS profile lifetime and bounded browser failure behavior without a live login.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from selenium.common.exceptions import NoSuchWindowException

from resume.cli import main
from resume.linkedin.browser import _detail_tabs, _firefox

if TYPE_CHECKING:
    from pytest import MonkeyPatch

    from resume.config import Config
    from resume.models import Profile


def test_macos_profile_survives_retries_locally(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Keep Firefox's dedicated profile available for retries after its driver closes.

    Args:
        tmp_path (Path): Temporary project root.
        monkeypatch (MonkeyPatch): Scoped browser and platform replacements.

    Returns:
        None: The private absolute profile stays inside the ignored local cache.
    """

    # Exercise the macOS launch contract on any test host without opening an application or needing a LinkedIn login.
    monkeypatch.setattr("resume.linkedin.browser.sys.platform", "darwin")
    monkeypatch.setattr("resume.linkedin.browser._listen_port", lambda: 2829)
    monkeypatch.setattr("resume.linkedin.browser._wait_for_browser", lambda port: None)
    browser = MagicMock()
    factory = MagicMock(return_value=browser)
    monkeypatch.setattr("resume.linkedin.browser.webbrowser.BackgroundBrowser", factory)
    driver = MagicMock()
    driver.__enter__.return_value = driver
    monkeypatch.setattr("resume.linkedin.browser.webdriver.Firefox", MagicMock(return_value=driver))
    monkeypatch.setattr("resume.linkedin.browser.Service", MagicMock())

    with _firefox(tmp_path, None) as captured:
        assert captured is driver
        arguments = factory.call_args.args[0]
        profile = Path(arguments[arguments.index("-profile") + 1])
        assert profile.is_absolute()
        assert profile.is_dir()
        assert 'user_pref("marionette.port", 2829)' in (profile / "user.js").read_text(encoding="utf-8")
        browser.open.assert_called_once_with("https://www.linkedin.com/login")

    # The driver session ends, but the persistent profile and its private permissions must survive for the next attempt.
    assert profile == tmp_path / ".cache/firefox"
    assert profile.is_dir()
    assert profile.stat().st_mode & 0o777 == 0o700
    driver.__exit__.assert_called_once()


def test_closed_window_is_an_actionable_cli_failure(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Return a clean failure if the interactive browser window is closed during login.

    Args:
        tmp_path (Path): Temporary project root.
        monkeypatch (MonkeyPatch): Scoped capture replacement.

    Returns:
        None: The command reports failure and never saves a snapshot.
    """
    config = tmp_path / "resume.config.yaml"
    config.write_text("linkedin:\n  username: example-person\n", encoding="utf-8")

    def capture(config: Config, root: Path, connect_port: int | None = None) -> Profile:
        """
        Simulate a user closing the only browser window during authentication.

        Args:
            config (Config): Unused capture configuration.
            root (Path): Unused project directory.
            connect_port (int | None): Unused existing-session port.

        Returns:
            Profile: No profile is produced because the browser window has closed.
        """
        raise NoSuchWindowException("closed")

    monkeypatch.setattr("resume.cli.capture_profile", capture)
    assert main(["--config", str(config), "capture"]) == 2
    assert not (tmp_path / "data/profile.json").exists()


def test_detail_tabs_exclude_unrelated_forms() -> None:
    """
    Limit tab switching to visible controls in the profile's primary content.

    Returns:
        None: Hidden controls and unrelated sidebar forms cannot be clicked as tabs.
    """
    browser = MagicMock()
    primary = MagicMock()
    browser.find_elements.return_value = [primary]
    received, given, hidden = MagicMock(), MagicMock(), MagicMock()
    received.text, given.text, hidden.text = "Received", "Given", "Hidden form"
    received.is_displayed.return_value = given.is_displayed.return_value = True
    hidden.is_displayed.return_value = False
    primary.find_elements.return_value = [received, given, hidden]
    assert _detail_tabs(browser) == {"Received": received, "Given": given}
    browser.find_element.assert_not_called()
