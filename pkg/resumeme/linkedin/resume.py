"""
Publish an unchanged release PDF and reconcile optional recruiter-sharing preferences.
"""

from __future__ import annotations

import hashlib
import logging
import re
import tempfile
import unicodedata
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from pypdf import PdfReader
from pypdf.errors import PdfReadError
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from resumeme.exceptions import BrowserError, BrowserWaitError
from resumeme.linkedin.account import check_owner
from resumeme.linkedin.browser import _browser, _login, _navigate
from resumeme.linkedin.credentials import login_credentials
from resumeme.linkedin.retrying import retry_selenium

if TYPE_CHECKING:
    from typing import Literal

    from selenium.webdriver.remote.webdriver import WebDriver
    from selenium.webdriver.remote.webelement import WebElement

    from resumeme.config import Config

__all__ = ["publish_resume"]

_LOGGER = logging.getLogger(__name__)
_SETTINGS_PATH = "/jobs/application-settings/"
_SETTINGS_PATHS = {_SETTINGS_PATH.rstrip("/"), "/jobs/preferences/application-preferences"}
_MAIN = ':is(main, [role="main"])'
_LOADING_QUERY = f'{_MAIN} [role="progressbar"], {_MAIN} [aria-busy="true"], {_MAIN}[aria-busy="true"]'
_RECRUITER_LABELS = ("share resume data with recruiters", "share resume data with hirers", "allow recruiters to view your resumes")
_UPLOAD_TIMEOUT_SECONDS = 120
_RESUME_NAME = re.compile(r"[\w .()'&+-]{1,240}\.pdf", re.IGNORECASE)


def _pdf_bytes(pdf: Path) -> bytes:
    """
    Validate the supplied document without changing the bytes covered by its release signature.

    Args:
        pdf (Path): Explicit PDF selected for upload.

    Returns:
        bytes: Original, unencrypted PDF containing at least one page.

    Raises:
        BrowserError: The document is unreadable, empty, or encrypted.
        OSError: The input cannot be read.
    """
    content = pdf.read_bytes()

    if not content.startswith(b"%PDF-"):
        raise BrowserError("Resume upload requires a valid PDF; select the verified release's resume.pdf.")

    try:
        document = PdfReader(BytesIO(content))

        if document.is_encrypted or not document.pages:
            raise BrowserError("Resume upload requires an unencrypted PDF containing at least one page.")
    except PdfReadError as error:
        raise BrowserError("The resume PDF cannot be read. Download and verify the release again.") from error

    # LinkedIn recommends less than 2 MB; leave acceptance to its UI rather than recompressing a signed file.
    if len(content) >= 2_000_000:
        _LOGGER.warning("LinkedIn recommends resumes smaller than 2 MB", extra={"file.size": len(content)})

    return content


def _resume_filename(name: str, content: bytes) -> str:
    """
    Include the profile owner's name while keeping retries bound to exact PDF bytes.

    Args:
        name (str): Captured profile display name or configured LinkedIn username fallback.
        content (bytes): Signed PDF bytes selected for upload.

    Returns:
        str: ASCII filename such as `emma-doyle-resume-cbfd27b0e5f67b8d.pdf`.
    """
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").casefold()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name).strip("-") or "linkedin-profile"
    digest = hashlib.sha256(content).hexdigest()[:16]
    return f"{slug}-resume-{digest}.pdf"


def _upload_input(driver: WebDriver) -> WebElement | Literal[False]:
    """
    Find an unambiguous PDF input only within LinkedIn's application settings.

    Args:
        driver (WebDriver): Browser navigating to application preferences.

    Returns:
        WebElement | Literal[False]: Enabled file input, or False while the form loads.

    Raises:
        BrowserError: The destination changed or multiple upload controls are present.
    """
    location = urlsplit(driver.current_url)

    if location.scheme != "https" or location.netloc != "www.linkedin.com" or location.path.rstrip("/") not in _SETTINGS_PATHS:
        raise BrowserError("LinkedIn left its application settings. No resume upload was submitted on this page.")

    # Wait for the saved list to finish loading before deciding that a content-derived filename is absent.
    if any(item.is_displayed() for item in driver.find_elements(By.CSS_SELECTOR, _LOADING_QUERY)):
        return False

    # File inputs are commonly hidden behind a styled Upload button; Selenium can send a path directly without a desktop picker.
    fields = []

    for field in driver.find_elements(By.CSS_SELECTOR, f'{_MAIN} input[type="file"]'):
        accepted = {item.strip().lower() for item in (field.get_attribute("accept") or "").split(",")}

        if field.is_enabled() and (accepted == {""} or accepted.intersection({".pdf", "application/pdf", "application/*", "*/*"})):
            fields.append(field)

    if len(fields) > 1:
        raise BrowserError("LinkedIn shows multiple resume upload inputs. Check Resumes and application data interactively.")

    return fields[0] if fields else False


