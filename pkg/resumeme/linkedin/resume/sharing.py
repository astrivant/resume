"""
Read and reconcile LinkedIn's recruiter resume-data sharing preference.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from resumeme.exceptions import BrowserError, BrowserWaitError
from resumeme.linkedin.resume import settings as resume_settings
from resumeme.linkedin.retrying import retry_selenium

if TYPE_CHECKING:
    from typing import Literal

    from selenium.webdriver.remote.webdriver import WebDriver
    from selenium.webdriver.remote.webelement import WebElement

    from resumeme.config import Config

_LOGGER = logging.getLogger(__name__)
_RECRUITER_LABELS = ("share resume data with recruiters", "share resume data with hirers", "allow recruiters to view your resumes")


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
        By.CSS_SELECTOR,
        f'{resume_settings._MAIN} [role="switch"], {resume_settings._MAIN} [role="checkbox"], '
        f'{resume_settings._MAIN} input[type="checkbox"]',
    ):
        identifier = control.get_attribute("id")
        labels = [
            label
            for label in driver.find_elements(By.CSS_SELECTOR, f"{resume_settings._MAIN} label[for]")
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
        resume_settings._settings(driver, config)
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
