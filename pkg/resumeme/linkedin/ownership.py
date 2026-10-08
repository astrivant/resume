"""
Update the authenticated owner's About editor with a public signing identity.
"""

from __future__ import annotations

import logging
import os
import tempfile
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from resumeme.linkedin.browser import _browser, _login, _navigate
from resumeme.linkedin.identity import ownership_block, reconcile_about, release_destination
from resumeme.linkedin.retrying import retry
from resumeme.signing import public_key_fingerprint

if TYPE_CHECKING:
    from pathlib import Path

    from selenium.webdriver.remote.webdriver import WebDriver
    from selenium.webdriver.remote.webelement import WebElement

    from resumeme.config import Config

__all__ = ["publish_ownership"]
_LOGGER = logging.getLogger(__name__)


def _editor(driver: WebDriver, config: Config) -> tuple[WebElement, WebElement]:
    """
    Read a fresh owner-scoped About editor and its Save control.

    Args:
        driver (WebDriver): Authenticated browser session.
        config (Config): Expected profile owner and page timeout.

    Returns:
        tuple[WebElement, WebElement]: The unique About textarea and Save button.

    Raises:
        ValueError: Navigation or available controls do not identify the configured owner's editor.
    """
    username = config.linkedin.username
    profile_path = f"/in/{username}/"
    profile_url = f"https://www.linkedin.com{profile_path}"
    summary_path = f"{profile_path}edit/forms/summary/new/"
    wait = WebDriverWait(driver, config.capture.page_timeout_seconds)
    _navigate(driver, profile_url, config.capture)
    wait.until(lambda page: page.find_elements(By.CSS_SELECTOR, 'main h1, section[aria-label="Primary content"] h2'))
    location = urlsplit(driver.current_url)

    if location.scheme != "https" or location.hostname != "www.linkedin.com" or location.path.rstrip("/") != profile_path.rstrip("/"):
        raise ValueError("LinkedIn redirected away from the configured owner; About was not edited.")

    # Owner edit links also cover a minimal profile whose About section has not yet been created.
    owner_paths = {summary_path, f"{profile_path}edit/intro/"}
    controls = driver.find_elements(By.CSS_SELECTOR, "a[href]")
    editable = any(
        element.is_displayed()
        and urlsplit(element.get_attribute("href") or "").hostname == "www.linkedin.com"
        and urlsplit(element.get_attribute("href") or "").path in owner_paths
        for element in controls
    )

    if not editable:
        raise ValueError("No owner edit control found. Sign in as linkedin.username before updating About.")

    _navigate(driver, f"https://www.linkedin.com{summary_path}", config.capture)
    wait.until(lambda page: page.find_elements(By.CSS_SELECTOR, '[role="dialog"] textarea'))
    location = urlsplit(driver.current_url)

    if location.scheme != "https" or location.hostname != "www.linkedin.com" or location.path != summary_path:
        raise ValueError("LinkedIn did not open the configured owner's About editor.")

    dialogs = [dialog for dialog in driver.find_elements(By.CSS_SELECTOR, '[role="dialog"]') if dialog.is_displayed()]

    if len(dialogs) != 1:
        raise ValueError("Expected one About dialog; no changes were submitted.")

    dialog = dialogs[0]
    fields = [element for element in dialog.find_elements(By.CSS_SELECTOR, "textarea") if element.is_displayed()]
    buttons = [
        element
        for element in dialog.find_elements(By.CSS_SELECTOR, "button")
        if element.is_displayed() and element.text.strip().casefold() == "save"
    ]

    if len(fields) != 1 or len(buttons) != 1:
        raise ValueError("Cannot identify the About textarea and Save button. Use LinkedIn's English interface and retry.")

    return fields[0], buttons[0]


