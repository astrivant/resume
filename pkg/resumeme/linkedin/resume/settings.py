"""
Locate LinkedIn's saved-resume controls on its application settings page.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from resumeme.exceptions import BrowserError
from resumeme.linkedin.browser.runtime import _navigate

if TYPE_CHECKING:
    from typing import Literal

    from selenium.webdriver.remote.webdriver import WebDriver
    from selenium.webdriver.remote.webelement import WebElement

    from resumeme.config import Config

_LOGGER = logging.getLogger(__name__)
_SETTINGS_PATH = "/jobs/application-settings/"
_SETTINGS_PATHS = {_SETTINGS_PATH.rstrip("/"), "/jobs/preferences/application-preferences"}
_MAIN = ':is(main, [role="main"])'
_LOADING_QUERY = f'{_MAIN} [role="progressbar"], {_MAIN} [aria-busy="true"], {_MAIN}[aria-busy="true"]'


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


def _settings(driver: WebDriver, config: Config) -> WebElement:
    """
    Load fresh settings before inspecting saved files or selecting an upload.

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