def _send_pdf_file(driver: WebDriver, field: WebElement, pdf: Path) -> None:
    """
    Select the PDF through LinkedIn's hidden file control without opening a desktop picker.

    Args:
        driver (WebDriver): Browser displaying validated application settings.
        field (WebElement): Unique file input returned by `_upload_input`.
        pdf (Path): Staged, content-addressed PDF.

    Returns:
        None: The file input receives the exact staged path.
    """
    if field.is_displayed():
        field.send_keys(str(pdf.resolve()))
        return

    original_class = field.get_attribute("class")
    original_style = field.get_attribute("style")

    # LinkedIn hides its file input behind a label; expose a 1px control briefly for Selenium's file selection.
    driver.execute_script(
        """
        const input = arguments[0];
        input.classList.remove('hidden');
        for (const [name, value] of Object.entries({
          display: 'block', visibility: 'visible', position: 'fixed', left: '0', top: '0',
          width: '1px', height: '1px', opacity: '0.01'
        })) input.style.setProperty(name, value, 'important');
        """,
        field,
    )

    try:
        field.send_keys(str(pdf.resolve()))
    finally:
        # Restore LinkedIn's original hidden control after the file-change event has fired.
        driver.execute_script(
            """
            const input = arguments[0];
            const className = arguments[1];
            const style = arguments[2];
            if (className === null) input.removeAttribute('class');
            else input.setAttribute('class', className);
            if (style === null) input.removeAttribute('style');
            else input.setAttribute('style', style);
            """,
            field,
            original_class,
            original_style,
        )


def _settings(driver: WebDriver, config: Config) -> WebElement:
    """
    Load a fresh settings page before inspecting saved files or selecting an upload.

    Args:
        driver (WebDriver): Authenticated browser owned by the caller.
        config (Config): Navigation and retry policy.

    Returns:
        WebElement: Unique ready PDF upload control on the allowed route.
    """
    _LOGGER.info("Opening LinkedIn application settings; waiting for the PDF upload control")
    _navigate(driver, f"https://www.linkedin.com{_SETTINGS_PATH}", config.capture)
    return WebDriverWait(driver, config.capture.page_timeout_seconds).until(
        _upload_input,
        message="LinkedIn application settings did not expose a ready PDF upload control. No file was submitted on this visit.",
    )


def _saved(driver: WebDriver, filename: str) -> bool:
    """
    Recognize a saved filename independently of the browser's selected file or upload notifications.

    Args:
        driver (WebDriver): Browser displaying loaded application settings.
        filename (str): Internally generated ASCII filename containing the PDF digest.

    Returns:
        bool: A visible filename appears outside file inputs, progress indicators, and transient notifications.
    """
    if any(item.is_displayed() for item in driver.find_elements(By.CSS_SELECTOR, _LOADING_QUERY)):
        return False

    # LinkedIn may render the PDF extension separately; match an entire text element, never a substring in an error message.
    names = (filename, filename.removesuffix(".pdf"))
    predicate = " or ".join(f"normalize-space(.)='{name}'" for name in names)
    selector = (
        f"//*[self::main or @role='main']//*[({predicate}) and not(self::input) "
        "and not(ancestor-or-self::*[@role='alert' or @role='status' or @role='dialog' or self::dialog])]"
    )
    return any(item.is_displayed() for item in driver.find_elements(By.XPATH, selector))