def _update_about(driver: WebDriver, config: Config, root: Path, block: str, *, dry_run: bool) -> str:
    """
    Reconcile fresh server state on each retry and confirm persistence after Save.

    Args:
        driver (WebDriver): Authenticated browser whose lifetime belongs to the caller.
        config (Config): Owner identity and bounded exponential retry policy.
        root (Path): Project root for a private, ignored backup before submission.
        block (str): Public ownership lines derived from the signing key.
        dry_run (bool): Read and preview without mutating the textarea or submitting.

    Returns:
        str: Complete resulting About text, or the proposed text in preview mode.

    Raises:
        ValueError: Concurrent changes, an ambiguous block, or a field limit prevent a safe update.
    """
    baseline: str | None = None
    desired: str | None = None

    def reconcile() -> str:
        """
        Reload current state before deciding whether a Save is still necessary.

        Returns:
            str: Confirmed or previewed About text.
        """
        nonlocal baseline, desired
        field, save = _editor(driver, config)
        current = field.get_attribute("value") or ""

        # An uncertain response may follow a successful Save; a fresh read recognizes it without submitting twice.
        if desired is not None:
            if current == desired:
                return desired

            if current != baseline:
                raise ValueError("About changed during this update. No further writes were attempted; review it and retry.")
        else:
            baseline = current
            desired = reconcile_about(current, block)

        if dry_run or current == desired:
            _LOGGER.info("About reconciliation completed without a write", extra={"publication.dry_run": dry_run})
            return desired

        maximum = field.get_attribute("maxlength")

        if maximum and int(maximum) >= 0 and len(desired.encode("utf-16-le")) // 2 > int(maximum):
            raise ValueError("The ownership block exceeds LinkedIn's About character limit. Shorten your About text and retry.")

        # Keep a recoverable local copy with private permissions; neither backups nor browser state are CI artifacts.
        directory = root / ".cache/ownership"
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)

        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=directory, prefix="about-before-", suffix=".txt", delete=False
        ) as backup:
            backup.write(current)

        field.clear()
        field.send_keys(desired)

        if field.get_attribute("value") != desired:
            raise ValueError("LinkedIn did not accept the complete About text; Save was not clicked.")

        save.click()
        _LOGGER.info("About submitted; verifying persisted text")
        WebDriverWait(driver, config.capture.page_timeout_seconds).until(
            lambda page: not any(dialog.is_displayed() for dialog in page.find_elements(By.CSS_SELECTOR, '[role="dialog"]'))
        )

        # Reopening fetches persisted text instead of trusting a toast or the textarea we just changed.
        confirmed, _ = _editor(driver, config)

        if confirmed.get_attribute("value") != desired:
            raise ValueError("LinkedIn did not retain the expected About text. Inspect the live profile before retrying.")

        return desired

    return retry(
        reconcile,
        attempts=config.capture.retry_attempts,
        backoff=config.capture.retry_backoff_seconds,
        max_backoff=config.capture.retry_max_backoff_seconds,
        exceptions=(TimeoutException, StaleElementReferenceException, NoSuchElementException),
    )


def publish_ownership(
    config: Config, root: Path, public_key: Path, *, dry_run: bool = False, headless: bool = False, connect_port: int | None = None
) -> str:
    """
    Maintain the public ownership block independently of captured résumé content.

    Args:
        config (Config): Profile identity and ownership destination settings.
        root (Path): Configuration directory, also owning ignored browser state and backups.
        public_key (Path): Public key downloaded from a signed release.
        dry_run (bool): Preview the complete About without saving it.
        headless (bool): Authenticate unattended using the existing LinkedIn environment variables.
        connect_port (int | None): Explicit existing local Firefox Marionette port.

    Returns:
        str: Previewed or confirmed About text.

    Raises:
        ValueError: Authentication options, public key, destination, or profile ownership are invalid.
    """
    if headless and connect_port is not None:
        raise ValueError("Headless ownership updates cannot attach to an interactive browser session.")

    if headless and not all(os.environ.get(key) for key in ("LINKEDIN_USERNAME", "LINKEDIN_PASSWORD")):
        raise ValueError("Headless ownership updates require LINKEDIN_USERNAME and LINKEDIN_PASSWORD.")

    # Derive all public values before opening the browser; this command never receives the private signing key.
    block = ownership_block(public_key_fingerprint(public_key), release_destination(config.linkedin.ownership, root))
    _LOGGER.info("Starting About publication", extra={"publication.dry_run": dry_run})

    with _browser(root, config.capture, connect_port, headless=headless) as driver:
        driver.set_page_load_timeout(config.capture.page_timeout_seconds)
        driver.set_window_size(1440, 1000)

        if connect_port is None:
            _navigate(driver, "https://www.linkedin.com/login", config.capture)

        _login(driver, config.capture, headless=headless)
        _LOGGER.info("Login detected; loading the owner's About editor")
        return _update_about(driver, config, root, block, dry_run=dry_run)
