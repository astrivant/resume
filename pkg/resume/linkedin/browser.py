"""
Collect a profile through a visible, local Firefox session owned by the user.
"""

from __future__ import annotations

import os
import signal
import socket
import sys
import time
import webbrowser
from contextlib import contextmanager
from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from attrs import evolve
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, NoSuchWindowException, StaleElementReferenceException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait

from resume.linkedin.media import cache_media
from resume.linkedin.parsing import detail_links, merge_profile_html, parse_contact, parse_detail, parse_profile
from resume.linkedin.retrying import retry
from resume.models import save_profile

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from selenium.webdriver.remote.webdriver import WebDriver
    from selenium.webdriver.remote.webelement import WebElement

    from resume.config import Capture, Config
    from resume.models import Entry, Profile, Section

__all__ = ["capture_profile"]

_SCROLL_SCRIPT = """
const main = document.querySelector('main');
let node = main?.querySelector('section[aria-label="Primary content"]') || main;
let target = document.scrollingElement;
while (node && node !== document.body) {
    if (['auto', 'scroll'].includes(getComputedStyle(node).overflowY) && node.scrollHeight > node.clientHeight) {
        target = node;
        break;
    }
    node = node.parentElement;
}
if (arguments[0] === 'top') target.scrollTop = 0;
else target.scrollTop += Math.max(target.clientHeight * 0.8, 600);
return target.scrollTop + target.clientHeight >= target.scrollHeight - 5;
"""


def _listen_port() -> int:
    """
    Reserve an available loopback port for a dedicated Firefox session.

    Returns:
        int: Port to use for Marionette.
    """
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_browser(port: int) -> None:
    """
    Wait up to thirty seconds for Firefox's local automation endpoint.

    Args:
        port (int): Loopback Marionette port.

    Returns:
        None: Firefox accepts local connections.

    Raises:
        TimeoutError: Firefox did not start successfully.
    """
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                return
        except OSError:
            time.sleep(0.25)
    raise TimeoutError("Firefox did not open its local automation port. Close any profile-error dialog and retry.")


@contextmanager
def _firefox(root: Path, connect_port: int | None) -> Iterator[WebDriver]:
    """
    Launch macOS Firefox through the Python browser client with a live profile path.

    Args:
        root (Path): Configuration directory holding the ignored local browser profile.
        connect_port (int | None): Explicit port of a manually launched local Firefox.

    Yields:
        WebDriver: Browser whose local profile survives retries without exporting credentials.
    """
    os.environ.setdefault("SE_CACHE_PATH", str(root / ".cache/selenium"))
    os.environ.setdefault("SE_AVOID_STATS", "true")
    diagnostics = root / ".cache/capture"
    diagnostics.mkdir(parents=True, exist_ok=True)
    options = Options()
    options.set_preference("intl.accept_languages", "en-US,en")
    owns_process = sys.platform == "darwin" and connect_port is None
    if sys.platform == "darwin":
        options.binary_location = "/Applications/Firefox.app/Contents/MacOS/firefox"
    profile = (root / ".cache/firefox").resolve()
    profile.mkdir(parents=True, exist_ok=True, mode=0o700)
    profile.chmod(0o700)
    if connect_port is None:
        if sys.platform == "darwin":
            connect_port = _listen_port()
            (profile / "user.js").write_text(
                f'user_pref("marionette.port", {connect_port});\n'
                'user_pref("browser.shell.checkDefaultBrowser", false);\n'
                'user_pref("signon.rememberSignons", false);\n'
                'user_pref("intl.accept_languages", "en-US,en");\n',
                encoding="utf-8",
            )
            browser = webbrowser.BackgroundBrowser(
                ["/usr/bin/open", "-na", "Firefox", "--args", "-no-remote", "--marionette", "-profile", str(profile), "%s"]
            )
            if not browser.open("https://www.linkedin.com/login"):
                raise RuntimeError("macOS could not launch Firefox.")
        else:
            options.add_argument("-profile")
            options.add_argument(str(profile))
    service_args = []
    if connect_port is not None:
        _wait_for_browser(connect_port)
        service_args = ["--connect-existing", "--marionette-port", str(connect_port)]
    service = Service(service_args=service_args, log_output=str(diagnostics / "firefox.log"))
    process_id: object = None
    try:
        with webdriver.Firefox(options=options, service=service) as driver:
            process_id = driver.capabilities.get("moz:processID")
            yield driver
    finally:
        # On macOS, deleting an attached session can leave the app alive and the profile locked.
        # Terminate only the process created for this capture, never an explicitly attached session.
        if owns_process and isinstance(process_id, int) and process_id > 0:
            try:
                os.kill(process_id, signal.SIGTERM)
            except ProcessLookupError:
                pass


