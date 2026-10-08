"""
Collect a profile through Firefox or Chrome with interactive or unattended authentication.
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import sys
import time
import webbrowser
from contextlib import contextmanager
from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from attrs import evolve
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, NoSuchWindowException, StaleElementReferenceException, TimeoutException
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait

from resumeme.compiler.asts.parsing import detail_links, merge_profile_html, parse_contact, parse_detail, parse_profile
from resumeme.compiler.asts.profile import save_profile
from resumeme.linkedin.media import cache_media
from resumeme.linkedin.retrying import retry
from resumeme.telemetry import safe_log_url

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path
    from typing import Literal

    from selenium.webdriver.remote.webdriver import WebDriver
    from selenium.webdriver.remote.webelement import WebElement

    from resumeme.compiler.asts.profile import Entry, Profile, Section
    from resumeme.config import Capture, Config

__all__ = ["capture_profile"]
_LOGGER = logging.getLogger(__name__)

_SCROLL_SCRIPT = """
const main = document.querySelector('main');
let node = main?.querySelector('section[aria-label="Primary content"]') || main;
let target = document.scrollingElement;
while (node && node !== document.body) {
    if (['auto', 'scroll'].includes(getComputedStyle(node).overflowY) && node.scrollHeight > node.clientHeight) {
        target = node;
        break;
    }
    node = node.parentElement;
}
if (arguments[0] === 'top') target.scrollTop = 0;
else target.scrollTop += Math.max(target.clientHeight * 0.8, 600);
return target.scrollTop + target.clientHeight >= target.scrollHeight - 5;
"""


def _listen_port() -> int:
    """
    Reserve an available loopback port for a dedicated Firefox session.

    Returns:
        int: Port to use for Marionette.
    """

    # Let the OS choose a free local port rather than requiring users to coordinate a fixed automation port.
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_browser(port: int) -> None:
    """
    Wait up to thirty seconds for Firefox's local automation endpoint.

    Args:
        port (int): Loopback Marionette port.

    Returns:
        None: Firefox accepts local connections.

    Raises:
        TimeoutError: Firefox did not start successfully.
    """

    # Bound application startup separately from interactive login, which deliberately has no deadline.
    deadline = time.monotonic() + 30

    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                return
        except OSError:
            time.sleep(0.25)

    raise TimeoutError("Firefox did not open its local automation port. Close any profile-error dialog and retry.")


@contextmanager
def _firefox(root: Path, connect_port: int | None, *, headless: bool = False) -> Iterator[WebDriver]:
    """
    Launch macOS Firefox through the Python browser client with a live profile path.

    Args:
        root (Path): Configuration directory holding the ignored local browser profile.
        connect_port (int | None): Explicit port of a manually launched local Firefox.
        headless (bool): Launch without a visible window for unattended capture.

    Yields:
        WebDriver: Browser whose local profile survives retries without exporting credentials.
    """

    # Keep browser tooling and diagnostics in ignored project caches while honoring explicit Selenium overrides.
    os.environ.setdefault("SE_CACHE_PATH", str(root / ".cache/selenium"))
    os.environ.setdefault("SE_AVOID_STATS", "true")
    diagnostics = root / ".cache/capture"
    diagnostics.mkdir(parents=True, exist_ok=True)
    options = Options()
    options.set_preference("intl.accept_languages", "en-US,en")
    owns_process = sys.platform == "darwin" and connect_port is None and not headless

    if headless:
        options.add_argument("-headless")

    if sys.platform == "darwin":
        options.binary_location = "/Applications/Firefox.app/Contents/MacOS/firefox"

    # Firefox needs an existing absolute profile path; retain it across attempts to preserve the local login.
    profile = (root / ".cache/firefox").resolve()
    profile.mkdir(parents=True, exist_ok=True, mode=0o700)
    profile.chmod(0o700)

    if connect_port is None:
        if owns_process:
            # Launch through macOS application services, then attach Selenium to this dedicated Firefox process.
            connect_port = _listen_port()
            (profile / "user.js").write_text(
                f'user_pref("marionette.port", {connect_port});\n'
                'user_pref("browser.shell.checkDefaultBrowser", false);\n'
                'user_pref("signon.rememberSignons", false);\n'
                'user_pref("intl.accept_languages", "en-US,en");\n',
                encoding="utf-8",
            )
            browser = webbrowser.BackgroundBrowser(
                ["/usr/bin/open", "-na", "Firefox", "--args", "-no-remote", "--marionette", "-profile", str(profile), "%s"]
            )

            if not browser.open("https://www.linkedin.com/login"):
                raise RuntimeError("macOS could not launch Firefox.")
        else:
            # Native Selenium launch is sufficient on other platforms, but it must use the same persistent profile.
            options.add_argument("-profile")
            options.add_argument(str(profile))

    service_args = []

    if connect_port is not None:
        # Both explicit attachments and macOS launches must be listening before geckodriver tries to attach.
        _wait_for_browser(connect_port)
        service_args = ["--connect-existing", "--marionette-port", str(connect_port)]

    service = Service(service_args=service_args, log_output=str(diagnostics / "firefox.log"))
    process_id: object = None

    try:
        with webdriver.Firefox(options=options, service=service) as driver:
            process_id = driver.capabilities.get("moz:processID")
            yield driver
    finally:
        # On macOS, deleting an attached session can leave the app alive and the profile locked.
        # Terminate only the process created for this capture, never an explicitly attached session.
        if owns_process and isinstance(process_id, int) and process_id > 0:
            try:
                os.kill(process_id, signal.SIGTERM)
            except ProcessLookupError:
                pass


@contextmanager
def _chrome(root: Path, *, headless: bool = False) -> Iterator[WebDriver]:
    """
    Launch Chrome with a persistent project-owned profile and Selenium-managed driver.

    Args:
        root (Path): Configuration directory holding ignored browser state and diagnostics.
        headless (bool): Launch without a visible window for unattended capture.

    Yields:
        WebDriver: Browser session closed on exit; the private login profile survives retries.
    """
    os.environ.setdefault("SE_CACHE_PATH", str(root / ".cache/selenium"))
    os.environ.setdefault("SE_AVOID_STATS", "true")
    diagnostics = root / ".cache/capture"
    diagnostics.mkdir(parents=True, exist_ok=True)

    # Keep automation separate from the user's daily browser and Firefox's incompatible profile format.
    profile = (root / ".cache/chrome").resolve()
    profile.mkdir(parents=True, exist_ok=True, mode=0o700)
    profile.chmod(0o700)
    options = ChromeOptions()
    options.add_argument(f"--user-data-dir={profile}")
    options.add_argument("--lang=en-US")
    options.add_experimental_option(
        "prefs", {"intl.accept_languages": "en-US,en", "credentials_enable_service": False, "profile.password_manager_enabled": False}
    )

    if headless:
        options.add_argument("--headless=new")

    # Selenium resolves the installed Chrome and matching driver; the context owns cleanup even after capture errors.
    service = ChromeService(log_output=str(diagnostics / "chrome.log"))

    with webdriver.Chrome(options=options, service=service) as driver:
        yield driver


@contextmanager
def _browser(root: Path, settings: Capture, connect_port: int | None = None, *, headless: bool = False) -> Iterator[WebDriver]:
    """
    Select the configured browser without changing shared login or capture behavior.

    Args:
        root (Path): Configuration directory for the selected browser's local profile.
        settings (Capture): Browser selection, defaulting to Firefox.
        connect_port (int | None): Existing Firefox Marionette port; Chrome always launches a dedicated session.
        headless (bool): Launch without a desktop window.

    Yields:
        WebDriver: Browser owned by the selected launcher.

    Raises:
        ValueError: Chrome was selected with a Firefox-only attachment port.
    """
    if settings.browser == "chrome" and connect_port is not None:
        raise ValueError("--connect-port is only supported with capture.browser: firefox. Omit it to launch Chrome.")

    # Both capture and ownership updates share selection so changing the config cannot route them to different sessions.
    session = _chrome(root, headless=headless) if settings.browser == "chrome" else _firefox(root, connect_port, headless=headless)
    _LOGGER.info("Opening browser", extra={"browser.name": settings.browser, "browser.headless": headless})

    with session as driver:
        yield driver


def _text_changed(previous: str) -> Callable[[WebDriver], bool]:
    """
    Bind the previous text for a typed Selenium wait predicate.

    Args:
        previous (str): Content before scrolling or changing pages.

    Returns:
        Callable[[WebDriver], bool]: Predicate that detects updated main content.
    """
    return lambda page: page.find_element(By.CSS_SELECTOR, "main").text != previous


def _navigate(driver: WebDriver, url: str, settings: Capture) -> None:
    """
    Retry timed-out read-only navigations without changing authentication state.

    Args:
        driver (WebDriver): Existing authenticated browser.
        url (str): Login or owner-scoped profile URL.
        settings (Capture): Timeout and retry limits.

    Returns:
        None: Navigation completed or its final timeout propagated.
    """

    def navigate() -> None:
        """
        Measure one navigation without exposing Selenium's wire payloads or credentials.

        Returns:
            None: The browser reached the requested destination.
        """
        started = time.monotonic()
        _LOGGER.debug("Browser navigation started", extra={"url.full": safe_log_url(url)})
        driver.get(url)
        _LOGGER.debug(
            "Browser navigation completed", extra={"url.full": safe_log_url(url), "request.duration_seconds": time.monotonic() - started}
        )

    # Retry read-only navigation in the existing session so transient page failures do not reset authentication.
    retry(
        navigate,
        attempts=settings.retry_attempts,
        backoff=settings.retry_backoff_seconds,
        exceptions=(TimeoutException,),
        max_backoff=settings.retry_max_backoff_seconds,
    )


def _authenticated(driver: WebDriver) -> bool:
    """
    Require both a LinkedIn session cookie and a completed authentication redirect.

    Args:
        driver (WebDriver): Browser on the tab being checked.

    Returns:
        bool: The current LinkedIn tab has finished authentication.
    """
    location = urlsplit(driver.current_url)
    host = location.hostname or ""
    path = location.path.casefold().strip("/").split("/", 1)[0]
    authenticating = path in {"login", "signup", "checkpoint", "challenge", "authwall", "uas"}
    return (host == "linkedin.com" or host.endswith(".linkedin.com")) and not authenticating and driver.get_cookie("li_at") is not None


def _login_page(driver: WebDriver) -> str:
    """
    Classify the login location without exposing URL tokens or account identifiers.

    Args:
        driver (WebDriver): Browser being authenticated.

    Returns:
        str: Allowlisted route category, never a raw URL, cookie, or page body.
    """
    location = urlsplit(driver.current_url)

    if location.scheme != "https" or location.hostname not in {"linkedin.com", "www.linkedin.com"}:
        return "unexpected origin"

    route = location.path.casefold().strip("/").split("/", 1)[0]
    return route if route in {"login", "signup", "checkpoint", "challenge", "authwall", "uas", "feed", "in"} else "other LinkedIn page"


def _login_form(driver: WebDriver) -> tuple[WebElement, WebElement, WebElement] | Literal[True, False]:
    """
    Wait for a complete usable form or an already authenticated session.

    Args:
        driver (WebDriver): Browser whose location is rechecked on every poll.

    Returns:
        tuple[WebElement, WebElement, WebElement] | Literal[True, False]: Username, password, and submit controls; True if signed in;
            False while any control is hidden or disabled.

    Raises:
        ValueError: The form is no longer on LinkedIn's HTTPS origin.
        NoSuchElementException: A control has not appeared; the caller's explicit wait retries the lookup.
    """

    # Redirects can finish during the wait; check the origin before looking up or returning credential controls.
    if _login_page(driver) == "unexpected origin":
        raise ValueError("LinkedIn login redirected to an unexpected origin.")

    if _authenticated(driver):
        return True

    controls = (
        driver.find_element(By.ID, "username"),
        driver.find_element(By.ID, "password"),
        driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]'),
    )
    return controls if all(control.is_displayed() and control.is_enabled() for control in controls) else False


def _login(driver: WebDriver, settings: Capture, *, headless: bool) -> None:
    """
    Submit configured credentials once, then observe authentication without retrying a password submission.

    Args:
        driver (WebDriver): Browser on LinkedIn's login page or an authenticated tab.
        settings (Capture): Existing page timeout for unattended authentication.
        headless (bool): Fail when interactive intervention is needed rather than waiting for an absent user.

    Returns:
        None: Authentication succeeded, including any manually completed challenge in interactive mode.

    Raises:
        ValueError: Credentials are incomplete or unattended authentication requires intervention.
    """
    username = os.environ.get("LINKEDIN_USERNAME", "")
    password = os.environ.get("LINKEDIN_PASSWORD", "")

    if bool(username) != bool(password) or (headless and not username):
        raise ValueError("Set both LINKEDIN_USERNAME (login email) and LINKEDIN_PASSWORD for unattended capture.")

    if username and not _authenticated(driver):
        _LOGGER.info("Waiting for the LinkedIn login form")

        def prepare() -> tuple[WebElement, WebElement, WebElement] | Literal[True]:
            """
            Retry form observation while leaving challenges for interactive completion.

            Returns:
                tuple[WebElement, WebElement, WebElement] | Literal[True]: Ready controls or an observed authenticated session.
            """
            try:
                return WebDriverWait(driver, settings.page_timeout_seconds, ignored_exceptions=(StaleElementReferenceException,)).until(
                    _login_form
                )
            except TimeoutException as error:
                # A challenge is not a transient missing form. Never reload it or replay credentials to get past it.
                if _login_page(driver) in {"checkpoint", "challenge", "authwall"}:
                    if headless:
                        raise ValueError(
                            f"LinkedIn login form is unavailable (page state: {_login_page(driver)}). "
                            "Complete sign-in interactively using this command without --headless. No credentials were submitted."
                        ) from error

                    _wait_for_login(driver)
                    return True

                raise

        try:
            controls = retry(
                prepare,
                attempts=settings.retry_attempts,
                backoff=settings.retry_backoff_seconds,
                max_backoff=settings.retry_max_backoff_seconds,
                exceptions=(TimeoutException,),
            )
        except TimeoutException as error:
            if not headless:
                _LOGGER.warning("LinkedIn's login form is unavailable. Finish signing in in the browser; waiting for login.")
                _wait_for_login(driver)
                return

            raise ValueError(
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
        _LOGGER.info("Submitting LinkedIn credentials once; waiting for authentication")

        try:
            submit.click()
        except TimeoutException:
            # A click can submit successfully and time out waiting for the destination's assets. Observe its result without resubmitting.
            _LOGGER.warning("Sign-in navigation timed out; checking the existing session without resubmitting credentials.")

    if not headless:
        _wait_for_login(driver)
        return

    # Interactive capture still waits indefinitely; an unattended runner cannot complete MFA, CAPTCHA, or account challenges.
    try:
        WebDriverWait(driver, settings.page_timeout_seconds).until(_authenticated)
    except TimeoutException as error:
        raise ValueError(
            f"Unattended LinkedIn login did not complete (page state: {_login_page(driver)}). "
            "Check LINKEDIN_USERNAME (login email) and LINKEDIN_PASSWORD, or run this command without --headless "
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
        NoSuchWindowException: The user closed every browser window.
        KeyboardInterrupt: The user cancelled the capture command.
    """

    # Password lookup and MFA are user-paced; cancellation or closed windows end this wait instead of a timer.
    while True:
        handles = driver.window_handles
        _LOGGER.debug("Checking browser login state", extra={"browser.tabs": len(handles)})

        if not handles:
            raise NoSuchWindowException("The capture window was closed during login.")

        # Login can finish in a different tab, so inspect all open tabs rather than trusting the initially active one.
        for handle in handles:
            try:
                driver.switch_to.window(handle)

                if _authenticated(driver):
                    return
            except NoSuchWindowException:
                continue

        time.sleep(1)


