"""
Collect LinkedIn profile sections through the configured browser session.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from attrs import evolve
from bs4 import BeautifulSoup
from selenium.common.exceptions import StaleElementReferenceException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from resumeme.compiler.asts.parsing import detail_links, merge_profile_html, parse_contact, parse_detail, parse_profile
from resumeme.compiler.asts.profile import save_profile
from resumeme.compiler.asts.sections import section_key
from resumeme.exceptions import BrowserElementError, BrowserError, BrowserTimeoutError
from resumeme.linkedin.browser import auth as browser_auth
from resumeme.linkedin.browser import runtime as browser_runtime
from resumeme.linkedin.browser import scripts as browser_scripts
from resumeme.linkedin.capture.capacity import resize_capture_plan
from resumeme.linkedin.capture.refinement import refine_capture_plan
from resumeme.linkedin.capture.shards import CaptureRoute, CaptureShard, assign_routes, make_capture_plan
from resumeme.linkedin.capture.timings import apply_timings, read_timings
from resumeme.linkedin.capture.viewport import wait_for_content
from resumeme.linkedin.credentials import login_credentials
from resumeme.linkedin.media import cache_media
from resumeme.linkedin.retrying import retry_selenium

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from typing import Literal

    from selenium.webdriver.remote.webdriver import WebDriver
    from selenium.webdriver.remote.webelement import WebElement

    from resumeme.compiler.asts.profile import Entry, Profile, Section
    from resumeme.config import Capture, Config
    from resumeme.linkedin.capture.shards import CapturePlan

__all__ = ["capture_profile", "capture_profile_shard", "prepare_capture_plan"]
_LOGGER = logging.getLogger(__name__)

# Publicly consumed internal names remain available through this module for the capture workflow and existing integrations.
_state_root = browser_runtime._state_root
_browser = browser_runtime._browser
_navigate = browser_runtime._navigate
_text_changed = browser_runtime._text_changed
_login = browser_auth._login
_wait_for_login = browser_auth._wait_for_login
_authenticated = browser_auth._authenticated
_login_page = browser_auth._login_page
_headless_login_ready = browser_auth._headless_login_ready
_login_form = browser_auth._login_form


def _expand(driver: WebDriver, settings: Capture) -> list[str]:
    """
    Expand text and lazy lists until the document settles or an explicit bound fails.

    Args:
        driver (WebDriver): Authenticated browser on a profile or detail page.
        settings (Capture): Bounded wait and scrolling settings.

    Returns:
        list[str]: DOM snapshots retaining content evicted during virtualized scrolling.

    Raises:
        BrowserError: A configured expansion bound prevents a complete capture.
        BrowserTimeoutError: LinkedIn content did not settle within the scrolling limit.
    """

    # Always start at the top: later snapshots may evict earlier cards from LinkedIn's virtualized DOM.
    WebDriverWait(driver, settings.page_timeout_seconds).until(lambda page: page.find_elements(By.CSS_SELECTOR, "main"))
    driver.execute_script(browser_scripts.SCROLL_PROFILE_CONTENT, "top")
    previous = ""
    settled = 0
    snapshots: list[str] = []

    for _ in range(settings.max_scrolls):
        # A profile heading alone is not ready: moving first can permanently skip still-loading About/Featured cards.
        wait_for_content(driver, settings)

        # Capture the current viewport before expanding or scrolling can replace its content.
        snapshots.append(driver.page_source)
        buttons = driver.find_elements(
            By.CSS_SELECTOR,
            "main button.inline-show-more-text__button, main button.pvs-list__see-more-button, "
            "main button[aria-label='Show more'], main button[aria-label='See more']",
        )

        # Expand visible text in place; stale buttons are expected when LinkedIn rerenders a card during the loop.
        clicked = False

        for button in buttons:
            try:
                if button.is_displayed() and button.is_enabled() and "less" not in button.text.casefold():
                    driver.execute_script(browser_scripts.CLICK_ELEMENT, button)
                    clicked = True
            except StaleElementReferenceException:
                # Restart this viewport with fresh DOM so a rerender cannot make the capture look complete prematurely.
                clicked = True
                break

        if clicked:
            # Re-read the expanded viewport before scrolling can evict the content we just requested.
            settled = 0
            continue

        at_bottom: object = driver.execute_script(browser_scripts.SCROLL_PROFILE_CONTENT, "next")
        current = driver.find_element(By.CSS_SELECTOR, "main").text
        _LOGGER.debug(
            "Expanding profile content",
            extra={"capture.snapshots": len(snapshots), "capture.at_bottom": at_bottom is True, "capture.expanded": clicked},
        )

        # Require several quiet bottom-of-page observations so a temporary loading gap is not mistaken for completion.
        if at_bottom is True and current == previous and not clicked:
            settled += 1

            if settled >= 3:
                snapshots.append(driver.page_source)
                return snapshots
        else:
            settled = 0

        previous = current

    raise BrowserTimeoutError("Capture reached max_scrolls before the page settled; raise the limit and retry.")


def _primary_content(driver: WebDriver) -> WebElement:
    """
    Select profile content without including sibling sidebar forms.

    Args:
        driver (WebDriver): Browser displaying a profile or detail page.

    Returns:
        WebElement: Primary content section, or main for the older layout.
    """
    primary = driver.find_elements(By.CSS_SELECTOR, 'main section[aria-label="Primary content"]')
    return primary[0] if primary else driver.find_element(By.CSS_SELECTOR, "main")


def _detail_tabs(driver: WebDriver, scope: WebElement | None = None) -> dict[str, WebElement]:
    """
    Find visible content tabs while excluding sidebar forms and footer controls.

    Args:
        driver (WebDriver): Browser on a dedicated profile section page.
        scope (WebElement | None): One profile card for inline tabs, or None for the detail page's primary content.

    Returns:
        dict[str, WebElement]: Visible tab labels mapped to their interactive elements.
    """

    # Scope tab discovery to profile content so unrelated sidebar forms do not become capture targets.
    if scope is None:
        scope = _primary_content(driver)
    return {
        label: element
        for element in scope.find_elements(By.CSS_SELECTOR, "label[for], [role='tab']")
        if element.is_displayed() and (label := element.text.strip())
    }


def _tab_selected(driver: WebDriver, tab: WebElement) -> bool:
    """
    Read the selected state from an ARIA tab or the input associated with a label.

    Args:
        driver (WebDriver): Browser owning the tab and its associated input.
        tab (WebElement): Freshly acquired tab control.

    Returns:
        bool: Whether this tab is already active, including labels whose input is visually hidden.
    """
    if tab.get_attribute("aria-selected") == "true" or tab.get_attribute("aria-checked") == "true":
        return True

    # LinkedIn's newer layout uses labels and hidden inputs instead of role=tab controls.
    identifier = tab.get_attribute("for")
    return bool(identifier and any(control.is_selected() for control in driver.find_elements(By.ID, identifier)))


def _select_tab(driver: WebDriver, label: str, scope: Callable[[], WebElement], settings: Capture) -> None:
    """
    Activate a tab without assuming the first listed tab is currently selected.

    Args:
        driver (WebDriver): Browser displaying profile content.
        label (str): Visible tab label discovered within the target section.
        scope (Callable[[], WebElement]): Reacquires the current content container after DOM replacement.
        settings (Capture): Timeout for tab activation.

    Returns:
        None: The tab was already active or its content changed; expansion still waits for loading to settle.

    Raises:
        BrowserElementError: A discovered tab disappeared before it could be collected.
        TimeoutException: Rendered content does not acknowledge the tab switch.
    """
    container = scope()
    tab = _detail_tabs(driver, container).get(label)

    if tab is None:
        raise BrowserElementError(f"The {label} tab disappeared during profile capture.")

    if _tab_selected(driver, tab):
        return

    before = container.text
    driver.execute_script(browser_scripts.SCROLL_ELEMENT_INTO_VIEW, tab)
    tab.click()

    def selected(page: WebDriver) -> bool:
        """
        Observe changed content without retaining stale DOM references.

        Args:
            page (WebDriver): Browser being polled by Selenium.

        Returns:
            bool: The target control still exists and its content acknowledges the switch.
        """
        current = scope()
        control = _detail_tabs(page, current).get(label)

        # A checkbox can update before the tab's request returns. Do not merge the previous tab's entries into the next one.
        return control is not None and current.text != before

    WebDriverWait(driver, settings.page_timeout_seconds, ignored_exceptions=(StaleElementReferenceException,)).until(selected)


def _profile_card(driver: WebDriver, key: str, settings: Capture) -> WebElement:
    """
    Find one profile card, scrolling to restore it when LinkedIn has virtualized it away.

    Args:
        driver (WebDriver): Browser on the owner profile.
        key (str): Normalized section heading to locate.
        settings (Capture): Bounds on loading and scrolling.

    Returns:
        WebElement: Current section container, excluding neighboring cards and sidebar controls.

    Raises:
        BrowserElementError: The previously observed section cannot be located within the scroll bound.
    """

    def locate(page: WebDriver) -> WebElement | Literal[False]:
        """
        Resolve a heading to its nearest section in the profile's primary content.

        Args:
            page (WebDriver): Current owner profile page.

        Returns:
            WebElement | Literal[False]: Matching card, or False until it is rendered.
        """
        content = _primary_content(page)

        for heading in content.find_elements(By.CSS_SELECTOR, "h2"):
            if section_key(heading.text) == key:
                return heading.find_element(By.XPATH, "ancestor::section[1]")

        return False

    card = locate(driver)

    if card:
        return card

    # Revisit earlier cards without reloading the page or resetting the tab selected by the caller.
    driver.execute_script(browser_scripts.SCROLL_PROFILE_CONTENT, "top")

    for _ in range(settings.max_scrolls):
        try:
            return WebDriverWait(driver, 1.5, ignored_exceptions=(StaleElementReferenceException,)).until(locate)
        except TimeoutException:
            driver.execute_script(browser_scripts.SCROLL_PROFILE_CONTENT, "next")

    raise BrowserElementError(f"The {key} profile section disappeared during tab capture.")


def _inline_section(snapshots: list[str], key: str, title: str) -> Section:
    """
    Parse the last observed version of one inline tab after expansion settles.

    Args:
        snapshots (list[str]): Rendered pages collected after selecting this tab.
        key (str): Section identifier.
        title (str): Display heading retained in the snapshot.

    Returns:
        Section: Selected tab's entries or an explicit empty state.

    Raises:
        BrowserElementError: The target card was absent from every expanded viewport.
    """

    # Earlier frames can still contain the previous tab. Prefer the last observation, not the longest card across frames.
    for html in reversed(snapshots):
        soup = BeautifulSoup(html, "html.parser")
        primary = soup.select_one('main section[aria-label="Primary content"]') or soup.select_one("main")

        if primary is None:
            continue

        for heading in primary.select("h2"):
            if section_key(heading.get_text(" ", strip=True)) == key and (card := heading.find_parent("section")) is not None:
                return parse_detail(f"<main>{card}</main>", key, title)

    raise BrowserElementError(f"No inline content found for {title} after tab expansion.")


def _inline_tabs(driver: WebDriver, username: str, section: Section, settings: Capture) -> Section:
    """
    Collect every profile-card tab when the initial view exposes no detail-page link.

    Args:
        driver (WebDriver): Authenticated browser reused for all tab selections.
        username (str): Owner slug constraining any detail links revealed by other tabs.
        section (Section): Preview whose content must be replaced only after complete collection.
        settings (Capture): Existing expansion, navigation, and pagination bounds.

    Returns:
        Section: All inline variants, or the complete dedicated section when a tab reveals a detail link.

    Raises:
        BrowserError: A tab, section, or pagination boundary cannot be fully collected.
        TimeoutException: Profile navigation or tab activation fails to settle.
    """
    _navigate(driver, f"https://www.linkedin.com/in/{username}/", settings)
    snapshots = _expand(driver, settings)
    scope = partial(_profile_card, driver, section.key, settings)
    labels = list(_detail_tabs(driver, scope()))
    entries: list[Entry] = []

    for label in labels or [""]:
        if label:
            _LOGGER.info("Capturing inline profile tab", extra={"profile.section": section.key, "profile.tab": label})
            _select_tab(driver, label, scope, settings)
            snapshots = _expand(driver, settings)

        # A different tab may reveal Show all. Its owner-scoped detail page can then exhaust every tab and page.
        route = detail_links(merge_profile_html(snapshots), username).get(section.key)

        if route:
            _LOGGER.info("Following detail page revealed by profile tab", extra={"profile.section": section.key})
            return _details(driver, route, section.key, section.title, settings)

        collected = _inline_section(snapshots, section.key, section.title)
        entries.extend(evolve(entry, title=f"{label}: {entry.title}") if label else entry for entry in collected.entries)

    return evolve(section, entries=entries)


def _details(driver: WebDriver, url: str, key: str, title: str, settings: Capture, *, tab: str | None = None) -> Section:
    """
    Follow all loaded detail pages and reject pagination that cannot be exhausted.

    Args:
        driver (WebDriver): Authenticated browser.
        url (str): Owner-scoped detail route.
        key (str): Section identifier.
        title (str): Section title.
        settings (Capture): Page and expansion limits.
        tab (str | None): Collect exactly this independently planned tab, or all tabs when absent.

    Returns:
        Section: All entries collected across detail pages.

    Raises:
        BrowserError: Pagination loops or exceeds the configured limit.
    """
    _navigate(driver, url, settings)
    WebDriverWait(driver, settings.page_timeout_seconds).until(
        lambda page: page.find_element(By.CSS_SELECTOR, "main").text.strip().casefold().startswith(title.casefold())
    )

    # These sections partition real content across tabs, such as recommendations received versus given.
    tabs = []

    if key in {"recommendations", "interests"}:
        tabs = list(_detail_tabs(driver))

    if tab is not None:
        if tab not in tabs:
            raise BrowserElementError("A planned detail tab is no longer present; rerun capture planning.")

        tabs = [tab]

    if not tabs:
        return _detail_pages(driver, key, title, settings)

    entries: list[Entry] = []

    for label in tabs:
        _LOGGER.info("Capturing detail tab", extra={"profile.section": key, "profile.tab": label})
        _select_tab(driver, label, partial(_primary_content, driver), settings)
        collected = _detail_pages(driver, key, title, settings)

        # Carry tab provenance into the portable text so the merged section remains understandable without browser state.
        entries.extend(evolve(entry, title=f"{label}: {entry.title}") for entry in collected.entries)

    return evolve(collected, entries=entries)


def _detail_pages(driver: WebDriver, key: str, title: str, settings: Capture) -> Section:
    """
    Collect the active section tab across scrolling and pagination.

    Args:
        driver (WebDriver): Browser on the selected detail tab.
        key (str): Stable section identifier.
        title (str): Display heading.
        settings (Capture): Expansion and pagination limits.

    Returns:
        Section: Entries from every loaded page of the selected tab.

    Raises:
        BrowserError: Pagination repeats content or exceeds the configured limit.
    """
    collected = parse_detail_after_expansion(driver, key, title, settings)

    # Repeated page text detects stalled or cyclic pagination without relying on changing page URLs.
    seen = {driver.find_element(By.CSS_SELECTOR, "main").text}

    for page_number in range(1, settings.max_pages_per_section + 1):
        next_buttons = driver.find_elements(By.CSS_SELECTOR, "main button[aria-label='Next'], main button.artdeco-pagination__button--next")
        next_button = next((button for button in next_buttons if button.is_displayed() and button.is_enabled()), None)

        if next_button is None:
            return collected

        # Exhaustion is a capture failure, not permission to return a silently truncated employment history.
        if page_number == settings.max_pages_per_section:
            raise BrowserError(f"Capture reached max_pages_per_section for {title}.")

        before = driver.find_element(By.CSS_SELECTOR, "main").text
        next_button.click()
        WebDriverWait(driver, settings.page_timeout_seconds).until(_text_changed(before))
        section = parse_detail_after_expansion(driver, key, title, settings)
        signature = driver.find_element(By.CSS_SELECTOR, "main").text

        if signature in seen:
            raise BrowserError(f"Pagination repeated content in {title}.")

        seen.add(signature)
        collected = evolve(collected, entries=[*collected.entries, *section.entries])

    raise BrowserError(f"Capture reached max_pages_per_section for {title}.")


def parse_detail_after_expansion(driver: WebDriver, key: str, title: str, settings: Capture) -> Section:
    """
    Wait for a detail page to finish expanding before parsing it.

    Args:
        driver (WebDriver): Browser on the target detail page.
        key (str): Section identifier.
        title (str): Section heading.
        settings (Capture): Expansion limits.

    Returns:
        Section: Parsed detail content.
    """
    snapshots = _expand(driver, settings)

    # Validate the settled page first, then recover entries that disappeared from earlier virtualized viewports.
    combined = parse_detail(snapshots[-1], key, title)
    entries: dict[tuple[str, tuple[str, ...]], Entry] = {}

    for snapshot in snapshots:
        try:
            section = parse_detail(snapshot, key, title)
        except ValueError:
            # Initial virtualized snapshots can contain only the heading; the final page must parse above.
            continue

        for entry in section.entries:
            # Merge observations of the same text while keeping newly loaded media and the largest observed endorsement count.
            identity = (entry.title, tuple(entry.paragraphs))
            previous = entries.get(identity, entry)
            entries[identity] = evolve(
                entry,
                images=list({item.url: item for item in [*previous.images, *entry.images]}.values()),
                links=list({item.url: item for item in [*previous.links, *entry.links]}.values()),
                skills=list(
                    {
                        item.name.casefold(): item
                        for item in sorted([*previous.skills, *entry.skills], key=lambda skill: skill.endorsements)
                    }.values()
                ),
            )

    return evolve(combined, entries=list(entries.values()))


def _contact(driver: WebDriver, username: str, settings: Capture) -> Section:
    """
    Open the owner's read-only contact overlay and wait for its content.

    Args:
        driver (WebDriver): Authenticated local browser.
        username (str): Configured owner slug.
        settings (Capture): Page loading and retry limits.

    Returns:
        Section: Contact information displayed by LinkedIn.
    """

    # Wait for the owner's contact dialog itself; page readiness does not mean the overlay has populated.
    _navigate(driver, f"https://www.linkedin.com/in/{username}/overlay/contact-info/", settings)
    WebDriverWait(driver, settings.page_timeout_seconds).until(
        lambda page: any(
            dialog.is_displayed() and "contact info" in dialog.text.casefold()
            for dialog in page.find_elements(By.CSS_SELECTOR, 'dialog[open], [role="dialog"]')
        )
    )
    return parse_contact(driver.page_source)


def _route_weight(section: Section | None, title: str) -> int:
    """
    Estimate route cost from overview text so larger profile sections land on separate workers.

    Args:
        section (Section | None): Overview preview for the route, when LinkedIn provides one.
        title (str): Route heading used when the preview is absent.

    Returns:
        int: Positive relative work estimate for deterministic shard balancing.
    """
    if section is None:
        return max(1, len(title) // 80 + 1)

    text_size = sum(len(entry.title) + sum(map(len, entry.paragraphs)) for entry in section.entries)
    return max(1, len(section.entries) * 2 + text_size // 500 + 1)


def prepare_capture_plan(config: Config, root: Path, *, headless: bool = False, timings_path: Path | None = None) -> CapturePlan:
    """
    Authenticate once and capture the profile overview plus owner-scoped section routes.

    Args:
        config (Config): Profile owner and browser settings.
        root (Path): Configuration directory for browser state and diagnostics.
        headless (bool): Use environment credentials without opening a desktop window.
        timings_path (Path | None): Previous measurements used for bounded tab discovery and adaptive scheduling.

    Returns:
        CapturePlan: Base profile and all detail routes assigned to six workers.

    Raises:
        BrowserError: The profile is missing, redirected, or cannot be fully expanded.
    """
    if headless:
        login_credentials(headless=True, profile=config.linkedin.username)

    username = config.linkedin.username
    _LOGGER.info("Starting LinkedIn capture plan", extra={"browser.name": config.capture.browser.title()})

    with _browser(root, config.capture, headless=headless) as driver:
        driver.set_page_load_timeout(config.capture.page_timeout_seconds)
        driver.set_window_size(1440, 1000)
        _navigate(driver, "https://www.linkedin.com/login", config.capture)
        _login(driver, config.capture, headless=headless, profile_username=config.linkedin.username)
        _navigate(driver, f"https://www.linkedin.com/in/{username}/", config.capture)

        # The overview is the sole source of identity, section order, and route ownership for all six workers.
        try:
            retry_selenium(
                lambda: WebDriverWait(driver, config.capture.page_timeout_seconds).until(
                    lambda page: page.find_elements(By.CSS_SELECTOR, "main h1, section[aria-label='Primary content'] h2")
                ),
                config.capture,
            )
        except TimeoutException as error:
            diagnostic = _state_root(root) / "capture/profile.html"
            diagnostic.write_text(driver.page_source, encoding="utf-8")
            driver.save_screenshot(str(_state_root(root) / "capture/profile.png"))
            raise BrowserTimeoutError(f"The profile heading did not load at {driver.current_url}; inspect {diagnostic}.") from error

        expected = f"/in/{username}/".casefold()

        if urlsplit(driver.current_url).path.casefold().rstrip("/") + "/" != expected:
            raise BrowserError("LinkedIn redirected away from the configured profile.")

        snapshots = retry_selenium(partial(_expand, driver, config.capture), config.capture)
        html = merge_profile_html(snapshots)
        (_state_root(root) / "capture/profile.html").write_text(html, encoding="utf-8")
        profile = parse_profile(html, username)
        detail_routes = detail_links(html, username)

        # Only routes absent from the overview are scheduled; previews without a LinkedIn detail page are already complete.
        sections = {section.key: section for section in profile.sections}
        routes: list[CaptureRoute] = []

        for key, url in detail_routes.items():
            title = sections[key].title if key in sections else key.replace("-", " ").title()
            routes.append(CaptureRoute(key, title, url, "detail", _route_weight(sections.get(key), title)))

        for section in profile.sections:
            if section.key in {"recommendations", "interests"} and section.key not in detail_routes:
                routes.append(
                    CaptureRoute(
                        section.key,
                        section.title,
                        f"https://www.linkedin.com/in/{username}/",
                        "inline",
                        _route_weight(section, section.title),
                    )
                )

        if f"/in/{username}/overlay/contact-info" in html:
            routes.append(
                CaptureRoute(
                    "contact",
                    "Contact info",
                    f"https://www.linkedin.com/in/{username}/overlay/contact-info/",
                    "contact",
                    1,
                )
            )

        plan = make_capture_plan(
            evolve(profile, captured_at=datetime.now(UTC).isoformat()),
            config.capture.browser,
            routes,
            shard_count=config.capture.sharding.initial,
        )

        if timings_path is not None:

            def discover(route: CaptureRoute) -> list[str]:
                """
                Inspect independently selectable tabs without traversing their content.

                Args:
                    route (CaptureRoute): Known owner-scoped detail section.

                Returns:
                    list[str]: Visible labels in source order.
                """
                _navigate(driver, route.url, config.capture)
                WebDriverWait(driver, config.capture.page_timeout_seconds).until(
                    lambda page: page.find_element(By.CSS_SELECTOR, "main").text.strip().casefold().startswith(route.title.casefold())
                )
                return list(_detail_tabs(driver))

            plan = apply_timings(plan, timings_path)
            plan = refine_capture_plan(
                plan, read_timings(timings_path), lambda route: retry_selenium(partial(discover, route), config.capture)
            )
            plan = apply_timings(plan, timings_path)
            plan = resize_capture_plan(plan, read_timings(timings_path), config.capture.sharding)

    return plan


def capture_profile_shard(
    config: Config,
    root: Path,
    plan: CapturePlan,
    shard_index: int,
    shard_count: int,
    *,
    headless: bool = False,
) -> CaptureShard:
    """
    Collect only the owner-scoped routes assigned to one deterministic worker.

    Args:
        config (Config): Profile and browser settings.
        root (Path): Configuration directory for temporary browser state.
        plan (CapturePlan): Validated worker plan from the bootstrap job.
        shard_index (int): One-based matrix worker index.
        shard_count (int): Matrix size, which must match the plan.
        headless (bool): Use environment credentials without opening a desktop window.

    Returns:
        CaptureShard: Complete section results owned by this worker.

    Raises:
        BrowserError: Login or assigned route collection fails.
        ValueError: The requested worker or browser does not match the plan.
    """
    if config.capture.browser != plan.browser:
        raise ValueError("Capture shard browser differs from the browser that created its session cache.")

    assignments = assign_routes(plan)

    if shard_count != plan.shard_count or shard_index not in assignments:
        raise ValueError("Capture shard index and count must match the frozen worker plan.")

    routes = assignments[shard_index]

    # Empty shards still publish an explicit result, allowing aggregation to prove all planned workers completed.
    if not routes:
        return CaptureShard(plan.capture_id, plan.browser, shard_index, shard_count, [])

    _LOGGER.info(
        "Starting LinkedIn capture shard",
        extra={"browser.name": plan.browser.title(), "capture.shard": shard_index, "capture.shard_count": shard_count},
    )
    collected: list[Section] = []
    route_seconds: dict[str, float] = {}
    worker_started = time.monotonic()

    with _browser(root, config.capture, headless=headless) as driver:
        driver.set_page_load_timeout(config.capture.page_timeout_seconds)
        driver.set_window_size(1440, 1000)
        _navigate(driver, f"https://www.linkedin.com/in/{config.linkedin.username}/", config.capture)

        # The bootstrap job owns credentials; workers verify its cached session and never receive login secrets.
        if not retry_selenium(partial(_authenticated, driver), config.capture):
            raise BrowserError("The encrypted LinkedIn session cache is no longer authenticated; rerun the capture bootstrap.")

        for route in routes:
            _LOGGER.info("Collecting assigned profile route", extra={"profile.section": route.key, "capture.shard": shard_index})

            if route.kind == "detail":
                operation = partial(_details, driver, route.url, route.key, route.title, config.capture)

                if route.tab is not None:
                    operation = partial(_details, driver, route.url, route.key, route.title, config.capture, tab=route.tab)
            elif route.kind == "inline":
                section = next((item for item in plan.profile.sections if item.key == route.key), None)

                if section is None:
                    raise BrowserError(f"The inline section {route.title} is missing from the capture plan.")

                operation = partial(_inline_tabs, driver, config.linkedin.username, section, config.capture)
            else:
                operation = partial(_contact, driver, config.linkedin.username, config.capture)

            # Measure the entire traversal and its backoffs, excluding browser startup and session authentication.
            started = time.monotonic()
            collected.append(evolve(retry_selenium(operation, config.capture), key=route.unit_key))
            route_seconds[route.unit_key] = max(time.monotonic() - started, 0.000001)
            _LOGGER.info(
                "Completed profile route",
                extra={
                    "profile.section": route.key,
                    "capture.unit": route.unit_key,
                    "capture.shard": shard_index,
                    "capture.duration_seconds": route_seconds[route.unit_key],
                },
            )

    return CaptureShard(
        plan.capture_id, plan.browser, shard_index, shard_count, collected, route_seconds, time.monotonic() - worker_started
    )


def capture_profile(config: Config, root: Path, connect_port: int | None = None, *, headless: bool = False) -> Profile:
    """
    Open the configured browser, collect the owner profile, and cache its images.

    Args:
        config (Config): Profile and capture settings.
        root (Path): Configuration directory for caches and output assets.
        connect_port (int | None): Existing local Firefox Marionette port, if explicitly requested.
        headless (bool): Use environment credentials without opening an interactive window.

    Returns:
        Profile: Captured profile without exported browser credentials.

    Raises:
        TimeoutException: A page did not load after bounded retries.
        BrowserError: The profile is missing, redirected, or cannot be fully expanded.
    """
    if headless and connect_port is not None:
        raise BrowserError("Headless capture cannot attach to an interactive browser session.")

    # Reject missing credentials or a public identifier used as a login before opening a browser.
    login_credentials(headless=headless, profile=config.linkedin.username)

    name = config.capture.browser.title()
    _LOGGER.info("Starting LinkedIn capture", extra={"browser.name": name, "browser.headless": headless})
    warnings: list[str] = []

    # Own one browser lifecycle across login, profile expansion, detail pages, and contact capture.
    with _browser(root, config.capture, connect_port, headless=headless) as driver:
        driver.set_page_load_timeout(config.capture.page_timeout_seconds)
        driver.set_window_size(1440, 1000)

        if connect_port is None:
            _navigate(driver, "https://www.linkedin.com/login", config.capture)

        _login(driver, config.capture, headless=headless, profile_username=config.linkedin.username)
        _LOGGER.info("Login detected; loading profile")
        username = config.linkedin.username
        _navigate(driver, f"https://www.linkedin.com/in/{username}/", config.capture)

        def profile_content_ready() -> None:
            """
            Wait for the requested profile's primary heading after the browser navigation.

            Returns:
                None: A profile heading is present in the current document.
            """
            WebDriverWait(
                driver,
                config.capture.page_timeout_seconds,
                ignored_exceptions=(StaleElementReferenceException,),
            ).until(lambda page: page.find_elements(By.CSS_SELECTOR, 'main h1, section[aria-label="Primary content"] h2'))

        try:
            # LinkedIn can finish navigation before hydrating the heading; retry this read on the same profile route.
            retry_selenium(profile_content_ready, config.capture)
        except TimeoutException as error:
            # Retain the actual failed page for markup/debugging work instead of reporting only a generic timeout.
            diagnostic = _state_root(root) / "capture/profile.html"
            diagnostic.write_text(driver.page_source, encoding="utf-8")
            driver.save_screenshot(str(_state_root(root) / "capture/profile.png"))
            raise BrowserTimeoutError(f"The profile heading did not load at {driver.current_url}; inspect {diagnostic}.") from error

        # A successful navigation can still land on an auth wall or another profile; bind collection to the requested owner.
        expected = f"/in/{username}/".casefold()

        if urlsplit(driver.current_url).path.casefold().rstrip("/") + "/" != expected:
            raise BrowserError("LinkedIn redirected away from the configured profile.")

        snapshots = retry_selenium(partial(_expand, driver, config.capture), config.capture)
        html = merge_profile_html(snapshots)
        (_state_root(root) / "capture/profile.html").write_text(html, encoding="utf-8")
        profile = parse_profile(html, username)
        routes = detail_links(html, username)

        # Dedicated detail pages supersede preview cards only after their full expansion and pagination succeed.
        replacements: dict[str, Section] = {}

        # Small tabbed sections may have no Show all link until another tab is selected; collect those cards directly.
        for section in profile.sections:
            if section.key in {"recommendations", "interests"} and section.key not in routes:
                _LOGGER.info("Capturing profile section inline", extra={"profile.section": section.key})

                try:
                    replacements[section.key] = retry_selenium(
                        partial(_inline_tabs, driver, username, section, config.capture), config.capture
                    )
                finally:
                    (_state_root(root) / f"capture/{section.key}.html").write_text(driver.page_source, encoding="utf-8")

        for key, url in routes.items():
            title = next((section.title for section in profile.sections if section.key == key), key.replace("-", " ").title())
            _LOGGER.info("Capturing profile section", extra={"profile.section": key})

            try:
                replacements[key] = retry_selenium(partial(_details, driver, url, key, title, config.capture), config.capture)
            finally:
                (_state_root(root) / f"capture/{key}.html").write_text(driver.page_source, encoding="utf-8")

        # Preserve profile order and append any detail-only sections discovered outside the initial cards.
        sections = [replacements.pop(section.key, section) for section in profile.sections]
        sections.extend(replacements.values())

        if f"/in/{username}/overlay/contact-info" in html:
            _LOGGER.info("Capturing contact information")
            contact = retry_selenium(partial(_contact, driver, username, config.capture), config.capture)
            sections.insert(0, contact)

        profile = evolve(profile, sections=sections, warnings=warnings, captured_at=datetime.now(UTC).isoformat())

    _LOGGER.info("Downloading profile images and linked project previews")

    # Browser access is finished; checkpoint the text before independent media downloads can fail or be interrupted.
    save_profile(
        evolve(profile, warnings=[*warnings, "Media download is not yet complete."]),
        _state_root(root) / "capture/profile.json",
    )
    return cache_media(profile, config, root)
