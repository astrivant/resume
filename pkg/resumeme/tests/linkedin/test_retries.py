"""
Verify exponential retry timing and indefinite login monitoring without real sleeps.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, PropertyMock

import pytest
import requests
from selenium.common.exceptions import InvalidSessionIdException, NoSuchWindowException, TimeoutException, WebDriverException
from urllib3.response import HTTPResponse

from resumeme.config import Capture
from resumeme.exceptions import BrowserError, BrowserTimeoutError, ResumeUploadConfirmationError
from resumeme.linkedin.browser import _wait_for_login
from resumeme.linkedin.media import _ExponentialRetry
from resumeme.linkedin.retrying import is_retryable_linkedin_error, retry, retry_selenium

if TYPE_CHECKING:
    from pytest import MonkeyPatch


def test_exponential_backoff_caps_and_stops(monkeypatch: MonkeyPatch) -> None:
    """
    Double retry delays up to the configured cap and stop after the total attempt limit.

    Args:
        monkeypatch (MonkeyPatch): Replaces sleeping with a deterministic recorder.

    Returns:
        None: Attempts and delay sequence match the bounded exponential contract.
    """

    # Record requested waits instead of sleeping so exact backoff behavior is deterministic and fast to verify.
    delays: list[float] = []
    monkeypatch.setattr("resumeme.linkedin.retrying.time.sleep", delays.append)
    operation = MagicMock(side_effect=TimeoutError("transient"))

    with pytest.raises(TimeoutError):
        retry(operation, attempts=8, backoff=10, max_backoff=300, exceptions=(TimeoutError,))

    assert operation.call_count == 8
    assert delays == [10, 20, 40, 80, 160, 300, 300]


def test_permanent_errors_are_not_retried(monkeypatch: MonkeyPatch) -> None:
    """
    Propagate invalid input without sleeping or replaying the operation.

    Args:
        monkeypatch (MonkeyPatch): Scoped sleep replacement.

    Returns:
        None: A permanent failure stops after one attempt.
    """
    sleep = MagicMock()
    monkeypatch.setattr("resumeme.linkedin.retrying.time.sleep", sleep)
    operation = MagicMock(side_effect=ValueError("invalid profile"))

    with pytest.raises(ValueError):
        retry(operation, attempts=5, backoff=10, exceptions=(TimeoutError,))

    operation.assert_called_once()
    sleep.assert_not_called()


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (requests.ConnectionError("connection reset"), True),
        (requests.ReadTimeout("request timed out"), True),
        (requests.exceptions.RetryError("transient statuses exhausted"), True),
        (requests.exceptions.SSLError("invalid certificate"), False),
        (requests.exceptions.InvalidURL("bad URL"), False),
        (InvalidSessionIdException("session gone"), True),
        (NoSuchWindowException("window closed"), True),
        (BrowserTimeoutError("profile page did not load"), True),
        (ResumeUploadConfirmationError("upload outcome is uncertain"), False),
        (TimeoutException("transient browser wait"), True),
        (BrowserError("LinkedIn requires MFA"), False),
        (ValueError("bad configuration"), False),
    ],
)
def test_linkedin_retry_classifier_distinguishes_transient_and_permanent_errors(error: Exception, expected: bool) -> None:
    """
    Retry network and browser instability without repeating authentication challenges or invalid configuration.

    Args:
        error (Exception): Failure raised by one LinkedIn command attempt.
        expected (bool): Expected whole-command retry decision.

    Returns:
        None: The classifier distinguishes retryable transport failures from permanent account or input failures.
    """
    assert is_retryable_linkedin_error(error) is expected


@pytest.mark.parametrize(("status", "expected"), [(408, True), (429, True), (500, True), (503, True), (403, False), (404, False)])
def test_linkedin_http_retry_classifier_uses_response_status(status: int, expected: bool) -> None:
    """
    Retry server throttling and transient server errors, but stop on authorization or missing-resource responses.

    Args:
        status (int): HTTP status returned by the LinkedIn request.
        expected (bool): Expected whole-command retry decision.

    Returns:
        None: Only rate limits and transient server statuses are classified for retry.
    """
    response = requests.Response()
    response.status_code = status
    assert is_retryable_linkedin_error(requests.HTTPError(response=response)) is expected


def test_retry_predicate_stops_matched_nontransient_errors(monkeypatch: MonkeyPatch) -> None:
    """
    Preserve the matched exception when a retry filter classifies it as permanent.

    Args:
        monkeypatch (MonkeyPatch): Scoped sleep replacement.

    Returns:
        None: A filtered failure receives one attempt and no backoff.
    """
    sleep = MagicMock()
    monkeypatch.setattr("resumeme.linkedin.retrying.time.sleep", sleep)
    operation = MagicMock(side_effect=TimeoutError("operation is not safe to repeat"))

    with pytest.raises(TimeoutError, match="not safe"):
        retry(operation, attempts=5, backoff=10, exceptions=(TimeoutError,), should_retry=lambda _: False)

    operation.assert_called_once()
    sleep.assert_not_called()


def test_selenium_retry_recovers_transient_remote_errors(monkeypatch: MonkeyPatch) -> None:
    """
    Retry a read-only browser call after a recoverable WebDriver transport error.

    Args:
        monkeypatch (MonkeyPatch): Replaces delays with an immediate recorder.

    Returns:
        None: The successful read is returned after one configured retry.
    """
    delays: list[float] = []
    monkeypatch.setattr("resumeme.linkedin.retrying.time.sleep", delays.append)
    settings = Capture(retry_attempts=3, retry_backoff_seconds=2, retry_max_backoff_seconds=5)
    operation = MagicMock(side_effect=[WebDriverException("disconnected from remote end"), "ready"])

    assert retry_selenium(operation, settings) == "ready"
    assert operation.call_count == 2
    assert delays == [2]


def test_selenium_retry_does_not_replay_a_dead_session(monkeypatch: MonkeyPatch) -> None:
    """
    Fail immediately when Selenium reports that its session no longer exists.

    Args:
        monkeypatch (MonkeyPatch): Verifies there is no retry delay.

    Returns:
        None: Invalid sessions are not replayed as transient page failures.
    """
    sleep = MagicMock()
    monkeypatch.setattr("resumeme.linkedin.retrying.time.sleep", sleep)
    operation = MagicMock(side_effect=InvalidSessionIdException("session is gone"))

    with pytest.raises(InvalidSessionIdException):
        retry_selenium(operation, Capture(retry_attempts=4, retry_backoff_seconds=1))

    operation.assert_called_once()
    sleep.assert_not_called()


def test_http_backoff_has_initial_delay_and_respects_retry_after(monkeypatch: MonkeyPatch) -> None:
    """
    Apply the initial wait to HTTP retries and cap server-provided Retry-After delays.

    Args:
        monkeypatch (MonkeyPatch): Scoped sleep replacement.

    Returns:
        None: HTTP delays follow the same policy as browser retries.
    """
    delays: list[float] = []
    monkeypatch.setattr("resumeme.linkedin.media.time.sleep", delays.append)
    policy = _ExponentialRetry(total=5, backoff_factor=10, backoff_max=300, retry_after_max=300)
    response = HTTPResponse(status=503)
    policy = policy.increment(method="GET", response=response)
    policy.sleep(response)
    policy = policy.increment(method="GET", response=response)
    policy.sleep(response)
    policy.sleep(HTTPResponse(status=429, headers={"Retry-After": "600"}))
    assert delays == [10, 20, 300]


def test_login_waits_for_browser_state_without_a_deadline(monkeypatch: MonkeyPatch) -> None:
    """
    Continue monitoring until the authenticated cookie appears, independent of elapsed time.

    Args:
        monkeypatch (MonkeyPatch): Replaces waiting with deterministic observations.

    Returns:
        None: Login completes on the observed browser state after any number of polls.
    """
    waits: list[float] = []
    monkeypatch.setattr("resumeme.linkedin.browser_auth.time.sleep", waits.append)
    browser = MagicMock()
    browser.window_handles = ["login"]
    browser.current_url = "https://www.linkedin.com/feed/"

    # A long sequence of unauthenticated observations must still complete once browser state indicates successful login.
    browser.get_cookie.side_effect = [None] * 1000 + [{"name": "li_at", "value": "fixture"}]
    _wait_for_login(browser)
    assert len(waits) == 1000
    assert browser.get_cookie.call_count == 1001


def test_login_waits_through_challenges_and_checks_other_tabs(monkeypatch: MonkeyPatch) -> None:
    """
    Ignore unrelated tabs and unfinished challenges even if an old cookie remains.

    Args:
        monkeypatch (MonkeyPatch): Replaces the polling delay with a recorder.

    Returns:
        None: Only the authenticated LinkedIn tab completes the wait.
    """
    sleep = MagicMock()
    monkeypatch.setattr("resumeme.linkedin.browser_auth.time.sleep", sleep)
    browser = MagicMock()
    browser.window_handles = ["first", "second"]
    type(browser).current_url = PropertyMock(
        side_effect=[
            "https://linkedin.com.example.org/feed/",
            "https://www.linkedin.com/checkpoint/challenge/",
            "https://www.linkedin.com/login",
            "https://www.linkedin.com/feed/",
        ]
    )
    browser.get_cookie.return_value = {"name": "li_at", "value": "fixture"}
    _wait_for_login(browser)
    sleep.assert_called_once_with(1)
    browser.get_cookie.assert_called_once_with("li_at")


def test_login_wait_is_interruptible(monkeypatch: MonkeyPatch) -> None:
    """
    Allow Ctrl-C to cancel an indefinite wait without leaving a watcher behind.

    Args:
        monkeypatch (MonkeyPatch): Injects cancellation at the polling boundary.

    Returns:
        None: Cancellation propagates immediately to the command's cleanup handler.
    """
    monkeypatch.setattr("resumeme.linkedin.browser_auth.time.sleep", MagicMock(side_effect=KeyboardInterrupt))
    browser = MagicMock()
    browser.window_handles = ["login"]
    browser.current_url = "https://www.linkedin.com/login"

    with pytest.raises(KeyboardInterrupt):
        _wait_for_login(browser)


def test_closing_login_window_cancels_waiting() -> None:
    """
    Stop immediately when the user closes the capture browser.

    Returns:
        None: No background login watcher remains after window closure.
    """
    browser = MagicMock()
    browser.window_handles = []

    with pytest.raises(NoSuchWindowException):
        _wait_for_login(browser)