def _expand(driver: WebDriver, settings: Capture) -> list[str]:
    """
    Expand text and lazy lists until the document settles or an explicit bound fails.

    Args:
        driver (WebDriver): Authenticated browser on a profile or detail page.
        settings (Capture): Bounded wait and scrolling settings.

    Returns:
        list[str]: DOM snapshots retaining content evicted during virtualized scrolling.

    Raises:
        ValueError: A loading or expansion bound prevents a complete capture.
    """

    # Always start at the top: later snapshots may evict earlier cards from LinkedIn's virtualized DOM.
    WebDriverWait(driver, settings.page_timeout_seconds).until(lambda page: page.find_elements(By.CSS_SELECTOR, "main"))
    driver.execute_script(_SCROLL_SCRIPT, "top")
    previous = ""
    settled = 0
    snapshots: list[str] = []

    for _ in range(settings.max_scrolls):
        # Capture the current viewport before expanding or scrolling can replace its content.
        snapshots.append(driver.page_source)
        buttons = driver.find_elements(
            By.CSS_SELECTOR,
            "main button.inline-show-more-text__button, main button.pvs-list__see-more-button, "
            "main button[aria-label='Show more'], main button[aria-label='See more']",
        )

        # Expand visible text in place; stale buttons are expected when LinkedIn rerenders a card during the loop.
        clicked = False

        for button in buttons:
            try:
                if button.is_displayed() and button.is_enabled() and "less" not in button.text.casefold():
                    driver.execute_script("arguments[0].click()", button)
                    clicked = True
            except StaleElementReferenceException:
                continue

        at_bottom: object = driver.execute_script(_SCROLL_SCRIPT, "next")
        current = driver.find_element(By.CSS_SELECTOR, "main").text
        _LOGGER.debug(
            "Expanding profile content",
            extra={"capture.snapshots": len(snapshots), "capture.at_bottom": at_bottom is True, "capture.expanded": clicked},
        )

        # Require several quiet bottom-of-page observations so a temporary loading gap is not mistaken for completion.
        if at_bottom is True and current == previous and not clicked:
            settled += 1

            if settled >= 3:
                snapshots.append(driver.page_source)
                return snapshots
        else:
            settled = 0

        previous = current

        try:
            WebDriverWait(driver, 1.5, poll_frequency=0.25).until(_text_changed(current))
        except TimeoutException:
            pass

    raise ValueError("Capture reached max_scrolls before the page settled; raise the limit and retry.")


