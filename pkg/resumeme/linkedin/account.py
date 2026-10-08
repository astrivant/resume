"""
Confirm the authenticated account owns the configured public profile before publication.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from resumeme.exceptions import BrowserError
from resumeme.linkedin.browser import _navigate

if TYPE_CHECKING:
    from selenium.webdriver.remote.webdriver import WebDriver

    from resumeme.config import Config

__all__ = ["check_owner"]


def check_owner(driver: WebDriver, config: Config) -> str:
    """
    Confirm the configured profile exposes owner edit controls before changing account data.

    Args:
        driver (WebDriver): Authenticated browser owned by the caller.
        config (Config): Expected LinkedIn owner and navigation policy.

    Returns:
        str: Verified owner-scoped profile path.

    Raises:
        BrowserError: A redirect or missing owner controls prevents profile mutation.
    """
    path = f"/in/{config.linkedin.username}/"
    _navigate(driver, f"https://www.linkedin.com{path}", config.capture)
    WebDriverWait(driver, config.capture.page_timeout_seconds).until(
        lambda page: page.find_elements(By.CSS_SELECTOR, 'main h1, section[aria-label="Primary content"] h2')
    )
    location = urlsplit(driver.current_url)

    if location.scheme != "https" or location.hostname != "www.linkedin.com" or location.path.rstrip("/") != path.rstrip("/"):
        raise BrowserError("LinkedIn redirected away from the configured owner; no account changes were submitted.")

    # An intro edit link also identifies owners whose Skills section is still empty.
    editable = any(
        link.is_displayed()
        and urlsplit(link.get_attribute("href") or "").hostname == "www.linkedin.com"
        and urlsplit(link.get_attribute("href") or "").path in {f"{path}edit/intro/", f"{path}edit/forms/skill/new/"}
        for link in driver.find_elements(By.CSS_SELECTOR, "a[href]")
    )

    if not editable:
        raise BrowserError("No owner edit control found. Sign in as linkedin.username before publishing account data.")

    return path
