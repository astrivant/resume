"""
Publish the verified release PDF and reconcile the optional recruiter-sharing preference.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from resumeme.exceptions import BrowserError
from resumeme.linkedin.browser import _browser, _login, _navigate
from resumeme.linkedin.credentials import login_credentials
from resumeme.linkedin.resume_library import _replace_existing_resumes
from resumeme.linkedin.resume_sharing import _recruiter_sharing
from resumeme.linkedin.resume_upload import _pdf_bytes, _resume_filename, _upload_resume

if TYPE_CHECKING:
    from resumeme.config import Config

__all__ = ["publish_resume"]
_LOGGER = logging.getLogger(__name__)


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
        raise BrowserError("Set publishing.linkedin.resume.publish: true to opt in to saving resumes on LinkedIn.")

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

            _login(driver, config.capture, headless=headless, profile_username=config.linkedin.username)
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
