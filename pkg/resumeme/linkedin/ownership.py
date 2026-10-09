"""
Update the authenticated owner's About editor with a public signing identity.
"""

from __future__ import annotations

import logging
import re
import tempfile
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

from resumeme.exceptions import BrowserError
from resumeme.linkedin import browser_scripts
from resumeme.linkedin.browser import _browser, _login, _navigate
from resumeme.linkedin.credentials import login_credentials
from resumeme.linkedin.identity import ownership_block, reconcile_about, release_destination
from resumeme.linkedin.retrying import retry_selenium
from resumeme.signing import public_key_fingerprint

if TYPE_CHECKING:
    from pathlib import Path

    from selenium.webdriver.remote.webdriver import WebDriver
    from selenium.webdriver.remote.webelement import WebElement

    from resumeme.config import Config

__all__ = ["publish_ownership"]
_LOGGER = logging.getLogger(__name__)
_DIALOGS = 'dialog[open], [role="dialog"]'
_FIELDS = 'textarea, [contenteditable="true"][role="textbox"][aria-label="About"]'


def _about_text(driver: WebDriver, field: WebElement) -> str:
    """
    Read actual paragraph and hard-break boundaries without visual line wrapping.

    Args:
        driver (WebDriver): Browser evaluating the editor's DOM structure.
        field (WebElement): Owner-scoped textarea or rich text About field.

    Returns:
        str: Current editor text, including its displayed line breaks.

    Raises:
        BrowserError: The rich text field does not expose readable text.
    """
    if field.get_attribute("contenteditable") != "true":
        return field.get_attribute("value") or ""

    # innerText contains visual line wraps, which become unintended hard breaks when text is saved again.
    value = driver.execute_script(browser_scripts.READ_ABOUT_EDITOR, field)

    if not isinstance(value, str):
        raise BrowserError("Cannot read the About editor's text; no changes were submitted.")

    return _about_spacing(value)


def _same_about_text(observed: str, expected: str) -> bool:
    """
    Compare persisted About content while ignoring editor-added line-break spacing.

    Args:
        observed (str): Text LinkedIn returns after saving a rich text field.
        expected (str): Text submitted through the editor.

    Returns:
        bool: Whether both values contain the same words, URLs, and punctuation in order.
    """
    return " ".join(observed.split()) == " ".join(expected.split())


def _about_spacing(text: str) -> str:
    """
    Reduce repeated empty About paragraphs to one blank line.

    Args:
        text (str): Text from LinkedIn's rich editor or the user's original profile.

    Returns:
        str: Same words and line breaks, with runs of three or more newlines reduced to two.
    """
    return re.sub(r"\n{3,}", "\n\n", text)


def _fill_about(driver: WebDriver, field: WebElement, text: str) -> None:
    """
    Enter plain text through editor events while preserving the intended line breaks.

    Args:
        driver (WebDriver): Browser providing the platform's Select All modifier.
        field (WebElement): Verified About editor, owned by the caller.
        text (str): Complete reconciled About text.

    Returns:
        None: Text was entered; the caller must compare it before clicking Save.
    """
    if field.get_attribute("contenteditable") != "true":
        field.clear()
        field.send_keys(text)
        return

    # Rich text editors track keyboard input. Assigning innerHTML can leave their application state unchanged.
    modifier = Keys.COMMAND if "mac" in str(driver.capabilities.get("platformName", "")).lower() else Keys.CONTROL
    field.click()
    field.send_keys(modifier, "a")
    field.send_keys(Keys.BACKSPACE)
    paragraphs = text.split("\n\n")

    for paragraph_index, paragraph in enumerate(paragraphs):
        if paragraph_index:
            # Enter twice creates a blank paragraph; text extraction collapses any extra empty editor blocks.
            field.send_keys(Keys.ENTER)
            field.send_keys(Keys.ENTER)

        lines = paragraph.split("\n")

        if lines[0]:
            field.send_keys(lines[0])

        # Only line breaks within one paragraph use Shift+Enter; keep its modifier release separate from text input.
        for line in lines[1:]:
            field.send_keys(Keys.SHIFT, Keys.ENTER)
            field.send_keys(line)


def _about_editor_open(driver: WebDriver) -> bool:
    """
    Detect whether LinkedIn still displays the editable About dialog.

    Args:
        driver (WebDriver): Browser displaying an About save response or follow-up modal.

    Returns:
        bool: Whether a visible dialog still contains the visible About editor.
    """
    return any(
        dialog.is_displayed() and any(field.is_displayed() for field in dialog.find_elements(By.CSS_SELECTOR, _FIELDS))
        for dialog in driver.find_elements(By.CSS_SELECTOR, _DIALOGS)
    )