def _saved_resume_names(driver: WebDriver) -> set[str]:
    """
    Read visible PDF filenames from the saved-resume list, excluding notices and dialogs.

    Args:
        driver (WebDriver): Browser displaying LinkedIn's application settings.

    Returns:
        set[str]: Distinct visible filenames that can be managed from this page.
    """
    if any(item.is_displayed() for item in driver.find_elements(By.CSS_SELECTOR, _LOADING_QUERY)):
        return set()

    selector = (
        "//*[self::main or @role='main']//*[contains(translate(normalize-space(.), "
        "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '.pdf') "
        "and not(self::input) and not(ancestor-or-self::*[@role='alert' or @role='status' or @role='dialog' or self::dialog])]"
    )
    names = set()

    for element in driver.find_elements(By.XPATH, selector):
        if not element.is_displayed():
            continue

        name = " ".join(element.text.split())

        if _RESUME_NAME.fullmatch(name):
            names.add(name)

    return names


def _xpath_literal(value: str) -> str:
    """
    Encode a visible filename as an XPath string literal, including apostrophes.

    Args:
        value (str): Text to compare in a LinkedIn page selector.

    Returns:
        str: XPath literal expression preserving the exact input string.
    """
    if "'" not in value:
        return f"'{value}'"

    if '"' not in value:
        return f'"{value}"'

    pieces = value.split("'")
    return "concat(" + ', "\'", '.join(f"'{piece}'" for piece in pieces) + ")"


def _action_name(element: WebElement) -> str:
    """
    Read the accessible name used to distinguish a resume menu from unrelated controls.

    Args:
        element (WebElement): Candidate button, link, or role button.

    Returns:
        str: Normalized visible and accessible label.
    """
    values = [element.get_attribute("aria-label"), element.get_attribute("title"), element.text]
    return " ".join(" ".join(value.split()) for value in values if value).casefold()


def _resume_action(driver: WebDriver, filename: str, names: set[str]) -> tuple[WebElement, bool]:
    """
    Bind one overflow or delete control to the row containing exactly one saved resume.

    Args:
        driver (WebDriver): Browser displaying LinkedIn's application settings.
        filename (str): Exact saved resume that should be removed.
        names (set[str]): All visible saved resume filenames used to reject page-level controls.

    Returns:
        tuple[WebElement, bool]: Control and whether it opens an overflow menu.

    Raises:
        BrowserError: No unique filename row or delete control can be identified safely.
    """
    literal = _xpath_literal(filename)
    stem_literal = _xpath_literal(filename.removesuffix(".pdf"))
    predicate = f"normalize-space(.)={literal} or normalize-space(.)={stem_literal}"
    selector = (
        f"//*[self::main or @role='main']//*[({predicate}) and not(self::input) "
        "and not(ancestor-or-self::*[@role='alert' or @role='status' or @role='dialog' or self::dialog])]"
    )
    labels = [element for element in driver.find_elements(By.XPATH, selector) if element.is_displayed()]

    if not labels:
        raise BrowserWaitError(f"LinkedIn no longer shows the saved resume {filename}.")

    other_names = {name.casefold() for name in names if name != filename}
    actions: dict[tuple[str, bool], tuple[WebElement, bool]] = {}

    # Climb from the exact filename until a small containing row has one relevant action.
    for label in labels:
        ancestor = label

        for _ in range(8):
            ancestor = ancestor.find_element(By.XPATH, "..")
            row_text = " ".join(ancestor.text.split()).casefold()

            if filename.casefold() not in row_text or any(name in row_text for name in other_names):
                continue

            candidates = []

            for control in ancestor.find_elements(By.CSS_SELECTOR, "button, [role='button'], a"):
                if not control.is_displayed() or not control.is_enabled():
                    continue

                name = _action_name(control)

                if re.search(r"\b(delete|remove)\b", name):
                    candidates.append((control, False))
                elif re.search(r"\b(more|option|options|action|actions)\b", name):
                    candidates.append((control, True))

            if len(candidates) > 1:
                raise BrowserError(f"LinkedIn shows multiple remove controls for {filename}; no resume was deleted.")

            if candidates:
                control, opens_menu = candidates[0]
                actions[(control.id, opens_menu)] = (control, opens_menu)
                break

    if len(actions) != 1:
        raise BrowserError(
            f"Could not identify one LinkedIn delete menu for {filename}. The new resume is saved; no older resume was deleted."
        )

    return next(iter(actions.values()))