def _detail_tabs(driver: WebDriver) -> dict[str, WebElement]:
    """
    Find visible content tabs while excluding sidebar forms and footer controls.

    Args:
        driver (WebDriver): Browser on a dedicated profile section page.

    Returns:
        dict[str, WebElement]: Visible tab labels mapped to their interactive elements.
    """

    # Scope tab discovery to profile content so unrelated sidebar forms do not become capture targets.
    primary = driver.find_elements(By.CSS_SELECTOR, 'main section[aria-label="Primary content"]')
    scope = primary[0] if primary else driver.find_element(By.CSS_SELECTOR, "main")
    return {
        label: element
        for element in scope.find_elements(By.CSS_SELECTOR, "label[for], [role='tab']")
        if element.is_displayed() and (label := element.text.strip())
    }


def _details(driver: WebDriver, url: str, key: str, title: str, settings: Capture) -> Section:
    """
    Follow all loaded detail pages and reject pagination that cannot be exhausted.

    Args:
        driver (WebDriver): Authenticated browser.
        url (str): Owner-scoped detail route.
        key (str): Section identifier.
        title (str): Section title.
        settings (Capture): Page and expansion limits.

    Returns:
        Section: All entries collected across detail pages.

    Raises:
        ValueError: Pagination loops or exceeds the configured limit.
    """
    _navigate(driver, url, settings)
    WebDriverWait(driver, settings.page_timeout_seconds).until(
        lambda page: page.find_element(By.CSS_SELECTOR, "main").text.strip().casefold().startswith(title.casefold())
    )

    # These sections partition real content across tabs, such as recommendations received versus given.
    tabs = []

    if key in {"recommendations", "interests"}:
        tabs = list(_detail_tabs(driver))

    collected = _detail_pages(driver, key, title, settings)

    if not tabs:
        return collected

    entries: list[Entry] = []

    for index, label in enumerate(tabs):
        if index:
            # Pagination and tab switches replace DOM nodes; reacquire the tab instead of reusing a stale element.
            tab = _detail_tabs(driver).get(label)

            if tab is None:
                raise NoSuchElementException(f"The {label} tab disappeared while capturing {title}.")

            before = driver.find_element(By.CSS_SELECTOR, "main").text
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'})", tab)
            tab.click()
            WebDriverWait(driver, settings.page_timeout_seconds).until(_text_changed(before))
            collected = _detail_pages(driver, key, title, settings)

        # Carry tab provenance into the portable text so the merged section remains understandable without browser state.
        entries.extend(evolve(entry, title=f"{label}: {entry.title}") for entry in collected.entries)

    return evolve(collected, entries=entries)


