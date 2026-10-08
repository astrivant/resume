"""
Exercise sign-in timeouts at the form and submission boundaries without live accounts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException, TimeoutException
from selenium.webdriver.common.by import By

from resumeme.config import Capture
from resumeme.linkedin.browser import _login, _login_form

if TYPE_CHECKING:
    from pytest import CaptureFixture, MonkeyPatch


def _browser(monkeypatch: MonkeyPatch) -> tuple[MagicMock, MagicMock, MagicMock, MagicMock]:
    """
    Model a complete login form whose single submission establishes a session.

    Args:
        monkeypatch (MonkeyPatch): Installs synthetic environment credentials.

    Returns:
        tuple[MagicMock, MagicMock, MagicMock, MagicMock]: Driver, username, password, and submit controls.
    """
    monkeypatch.setenv("LINKEDIN_USERNAME", "test@example.org")
    monkeypatch.setenv("LINKEDIN_PASSWORD", "synthetic-password")
    driver, username, password, submit = (MagicMock() for _ in range(4))
    driver.current_url = "https://www.linkedin.com/login?token=private-token#private-fragment"
    driver.get_cookie.return_value = None
    controls = {
        (By.CSS_SELECTOR, 'input#username, input[autocomplete="username"]'): [username],
        (By.CSS_SELECTOR, 'input#password, input[autocomplete="current-password"]'): [password],
    }
    driver.find_elements.side_effect = lambda kind, selector: controls[kind, selector]
    password.find_elements.return_value = [submit]

    def authenticate() -> None:
        """
        Complete authentication as the observable effect of submitting the form.

        Returns:
            None: The fake browser has left login and acquired its session cookie.
        """
        driver.current_url = "https://www.linkedin.com/feed/"
        driver.get_cookie.return_value = {"name": "li_at", "value": "synthetic-cookie"}

    submit.click.side_effect = authenticate
    return driver, username, password, submit


@pytest.mark.parametrize("headless", [False, True])
def test_submit_timeout_observes_success_without_repeating_credentials(monkeypatch: MonkeyPatch, headless: bool) -> None:
    """
    Recover a successful sign-in whose click timed out waiting for the next page.

    Args:
        monkeypatch (MonkeyPatch): Isolates credentials and the fake browser's response.
        headless (bool): Whether sign-in runs unattended or in a local window.

    Returns:
        None: Authentication is observed after the timeout and submission happens only once.
    """
    driver, username, password, submit = _browser(monkeypatch)
    driver.window_handles = ["login"]

    def submit_then_timeout() -> None:
        """
        Model a committed login followed by an incomplete page load.

        Returns:
            None: The browser authenticates before reporting the navigation timeout.
        """
        driver.current_url = "https://www.linkedin.com/feed/"
        driver.get_cookie.return_value = {"name": "li_at", "value": "synthetic-cookie"}
        raise TimeoutException("Navigation has not finished")

    submit.click.side_effect = submit_then_timeout
    _login(driver, Capture(page_timeout_seconds=0), headless=headless)
    username.send_keys.assert_called_once_with("test@example.org")
    password.send_keys.assert_called_once_with("synthetic-password")
    submit.click.assert_called_once()


def test_submit_timeout_without_authentication_still_fails(monkeypatch: MonkeyPatch) -> None:
    """
    Require an observed session before treating an uncertain submission as successful.

    Args:
        monkeypatch (MonkeyPatch): Supplies an unanswered sign-in submission.

    Returns:
        None: The headless attempt fails clearly without resubmitting the password.
    """
    driver, username, password, submit = _browser(monkeypatch)
    submit.click.side_effect = TimeoutException()

    with pytest.raises(ValueError, match=r"Unattended LinkedIn login did not complete.*page state: login"):
        _login(driver, Capture(page_timeout_seconds=0), headless=True)

    username.send_keys.assert_called_once_with("test@example.org")
    password.send_keys.assert_called_once_with("synthetic-password")
    submit.click.assert_called_once()


@pytest.mark.parametrize("failure", [NoSuchElementException, StaleElementReferenceException])
def test_login_form_retries_with_configured_exponential_backoff(monkeypatch: MonkeyPatch, failure: type[Exception]) -> None:
    """
    Recover delayed or rerendered form controls before submitting credentials.

    Args:
        monkeypatch (MonkeyPatch): Replaces sleeping with a deterministic delay recorder.
        failure (type[Exception]): Transient control lookup failure.

    Returns:
        None: Form observations use capped exponential delays and credentials are submitted once.
    """
    driver, username, password, submit = _browser(monkeypatch)
    lookup: dict[tuple[str, str], list[MagicMock]] = {
        (By.CSS_SELECTOR, 'input#username, input[autocomplete="username"]'): [username],
        (By.CSS_SELECTOR, 'input#password, input[autocomplete="current-password"]'): [password],
    }
    attempts = 0

    def delayed_controls(kind: str, selector: str) -> list[MagicMock]:
        """
        Fail the first two observations, then retain the form through credential entry and submission.

        Args:
            kind (str): Selenium selector mechanism.
            selector (str): Requested form control selector.

        Returns:
            list[MagicMock]: Form controls after transient lookup failures.
        """
        nonlocal attempts
        attempts += 1

        if attempts <= 2:
            raise failure()

        return lookup[kind, selector]

    driver.find_elements.side_effect = delayed_controls
    delays: list[float] = []
    monkeypatch.setattr("resumeme.linkedin.retrying.time.sleep", delays.append)
    settings = Capture(page_timeout_seconds=0, retry_attempts=3, retry_backoff_seconds=2, retry_max_backoff_seconds=3)
    _login(driver, settings, headless=True)
    assert delays == [2, 3]
    username.send_keys.assert_called_once_with("test@example.org")
    password.send_keys.assert_called_once_with("synthetic-password")
    submit.click.assert_called_once()


@pytest.mark.parametrize("raises", [False, True])
def test_missing_login_form_reports_stage_without_leaking_page_data(
    monkeypatch: MonkeyPatch, capsys: CaptureFixture[str], raises: bool
) -> None:
    """
    Bound a permanently missing form and report the failed phase without private browser data.

    Args:
        monkeypatch (MonkeyPatch): Installs synthetic credentials and immediate retry delays.
        capsys (CaptureFixture[str]): Captures progress and retry diagnostics.
        raises (bool): Whether Selenium raises during lookup instead of returning no matching controls.

    Returns:
        None: Retries exhaust without typing, submitting, or printing secrets and URL tokens.
    """
    driver, username, password, submit = _browser(monkeypatch)
    driver.find_elements.side_effect = NoSuchElementException("private-page-data") if raises else None
    driver.find_elements.return_value = []
    settings = Capture(page_timeout_seconds=0, retry_attempts=2, retry_backoff_seconds=0)

    with pytest.raises(ValueError, match=r"login form did not become ready after 2 attempts.*page state: login") as error:
        _login(driver, settings, headless=True)

    assert driver.find_elements.call_count == (2 if raises else 4)
    username.send_keys.assert_not_called()
    password.send_keys.assert_not_called()
    submit.click.assert_not_called()
    captured = capsys.readouterr()
    diagnostics = str(error.value) + captured.out + captured.err

    for private in ("test@example.org", "synthetic-password", "private-token", "private-fragment", "private-page-data"):
        assert private not in diagnostics


def test_redirect_during_form_retry_rejects_untrusted_origin(monkeypatch: MonkeyPatch) -> None:
    """
    Recheck credential destination when a redirect completes between observations.

    Args:
        monkeypatch (MonkeyPatch): Models the redirect during the retry delay.

    Returns:
        None: A form on the new origin is never read or submitted.
    """
    driver, username, password, submit = _browser(monkeypatch)
    driver.find_elements.side_effect = NoSuchElementException()
    monkeypatch.setattr(
        "resumeme.linkedin.retrying.time.sleep", lambda delay: setattr(driver, "current_url", "https://unrelated.example/login")
    )

    with pytest.raises(ValueError, match="unexpected origin"):
        _login(driver, Capture(page_timeout_seconds=0, retry_attempts=2), headless=True)

    driver.find_elements.assert_called_once_with(By.CSS_SELECTOR, 'input#username, input[autocomplete="username"]')
    username.send_keys.assert_not_called()
    password.send_keys.assert_not_called()
    submit.click.assert_not_called()


def test_existing_session_detected_while_waiting_for_form(monkeypatch: MonkeyPatch) -> None:
    """
    Accept a completed login redirect instead of waiting for a form that disappeared.

    Args:
        monkeypatch (MonkeyPatch): Completes authentication during the retry delay.

    Returns:
        None: A retained session avoids all credential submission.
    """
    driver, username, password, submit = _browser(monkeypatch)
    driver.find_elements.side_effect = NoSuchElementException()
    driver.get_cookie.return_value = {"name": "li_at", "value": "synthetic-cookie"}
    monkeypatch.setattr(
        "resumeme.linkedin.retrying.time.sleep", lambda delay: setattr(driver, "current_url", "https://www.linkedin.com/feed/")
    )
    _login(driver, Capture(page_timeout_seconds=0, retry_attempts=2), headless=True)
    username.send_keys.assert_not_called()
    password.send_keys.assert_not_called()
    submit.click.assert_not_called()


@pytest.mark.parametrize(
    "control,state", [(0, "is_displayed"), (0, "is_enabled"), (1, "is_displayed"), (1, "is_enabled"), (2, "is_displayed")]
)
def test_form_wait_requires_all_controls_ready(monkeypatch: MonkeyPatch, control: int, state: str) -> None:
    """
    Reject partially rendered forms before any input or submission.

    Args:
        monkeypatch (MonkeyPatch): Supplies synthetic environment credentials.
        control (int): Username, password, or submit control that is not ready.
        state (str): Visibility or enabled property returning false.

    Returns:
        None: Credential fields must be editable and the submit control must be visible before typing.
    """
    driver, *controls = _browser(monkeypatch)
    unavailable = getattr(controls[control], state)
    unavailable.return_value = False
    assert _login_form(driver) is False
    unavailable.return_value = True
    assert _login_form(driver) == tuple(controls)


@pytest.mark.parametrize("control", [0, 1, 2])
def test_form_ignores_hidden_duplicate_controls(monkeypatch: MonkeyPatch, control: int) -> None:
    """
    Select the visible login component when responsive markup includes a hidden copy first.

    Args:
        monkeypatch (MonkeyPatch): Supplies synthetic environment credentials.
        control (int): Username, password, or submit list containing a hidden first match.

    Returns:
        None: Hidden fields and buttons never receive credentials or clicks.
    """
    driver, username, password, submit = _browser(monkeypatch)
    hidden = MagicMock()
    hidden.is_displayed.return_value = False
    driver.find_elements.side_effect = [
        [hidden, username] if control == 0 else [username],
        [hidden, password] if control == 1 else [password],
    ]
    password.find_elements.return_value = [hidden, submit] if control == 2 else [submit]
    assert _login_form(driver) == (username, password, submit)
    hidden.send_keys.assert_not_called()
    hidden.click.assert_not_called()


@pytest.mark.parametrize("enables", [False, True])
def test_submit_enablement_is_checked_after_typing(monkeypatch: MonkeyPatch, enables: bool) -> None:
    """
    Let controlled forms enable submission after credentials are entered, while refusing a button that stays disabled.

    Args:
        monkeypatch (MonkeyPatch): Supplies credentials and a controlled sign-in form.
        enables (bool): Whether filling the password makes the submit button usable.

    Returns:
        None: Credentials are typed once; only a subsequently enabled button is clicked.
    """
    driver, username, password, submit = _browser(monkeypatch)
    submit.is_enabled.return_value = False
    password.send_keys.side_effect = lambda value: setattr(submit.is_enabled, "return_value", enables)
    settings = Capture(page_timeout_seconds=0)

    if enables:
        _login(driver, settings, headless=True)
        submit.click.assert_called_once()
    else:
        with pytest.raises(ValueError, match="sign-in button did not become ready after filling credentials"):
            _login(driver, settings, headless=True)

        submit.click.assert_not_called()

    username.send_keys.assert_called_once_with("test@example.org")
    password.send_keys.assert_called_once_with("synthetic-password")


def test_submit_reacquires_a_button_replaced_after_typing(monkeypatch: MonkeyPatch) -> None:
    """
    Follow a client-rendered button replacement without clicking the stale pre-entry element.

    Args:
        monkeypatch (MonkeyPatch): Supplies a form whose submit control changes after password entry.

    Returns:
        None: Only the current button is clicked, with no repeated credential entry.
    """
    driver, username, password, submit = _browser(monkeypatch)
    replacement = MagicMock()
    replacement.click.side_effect = submit.click.side_effect
    password.find_elements.side_effect = [[submit], [replacement]]
    _login(driver, Capture(page_timeout_seconds=0), headless=True)
    submit.click.assert_not_called()
    replacement.click.assert_called_once()
    username.send_keys.assert_called_once()
    password.send_keys.assert_called_once()


@pytest.mark.parametrize("authenticated", [False, True])
def test_submit_rechecks_origin_and_session_after_typing(monkeypatch: MonkeyPatch, authenticated: bool) -> None:
    """
    Observe a completed login or reject a redirected form before clicking a reacquired button.

    Args:
        monkeypatch (MonkeyPatch): Supplies a form whose destination changes after password entry.
        authenticated (bool): Whether entry completes authentication instead of redirecting to another origin.

    Returns:
        None: Neither an already completed login nor an unrelated destination receives a submit click.
    """
    driver, username, password, submit = _browser(monkeypatch)

    if authenticated:
        password.send_keys.side_effect = lambda value: submit.click.side_effect()
        _login(driver, Capture(page_timeout_seconds=0), headless=True)
    else:
        password.send_keys.side_effect = lambda value: setattr(driver, "current_url", "https://unrelated.example/login")

        with pytest.raises(ValueError, match="unexpected origin"):
            _login(driver, Capture(page_timeout_seconds=0), headless=True)

    submit.click.assert_not_called()
    username.send_keys.assert_called_once()
    password.send_keys.assert_called_once()


@pytest.mark.parametrize("headless", [False, True])
def test_challenge_before_login_form_stops_retries(monkeypatch: MonkeyPatch, headless: bool) -> None:
    """
    Route missing-form challenges to interactive completion without reloading or submitting.

    Args:
        monkeypatch (MonkeyPatch): Replaces interactive waiting and records retry delays.
        headless (bool): Whether an interactive browser is available for challenge completion.

    Returns:
        None: Headless execution fails clearly; interactive execution retains its indefinite wait.
    """
    driver, username, password, submit = _browser(monkeypatch)
    driver.current_url = "https://www.linkedin.com/checkpoint/challenge/private-token"
    driver.find_elements.side_effect = NoSuchElementException()
    interactive, sleep = MagicMock(), MagicMock()
    monkeypatch.setattr("resumeme.linkedin.browser._wait_for_login", interactive)
    monkeypatch.setattr("resumeme.linkedin.retrying.time.sleep", sleep)

    if headless:
        with pytest.raises(ValueError, match="login form is unavailable.*page state: checkpoint"):
            _login(driver, Capture(page_timeout_seconds=0), headless=headless)

        interactive.assert_not_called()
    else:
        _login(driver, Capture(page_timeout_seconds=0), headless=headless)
        interactive.assert_called_once_with(driver)

    sleep.assert_not_called()
    username.send_keys.assert_not_called()
    password.send_keys.assert_not_called()
    submit.click.assert_not_called()
    driver.get.assert_not_called()
