"""
Verify macOS profile lifetime and bounded browser failure behavior without a live login.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from selenium.common.exceptions import NoSuchWindowException, TimeoutException
from selenium.webdriver.common.by import By

from resumeme.cli import main
from resumeme.config import Capture
from resumeme.linkedin.browser import _detail_tabs, _firefox, _login

if TYPE_CHECKING:
    from pytest import MonkeyPatch

    from resumeme.compiler.asts.profile import Profile
    from resumeme.config import Config


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
    monkeypatch.setattr("resumeme.linkedin.browser.sys.platform", "darwin")
    monkeypatch.setattr("resumeme.linkedin.browser._listen_port", lambda: 2829)
    monkeypatch.setattr("resumeme.linkedin.browser._wait_for_browser", lambda port: None)
    browser = MagicMock()
    factory = MagicMock(return_value=browser)
    monkeypatch.setattr("resumeme.linkedin.browser.webbrowser.BackgroundBrowser", factory)
    driver = MagicMock()
    driver.__enter__.return_value = driver
    monkeypatch.setattr("resumeme.linkedin.browser.webdriver.Firefox", MagicMock(return_value=driver))
    monkeypatch.setattr("resumeme.linkedin.browser.Service", MagicMock())

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
    config = tmp_path / "resumeme.config.yaml"
    config.write_text("linkedin:\n  username: example-person\n", encoding="utf-8")

    def capture(config: Config, root: Path, connect_port: int | None = None, *, headless: bool = False) -> Profile:
        """
        Simulate a user closing the only browser window during authentication.

        Args:
            config (Config): Unused capture configuration.
            root (Path): Unused project directory.
            connect_port (int | None): Unused existing-session port.
            headless (bool): Unused unattended capture mode.

        Returns:
            Profile: No profile is produced because the browser window has closed.
        """
        raise NoSuchWindowException("closed")

    monkeypatch.setattr("resumeme.cli.capture_profile", capture)
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


def test_headless_launch_uses_native_firefox_without_opening_a_window(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Keep unattended launch independent from the interactive macOS application launcher.

    Args:
        tmp_path (Path): Temporary browser profile directory.
        monkeypatch (MonkeyPatch): Browser and platform substitutions.

    Returns:
        None: Selenium receives headless options and owns cleanup without opening a desktop window.
    """
    monkeypatch.setattr("resumeme.linkedin.browser.sys.platform", "darwin")
    launcher = MagicMock(side_effect=AssertionError("Headless capture must not open a desktop window"))
    monkeypatch.setattr("resumeme.linkedin.browser.webbrowser.BackgroundBrowser", launcher)
    factory = MagicMock()
    monkeypatch.setattr("resumeme.linkedin.browser.webdriver.Firefox", factory)
    monkeypatch.setattr("resumeme.linkedin.browser.Service", MagicMock())

    with _firefox(tmp_path, None, headless=True):
        options = factory.call_args.kwargs["options"]
        assert "-headless" in options.arguments
        assert "-profile" in options.arguments

    launcher.assert_not_called()


@pytest.mark.parametrize("challenge", [False, True])
def test_headless_login_submits_once_and_requires_observed_success(monkeypatch: MonkeyPatch, challenge: bool) -> None:
    """
    Observe login completion without repeated password submissions or unlimited waits in CI.

    Args:
        monkeypatch (MonkeyPatch): Synthetic credentials and deterministic Selenium wait.
        challenge (bool): Whether authentication requires interactive intervention.

    Returns:
        None: Successful login continues, challenges fail, and credentials are submitted only once.
    """
    monkeypatch.setenv("LINKEDIN_USERNAME", "example@example.org")
    monkeypatch.setenv("LINKEDIN_PASSWORD", "synthetic-secret")
    driver = MagicMock()
    driver.current_url = "https://www.linkedin.com/login"
    driver.get_cookie.return_value = None
    username = MagicMock()
    wait = MagicMock()
    wait.until.side_effect = [username, TimeoutException() if challenge else True]
    monkeypatch.setattr("resumeme.linkedin.browser.WebDriverWait", MagicMock(return_value=wait))
    interactive = MagicMock(side_effect=AssertionError("Headless login cannot enter the interactive wait"))
    monkeypatch.setattr("resumeme.linkedin.browser._wait_for_login", interactive)

    if challenge:
        with pytest.raises(ValueError, match="Unattended LinkedIn login") as error:
            _login(driver, Capture(), headless=True)

        assert "synthetic-secret" not in str(error.value)
    else:
        _login(driver, Capture(), headless=True)

    username.send_keys.assert_called_once_with("example@example.org")
    driver.find_element.return_value.send_keys.assert_called_once_with("synthetic-secret")
    driver.find_element.return_value.click.assert_called_once()
    driver.find_element.assert_any_call(By.CSS_SELECTOR, 'button[type="submit"]')
    interactive.assert_not_called()


@pytest.mark.parametrize("username,password", [("", ""), ("example@example.org", ""), ("", "synthetic-secret")])
def test_headless_missing_credentials_leave_snapshot_untouched(
    tmp_path: Path, monkeypatch: MonkeyPatch, username: str, password: str
) -> None:
    """
    Reject missing or partial secrets before starting a browser or replacing accepted inputs.

    Args:
        tmp_path (Path): Configuration and existing snapshot root.
        monkeypatch (MonkeyPatch): Scoped environment and browser substitutions.
        username (str): Login account, possibly absent.
        password (str): Password, possibly absent.

    Returns:
        None: The CLI fails visibly and the previous snapshot is unchanged.
    """
    monkeypatch.setenv("LINKEDIN_USERNAME", username)
    monkeypatch.setenv("LINKEDIN_PASSWORD", password)
    browser = MagicMock(side_effect=AssertionError("Missing secrets must fail before browser launch"))
    monkeypatch.setattr("resumeme.linkedin.browser._firefox", browser)
    config = tmp_path / "resumeme.config.yaml"
    config.write_text("linkedin:\n  username: example-person\n")
    snapshot = tmp_path / "data/profile.json"
    snapshot.parent.mkdir()
    snapshot.write_text("previous accepted snapshot")
    assert main(["--config", str(config), "capture", "--headless"]) == 2
    assert snapshot.read_text() == "previous accepted snapshot"
    browser.assert_not_called()


def test_login_never_sends_credentials_to_a_redirected_origin(monkeypatch: MonkeyPatch) -> None:
    """
    Refuse credential submission if the browser leaves LinkedIn before rendering the login form.

    Args:
        monkeypatch (MonkeyPatch): Synthetic login credentials.

    Returns:
        None: An unrelated form never receives account secrets.
    """
    monkeypatch.setenv("LINKEDIN_USERNAME", "example@example.org")
    monkeypatch.setenv("LINKEDIN_PASSWORD", "synthetic-secret")
    driver = MagicMock()
    driver.current_url = "https://unrelated.example/login"

    with pytest.raises(ValueError, match="unexpected origin"):
        _login(driver, Capture(), headless=True)

    driver.find_element.assert_not_called()