def _detail_pages(driver: WebDriver, key: str, title: str, settings: Capture) -> Section:
    """
    Collect the active section tab across scrolling and pagination.

    Args:
        driver (WebDriver): Browser on the selected detail tab.
        key (str): Stable section identifier.
        title (str): Display heading.
        settings (Capture): Expansion and pagination limits.

    Returns:
        Section: Entries from every loaded page of the selected tab.

    Raises:
        ValueError: Pagination repeats content or exceeds the configured limit.
    """
    collected = parse_detail_after_expansion(driver, key, title, settings)

    # Repeated page text detects stalled or cyclic pagination without relying on changing page URLs.
    seen = {driver.find_element(By.CSS_SELECTOR, "main").text}

    for page_number in range(1, settings.max_pages_per_section + 1):
        next_buttons = driver.find_elements(By.CSS_SELECTOR, "main button[aria-label='Next'], main button.artdeco-pagination__button--next")
        next_button = next((button for button in next_buttons if button.is_displayed() and button.is_enabled()), None)

        if next_button is None:
            return collected

        # Exhaustion is a capture failure, not permission to return a silently truncated employment history.
        if page_number == settings.max_pages_per_section:
            raise ValueError(f"Capture reached max_pages_per_section for {title}.")

        before = driver.find_element(By.CSS_SELECTOR, "main").text
        next_button.click()
        WebDriverWait(driver, settings.page_timeout_seconds).until(_text_changed(before))
        section = parse_detail_after_expansion(driver, key, title, settings)
        signature = driver.find_element(By.CSS_SELECTOR, "main").text

        if signature in seen:
            raise ValueError(f"Pagination repeated content in {title}.")

        seen.add(signature)
        collected = evolve(collected, entries=[*collected.entries, *section.entries])

    raise ValueError(f"Capture reached max_pages_per_section for {title}.")