def _text_changed(previous: str) -> Callable[[WebDriver], bool]:
    """
    Bind the previous text for a typed Selenium wait predicate.

    Args:
        previous (str): Content before scrolling or changing pages.

    Returns:
        Callable[[WebDriver], bool]: Predicate that detects updated main content.
    """
    return lambda page: page.find_element(By.CSS_SELECTOR, "main").text != previous


def _navigate(driver: WebDriver, url: str, settings: Capture) -> None:
    """
    Retry timed-out read-only navigations without changing authentication state.

    Args:
        driver (WebDriver): Existing authenticated browser.
        url (str): Login or owner-scoped profile URL.
        settings (Capture): Timeout and retry limits.

    Returns:
        None: Navigation completed or its final timeout propagated.
    """
    retry(
        lambda: driver.get(url),
        attempts=settings.retry_attempts,
        backoff=settings.retry_backoff_seconds,
        exceptions=(TimeoutException,),
        max_backoff=settings.retry_max_backoff_seconds,
    )


def _wait_for_login(driver: WebDriver) -> None:
    """
    Monitor the interactive browser until authentication succeeds or the user cancels.

    Args:
        driver (WebDriver): Browser owned by the capture process.

    Returns:
        None: A LinkedIn tab has an authenticated session and has left login or challenge pages.

    Raises:
        NoSuchWindowException: The user closed every browser window.
        KeyboardInterrupt: The user cancelled the capture command.
    """
    while True:
        handles = driver.window_handles
        if not handles:
            raise NoSuchWindowException("The capture window was closed during login.")
        for handle in handles:
            try:
                driver.switch_to.window(handle)
                location = urlsplit(driver.current_url)
                host = location.hostname or ""
                path = location.path.casefold().strip("/").split("/", 1)[0]
                authenticating = path in {"login", "signup", "checkpoint", "challenge", "authwall", "uas"}
                if (
                    (host == "linkedin.com" or host.endswith(".linkedin.com"))
                    and not authenticating
                    and driver.get_cookie("li_at") is not None
                ):
                    return
            except NoSuchWindowException:
                continue
        time.sleep(1)


def _expand(driver: WebDriver, settings: Capture) -> list[str]:
    """
    Expand text and lazy lists until the document settles or an explicit bound fails.

    Args:
        driver (WebDriver): Authenticated browser on a profile or detail page.
        settings (Capture): Bounded wait and scrolling settings.

    Returns:
        list[str]: DOM snapshots retaining content evicted during virtualized scrolling.

    Raises:
        ValueError: A loading or expansion bound prevents a complete capture.
    """
    WebDriverWait(driver, settings.page_timeout_seconds).until(lambda page: page.find_elements(By.CSS_SELECTOR, "main"))
    driver.execute_script(_SCROLL_SCRIPT, "top")
    previous = ""
    settled = 0
    snapshots: list[str] = []
    for _ in range(settings.max_scrolls):
        snapshots.append(driver.page_source)
        buttons = driver.find_elements(
            By.CSS_SELECTOR,
            "main button.inline-show-more-text__button, main button.pvs-list__see-more-button, "
            "main button[aria-label='Show more'], main button[aria-label='See more']",
        )
        clicked = False
        for button in buttons:
            try:
                if button.is_displayed() and button.is_enabled() and "less" not in button.text.casefold():
                    driver.execute_script("arguments[0].click()", button)
                    clicked = True
            except StaleElementReferenceException:
                continue
        at_bottom: object = driver.execute_script(_SCROLL_SCRIPT, "next")
        current = driver.find_element(By.CSS_SELECTOR, "main").text
        if at_bottom is True and current == previous and not clicked:
            settled += 1
            if settled >= 3:
                snapshots.append(driver.page_source)
                return snapshots
        else:
            settled = 0
        previous = current
        try:
            WebDriverWait(driver, 1.5, poll_frequency=0.25).until(_text_changed(current))
        except TimeoutException:
            pass
    raise ValueError("Capture reached max_scrolls before the page settled; raise the limit and retry.")