def _delete_menu_item(driver: WebDriver) -> WebElement | Literal[False]:
    """
    Find the Delete command in LinkedIn's opened resume menu.

    Args:
        driver (WebDriver): Browser after opening one saved resume's action menu.

    Returns:
        WebElement | Literal[False]: Unique visible delete command, or False while the menu opens.

    Raises:
        BrowserError: Multiple delete commands are visible.
    """
    selector = "[role='menu'] button, [role='menu'] [role='menuitem'], [role='menuitem'], [role='menu'] a"
    matches = [
        element
        for element in driver.find_elements(By.CSS_SELECTOR, selector)
        if element.is_displayed() and re.search(r"\b(delete|remove)\b", _action_name(element))
    ]

    if len(matches) > 1:
        raise BrowserError("LinkedIn shows multiple delete menu items; no saved resume was deleted.")

    return matches[0] if matches else False


def _delete_confirmation(driver: WebDriver) -> WebElement | Literal[False]:
    """
    Identify an explicit Delete confirmation without matching unrelated page controls.

    Args:
        driver (WebDriver): Browser after selecting Delete from a resume menu.

    Returns:
        WebElement | Literal[False]: Unique delete confirmation, or False when LinkedIn deletes immediately.

    Raises:
        BrowserError: A confirmation dialog is ambiguous or offers no explicit delete action.
    """
    dialogs = [dialog for dialog in driver.find_elements(By.CSS_SELECTOR, "[role='dialog'], dialog[open]") if dialog.is_displayed()]

    if not dialogs:
        return False

    if len(dialogs) > 1:
        raise BrowserError("LinkedIn shows multiple confirmation dialogs; no saved resume was deleted.")

    controls = [
        element
        for element in dialogs[0].find_elements(By.CSS_SELECTOR, "button, [role='button'], [role='menuitem']")
        if element.is_displayed() and re.search(r"\b(delete|remove)\b", _action_name(element))
    ]

    if len(controls) != 1:
        raise BrowserError("LinkedIn's resume deletion confirmation is ambiguous; no saved resume was deleted.")

    return controls[0]


def _delete_saved_resume(driver: WebDriver, config: Config, filename: str) -> None:
    """
    Delete one older saved resume, then confirm its absence from freshly loaded settings.

    Args:
        driver (WebDriver): Authenticated browser that owns the LinkedIn profile.
        config (Config): Bounded browser retry settings.
        filename (str): Saved resume selected for deletion; the new release PDF is never passed here.

    Returns:
        None: The named saved resume is confirmed absent.

    Raises:
        BrowserError: The delete action cannot be safely bound or LinkedIn does not confirm removal.
    """
    policy = config.capture
    _settings(driver, config)
    names = retry_selenium(lambda: _saved_resume_names(driver), policy)

    if filename not in names:
        return

    control, opens_menu = retry_selenium(lambda: _resume_action(driver, filename, names), policy)

    # Click each destructive control once. A lost response is reconciled by a fresh read below.
    try:
        control.click()

        if opens_menu:
            item = WebDriverWait(driver, policy.page_timeout_seconds).until(
                _delete_menu_item,
                message="LinkedIn did not expose Delete for this saved resume.",
            )
            item.click()

        confirmation = _delete_confirmation(driver)

        if confirmation:
            confirmation.click()
    except WebDriverException:
        _LOGGER.warning("LinkedIn resume deletion response was uncertain; checking saved resumes without clicking again")

    def confirm_deleted() -> None:
        """
        Verify a deletion after reloading server-backed application settings.

        Returns:
            None: LinkedIn no longer lists the selected filename.

        Raises:
            BrowserWaitError: LinkedIn still lists the selected resume.
        """
        _settings(driver, config)

        if filename in _saved_resume_names(driver):
            raise BrowserWaitError(f"LinkedIn still lists the saved resume {filename}.")

    try:
        retry_selenium(confirm_deleted, policy)
    except WebDriverException as error:
        raise BrowserError(
            f"Could not confirm removal of {filename}. The new resume remains saved; inspect LinkedIn's resume list before retrying."
        ) from error

    _LOGGER.info("Removed an older LinkedIn saved resume")