def parse_detail_after_expansion(driver: WebDriver, key: str, title: str, settings: Capture) -> Section:
    """
    Wait for a detail page to finish expanding before parsing it.

    Args:
        driver (WebDriver): Browser on the target detail page.
        key (str): Section identifier.
        title (str): Section heading.
        settings (Capture): Expansion limits.

    Returns:
        Section: Parsed detail content.
    """
    snapshots = _expand(driver, settings)

    # Validate the settled page first, then recover entries that disappeared from earlier virtualized viewports.
    combined = parse_detail(snapshots[-1], key, title)
    entries: dict[tuple[str, tuple[str, ...]], Entry] = {}

    for snapshot in snapshots:
        try:
            section = parse_detail(snapshot, key, title)
        except ValueError:
            # Initial virtualized snapshots can contain only the heading; the final page must parse above.
            continue

        for entry in section.entries:
            # Merge observations of the same text while keeping newly loaded media and the largest observed endorsement count.
            identity = (entry.title, tuple(entry.paragraphs))
            previous = entries.get(identity, entry)
            entries[identity] = evolve(
                entry,
                images=list({item.url: item for item in [*previous.images, *entry.images]}.values()),
                links=list({item.url: item for item in [*previous.links, *entry.links]}.values()),
                skills=list(
                    {
                        item.name.casefold(): item
                        for item in sorted([*previous.skills, *entry.skills], key=lambda skill: skill.endorsements)
                    }.values()
                ),
            )

    return evolve(combined, entries=list(entries.values()))