def _detail_tabs(driver: WebDriver) -> dict[str, WebElement]:
    """
    Find visible content tabs while excluding sidebar forms and footer controls.

    Args:
        driver (WebDriver): Browser on a dedicated profile section page.

    Returns:
        dict[str, WebElement]: Visible tab labels mapped to their interactive elements.
    """
    primary = driver.find_elements(By.CSS_SELECTOR, 'main section[aria-label="Primary content"]')
    scope = primary[0] if primary else driver.find_element(By.CSS_SELECTOR, "main")
    return {
        label: element
        for element in scope.find_elements(By.CSS_SELECTOR, "label[for], [role='tab']")
        if element.is_displayed() and (label := element.text.strip())
    }


def _details(driver: WebDriver, url: str, key: str, title: str, settings: Capture) -> Section:
    """
    Follow all loaded detail pages and reject pagination that cannot be exhausted.

    Args:
        driver (WebDriver): Authenticated browser.
        url (str): Owner-scoped detail route.
        key (str): Section identifier.
        title (str): Section title.
        settings (Capture): Page and expansion limits.

    Returns:
        Section: All entries collected across detail pages.

    Raises:
        ValueError: Pagination loops or exceeds the configured limit.
    """
    _navigate(driver, url, settings)
    WebDriverWait(driver, settings.page_timeout_seconds).until(
        lambda page: page.find_element(By.CSS_SELECTOR, "main").text.strip().casefold().startswith(title.casefold())
    )
    tabs = []
    if key in {"recommendations", "interests"}:
        tabs = list(_detail_tabs(driver))
    collected = _detail_pages(driver, key, title, settings)
    if not tabs:
        return collected
    entries: list[Entry] = []
    for index, label in enumerate(tabs):
        if index:
            tab = _detail_tabs(driver).get(label)
            if tab is None:
                raise NoSuchElementException(f"The {label} tab disappeared while capturing {title}.")
            before = driver.find_element(By.CSS_SELECTOR, "main").text
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'})", tab)
            tab.click()
            WebDriverWait(driver, settings.page_timeout_seconds).until(_text_changed(before))
            collected = _detail_pages(driver, key, title, settings)
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
        ValueError: Pagination repeats content or exceeds the configured limit.
    """
    collected = parse_detail_after_expansion(driver, key, title, settings)
    seen = {driver.find_element(By.CSS_SELECTOR, "main").text}
    for page_number in range(1, settings.max_pages_per_section + 1):
        next_buttons = driver.find_elements(By.CSS_SELECTOR, "main button[aria-label='Next'], main button.artdeco-pagination__button--next")
        next_button = next((button for button in next_buttons if button.is_displayed() and button.is_enabled()), None)
        if next_button is None:
            return collected
        if page_number == settings.max_pages_per_section:
            raise ValueError(f"Capture reached max_pages_per_section for {title}.")
        before = driver.find_element(By.CSS_SELECTOR, "main").text
        next_button.click()
        WebDriverWait(driver, settings.page_timeout_seconds).until(_text_changed(before))
        section = parse_detail_after_expansion(driver, key, title, settings)
        signature = driver.find_element(By.CSS_SELECTOR, "main").text
        if signature in seen:
            raise ValueError(f"Pagination repeated content in {title}.")
        seen.add(signature)
        collected = evolve(collected, entries=[*collected.entries, *section.entries])
    raise ValueError(f"Capture reached max_pages_per_section for {title}.")


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
    combined = parse_detail(snapshots[-1], key, title)
    entries: dict[tuple[str, tuple[str, ...]], Entry] = {}
    for snapshot in snapshots:
        try:
            section = parse_detail(snapshot, key, title)
        except ValueError:
            # Initial virtualized snapshots can contain only the heading; the final page must parse above.
            continue
        for entry in section.entries:
            identity = (entry.title, tuple(entry.paragraphs))
            previous = entries.get(identity, entry)
            entries[identity] = evolve(
                entry,
                images=list({item.url: item for item in [*previous.images, *entry.images]}.values()),
                links=list({item.url: item for item in [*previous.links, *entry.links]}.values()),
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
    _navigate(driver, f"https://www.linkedin.com/in/{username}/overlay/contact-info/", settings)
    WebDriverWait(driver, settings.page_timeout_seconds).until(
        lambda page: any(
            dialog.is_displayed() and "contact info" in dialog.text.casefold()
            for dialog in page.find_elements(By.CSS_SELECTOR, 'dialog[open], [role="dialog"]')
        )
    )
    return parse_contact(driver.page_source)


def capture_profile(config: Config, root: Path, connect_port: int | None = None) -> Profile:
    """
    Open Firefox for manual login, collect the owner profile, and cache its images.

    Args:
        config (Config): Profile and capture settings.
        root (Path): Configuration directory for caches and output assets.
        connect_port (int | None): Existing local Firefox Marionette port, if explicitly requested.

    Returns:
        Profile: Captured profile without exported browser credentials.

    Raises:
        TimeoutException: A page did not load after bounded retries.
        ValueError: The profile is missing, redirected, or cannot be fully expanded.
    """
    print("Opening Firefox. Sign in to LinkedIn there; capture starts after login.", flush=True)
    warnings: list[str] = []
    with _firefox(root, connect_port) as driver:
        driver.set_page_load_timeout(config.capture.page_timeout_seconds)
        driver.set_window_size(1440, 1000)
        if connect_port is None:
            _navigate(driver, "https://www.linkedin.com/login", config.capture)
        _wait_for_login(driver)
        print("Login detected. Loading your profile…", flush=True)
        username = config.linkedin.username
        _navigate(driver, f"https://www.linkedin.com/in/{username}/", config.capture)
        try:
            WebDriverWait(driver, config.capture.page_timeout_seconds).until(
                lambda page: page.find_elements(By.CSS_SELECTOR, 'main h1, section[aria-label="Primary content"] h2')
            )
        except TimeoutException as error:
            diagnostic = root / ".cache/capture/profile.html"
            diagnostic.write_text(driver.page_source, encoding="utf-8")
            driver.save_screenshot(str(root / ".cache/capture/profile.png"))
            raise ValueError(f"The profile heading did not load at {driver.current_url}; inspect {diagnostic}.") from error
        expected = f"/in/{username}/".casefold()
        if urlsplit(driver.current_url).path.casefold().rstrip("/") + "/" != expected:
            raise ValueError("LinkedIn redirected away from the configured profile.")
        snapshots = retry(
            partial(_expand, driver, config.capture),
            attempts=config.capture.retry_attempts,
            backoff=config.capture.retry_backoff_seconds,
            max_backoff=config.capture.retry_max_backoff_seconds,
            exceptions=(NoSuchElementException, StaleElementReferenceException, TimeoutException),
        )
        html = merge_profile_html(snapshots)
        (root / ".cache/capture/profile.html").write_text(html, encoding="utf-8")
        profile = parse_profile(html, username)
        routes = detail_links(html, username)
        replacements: dict[str, Section] = {}
        for key, url in routes.items():
            title = next((section.title for section in profile.sections if section.key == key), key.replace("-", " ").title())
            print(f"Capturing {title}…", flush=True)
            try:
                replacements[key] = retry(
                    partial(_details, driver, url, key, title, config.capture),
                    attempts=config.capture.retry_attempts,
                    backoff=config.capture.retry_backoff_seconds,
                    max_backoff=config.capture.retry_max_backoff_seconds,
                    exceptions=(TimeoutException, StaleElementReferenceException, NoSuchElementException),
                )
            finally:
                (root / f".cache/capture/{key}.html").write_text(driver.page_source, encoding="utf-8")
        sections = [replacements.pop(section.key, section) for section in profile.sections]
        sections.extend(replacements.values())
        # Tabs can contain additional content that a single view does not expose.
        if any(section.key in {"recommendations", "interests"} and section.key not in routes for section in sections):
            warnings.append("Profile contains tabbed content; verify all tab variants are represented before accepting the snapshot.")
        if f"/in/{username}/overlay/contact-info" in html:
            print("Capturing Contact info…", flush=True)
            contact = retry(
                partial(_contact, driver, username, config.capture),
                attempts=config.capture.retry_attempts,
                backoff=config.capture.retry_backoff_seconds,
                max_backoff=config.capture.retry_max_backoff_seconds,
                exceptions=(TimeoutException, StaleElementReferenceException, NoSuchElementException),
            )
            sections.insert(0, contact)
        profile = evolve(profile, sections=sections, warnings=warnings, captured_at=datetime.now(UTC).isoformat())
    print("Downloading profile images and linked project previews…", flush=True)
    save_profile(
        evolve(profile, warnings=[*warnings, "Media download is not yet complete."]),
        root / ".cache/capture/profile.json",
    )
    return cache_media(profile, config, root)