def _replace_existing_resumes(driver: WebDriver, config: Config, keep_filename: str) -> None:
    """
    Remove every other saved resume after the new release PDF has been confirmed.

    Args:
        driver (WebDriver): Authenticated browser that owns the LinkedIn profile.
        config (Config): Bounded browser retry settings.
        keep_filename (str): Exact newly published PDF to preserve.

    Returns:
        None: The saved-resume list contains no other files.

    Raises:
        BrowserError: A saved file cannot be safely identified or removed.
    """
    policy = config.capture
    _settings(driver, config)
    names = retry_selenium(lambda: _saved_resume_names(driver), policy)

    # Never delete prior files unless the verified current release is visible in the same saved-resume list.
    if keep_filename not in names:
        raise BrowserError("The new release PDF is not visible in LinkedIn's saved-resume list; no previous resume was deleted.")

    # LinkedIn currently allows only a few saved resumes; this bound also prevents a page that keeps changing from looping forever.
    for _ in range(max(1, len(names) + 1)):
        older = sorted(names - {keep_filename})

        if not older:
            _LOGGER.info("LinkedIn saved resumes now contain only the current release PDF")
            return

        _delete_saved_resume(driver, config, older[0])
        _settings(driver, config)
        names = retry_selenium(lambda: _saved_resume_names(driver), policy)

    if names - {keep_filename}:
        raise BrowserError("LinkedIn's saved-resume list kept changing; older resumes may remain. Inspect it before retrying.")


def _recruiter_control(driver: WebDriver) -> tuple[WebElement, WebElement] | Literal[False]:
    """
    Identify the recruiter-data toggle by its accessible name or associated label.

    Args:
        driver (WebDriver): Browser displaying validated application settings.

    Returns:
        tuple[WebElement, WebElement] | Literal[False]: State-bearing control and clickable control or label; False while unavailable.

    Raises:
        BrowserError: More than one visible recruiter-sharing control matches.
    """
    matches = []

    for control in driver.find_elements(
        By.CSS_SELECTOR, f'{_MAIN} [role="switch"], {_MAIN} [role="checkbox"], {_MAIN} input[type="checkbox"]'
    ):
        identifier = control.get_attribute("id")
        labels = [
            label
            for label in driver.find_elements(By.CSS_SELECTOR, f"{_MAIN} label[for]")
            if identifier and label.get_attribute("for") == identifier and label.is_displayed()
        ]
        names = [control.accessible_name, *(label.text for label in labels)]

        # Match the recruiter-specific label so the adjacent Save resumes control is never toggled accidentally.
        if not any(label in " ".join(name.split()).casefold() for name in names for label in _RECRUITER_LABELS):
            continue

        if control.is_displayed():
            matches.append((control, control))
        elif control.get_attribute("data-artdeco-toggle-button") == "true":
            # LinkedIn hides its switch input and gives the associated accessibility label a zero-size box.
            toggle = control.find_element(By.XPATH, "..")

            if "artdeco-toggle" in (toggle.get_attribute("class") or "").split() and toggle.is_displayed():
                matches.append((control, toggle))
        elif len(labels) == 1:
            # Native checkboxes may be visually hidden behind their associated clickable label.
            matches.append((control, labels[0]))

    if len(matches) > 1:
        raise BrowserError("LinkedIn shows multiple recruiter-sharing controls. Check Resumes and application data interactively.")

    return matches[0] if matches else False


def _sharing_enabled(control: WebElement) -> bool:
    """
    Read the toggle's explicit state without interpreting a missing value as disabled.

    Args:
        control (WebElement): Recruiter switch or native checkbox identified by its label.

    Returns:
        bool: Current sharing state.

    Raises:
        BrowserError: The control does not expose a definite boolean state.
    """
    checked = control.get_attribute("aria-checked")

    if checked in {"true", "false"}:
        return checked == "true"

    if checked is None and control.tag_name == "input" and control.get_attribute("type") == "checkbox":
        return control.is_selected()

    raise BrowserError("LinkedIn's recruiter-sharing state could not be determined. Inspect the setting before retrying.")