def _contact(driver: WebDriver, username: str, settings: Capture) -> Section:
    """
    Open the owner's read-only contact overlay and wait for its content.

    Args:
        driver (WebDriver): Authenticated local browser.
        username (str): Configured owner slug.
        settings (Capture): Page loading and retry limits.

    Returns:
        Section: Contact information displayed by LinkedIn.
    """

    # Wait for the owner's contact dialog itself; page readiness does not mean the overlay has populated.
    _navigate(driver, f"https://www.linkedin.com/in/{username}/overlay/contact-info/", settings)
    WebDriverWait(driver, settings.page_timeout_seconds).until(
        lambda page: any(
            dialog.is_displayed() and "contact info" in dialog.text.casefold()
            for dialog in page.find_elements(By.CSS_SELECTOR, 'dialog[open], [role="dialog"]')
        )
    )
    return parse_contact(driver.page_source)


def capture_profile(config: Config, root: Path, connect_port: int | None = None, *, headless: bool = False) -> Profile:
    """
    Open the configured browser, collect the owner profile, and cache its images.

    Args:
        config (Config): Profile and capture settings.
        root (Path): Configuration directory for caches and output assets.
        connect_port (int | None): Existing local Firefox Marionette port, if explicitly requested.
        headless (bool): Use environment credentials without opening an interactive window.

    Returns:
        Profile: Captured profile without exported browser credentials.

    Raises:
        TimeoutException: A page did not load after bounded retries.
        ValueError: The profile is missing, redirected, or cannot be fully expanded.
    """
    if headless and connect_port is not None:
        raise ValueError("Headless capture cannot attach to an interactive browser session.")

    # Missing secrets fail before a browser is started; interactive users keep their unlimited login wait.
    if headless and not all(os.environ.get(key) for key in ("LINKEDIN_USERNAME", "LINKEDIN_PASSWORD")):
        raise ValueError("Headless capture requires LINKEDIN_USERNAME (login email) and LINKEDIN_PASSWORD.")

    name = config.capture.browser.title()
    _LOGGER.info("Starting LinkedIn capture", extra={"browser.name": name, "browser.headless": headless})
    warnings: list[str] = []

    # Own one browser lifecycle across login, profile expansion, detail pages, and contact capture.
    with _browser(root, config.capture, connect_port, headless=headless) as driver:
        driver.set_page_load_timeout(config.capture.page_timeout_seconds)
        driver.set_window_size(1440, 1000)

        if connect_port is None:
            _navigate(driver, "https://www.linkedin.com/login", config.capture)

        _login(driver, config.capture, headless=headless)
        _LOGGER.info("Login detected; loading profile")
        username = config.linkedin.username
        _navigate(driver, f"https://www.linkedin.com/in/{username}/", config.capture)

        try:
            WebDriverWait(driver, config.capture.page_timeout_seconds).until(
                lambda page: page.find_elements(By.CSS_SELECTOR, 'main h1, section[aria-label="Primary content"] h2')
            )
        except TimeoutException as error:
            # Retain the actual failed page for markup/debugging work instead of reporting only a generic timeout.
            diagnostic = root / ".cache/capture/profile.html"
            diagnostic.write_text(driver.page_source, encoding="utf-8")
            driver.save_screenshot(str(root / ".cache/capture/profile.png"))
            raise ValueError(f"The profile heading did not load at {driver.current_url}; inspect {diagnostic}.") from error

        # A successful navigation can still land on an auth wall or another profile; bind collection to the requested owner.
        expected = f"/in/{username}/".casefold()

        if urlsplit(driver.current_url).path.casefold().rstrip("/") + "/" != expected:
            raise ValueError("LinkedIn redirected away from the configured profile.")

        snapshots = retry(
            partial(_expand, driver, config.capture),
            attempts=config.capture.retry_attempts,
            backoff=config.capture.retry_backoff_seconds,
            max_backoff=config.capture.retry_max_backoff_seconds,
            exceptions=(NoSuchElementException, StaleElementReferenceException, TimeoutException),
        )
        html = merge_profile_html(snapshots)
        (root / ".cache/capture/profile.html").write_text(html, encoding="utf-8")
        profile = parse_profile(html, username)
        routes = detail_links(html, username)

        # Dedicated detail pages supersede preview cards only after their full expansion and pagination succeed.
        replacements: dict[str, Section] = {}

        for key, url in routes.items():
            title = next((section.title for section in profile.sections if section.key == key), key.replace("-", " ").title())
            _LOGGER.info("Capturing profile section", extra={"profile.section": key})

            try:
                replacements[key] = retry(
                    partial(_details, driver, url, key, title, config.capture),
                    attempts=config.capture.retry_attempts,
                    backoff=config.capture.retry_backoff_seconds,
                    max_backoff=config.capture.retry_max_backoff_seconds,
                    exceptions=(TimeoutException, StaleElementReferenceException, NoSuchElementException),
                )
            finally:
                (root / f".cache/capture/{key}.html").write_text(driver.page_source, encoding="utf-8")

        # Preserve profile order and append any detail-only sections discovered outside the initial cards.
        sections = [replacements.pop(section.key, section) for section in profile.sections]
        sections.extend(replacements.values())

        # Tabs can contain additional content that a single view does not expose.
        if any(section.key in {"recommendations", "interests"} and section.key not in routes for section in sections):
            warnings.append("Profile contains tabbed content; verify all tab variants are represented before accepting the snapshot.")

        if f"/in/{username}/overlay/contact-info" in html:
            _LOGGER.info("Capturing contact information")
            contact = retry(
                partial(_contact, driver, username, config.capture),
                attempts=config.capture.retry_attempts,
                backoff=config.capture.retry_backoff_seconds,
                max_backoff=config.capture.retry_max_backoff_seconds,
                exceptions=(TimeoutException, StaleElementReferenceException, NoSuchElementException),
            )
            sections.insert(0, contact)

        profile = evolve(profile, sections=sections, warnings=warnings, captured_at=datetime.now(UTC).isoformat())

    _LOGGER.info("Downloading profile images and linked project previews")

    # Browser access is finished; checkpoint the text before independent media downloads can fail or be interrupted.
    save_profile(
        evolve(profile, warnings=[*warnings, "Media download is not yet complete."]),
        root / ".cache/capture/profile.json",
    )
    return cache_media(profile, config, root)