def _editor(driver: WebDriver, config: Config) -> tuple[WebElement, WebElement]:
    """
    Read a fresh owner-scoped About editor and its Save control.

    Args:
        driver (WebDriver): Authenticated browser session.
        config (Config): Expected profile owner and page timeout.

    Returns:
        tuple[WebElement, WebElement]: The unique About text field and Save button.

    Raises:
        BrowserError: Navigation or available controls do not identify the configured owner's editor.
    """
    username = config.linkedin.username
    profile_path = f"/in/{username}/"
    profile_url = f"https://www.linkedin.com{profile_path}"
    summary_path = f"{profile_path}edit/forms/summary/new/"
    wait = WebDriverWait(driver, config.capture.page_timeout_seconds)
    _LOGGER.info("Checking profile owner before opening About")
    _navigate(driver, profile_url, config.capture)
    wait.until(lambda page: page.find_elements(By.CSS_SELECTOR, 'main h1, section[aria-label="Primary content"] h2'))
    location = urlsplit(driver.current_url)

    if location.scheme != "https" or location.hostname != "www.linkedin.com" or location.path.rstrip("/") != profile_path.rstrip("/"):
        raise BrowserError("LinkedIn redirected away from the configured owner; About was not edited.")

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
        raise BrowserError("No owner edit control found. Sign in as profile.linkedin.username before updating About.")

    _LOGGER.info("Opening the About editor")
    summary = next(
        (
            element
            for element in controls
            if element.is_displayed() and element.get_attribute("href") == f"{profile_url}edit/forms/summary/new/"
        ),
        None,
    )

    # The current client opens its native dialog through the owner link; a minimal profile may only expose intro editing.
    if summary is not None:
        driver.execute_script(browser_scripts.SCROLL_ELEMENT_INTO_VIEW, summary)
        summary.click()
    else:
        _navigate(driver, f"https://www.linkedin.com{summary_path}", config.capture)

    wait.until(
        lambda page: any(
            field.is_displayed()
            for dialog in page.find_elements(By.CSS_SELECTOR, _DIALOGS)
            if dialog.is_displayed()
            for field in dialog.find_elements(By.CSS_SELECTOR, _FIELDS)
        ),
        message="The owner About editor did not expose a visible textarea or rich text About field.",
    )
    location = urlsplit(driver.current_url)

    if (
        location.scheme != "https"
        or location.hostname != "www.linkedin.com"
        or location.path.rstrip("/") not in {summary_path.rstrip("/"), profile_path.rstrip("/")}
    ):
        raise BrowserError("LinkedIn did not open the configured owner's About editor.")

    dialogs = [dialog for dialog in driver.find_elements(By.CSS_SELECTOR, _DIALOGS) if dialog.is_displayed()]

    if len(dialogs) != 1:
        raise BrowserError("Expected one About dialog; no changes were submitted.")

    dialog = dialogs[0]
    fields = [element for element in dialog.find_elements(By.CSS_SELECTOR, _FIELDS) if element.is_displayed()]
    buttons = [
        element
        for element in dialog.find_elements(By.CSS_SELECTOR, "button")
        if element.is_displayed() and element.text.strip().casefold() == "save"
    ]

    if len(fields) != 1 or len(buttons) != 1:
        raise BrowserError("Cannot identify the About text field and Save button. Use LinkedIn's English interface and retry.")

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
        BrowserError: Concurrent changes, an ambiguous block, or a field limit prevent a safe update.
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
        current = _about_text(driver, field)

        # An uncertain response may follow a successful Save; a fresh read recognizes it without submitting twice.
        if desired is not None:
            if _same_about_text(current, desired):
                return desired

            if current != baseline:
                raise BrowserError("About changed during this update. No further writes were attempted; review it and retry.")
        else:
            baseline = current
            desired = _about_spacing(reconcile_about(current, block))

        if dry_run or (current == desired and not re.search(r"\n{3,}", current)):
            _LOGGER.info("About reconciliation completed without a write", extra={"publication.dry_run": dry_run})
            return desired

        maximum = field.get_attribute("maxlength")

        if maximum and int(maximum) >= 0 and len(desired.encode("utf-16-le")) // 2 > int(maximum):
            raise BrowserError("The ownership block exceeds LinkedIn's About character limit. Shorten your About text and retry.")

        # Keep a recoverable local copy with private permissions; neither backups nor browser state are CI artifacts.
        directory = root / ".cache/ownership"
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)

        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=directory, prefix="about-before-", suffix=".txt", delete=False
        ) as backup:
            backup.write(current)

        _fill_about(driver, field, desired)

        if _about_text(driver, field) != desired:
            raise BrowserError("LinkedIn did not accept the complete About text; Save was not clicked.")

        save.click()
        _LOGGER.info("About submitted; verifying persisted text")
        WebDriverWait(driver, config.capture.page_timeout_seconds).until(
            lambda page: not _about_editor_open(page),
            message="About Save was submitted, but the editor did not close. Inspect the live About before retrying.",
        )

        # Reopening fetches persisted text instead of trusting a toast or the textarea we just changed.
        confirmed, _ = _editor(driver, config)

        if not _same_about_text(_about_text(driver, confirmed), desired):
            raise BrowserError("LinkedIn did not retain the expected About text. Inspect the live profile before retrying.")

        return desired

    return retry_selenium(reconcile, config.capture)


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
        BrowserError: Authentication options, public key, destination, or profile ownership are invalid.
    """
    if headless and connect_port is not None:
        raise BrowserError("Headless ownership updates cannot attach to an interactive browser session.")

    login_credentials(headless=headless, profile=config.linkedin.username)

    # Derive all public values before opening the browser; this command never receives the private signing key.
    block = ownership_block(public_key_fingerprint(public_key), release_destination(config.linkedin.ownership, root))
    _LOGGER.info("Starting About publication", extra={"publication.dry_run": dry_run})

    with _browser(root, config.capture, connect_port, headless=headless) as driver:
        driver.set_page_load_timeout(config.capture.page_timeout_seconds)
        driver.set_window_size(1440, 1000)

        if connect_port is None:
            _navigate(driver, "https://www.linkedin.com/login", config.capture)

        _login(driver, config.capture, headless=headless, profile_username=config.linkedin.username)
        _LOGGER.info("Login detected; loading the owner's About editor")
        return _update_about(driver, config, root, block, dry_run=dry_run)
