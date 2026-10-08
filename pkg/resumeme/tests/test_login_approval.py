"""
Verify bounded mobile-app approval and immediate MFA failures without browser sessions or real-time waits.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from bs4 import BeautifulSoup
from jsonschema import ValidationError

from resumeme.config import Capture, load_config
from resumeme.exceptions import BrowserError
from resumeme.linkedin.browser import _headless_login_ready, _login
from resumeme.linkedin.challenges import login_challenge

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import CaptureFixture, MonkeyPatch


def _driver(html: str) -> MagicMock:
    """
    Model visible challenge controls using actual CSS selection over a synthetic page.

    Args:
        html (str): Challenge page markup without account information.

    Returns:
        MagicMock: Unauthenticated browser on a private checkpoint URL that must never appear in output.
    """
    soup = BeautifulSoup(html, "html.parser")
    driver = MagicMock()
    driver.current_url = "https://www.linkedin.com/checkpoint/challenge/private-token?token=private-query"
    driver.get_cookie.return_value = None
    driver.find_element.return_value.text = soup.get_text(" ", strip=True)

    def controls(kind: str, selector: str) -> list[MagicMock]:
        """
        Match Selenium selectors and model control visibility.

        Args:
            kind (str): Selenium selector mechanism.
            selector (str): CSS selector supplied by the classifier.

        Returns:
            list[MagicMock]: Controls with visibility matching the synthetic markup.
        """
        return [MagicMock(is_displayed=MagicMock(return_value=not element.has_attr("hidden"))) for element in soup.select(selector)]

    driver.find_elements.side_effect = controls
    return driver


def _clock(monkeypatch: MonkeyPatch) -> tuple[list[float], list[float]]:
    """
    Replace Selenium's monotonic clock and sleep with deterministic elapsed-time accounting.

    Args:
        monkeypatch (MonkeyPatch): Scope clock replacements to the current test.

    Returns:
        tuple[list[float], list[float]]: Mutable current time and recorded sleep durations.
    """
    now, delays = [0.0], []

    def sleep(seconds: float) -> None:
        """
        Advance virtual time without delaying the test.

        Args:
            seconds (float): Requested poll interval.

        Returns:
            None: Elapsed time and observed delays are updated.
        """
        now[0] += seconds
        delays.append(seconds)

    monkeypatch.setattr("selenium.webdriver.support.wait.time.monotonic", lambda: now[0])
    monkeypatch.setattr("selenium.webdriver.support.wait.time.sleep", sleep)
    return now, delays


@pytest.mark.parametrize(
    "html,expected",
    [
        ("<h1>Check your LinkedIn app</h1><a>Verify using SMS</a>", "approval"),
        ("<p>Open the LinkedIn mobile app and tap Yes, it\u2019s me.</p>", "approval"),
        ("<p>We sent a notification to your signed-in device.</p>", "approval"),
        ('<h1>Check your LinkedIn app</h1><input autocomplete="one-time-code">', "mfa"),
        ('<h1>Check your LinkedIn app</h1><input autocomplete="one-time-code" hidden>', "approval"),
        ('<input id="input__phone_verification_pin">', "mfa"),
        ('<input name="pin">', "mfa"),
        ("<p>Enter the code from your authenticator app.</p>", "mfa"),
        ("<p>Enter the 6-digit security code.</p>", "mfa"),
        ('<iframe src="https://www.google.com/recaptcha/api2/anchor"></iframe>', "captcha"),
        ("<p>Verify you're human</p>", "captcha"),
        ("<p>Sign-in request was denied</p><p>Check your LinkedIn app</p>", "denied"),
        ("<p>Your request has expired</p><p>Check your LinkedIn app</p>", "expired"),
        ("<h1>Security verification</h1>", "unknown"),
    ],
)
def test_challenge_classification_uses_visible_evidence(html: str, expected: str) -> None:
    """
    Distinguish app approval from visible code controls, unsupported challenges, and unknown pages.

    Args:
        html (str): Synthetic challenge markup.
        expected (str): Required classification.

    Returns:
        None: The classifier selects the expected prompt without acting on any controls.
    """
    driver = _driver(html)
    assert login_challenge(driver) == expected
    driver.get.assert_not_called()


@pytest.mark.parametrize("phase", ["form", "entry", "submitted"])
def test_login_resumes_after_app_approval(monkeypatch: MonkeyPatch, capsys: CaptureFixture[str], phase: str) -> None:
    """
    Extend only app approval beyond page timeouts and continue the original session without resubmission.

    Args:
        monkeypatch (MonkeyPatch): Supplies credentials and a deterministic approval clock.
        capsys (CaptureFixture[str]): Captures the user action prompt, which must appear at default verbosity.
        phase (str): Login boundary at which the app approval prompt appears.

    Returns:
        None: Authentication resumes after approval with at most one credential submission.
    """
    now, delays = _clock(monkeypatch)
    monkeypatch.setenv("LINKEDIN_USERNAME", "example@example.org")
    monkeypatch.setenv("LINKEDIN_PASSWORD", "synthetic-password")
    driver = _driver("<h1>Check your LinkedIn app</h1>")
    driver.current_url = "https://www.linkedin.com/login"
    username, password, submit = MagicMock(), MagicMock(), MagicMock()
    monkeypatch.setattr("resumeme.linkedin.browser._wait_for_login", MagicMock(side_effect=AssertionError("Interactive wait")))

    def observe(page: MagicMock) -> bool:
        """
        Model approval in the existing session after ten seconds of virtual waiting.

        Args:
            page (MagicMock): Browser being observed.

        Returns:
            bool: True after the phone has approved the pending request.
        """
        if now[0] >= 10:
            page.current_url = "https://www.linkedin.com/feed/"
            return True

        return False

    def show_prompt(*args: str) -> None:
        """
        Model LinkedIn redirecting the current form to app approval.

        Args:
            *args (str): Ignored form-entry arguments.

        Returns:
            None: The existing browser moves to the pending approval page.
        """
        driver.current_url = "https://www.linkedin.com/checkpoint/challenge/private-token"

    # Retain the real login form predicates while supplying only their expected form controls.
    original_lookup = driver.find_elements.side_effect
    driver.find_elements.side_effect = lambda kind, selector: (
        [username] if "input#username" in selector else [password] if "input#password" in selector else original_lookup(kind, selector)
    )
    password.find_elements.return_value = [submit]
    monkeypatch.setattr("resumeme.linkedin.browser._authenticated", observe)

    if phase == "form":
        show_prompt()
    elif phase == "entry":
        password.send_keys.side_effect = show_prompt
    else:
        submit.click.side_effect = show_prompt

    _login(driver, Capture(page_timeout_seconds=1), headless=True)
    assert now[0] == 10 and delays == [1] * 10
    assert submit.click.call_count == int(phase == "submitted")
    assert username.send_keys.call_count == int(phase != "form")
    assert password.send_keys.call_count == int(phase != "form")
    output = capsys.readouterr().out
    assert output.count("Yes, it's me") == 1 and "900 seconds" in output
    assert "private-token" not in output
    driver.get.assert_not_called()


@pytest.mark.parametrize("seconds", [0, 30, 900])
def test_approval_wait_has_one_bounded_deadline(monkeypatch: MonkeyPatch, seconds: int) -> None:
    """
    End an unanswered approval after its configured limit without resetting the deadline on repeated prompts.

    Args:
        monkeypatch (MonkeyPatch): Replaces all sleeps and deadline reads.
        seconds (int): Approval limit, including disabled waiting and the full 15-minute default.

    Returns:
        None: The same pending session fails within one polling interval of the limit without navigation or submission.
    """
    now, delays = _clock(monkeypatch)
    driver = _driver("<h1>Check your LinkedIn app</h1>")

    with pytest.raises(BrowserError, match=f"app approval was not completed within {seconds} seconds"):
        _headless_login_ready(driver, Capture(app_approval_timeout_seconds=seconds))

    assert seconds <= now[0] <= seconds + 1
    assert all(delay == 1 for delay in delays)
    driver.get.assert_not_called()


@pytest.mark.parametrize(
    "html,message",
    [
        ('<input autocomplete="one-time-code">', "MFA code entry"),
        ("<p>Verify you're human</p>", "CAPTCHA"),
        ("<p>Sign-in request was denied</p>", "approval was denied"),
        ("<p>Your request has expired</p>", "approval expired"),
    ],
)
@pytest.mark.parametrize("during_wait", [False, True])
def test_unsupported_challenge_fails_on_first_observation(monkeypatch: MonkeyPatch, html: str, message: str, during_wait: bool) -> None:
    """
    Stop without an additional wait when MFA, CAPTCHA, denial, or expiry appears before or during approval.

    Args:
        monkeypatch (MonkeyPatch): Installs a clock and controlled challenge transition.
        html (str): Final challenge markup.
        message (str): Required error category.
        during_wait (bool): Whether LinkedIn first displays a supported app-approval prompt.

    Returns:
        None: The unsupported state raises before any sleep or repeated request.
    """
    now, delays = _clock(monkeypatch)
    driver = _driver(html)

    if during_wait:
        classification = MagicMock(side_effect=["approval", login_challenge(driver)])
        monkeypatch.setattr("resumeme.linkedin.browser.login_challenge", classification)

    with pytest.raises(BrowserError, match=message):
        _headless_login_ready(driver, Capture())

    assert now == [0] and delays == []
    driver.get.assert_not_called()


def test_unknown_checkpoint_does_not_start_approval_wait(monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]) -> None:
    """
    Keep an unrecognized checkpoint within the existing page timeout rather than granting an approval window.

    Args:
        monkeypatch (MonkeyPatch): Records any attempted polling sleeps.
        capsys (CaptureFixture[str]): Captures action notices.

    Returns:
        None: Unknown evidence requests another ordinary page observation without a 15-minute wait.
    """
    _, delays = _clock(monkeypatch)
    assert _headless_login_ready(_driver("<h1>Security verification</h1>"), Capture()) is False
    assert delays == [] and capsys.readouterr().out == ""


@pytest.mark.parametrize("value", [None, 0, 900, -1, 901, True])
def test_approval_timeout_configuration(tmp_path: Path, value: int | bool | None) -> None:
    """
    Default approval to 15 minutes and reject configuration values outside the supported bound.

    Args:
        tmp_path (Path): Config-only workspace.
        value (int | bool | None): Requested timeout, or None to exercise the default.

    Returns:
        None: Valid values survive schema loading and invalid values are rejected.
    """
    path = tmp_path / "resumeme.config.yaml"
    path.write_text(
        "linkedin: {username: example-person}\n" + (f"capture: {{app_approval_timeout_seconds: {value}}}\n" if value is not None else "")
    )

    if value is None or (type(value) is int and 0 <= value <= 900):
        assert load_config(path).capture.app_approval_timeout_seconds == (900 if value is None else value)
    else:
        with pytest.raises(ValidationError):
            load_config(path)