def _recruiter_sharing(driver: WebDriver, config: Config, *, dry_run: bool) -> None:
    """
    Apply an explicit sharing override once and confirm persistence through fresh settings reads.

    Args:
        driver (WebDriver): Authenticated browser whose account ownership was verified during upload.
        config (Config): Desired sharing state and bounded retry policy.
        dry_run (bool): Read the setting without changing it, including when upload is disabled.

    Returns:
        None: The override is absent, previewed, already satisfied, or confirmed after one click.

    Raises:
        BrowserError: The control is ambiguous, disabled, or cannot confirm the requested persisted state.
    """
    desired = config.linkedin.resume.share_with_recruiters

    if desired is None:
        return

    policy = config.capture

    def read() -> tuple[WebElement, WebElement]:
        """
        Observe the recruiter control after loading account settings from the server.

        Returns:
            tuple[WebElement, WebElement]: Current state control and its clickable target.
        """
        _settings(driver, config)
        return WebDriverWait(driver, policy.page_timeout_seconds).until(_recruiter_control)

    control, target = retry_selenium(read, policy)
    current = _sharing_enabled(control)
    _LOGGER.info("Recruiter sharing preference", extra={"sharing.current": current, "sharing.requested": desired, "dry_run": dry_run})

    if dry_run or current == desired:
        return

    if not control.is_enabled() or control.get_attribute("aria-disabled") == "true":
        raise BrowserError("LinkedIn's recruiter-sharing control is disabled. Check the saved resume and account settings interactively.")

    # A lost click response can still mean success; repeated clicks would invert a successfully applied preference.
    try:
        target.click()
        WebDriverWait(driver, policy.page_timeout_seconds).until(lambda _: _sharing_enabled(control) == desired)
    except WebDriverException:
        _LOGGER.warning("Recruiter-sharing response was uncertain; checking persisted settings without clicking again")

    def confirm() -> None:
        """
        Require the requested preference to survive a settings reload.

        Returns:
            None: The server reports the requested sharing state.

        Raises:
            BrowserWaitError: The stored state has not reached the requested value.
        """
        saved, _ = read()

        if _sharing_enabled(saved) != desired:
            raise BrowserWaitError("LinkedIn has not confirmed the requested recruiter-sharing setting.")

    try:
        retry_selenium(confirm, policy)
    except WebDriverException as error:
        raise BrowserError(
            "Could not confirm recruiter sharing. The resume is saved; inspect Share resume data with recruiters "
            "in LinkedIn's application settings, then retry the same PDF. No second toggle click was submitted."
        ) from error

    _LOGGER.info("Recruiter sharing preference confirmed", extra={"sharing.enabled": desired})


