"""
Wait for lazy profile content before a traversal moves it out of view.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.support.ui import WebDriverWait

from resumeme.linkedin.browser.scripts import PROFILE_CONTENT_STATE

if TYPE_CHECKING:
    from selenium.webdriver.remote.webdriver import WebDriver

    from resumeme.config import Capture

__all__ = ["wait_for_content"]

_QUIET_SECONDS = 1.0
_POLL_SECONDS = 0.25


def wait_for_content(driver: WebDriver, settings: Capture) -> None:
    """
    Require settled content and no visible loading placeholders before taking a snapshot.

    Args:
        driver (WebDriver): Browser at the viewport being collected.
        settings (Capture): Existing page timeout bounding incomplete hydration.

    Returns:
        None: The current content and layout have remained stable for a quiet interval.

    Raises:
        TimeoutException: Visible loading placeholders or changing content exceed the page timeout.
    """
    previous: str | None = None
    unchanged_since = time.monotonic()

    def ready(page: WebDriver) -> bool:
        """
        Observe content without logging profile text or retaining stale browser elements.

        Args:
            page (WebDriver): Browser polled by Selenium.

        Returns:
            bool: Loading is complete and consecutive observations span the quiet interval.
        """
        nonlocal previous, unchanged_since
        state: object = page.execute_script(PROFILE_CONTENT_STATE)
        now = time.monotonic()

        # Null means a visible placeholder is still loading; it must reset even an otherwise unchanged document.
        if not isinstance(state, str) or state != previous:
            previous = state if isinstance(state, str) else None
            unchanged_since = now
            return False

        return now - unchanged_since >= _QUIET_SECONDS

    WebDriverWait(
        driver, settings.page_timeout_seconds, poll_frequency=_POLL_SECONDS, ignored_exceptions=(StaleElementReferenceException,)
    ).until(ready, message="LinkedIn profile content did not finish loading before scrolling; retry capture.")
