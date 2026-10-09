"""
Start browser sessions with persistent, project-owned profiles.
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
from pathlib import Path
from typing import TYPE_CHECKING

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service

from resumeme.exceptions import BrowserError, BrowserLaunchError, BrowserTimeoutError
from resumeme.linkedin.retrying import retry_selenium
from resumeme.telemetry import safe_log_url

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from selenium.webdriver.remote.webdriver import WebDriver

    from resumeme.config import Capture

_LOGGER = logging.getLogger(__name__)


def _state_root(root: Path) -> Path:
    """
    Locate private browser files in the current command's temporary session when CI manages encrypted caching.

    Args:
        root (Path): Configuration directory used by ordinary local capture.

    Returns:
        Path: Absolute session directory, or the existing local cache location.

    Raises:
        BrowserError: An explicit session directory is not absolute.
    """
    value = os.environ.get("RESUMEME_BROWSER_STATE_DIR")

    if not value:
        return root / ".cache"

    path = Path(value)

    if not path.is_absolute():
        raise BrowserError("RESUMEME_BROWSER_STATE_DIR must be an absolute path.")

    return path.resolve()


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
        BrowserTimeoutError: Firefox did not start successfully.
    """

    # Bound application startup separately from interactive login, which deliberately has no deadline.
    deadline = time.monotonic() + 30

    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                return
        except OSError:
            time.sleep(0.25)

    raise BrowserTimeoutError("Firefox did not open its local automation port. Close any profile-error dialog and retry.")


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
    diagnostics = _state_root(root) / "capture"
    diagnostics.mkdir(parents=True, exist_ok=True)
    options = Options()
    options.set_preference("intl.accept_languages", "en-US,en")
    owns_process = sys.platform == "darwin" and connect_port is None and not headless

    if headless:
        options.add_argument("-headless")

    if sys.platform == "darwin":
        options.binary_location = "/Applications/Firefox.app/Contents/MacOS/firefox"

    # Firefox needs an existing absolute profile path; retain it across attempts to preserve the local login.
    profile = (_state_root(root) / "firefox").resolve()
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
                raise BrowserLaunchError("macOS could not launch Firefox.")
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
    diagnostics = _state_root(root) / "capture"
    diagnostics.mkdir(parents=True, exist_ok=True)

    # Keep automation separate from the user's daily browser and Firefox's incompatible profile format.
    profile = (_state_root(root) / "chrome").resolve()
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
        BrowserError: Chrome was selected with a Firefox-only attachment port.
    """
    if settings.browser == "chrome" and connect_port is not None:
        raise BrowserError("--connect-port is only supported with capture.browser: firefox. Omit it to launch Chrome.")

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
    retry_selenium(navigate, settings)
