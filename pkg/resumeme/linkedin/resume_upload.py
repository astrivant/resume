"""
Validate, name, upload, and verify the selected release PDF.
"""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING

from pypdf import PdfReader
from pypdf.errors import PdfReadError
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from resumeme.exceptions import BrowserError, BrowserWaitError
from resumeme.linkedin import resume_settings
from resumeme.linkedin.account import check_owner
from resumeme.linkedin.retrying import retry_selenium

if TYPE_CHECKING:
    from pathlib import Path

    from selenium.webdriver.remote.webdriver import WebDriver
    from selenium.webdriver.remote.webelement import WebElement

    from resumeme.config import Config

_LOGGER = logging.getLogger(__name__)
_UPLOAD_TIMEOUT_SECONDS = 120


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


def _saved(driver: WebDriver, filename: str) -> bool:
    """
    Recognize a saved filename independently of the browser's selected file or upload notifications.

    Args:
        driver (WebDriver): Browser displaying loaded application settings.
        filename (str): Internally generated ASCII filename containing the PDF digest.

    Returns:
        bool: A visible filename appears outside file inputs, progress indicators, and transient notifications.
    """
    if any(item.is_displayed() for item in driver.find_elements(By.CSS_SELECTOR, resume_settings._LOADING_QUERY)):
        return False

    # LinkedIn may render the PDF extension separately; match an entire text element, never a substring in an error message.
    names = (filename, filename.removesuffix(".pdf"))
    predicate = " or ".join(f"normalize-space(.)='{name}'" for name in names)
    selector = (
        f"//*[self::main or @role='main']//*[({predicate}) and not(self::input) "
        "and not(ancestor-or-self::*[@role='alert' or @role='status' or @role='dialog' or self::dialog])]"
    )
    return any(item.is_displayed() for item in driver.find_elements(By.XPATH, selector))


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
    field = retry_selenium(lambda: resume_settings._settings(driver, config), policy)

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
        resume_settings._settings(driver, config)

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
