"""
Verify lazy content is read before scrolling or fan-out can discard it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from selenium.common.exceptions import TimeoutException

from resumeme.compiler.asts.parsing import merge_profile_html, parse_profile
from resumeme.config import Capture
from resumeme.linkedin.browser import scripts
from resumeme.linkedin.capture.profile import _expand
from resumeme.linkedin.capture.viewport import wait_for_content

if TYPE_CHECKING:
    from collections.abc import Callable

    from pytest import MonkeyPatch
    from selenium.webdriver.remote.webdriver import WebDriver


@pytest.mark.parametrize(
    "states",
    [
        [None, "intro", "intro", None, "about", "about", "about"],
        ["intro", "intro", "about", "about", "about"],
        ["minimal", "minimal", "minimal"],
    ],
)
def test_viewport_requires_a_quiet_interval_after_loading(monkeypatch: MonkeyPatch, states: list[str | None]) -> None:
    """
    Restart readiness on placeholders, newly hydrated text, and geometry changes.

    Args:
        monkeypatch (MonkeyPatch): Replaces browser polling and the monotonic clock with deterministic observations.
        states (list[str | None]): Loading markers or content signatures at half-second intervals.

    Returns:
        None: Only the final observation is accepted, including for a genuinely minimal profile.
    """
    driver = MagicMock()
    driver.execute_script.side_effect = states
    monkeypatch.setattr("resumeme.linkedin.capture.viewport.time.monotonic", MagicMock(side_effect=[i / 2 for i in range(20)]))

    def poll(predicate: Callable[[WebDriver], bool], *, message: str) -> None:
        """
        Replay browser states without wall-clock sleeps.

        Args:
            predicate (Callable[[WebDriver], bool]): Production readiness predicate.
            message (str): Selenium timeout description.

        Returns:
            None: Every intermediate state is rejected and the last state is accepted.
        """
        assert [predicate(driver) for _ in states] == [False] * (len(states) - 1) + [True], message

    wait = MagicMock()
    wait.return_value.until.side_effect = poll
    monkeypatch.setattr("resumeme.linkedin.capture.viewport.WebDriverWait", wait)
    wait_for_content(driver, Capture(page_timeout_seconds=17))
    assert wait.call_args.args == (driver, 17)
    assert driver.execute_script.call_count == len(states)


def test_unfinished_content_uses_the_bounded_page_timeout(monkeypatch: MonkeyPatch) -> None:
    """
    Fail incomplete hydration rather than permitting a partial successful capture.

    Args:
        monkeypatch (MonkeyPatch): Supplies a browser whose skeleton never finishes loading.

    Returns:
        None: Selenium's timeout reaches the existing capture retry boundary.
    """
    driver = MagicMock()
    driver.execute_script.return_value = None

    with pytest.raises(TimeoutException, match="did not finish loading"):
        wait_for_content(driver, Capture(page_timeout_seconds=0))


def test_capture_reads_expanded_about_before_scrolling(monkeypatch: MonkeyPatch) -> None:
    """
    Preserve delayed overview content that has no detail route for a worker to recover.

    Args:
        monkeypatch (MonkeyPatch): Provides deterministic hydration, expansion, and viewport eviction.

    Returns:
        None: The overview contains the full About even when scrolling immediately removes it from the DOM.
    """
    intro = "<section><h1>Alex Example</h1></section>"
    about = "<section><h2>About</h2><p>Complete overview with expanded text.</p></section>"
    driver = MagicMock()
    button = MagicMock()
    button.text = "See more"
    phase = "loading"
    reads: list[str] = []

    def settle(page: WebDriver, settings: Capture) -> None:
        """
        Hydrate the current viewport before the collector reads its HTML.

        Args:
            page (WebDriver): Browser supplied by the capture loop.
            settings (Capture): Existing timeout settings.

        Returns:
            None: The current viewport has rendered text and fresh expansion controls.
        """
        reads.append(phase)
        text = "<section><h2>About</h2><p>Preview</p></section>" if phase == "loading" else about if phase == "expanded" else ""
        driver.page_source = f"<main>{intro}{text}</main>"
        driver.find_element.return_value.text = "Stable viewport"
        driver.find_elements.return_value = [button] if phase == "loading" else []

    def execute(script: str, *args: object) -> bool:
        """
        Expand in place, then evict the overview when the collector advances.

        Args:
            script (str): Production browser resource being executed.
            *args (object): Script arguments, including the scroll direction.

        Returns:
            bool: Whether the mock scroller has reached the bottom.
        """
        nonlocal phase

        if script == scripts.CLICK_ELEMENT:
            phase = "expanded"
        elif script == scripts.SCROLL_PROFILE_CONTENT and args == ("next",):
            assert "expanded" in reads, "Expanded About must be read before the first scroll"
            phase = "bottom"

        return True

    driver.execute_script.side_effect = execute
    monkeypatch.setattr("resumeme.linkedin.capture.profile.wait_for_content", settle)
    profile = parse_profile(merge_profile_html(_expand(driver, Capture(max_scrolls=8))), "example-person")
    assert [section.key for section in profile.sections] == ["about"]
    assert profile.sections[0].entries[0].title == "Complete overview with expanded text."
