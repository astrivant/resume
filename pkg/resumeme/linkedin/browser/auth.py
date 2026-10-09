"""
Authenticate a LinkedIn browser session and observe login challenges.
"""

from __future__ import annotations

import logging
import time
from functools import partial
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from selenium.common.exceptions import (
    InvalidSessionIdException,
    NoSuchWindowException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from resumeme.exceptions import BrowserError, BrowserWindowError
from resumeme.linkedin.approval.audit import record_approval_context
from resumeme.linkedin.challenges import observe_challenge
from resumeme.linkedin.credentials import login_credentials
from resumeme.linkedin.retrying import is_retryable_selenium_error, retry_selenium

if TYPE_CHECKING:
    from typing import Literal

    from selenium.webdriver.remote.webdriver import WebDriver
    from selenium.webdriver.remote.webelement import WebElement

    from resumeme.config import Capture
    from resumeme.linkedin.challenges import ChallengeObservation

__all__ = ["_login"]
_LOGGER = logging.getLogger(__name__)
_LOGIN_BLOCKED_STATES = frozenset({"checkpoint", "challenge", "authwall"})
_LOGIN_BLOCKED_MESSAGE = (
    "LinkedIn blocked unattended sign-in (page state: {state}). "
    "LinkedIn requires interactive verification that this headless run cannot complete. "
    "The profile refresh is blocked by LinkedIn, not by missing login environment variables. "
    "Signing in locally does not authenticate the CI runner. No profile changes were submitted."
)


def _authenticated(driver: WebDriver) -> bool:
    """
    Require both a LinkedIn session cookie and a completed authentication redirect.

    Args:
        driver (WebDriver): Browser on the tab being checked.

    Returns:
        bool: The current LinkedIn tab has finished authentication.
    """
    try:
        state = _login_page(driver)
    except BrowserError:
        # Interactive sign-in can visit another tab; only a trusted LinkedIn page can establish completion.
        return False

    authenticating = state in {"loading", "login", "signup", "checkpoint", "challenge", "authwall", "uas"}
    return not authenticating and driver.get_cookie("li_at") is not None


def _login_page(driver: WebDriver) -> str:
    """
    Classify pending navigation and LinkedIn routes, rejecting unsafe destinations with sanitized diagnostics.

    Args:
        driver (WebDriver): Browser being authenticated.

    Returns:
        str: Loading state or allowlisted LinkedIn route category, never a raw URL, cookie, or page body.

    Raises:
        BrowserError: The destination is malformed, outside HTTPS LinkedIn, or a browser-owned error page.
    """
    current_url = driver.current_url

    try:
        location = urlsplit(current_url)
        port = location.port
    except ValueError:
        # URL parsing errors can echo their input, including private checkpoint tokens or embedded credentials.
        raise BrowserError("LinkedIn login reached an invalid browser destination. Automatic sign-in stopped.") from None

    # An empty document is a pending navigation, never a form or evidence of successful authentication.
    if not current_url or (location.scheme == "about" and not location.netloc and location.path == "blank"):
        return "loading"

    browser_error = location.scheme == "about" and location.path in {"neterror", "certerror", "blocked"}

    if browser_error or (location.scheme == "chrome-error" and location.hostname == "chromewebdata"):
        raise BrowserError(
            "LinkedIn login navigation reached a browser error page. "
            "Check the runner's network, DNS, and TLS connectivity to LinkedIn; this is not a credential rejection."
        )

    # Apply the same domain boundary to regional LinkedIn redirects, credential controls, and session cookies.
    host = location.hostname or ""
    trusted_host = host == "linkedin.com" or host.endswith(".linkedin.com")

    if location.scheme != "https" or not trusted_host or port not in {None, 443} or location.username is not None:
        # Log only the origin components; checkpoint paths, userinfo, queries, and fragments can carry private values.
        origin = f"scheme={ascii(location.scheme[:32])}, host={ascii(host[:253])}, port={port if port is not None else 'default'}"
        raise BrowserError(
            f"LinkedIn login redirected to an unexpected origin ({origin}). "
            "Automatic sign-in stopped; no credentials will be sent to this destination."
        )

    route = location.path.casefold().strip("/").split("/", 1)[0]
    return route if route in {"login", "signup", "checkpoint", "challenge", "authwall", "uas", "feed", "in"} else "other LinkedIn page"


def _check_login_challenge(driver: WebDriver) -> ChallengeObservation:
    """
    Reject challenges that cannot be completed by approving the current sign-in from the mobile app.

    Args:
        driver (WebDriver): Browser on a verified LinkedIn challenge route.

    Returns:
        ChallengeObservation: Safe diagnostic evidence when waiting remains possible.

    Raises:
        BrowserError: Code-entry MFA, CAPTCHA, or a denied or expired approval requires ending this unattended attempt.
    """
    observation = observe_challenge(driver)
    challenge = observation.kind

    # Never enter a code, solve a CAPTCHA, or resend an approval request on the user's behalf.
    if challenge in {"mfa", "captcha", "denied", "expired"}:
        reason = {
            "mfa": "LinkedIn requires MFA code entry; unattended sign-in stops immediately.",
            "captcha": "LinkedIn requires a CAPTCHA; unattended sign-in stops immediately.",
            "denied": "LinkedIn sign-in approval was denied; unattended sign-in has stopped.",
            "expired": "LinkedIn sign-in approval expired; unattended sign-in has stopped.",
        }[challenge]
        raise BrowserError(reason + f" Checkpoint diagnostics: {observation.summary()}. No profile changes were submitted.")

    return observation


def _wait_for_app_approval(
    driver: WebDriver,
    settings: Capture,
    observation: ChallengeObservation,
    *,
    profile_username: str | None = None,
) -> bool:
    """
    Observe the existing session for a bounded mobile-app approval without submitting anything further.

    Args:
        driver (WebDriver): Browser displaying an approval prompt or an unrecognized verification checkpoint.
        settings (Capture): Maximum app-approval wait, independent of page loading timeouts.
        observation (ChallengeObservation): Initial classification and allowlisted diagnostic evidence.
        profile_username (str | None): Public configured profile identifier for the audit record.

    Returns:
        bool: True only after the existing browser has an authenticated LinkedIn session.

    Raises:
        BrowserError: Approval times out, is denied or expires, requires MFA or CAPTCHA, or leaves LinkedIn.
    """
    timeout = settings.app_approval_timeout_seconds
    last = observation

    # This action prompt must remain visible with the default ERROR log level and in buffered CI output.
    prompt = "LinkedIn is waiting for app approval." if observation.kind == "approval" else "LinkedIn displayed an unrecognized checkpoint."
    print(
        f'{prompt} Check your LinkedIn app for "Yes, it\'s me". Waiting up to {timeout} seconds. '
        f"Checkpoint diagnostics: {observation.summary()}.",
        flush=True,
    )
    record_approval_context(
        profile_username=profile_username,
        browser=settings.browser,
        checkpoint=observation.kind,
        timeout_seconds=timeout,
    )

    def approved(page: WebDriver) -> bool:
        """
        Observe authentication and stop immediately if the approval changes to an unsupported challenge.

        Args:
            page (WebDriver): Existing browser session owned by the capture command.

        Returns:
            bool: Whether LinkedIn completed authentication in this session.

        Raises:
            BrowserError: LinkedIn rejects the approval, requests code entry, or redirects outside its origin.
        """
        nonlocal last

        try:
            state = _login_page(page)

            if state == "loading":
                return False

            if _authenticated(page):
                return True

            if state in _LOGIN_BLOCKED_STATES:
                current = _check_login_challenge(page)

                if current != last:
                    _LOGGER.info("LinkedIn checkpoint changed: %s", current.summary())
                    last = current
            elif state in {"login", "signup", "uas"}:
                raise BrowserError("LinkedIn app approval ended without authentication. No profile changes were submitted.")

            return False
        except WebDriverException as error:
            if not is_retryable_selenium_error(error):
                raise

            # Keep polling inside the existing approval deadline after transient remote-driver failures.
            _LOGGER.debug("Transient browser error while observing LinkedIn app approval", extra={"error.type": type(error).__name__})
            return False

    # Keep one deadline even if LinkedIn redraws the prompt; poll the same session without replaying credentials.
    try:
        return WebDriverWait(driver, timeout, poll_frequency=1, ignored_exceptions=(StaleElementReferenceException,)).until(approved)
    except TimeoutException as error:
        raise BrowserError(
            f"LinkedIn sign-in approval was not completed within {timeout} seconds. "
            f"Checkpoint diagnostics: {last.summary()}. No profile changes were submitted."
        ) from error


def _headless_login_ready(driver: WebDriver, settings: Capture, *, profile_username: str | None = None) -> bool:
    """
    Observe login success or allow a bounded approval window for any checkpoint without a recognized hard failure.

    Args:
        driver (WebDriver): Browser whose current authentication state is being polled.
        settings (Capture): Bounded approval wait settings.
        profile_username (str | None): Public configured profile identifier for the audit record.

    Returns:
        bool: True after authentication, otherwise False while ordinary page loading may continue.

    Raises:
        BrowserError: The browser requires code entry, rejects approval, or leaves LinkedIn.
    """
    state = _login_page(driver)

    if state == "loading":
        return False

    if _authenticated(driver):
        return True

    if state in _LOGIN_BLOCKED_STATES:
        return _wait_for_app_approval(
            driver,
            settings,
            _check_login_challenge(driver),
            profile_username=profile_username,
        )

    return False


def _login_form(
    driver: WebDriver,
    *,
    unattended: Capture | None = None,
    profile_username: str | None = None,
) -> tuple[WebElement, WebElement, WebElement] | Literal[True, False]:
    """
    Wait for a complete usable form or an already authenticated session.

    Args:
        driver (WebDriver): Browser whose location is rechecked on every poll.
        unattended (Capture | None): Approval settings for headless login, or None for ordinary interactive login.
        profile_username (str | None): Public configured profile identifier for the audit record.

    Returns:
        tuple[WebElement, WebElement, WebElement] | Literal[True, False]: Editable username/password fields and visible submit control;
            True if signed in; False while the form is unavailable. Submit may remain disabled until credentials are entered.

    Raises:
        BrowserError: The form leaves LinkedIn, requires unsupported verification, or exhausts its app-approval wait.
    """

    # Redirects can finish during the wait; check the origin before looking up or returning credential controls.
    if _login_page(driver) == "loading":
        return False

    authenticated = (
        _headless_login_ready(driver, unattended, profile_username=profile_username) if unattended is not None else _authenticated(driver)
    )

    if authenticated:
        return True

    # LinkedIn serves both fixed-ID forms and generated-ID components with semantic autocomplete attributes.
    # Match autocomplete tokens: hydration can append "webauthn" after the form is found, including during credential entry.
    # Responsive layouts contain duplicate controls, so inspect all matches rather than waiting on a hidden first copy.
    username = next(
        (
            control
            for control in driver.find_elements(By.CSS_SELECTOR, 'input#username, input[autocomplete~="username"]')
            if control.is_displayed() and control.is_enabled()
        ),
        None,
    )
    password = next(
        (
            control
            for control in driver.find_elements(By.CSS_SELECTOR, 'input#password, input[autocomplete~="current-password"]')
            if control.is_displayed() and control.is_enabled()
        ),
        None,
    )

    if username is None or password is None:
        return False

    # Modern layouts use type=button. Scope to the password's nearest sign-in container to exclude other forms and SSO buttons.
    buttons = password.find_elements(
        By.XPATH,
        './ancestor::*[.//button[@type="submit" or normalize-space(.)="Sign in"]][1]'
        '//button[@type="submit" or normalize-space(.)="Sign in"]',
    )
    submit = next((button for button in buttons if button.is_displayed()), None)
    return (username, password, submit) if submit is not None else False


def _login_submit(
    driver: WebDriver,
    *,
    unattended: Capture | None = None,
    profile_username: str | None = None,
) -> WebElement | Literal[True, False]:
    """
    Observe an enabled sign-in button after credential entry without resubmitting or retaining stale controls.

    Args:
        driver (WebDriver): Browser whose form may rerender as credentials are entered.
        unattended (Capture | None): Approval settings for headless login, or None for ordinary interactive login.
        profile_username (str | None): Public configured profile identifier for the audit record.

    Returns:
        WebElement | Literal[True, False]: Enabled submit control, True if already authenticated, or False while unavailable.

    Raises:
        BrowserError: The form leaves LinkedIn, requires unsupported verification, or exhausts its app-approval wait.
    """
    controls = _login_form(driver, unattended=unattended, profile_username=profile_username)

    if isinstance(controls, bool):
        return controls

    # A disabled submit before typing is normal client-side validation, not an unavailable login form.
    submit = controls[2]
    return submit if submit.is_enabled() else False


def _login(driver: WebDriver, settings: Capture, *, headless: bool, profile_username: str | None = None) -> None:
    """
    Submit configured credentials once, then observe authentication without retrying a password submission.

    Args:
        driver (WebDriver): Browser on LinkedIn's login page or an authenticated tab.
        settings (Capture): Page loading timeout and bounded app-approval wait.
        headless (bool): Allow app approval but fail immediately for code-entry MFA or CAPTCHA.
        profile_username (str | None): Public configured profile identifier for the audit record.

    Returns:
        None: Authentication succeeded, including any manually completed challenge in interactive mode.

    Raises:
        BrowserError: Credentials are incomplete or unattended authentication requires intervention.
    """
    username, password = login_credentials(headless=headless)

    if username and not retry_selenium(partial(_authenticated, driver), settings):
        _LOGGER.info("Waiting for the LinkedIn login form")

        def prepare() -> tuple[WebElement, WebElement, WebElement] | Literal[True]:
            """
            Retry form observation while leaving challenges for interactive completion.

            Returns:
                tuple[WebElement, WebElement, WebElement] | Literal[True]: Ready controls or an observed authenticated session.
            """
            try:
                return WebDriverWait(driver, settings.page_timeout_seconds, ignored_exceptions=(StaleElementReferenceException,)).until(
                    partial(_login_form, unattended=settings if headless else None, profile_username=profile_username)
                )
            except TimeoutException as error:
                # A challenge is not a transient missing form. Never reload it or replay credentials to get past it.
                state = _login_page(driver)

                if state in _LOGIN_BLOCKED_STATES:
                    if headless:
                        raise BrowserError(_LOGIN_BLOCKED_MESSAGE.format(state=state) + " No credentials were submitted.") from error

                    _wait_for_login(driver)
                    return True

                raise

        try:
            controls = retry_selenium(prepare, settings)
        except TimeoutException as error:
            if not headless:
                _LOGGER.warning("LinkedIn's login form is unavailable. Finish signing in in the browser; waiting for login.")
                _wait_for_login(driver)
                return

            raise BrowserError(
                f"LinkedIn login form did not become ready after {settings.retry_attempts} attempts "
                f"(page state: {_login_page(driver)}). No credentials were submitted. "
                "Check LinkedIn in an interactive browser or increase capture.page_timeout_seconds for a slow page."
            ) from error

        if controls is True:
            return

        username_field, password_field, submit = controls
        username_field.clear()
        username_field.send_keys(username)
        password_field.clear()
        password_field.send_keys(password)

        # Wait for client-side validation after typing; reacquire the button if the page replaced its controls.
        try:
            ready: WebElement | Literal[True] = retry_selenium(
                lambda: WebDriverWait(driver, settings.page_timeout_seconds, ignored_exceptions=(StaleElementReferenceException,)).until(
                    partial(_login_submit, unattended=settings if headless else None, profile_username=profile_username)
                ),
                settings,
            )
        except TimeoutException as error:
            state = _login_page(driver)

            # A redirect during form entry can reach the same verification block as a submitted login.
            if headless and state in _LOGIN_BLOCKED_STATES:
                raise BrowserError(_LOGIN_BLOCKED_MESSAGE.format(state=state) + " No credentials were submitted.") from error

            raise BrowserError(
                f"LinkedIn sign-in button did not become ready after filling credentials (page state: {state}). "
                "No credentials were submitted. Check the login form interactively."
            ) from error

        if ready is True:
            return

        submit = ready
        _LOGGER.info("Submitting LinkedIn credentials once; waiting for authentication")

        try:
            submit.click()
        except WebDriverException as error:
            if not is_retryable_selenium_error(error):
                raise

            # A lost click response may mean credentials were submitted; observe login without clicking again.
            _LOGGER.warning("Sign-in response was uncertain; checking the existing session without resubmitting credentials.")

    if not headless:
        _wait_for_login(driver)
        return

    # Only recognized app approval extends the wait; code-entry MFA and CAPTCHA terminate at the first observation.
    try:
        retry_selenium(
            lambda: WebDriverWait(driver, settings.page_timeout_seconds, ignored_exceptions=(StaleElementReferenceException,)).until(
                partial(_headless_login_ready, settings=settings, profile_username=profile_username)
            ),
            settings,
        )
    except TimeoutException as error:
        state = _login_page(driver)

        if state == "loading":
            raise BrowserError(
                "LinkedIn login navigation did not finish (page state: loading). "
                "The browser remained blank; check the runner's network and browser availability. "
                "Credentials were not resubmitted."
            ) from error

        # A checkpoint does not establish that credentials are wrong; report the external verification requirement explicitly.
        if state in _LOGIN_BLOCKED_STATES:
            raise BrowserError(_LOGIN_BLOCKED_MESSAGE.format(state=state)) from error

        raise BrowserError(
            f"Unattended LinkedIn login did not complete (page state: {state}). "
            "Check LINKEDIN_USERNAME (login email/phone) and LINKEDIN_PASSWORD, or run this command without --headless "
            "to complete an account challenge interactively. No profile changes were submitted."
        ) from error


def _wait_for_login(driver: WebDriver) -> None:
    """
    Monitor the interactive browser until authentication succeeds or the user cancels.

    Args:
        driver (WebDriver): Browser owned by the capture process.

    Returns:
        None: A LinkedIn tab has an authenticated session and has left login or challenge pages.

    Raises:
        BrowserWindowError: The user closed every browser window.
        KeyboardInterrupt: The user cancelled the capture command.
    """

    # Password lookup and MFA are user-paced; cancellation or closed windows end this wait instead of a timer.
    while True:
        try:
            handles = driver.window_handles
        except InvalidSessionIdException as error:
            raise BrowserWindowError("The capture browser session ended during login.") from error
        except WebDriverException:
            # Remote browser hiccups do not end the user-paced wait; observe the same session on the next poll.
            time.sleep(1)
            continue

        _LOGGER.debug("Checking browser login state", extra={"browser.tabs": len(handles)})

        if not handles:
            raise BrowserWindowError("The capture window was closed during login.")

        # Login can finish in a different tab, so inspect all open tabs rather than trusting the initially active one.
        for handle in handles:
            try:
                driver.switch_to.window(handle)

                if _authenticated(driver):
                    return
            except NoSuchWindowException:
                continue
            except InvalidSessionIdException as error:
                raise BrowserWindowError("The capture browser session ended during login.") from error
            except WebDriverException:
                continue

        time.sleep(1)
