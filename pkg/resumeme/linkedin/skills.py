"""
Add validated skill proposals to the authenticated owner's profile without changing endorsements.
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from resumeme.codex.skills import load_skill_suggestions, normalize_skill
from resumeme.compiler.asts.profile import load_profile
from resumeme.config import project_path
from resumeme.linkedin.browser import _browser, _details, _login, _navigate
from resumeme.linkedin.retrying import retry

if TYPE_CHECKING:
    from pathlib import Path

    from selenium.webdriver.remote.webdriver import WebDriver
    from selenium.webdriver.remote.webelement import WebElement

    from resumeme.config import Config

__all__ = ["publish_skills"]

_MAX_PROFILE_SKILLS = 100
_TRANSIENT = (TimeoutException, StaleElementReferenceException, NoSuchElementException)


def _check_owner(driver: WebDriver, config: Config) -> str:
    """
    Confirm the configured profile exposes owner edit controls before visiting skill routes.

    Args:
        driver (WebDriver): Authenticated browser owned by the caller.
        config (Config): Expected LinkedIn owner and navigation policy.

    Returns:
        str: Verified owner-scoped profile path.

    Raises:
        ValueError: A redirect or missing owner controls prevents profile mutation.
    """
    path = f"/in/{config.linkedin.username}/"
    _navigate(driver, f"https://www.linkedin.com{path}", config.capture)
    WebDriverWait(driver, config.capture.page_timeout_seconds).until(
        lambda page: page.find_elements(By.CSS_SELECTOR, 'main h1, section[aria-label="Primary content"] h2')
    )
    location = urlsplit(driver.current_url)

    if location.scheme != "https" or location.hostname != "www.linkedin.com" or location.path.rstrip("/") != path.rstrip("/"):
        raise ValueError("LinkedIn redirected away from the configured owner; skills were not edited.")

    # An intro edit link also identifies owners whose Skills section is still empty.
    editable = any(
        link.is_displayed()
        and urlsplit(link.get_attribute("href") or "").hostname == "www.linkedin.com"
        and urlsplit(link.get_attribute("href") or "").path in {f"{path}edit/intro/", f"{path}edit/forms/skill/new/"}
        for link in driver.find_elements(By.CSS_SELECTOR, "a[href]")
    )

    if not editable:
        raise ValueError("No owner edit control found. Sign in as linkedin.username before publishing skills.")

    return path


def _current_skills(driver: WebDriver, config: Config) -> set[str]:
    """
    Read all current skill names using the existing bounded scrolling and pagination parser.

    Args:
        driver (WebDriver): Authenticated browser.
        config (Config): Expected owner and capture bounds.

    Returns:
        set[str]: Complete normalized skill names, including skills excluded from the PDF.

    Raises:
        ValueError: Ownership changes, navigation redirects, or complete pagination cannot be established.
    """
    path = _check_owner(driver, config) + "details/skills/"
    section = _details(driver, f"https://www.linkedin.com{path}", "skills", "Skills", config.capture)
    location = urlsplit(driver.current_url)

    if location.scheme != "https" or location.hostname != "www.linkedin.com" or location.path.rstrip("/") != path.rstrip("/"):
        raise ValueError("LinkedIn did not retain the owner's Skills page; no skills were submitted.")

    return {
        normalize_skill(name)
        for entry in section.entries
        for name in ([skill.name for skill in entry.skills] or [entry.title])
        if name.strip()
    }


def _skill_dialog(driver: WebDriver) -> WebElement:
    """
    Identify the single visible add-skill dialog before selecting any form controls.

    Args:
        driver (WebDriver): Browser displaying LinkedIn's skill form.

    Returns:
        WebElement: Unique visible dialog.

    Raises:
        NoSuchElementException: No unique dialog is available yet.
    """
    dialogs = [dialog for dialog in driver.find_elements(By.CSS_SELECTOR, '[role="dialog"]') if dialog.is_displayed()]

    if len(dialogs) != 1:
        raise NoSuchElementException("Expected one visible LinkedIn skill dialog.")

    return dialogs[0]


def _add_skill(driver: WebDriver, config: Config, name: str) -> None:
    """
    Select one exact skill suggestion and submit the owner-scoped form.

    Args:
        driver (WebDriver): Browser whose owner was checked by the current-state read.
        config (Config): Expected owner and navigation timeout.
        name (str): Validated plain-text skill name.

    Returns:
        None: Save was clicked and the dialog closed; the caller must verify persisted state.

    Raises:
        ValueError: The route or form is ambiguous, or LinkedIn offers no exact skill match.
    """
    path = f"/in/{config.linkedin.username}/edit/forms/skill/new/"
    _navigate(driver, f"https://www.linkedin.com{path}", config.capture)
    wait = WebDriverWait(driver, config.capture.page_timeout_seconds)
    dialog = wait.until(_skill_dialog)
    location = urlsplit(driver.current_url)

    if location.scheme != "https" or location.hostname != "www.linkedin.com" or location.path != path:
        raise ValueError("LinkedIn did not open the configured owner's Add skill form.")

    fields = [
        field
        for field in dialog.find_elements(By.CSS_SELECTOR, 'input[role="combobox"], input[id*="typeahead"], input[name="skill"]')
        if field.is_displayed() and field.is_enabled()
    ]

    if len(fields) != 1:
        raise ValueError("Cannot identify the skill input. Use LinkedIn's English interface and inspect the form.")

    fields[0].clear()
    fields[0].send_keys(name)

    def exact_options(page: WebDriver) -> list[WebElement]:
        """
        Reacquire exact autocomplete matches after LinkedIn replaces the suggestion list.

        Args:
            page (WebDriver): Current browser state supplied by Selenium's wait.

        Returns:
            list[WebElement]: Visible options matching the complete requested name.
        """
        return [
            option
            for option in page.find_elements(By.CSS_SELECTOR, '[role="option"]')
            if option.is_displayed() and normalize_skill(option.text) == normalize_skill(name)
        ]

    options = wait.until(exact_options)

    if len(options) != 1:
        raise ValueError(f"LinkedIn offered ambiguous matches for {name!r}; no skill was saved.")

    options[0].click()
    dialog = _skill_dialog(driver)
    buttons = [
        button
        for button in dialog.find_elements(By.CSS_SELECTOR, "button")
        if button.is_displayed() and button.is_enabled() and button.text.strip().casefold() == "save"
    ]

    if len(buttons) != 1:
        raise ValueError("Cannot identify the skill Save button; no changes were submitted.")

    # Do not select associations, endorsement controls, or suggested additional skills.
    buttons[0].click()
    wait.until(lambda page: not any(dialog.is_displayed() for dialog in page.find_elements(By.CSS_SELECTOR, '[role="dialog"]')))


def _update_skills(driver: WebDriver, config: Config, root: Path, names: list[str], *, dry_run: bool) -> list[str]:
    """
    Add missing skills with read-before-write retries and verification after every Save.

    Args:
        driver (WebDriver): Authenticated browser owned by the caller.
        config (Config): Retry policy and owner settings.
        root (Path): Root for ignored backups of the prior skill names.
        names (list[str]): Unique validated proposal names.
        dry_run (bool): Report missing names without filling or saving a form.

    Returns:
        list[str]: Names missing at the initial read, either previewed or confirmed present.

    Raises:
        ValueError: The proposal exceeds available skill slots or the live owner/form is ambiguous.
    """
    current = retry(
        lambda: _current_skills(driver, config),
        exceptions=_TRANSIENT,
        attempts=config.capture.retry_attempts,
        backoff=config.capture.retry_backoff_seconds,
        max_backoff=config.capture.retry_max_backoff_seconds,
    )
    missing = [name for name in names if normalize_skill(name) not in current]

    if len(current) + len(missing) > _MAX_PROFILE_SKILLS:
        raise ValueError("Proposed additions exceed LinkedIn's 100-skill limit. Reduce the proposal; existing skills will not be removed.")

    if dry_run or not missing:
        return missing

    # Preserve the original names locally; adding skills never deletes existing skills or their endorsements.
    directory = root / ".cache/skills"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, prefix="before-", suffix=".json", delete=False) as backup:
        json.dump(sorted(current), backup, ensure_ascii=False, indent=2)

    # Keep the preservation baseline across retries, including when Save succeeds but its response is lost.
    preserved = set(current)

    for name in missing:

        def reconcile(name: str = name) -> None:
            """
            Resolve uncertain Save outcomes from fresh server state before retrying an addition.

            Args:
                name (str): Current requested skill, bound before retry execution.

            Returns:
                None: The skill already existed or its persisted addition was verified.
            """
            observed = _current_skills(driver, config)

            if not preserved.issubset(observed):
                raise ValueError("Existing LinkedIn skills changed during publication. Stopped without removing or replacing any skill.")

            preserved.update(observed)

            if normalize_skill(name) in observed:
                return

            if len(observed) >= _MAX_PROFILE_SKILLS:
                raise ValueError("LinkedIn's skill list filled during publication. No existing skills were removed.")

            _add_skill(driver, config, name)
            confirmed = _current_skills(driver, config)

            # Never proceed after an unexpected loss; additions must preserve every previously observed skill.
            if not preserved.issubset(confirmed):
                raise ValueError("Existing LinkedIn skills changed during publication. Stopped without removing or replacing any skill.")

            preserved.update(confirmed)

            if normalize_skill(name) not in confirmed:
                raise TimeoutException("LinkedIn has not confirmed the saved skill; reread before any retry.")

        retry(
            reconcile,
            exceptions=_TRANSIENT,
            attempts=config.capture.retry_attempts,
            backoff=config.capture.retry_backoff_seconds,
            max_backoff=config.capture.retry_max_backoff_seconds,
        )

    return missing


def publish_skills(
    config: Config,
    root: Path,
    suggestions: Path,
    tag: str,
    *,
    dry_run: bool = False,
    headless: bool = False,
    connect_port: int | None = None,
) -> list[str]:
    """
    Validate a tagged proposal before optionally adding its missing skills to LinkedIn.

    Args:
        config (Config): Owner, proposal settings, explicit publish opt-in, and browser preferences.
        root (Path): Tagged repository and configuration root.
        suggestions (Path): Explicit JSON proposal file.
        tag (str): Existing tag matching the checkout and proposal.
        dry_run (bool): Preview additions without saving, even when publication is disabled.
        headless (bool): Authenticate with LinkedIn environment variables instead of interactive login.
        connect_port (int | None): Existing local Firefox Marionette port.

    Returns:
        list[str]: Newly added or proposed missing names; existing names are skipped.

    Raises:
        ValueError: Opt-in, tag, evidence, owner, or authentication requirements are not met.
    """
    if not dry_run and not config.codex.skills.publish:
        raise ValueError("Set codex.skills.publish: true to opt in to live LinkedIn skill additions.")

    profile = load_profile(project_path(root, config.output.profile), config.linkedin.username)
    proposal = load_skill_suggestions(suggestions, profile, config, root, tag)

    if not proposal.skills:
        return []

    if headless and (connect_port is not None or not all(os.environ.get(key) for key in ("LINKEDIN_USERNAME", "LINKEDIN_PASSWORD"))):
        raise ValueError("Headless skill publication requires LinkedIn login secrets and cannot attach to an interactive browser.")

    with _browser(root, config.capture, connect_port, headless=headless) as driver:
        driver.set_page_load_timeout(config.capture.page_timeout_seconds)
        driver.set_window_size(1440, 1000)

        if connect_port is None:
            _navigate(driver, "https://www.linkedin.com/login", config.capture)

        _login(driver, config.capture, headless=headless)
        return _update_skills(driver, config, root, [skill.name for skill in proposal.skills], dry_run=dry_run)