def _upload_resume(driver: WebDriver, config: Config, pdf: Path, *, dry_run: bool) -> str:
    """
    Submit at most one upload and reconcile uncertain outcomes by rereading saved resumes.

    Args:
        driver (WebDriver): Authenticated browser.
        config (Config): Expected owner and bounded exponential retry settings.
        pdf (Path): Temporary copy with a stable content-derived filename.
        dry_run (bool): Inspect ownership and settings without selecting a file.

    Returns:
        str: Filename confirmed on LinkedIn, or proposed by a dry run.

    Raises:
        BrowserError: Ownership, settings, or persisted upload cannot be confirmed.
    """
    check_owner(driver, config)
    policy = config.capture
    field = retry_selenium(lambda: _settings(driver, config), policy)

    if _saved(driver, pdf.name):
        _LOGGER.info("Release PDF already saved on LinkedIn", extra={"file.name": pdf.name})
        return pdf.name

    if dry_run:
        _LOGGER.info("Resume upload preview completed", extra={"file.name": pdf.name})
        return pdf.name

    # A timed-out WebDriver call may already have sent the file. Never resubmit blindly or remove another saved resume.
    try:
        _send_pdf_file(driver, field, pdf)
        # Stay on the upload page while LinkedIn processes the file; navigation can cancel its asynchronous upload.
        WebDriverWait(driver, max(_UPLOAD_TIMEOUT_SECONDS, policy.page_timeout_seconds)).until(lambda page: _saved(page, pdf.name))
    except WebDriverException:
        _LOGGER.warning("Resume upload response was uncertain; checking saved resumes before reporting its outcome")

    def confirm() -> str:
        """
        Require persistence across navigation, excluding a filename shown only in the local upload form.

        Returns:
            str: Filename visible after loading fresh server state.

        Raises:
            BrowserWaitError: The submitted PDF is not yet confirmed in saved resumes.
        """
        _settings(driver, config)

        if not _saved(driver, pdf.name):
            raise BrowserWaitError("The uploaded resume is not yet visible in LinkedIn's saved resumes.")

        return pdf.name

    try:
        confirmed = retry_selenium(confirm, policy)
    except WebDriverException as error:
        raise BrowserError(
            "Could not confirm the resume upload. Inspect LinkedIn Jobs > Preferences > Resumes and application data "
            f"for {pdf.name} or an upload error, then retry the same PDF. No second upload was submitted."
        ) from error

    _LOGGER.info("Release PDF saved on LinkedIn", extra={"file.name": confirmed})
    return confirmed


def publish_resume(
    config: Config,
    root: Path,
    pdf: Path,
    *,
    profile_name: str | None = None,
    dry_run: bool = False,
    headless: bool = False,
    connect_port: int | None = None,
) -> str:
    """
    Publish a supplied PDF and apply an explicit recruiter-sharing override after confirming it is saved.

    Args:
        config (Config): Owner, explicit upload opt-in, optional sharing override, and browser settings.
        root (Path): Configuration directory owning local browser state and private staging files.
        pdf (Path): Explicit release PDF; CI verifies its signature before calling this command.
        profile_name (str | None): Captured display name used in the uploaded filename; config username is the fallback.
        dry_run (bool): Validate the document, owner, upload form, and requested sharing control without writes, even when disabled.
        headless (bool): Use login environment variables without a desktop.
        connect_port (int | None): Existing local Firefox Marionette port.

    Returns:
        str: Saved or proposed content-derived filename.

    Raises:
        BrowserError: Publication is disabled, the PDF is invalid, or browser verification fails.
        OSError: The PDF cannot be read or its private staging copy cannot be written.
    """
    if not dry_run and not config.linkedin.resume.publish:
        raise BrowserError("Set linkedin.resume.publish: true to opt in to saving resumes on LinkedIn.")

    if headless and connect_port is not None:
        raise BrowserError("Headless resume publication cannot attach to an interactive browser.")

    content = _pdf_bytes(pdf)
    filename = _resume_filename(profile_name or config.linkedin.username, content)
    login_credentials(headless=headless, profile=config.linkedin.username)
    cache = root / ".cache/linkedin-resumes"
    cache.mkdir(parents=True, exist_ok=True)

    # Isolate a byte-for-byte copy so concurrent local runs cannot overwrite the selected file while the browser reads it.
    with tempfile.TemporaryDirectory(dir=cache) as directory:
        staged = Path(directory) / filename
        staged.write_bytes(content)

        with _browser(root, config.capture, connect_port, headless=headless) as driver:
            driver.set_page_load_timeout(config.capture.page_timeout_seconds)
            driver.set_window_size(1440, 1000)

            if connect_port is None:
                _navigate(driver, "https://www.linkedin.com/login", config.capture)

            _login(driver, config.capture, headless=headless)
            filename = _upload_resume(driver, config, staged, dry_run=dry_run)

            if config.linkedin.resume.replace_existing:
                if dry_run:
                    _LOGGER.info("Resume replacement previewed; existing LinkedIn resumes were not deleted")
                else:
                    # Remove previous copies only after `_upload_resume` has confirmed this release survives a reload.
                    _replace_existing_resumes(driver, config, filename)

            # LinkedIn requires a saved resume before sharing can be enabled; also reconcile when this PDF was already present.
            _recruiter_sharing(driver, config, dry_run=dry_run)
            return filename
