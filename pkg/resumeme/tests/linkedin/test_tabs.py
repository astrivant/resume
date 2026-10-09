"""
Verify complete collection of inline and dedicated profile tabs without a live account.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from selenium.common.exceptions import TimeoutException

from resumeme.compiler.asts.profile import Entry, Section
from resumeme.config import Capture, Config, LinkedIn
from resumeme.exceptions import BrowserElementError, ProfileError
from resumeme.linkedin.browser import _details, _inline_section, _inline_tabs, _profile_card, _select_tab, capture_profile

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from pytest import MonkeyPatch
    from selenium.webdriver.remote.webdriver import WebDriver
    from selenium.webdriver.remote.webelement import WebElement


def _tab(label: str, *, active: bool = False) -> MagicMock:
    """
    Model one visible ARIA tab with an explicit selected state.

    Args:
        label (str): Visible tab text.
        active (bool): Initial selected state.

    Returns:
        MagicMock: Tab whose state and click behavior can be changed by the test.
    """
    tab = MagicMock()
    tab.text = label
    tab.get_attribute.side_effect = {"aria-selected": str(active).lower()}.get
    return tab


def _card(body: str, title: str = "Interests") -> str:
    """
    Wrap tab content in a profile with neighboring content that must remain excluded.

    Args:
        body (str): Current tab's rendered HTML.
        title (str): Section heading.

    Returns:
        str: Synthetic profile DOM using the primary-content layout.
    """
    return (
        '<main><section aria-label="Primary content"><section><h1>Alex</h1></section>'
        f"<section><h2>{title}</h2>{body}</section><section><h2>Education</h2><p>Other content</p></section>"
        "</section><aside><h2>Interests</h2><p>Sidebar content</p></aside></main>"
    )


@pytest.mark.parametrize(
    "key,labels", [("interests", ["Companies", "Groups", "Newsletters", "Schools"]), ("recommendations", ["Received (2)", "Given (2)"])]
)
def test_inline_tabs_retain_every_variant(monkeypatch: MonkeyPatch, key: str, labels: list[str]) -> None:
    """
    Collect every inline tab when LinkedIn exposes no dedicated detail link.

    Args:
        monkeypatch (MonkeyPatch): Browser navigation and expansion boundaries.
        key (str): Tabbed section being captured.
        labels (list[str]): Visible controls, including counts in recommendation labels.

    Returns:
        None: Each nonempty tab survives with provenance, excluding neighboring sections and stale tab content.
    """
    driver, card = MagicMock(), MagicMock()
    card.find_elements.return_value = [_tab(label) for label in labels]
    title = key.title()
    stale = _card("<ul><li><h3>A much longer previous tab that must not win</h3></li></ul>", title)
    driver.page_source = stale
    monkeypatch.setattr("resumeme.linkedin.browser._navigate", MagicMock())
    monkeypatch.setattr("resumeme.linkedin.browser._profile_card", MagicMock(return_value=card))
    monkeypatch.setattr("resumeme.linkedin.browser._expand", lambda driver, settings: [stale, driver.page_source])

    def select(driver: WebDriver, label: str, scope: Callable[[], WebElement], settings: Capture) -> None:
        """
        Render the selected tab, with the last tab explicitly empty.

        Args:
            driver (WebDriver): Synthetic browser whose page source is replaced.
            label (str): Selected tab label.
            scope (Callable[[], WebElement]): Unused card lookup.
            settings (Capture): Unused wait bounds.

        Returns:
            None: The next expansion observes the selected variant.
        """
        body = "<div data-test-empty-state>No entries</div>" if label == labels[-1] else "<ul><li><h3>Shared name</h3></li></ul>"
        # The mock owns page_source; real WebDriver exposes it as a read-only property.
        browser.page_source = _card(body, title)

    browser = driver
    select_mock = MagicMock(side_effect=select)
    monkeypatch.setattr("resumeme.linkedin.browser._select_tab", select_mock)
    collected = _inline_tabs(driver, "alex", Section(key, title), Capture())
    assert [entry.title for entry in collected.entries] == [f"{label}: Shared name" for label in labels[:-1]]
    assert [call.args[1] for call in select_mock.call_args_list] == labels


def test_inline_tab_follows_newly_revealed_owner_route(monkeypatch: MonkeyPatch) -> None:
    """
    Prefer complete detail pagination when switching an inline tab reveals Show all.

    Args:
        monkeypatch (MonkeyPatch): Synthetic tab states and dedicated-page collector.

    Returns:
        None: A different owner's route is ignored and the later owner route replaces all previews.
    """
    driver, card = MagicMock(), MagicMock()
    card.find_elements.return_value = [_tab("Companies"), _tab("Schools")]
    preview = "<ul><li><h3>Preview</h3></li></ul>"
    wrong = _card(preview + '<a href="https://www.linkedin.com/in/someone-else/details/interests/">Show all</a>')
    url = "https://www.linkedin.com/in/alex/details/interests/?initialTabId=schools"
    revealed = _card(preview + f'<a href="{url}">Show all</a>')
    monkeypatch.setattr("resumeme.linkedin.browser._navigate", MagicMock())
    monkeypatch.setattr("resumeme.linkedin.browser._profile_card", MagicMock(return_value=card))
    monkeypatch.setattr("resumeme.linkedin.browser._select_tab", MagicMock())
    monkeypatch.setattr("resumeme.linkedin.browser._expand", MagicMock(side_effect=[[wrong], [wrong], [revealed]]))
    complete = Section("interests", "Interests", entries=[Entry(title="Complete collection")])
    details = MagicMock(return_value=complete)
    monkeypatch.setattr("resumeme.linkedin.browser._details", details)
    settings = Capture()
    assert _inline_tabs(driver, "alex", Section("interests", "Interests"), settings) == complete
    details.assert_called_once_with(driver, url, "interests", "Interests", settings)


@pytest.mark.parametrize("snapshots,error", [(["<main></main>"], BrowserElementError), ([_card("")], ProfileError)])
def test_unreadable_inline_tab_fails(snapshots: list[str], error: type[Exception]) -> None:
    """
    Preserve failure visibility when a tab disappears or its content never loads.

    Args:
        snapshots (list[str]): Missing card or bare heading without an explicit empty state.
        error (type[Exception]): Expected missing-card or parsing failure.

    Returns:
        None: Incomplete content cannot silently replace an accepted preview.
    """
    with pytest.raises(error):
        _inline_section(snapshots, "interests", "Interests")


def test_details_select_first_tab_when_initial_route_selects_last(monkeypatch: MonkeyPatch) -> None:
    """
    Read each tab under its own label when the route opens with a later tab selected.

    Args:
        monkeypatch (MonkeyPatch): Navigation and parsed detail-page boundary.

    Returns:
        None: The first tab is explicitly activated and no variant is duplicated under the wrong label.
    """
    driver, primary = MagicMock(), MagicMock()
    primary.text = "Interests\nSchools"
    tabs = [_tab("Companies"), _tab("Schools", active=True)]
    primary.find_elements.return_value = tabs
    driver.find_elements.return_value = [primary]
    driver.find_element.return_value = primary

    def activate(label: str) -> None:
        """
        Simulate the tab control updating selection and content together.

        Args:
            label (str): Tab receiving the click.

        Returns:
            None: Fresh element lookups expose the new selected state.
        """
        for tab in tabs:
            tab.get_attribute.side_effect = {"aria-selected": str(tab.text == label).lower()}.get

        primary.text = f"Interests\n{label}"

    tabs[0].click.side_effect = lambda: activate("Companies")
    tabs[1].click.side_effect = lambda: activate("Schools")
    monkeypatch.setattr("resumeme.linkedin.browser._navigate", MagicMock())
    monkeypatch.setattr(
        "resumeme.linkedin.browser._detail_pages",
        lambda driver, key, title, settings: Section(key, title, entries=[Entry(title=primary.text.splitlines()[-1])]),
    )
    result = _details(
        driver, "https://www.linkedin.com/in/alex/details/interests/?initialTabId=schools", "interests", "Interests", Capture()
    )
    assert [entry.title for entry in result.entries] == ["Companies: Companies", "Schools: Schools"]
    tabs[0].click.assert_called_once()
    tabs[1].click.assert_called_once()


def test_selected_checkbox_label_is_not_toggled_off() -> None:
    """
    Recognize LinkedIn's hidden checkbox state before clicking its visible label.

    Returns:
        None: An active label is left selected even though it has no ARIA selected attribute.
    """
    driver, card, control = MagicMock(), MagicMock(), MagicMock()
    tab = _tab("Received (2)")
    tab.get_attribute.side_effect = {"for": "received"}.get
    control.is_selected.return_value = True
    driver.find_elements.return_value = [control]
    card.find_elements.return_value = [tab]
    _select_tab(driver, tab.text, lambda: card, Capture())
    tab.click.assert_not_called()
    driver.find_elements.assert_called_once_with("id", "received")


def test_tab_selection_waits_for_content_after_selected_marker(monkeypatch: MonkeyPatch) -> None:
    """
    Keep old content out of the next tab while an asynchronous request is pending.

    Args:
        monkeypatch (MonkeyPatch): Deterministic replacement for Selenium's polling clock.

    Returns:
        None: A checked control alone cannot complete the wait before its content updates.
    """
    driver, card = MagicMock(), MagicMock()
    tab = _tab("Groups")
    card.text = "Companies content"
    card.find_elements.return_value = [tab]
    tab.click.side_effect = lambda: setattr(tab.get_attribute, "side_effect", {"aria-selected": "true"}.get)

    def poll(condition: Callable[[WebDriver], bool]) -> bool:
        """
        Observe selection before replacing the previous tab's content.

        Args:
            condition (Callable[[WebDriver], bool]): Production tab-ready condition.

        Returns:
            bool: True only after new content arrives.
        """
        assert not condition(driver)
        card.text = "Groups content"
        assert condition(driver)
        return True

    wait = MagicMock()
    wait.return_value.until.side_effect = poll
    monkeypatch.setattr("resumeme.linkedin.browser.WebDriverWait", wait)
    _select_tab(driver, "Groups", lambda: card, Capture())
    wait.return_value.until.assert_called_once()


@pytest.mark.parametrize("missing", [False, True])
def test_failed_tab_switch_is_not_accepted(missing: bool) -> None:
    """
    Reject a disappearing or unresponsive tab instead of relabeling its previous contents.

    Args:
        missing (bool): Remove the target tab, or leave it present but unable to activate.

    Returns:
        None: Both failures propagate through the existing retry contract.
    """
    driver, card = MagicMock(), MagicMock()
    card.text = "Interests\nCurrent content"
    card.find_elements.return_value = [] if missing else [_tab("Groups")]

    with pytest.raises(BrowserElementError if missing else TimeoutException):
        _select_tab(driver, "Groups", lambda: card, Capture(page_timeout_seconds=0))


def test_profile_card_recovers_after_virtualized_scroll(monkeypatch: MonkeyPatch) -> None:
    """
    Reacquire an inline section without navigating away and resetting its selected tab.

    Args:
        monkeypatch (MonkeyPatch): Primary-content lookup across virtualized viewports.

    Returns:
        None: Scrolling restores the intended card and keeps neighboring headings out of scope.
    """
    driver, primary, heading, card = MagicMock(), MagicMock(), MagicMock(), MagicMock()
    heading.text = "Interests"
    heading.find_element.return_value = card
    primary.find_elements.side_effect = [[], [heading]]
    monkeypatch.setattr("resumeme.linkedin.browser._primary_content", MagicMock(return_value=primary))
    assert _profile_card(driver, "interests", Capture()) is card
    assert driver.execute_script.call_args.args[1] == "top"
    driver.get.assert_not_called()


@pytest.mark.parametrize("dedicated", [False, True])
def test_capture_collects_hidden_tabbed_sections(tmp_path: Path, monkeypatch: MonkeyPatch, dedicated: bool) -> None:
    """
    Collect all source tabs even when their section is disabled in the PDF configuration.

    Args:
        tmp_path (Path): Isolated raw diagnostics and snapshot storage.
        monkeypatch (MonkeyPatch): Browser, tab collection, and media boundaries.
        dedicated (bool): Whether the initial profile exposes a dedicated detail route.

    Returns:
        None: Only fully collected content replaces the preview, without the old unvisited-tabs warning.
    """
    (tmp_path / ".cache/capture").mkdir(parents=True)
    session = MagicMock()
    driver = session.return_value.__enter__.return_value
    driver.current_url = "https://www.linkedin.com/in/alex/"
    link = '<a href="https://www.linkedin.com/in/alex/details/interests/">Show all</a>' if dedicated else ""
    driver.page_source = _card("<ul><li><h3>Preview</h3></li></ul>" + link)
    monkeypatch.setattr("resumeme.linkedin.browser._browser", session)
    monkeypatch.setattr("resumeme.linkedin.browser._login", MagicMock())
    monkeypatch.setattr("resumeme.linkedin.browser._navigate", MagicMock())
    monkeypatch.setattr("resumeme.linkedin.browser._expand", MagicMock(return_value=[driver.page_source]))
    monkeypatch.setattr("resumeme.linkedin.browser.cache_media", lambda profile, config, root: profile)
    complete = Section("interests", "Interests", entries=[Entry(title="Schools: Complete collection")])
    inline, detail = MagicMock(return_value=complete), MagicMock(return_value=complete)
    monkeypatch.setattr("resumeme.linkedin.browser._inline_tabs", inline)
    monkeypatch.setattr("resumeme.linkedin.browser._details", detail)
    config = Config(LinkedIn("alex"), section_order=["experience"])
    profile = capture_profile(config, tmp_path)
    assert next(section for section in profile.sections if section.key == "interests") == complete
    assert not profile.warnings
    assert inline.call_count == (0 if dedicated else 1)
    assert detail.call_count == (1 if dedicated else 0)
