"""
Inspect and manage saved LinkedIn resume entries.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from resumeme.exceptions import BrowserError, BrowserWaitError
from resumeme.linkedin import resume_settings
from resumeme.linkedin.retrying import retry_selenium

if TYPE_CHECKING:
    from typing import Literal

    from selenium.webdriver.remote.webdriver import WebDriver
    from selenium.webdriver.remote.webelement import WebElement

    from resumeme.config import Config

_LOGGER = logging.getLogger(__name__)


def _saved_resume_names(driver: WebDriver) -> set[str]:
    """
    Read visible PDF filenames from the saved-resume list, excluding notices and dialogs.

    Args:
        driver (WebDriver): Browser displaying LinkedIn's application settings.

    Returns:
        set[str]: Distinct visible filenames that can be managed from this page.
    """
    if any(item.is_displayed() for item in driver.find_elements(By.CSS_SELECTOR, resume_settings._LOADING_QUERY)):
        return set()

    selector = (
        "//*[self::main or @role='main']//*[contains(translate(normalize-space(.), "
        "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '.pdf') "
        "and not(self::input) and not(ancestor-or-self::*[@role='alert' or @role='status' or @role='dialog' or self::dialog])]"
    )
    names = set()

    for element in driver.find_elements(By.XPATH, selector):
        if not element.is_displayed():
            continue

        name = " ".join(element.text.split())

        # Preserve unusual Unicode and punctuation in names rather than overlooking a file during replacement.
        if name.casefold().endswith(".pdf") and len(name) <= 255:
            names.add(name)

    return names


def _xpath_literal(value: str) -> str:
    """
    Encode a visible filename as an XPath string literal, including apostrophes.

    Args:
        value (str): Text to compare in a LinkedIn page selector.

    Returns:
        str: XPath literal expression preserving the exact input string.
    """
    if "'" not in value:
        return f"'{value}'"

    if '"' not in value:
        return f'"{value}"'

    pieces = value.split("'")
    return "concat(" + ', "\'", '.join(f"'{piece}'" for piece in pieces) + ")"


def _action_name(element: WebElement) -> str:
    """
    Read the accessible name used to distinguish a resume menu from unrelated controls.

    Args:
        element (WebElement): Candidate button, link, or role button.

    Returns:
        str: Normalized visible and accessible label.
    """
    values = [element.get_attribute("aria-label"), element.get_attribute("title"), element.text]
    return " ".join(" ".join(value.split()) for value in values if value).casefold()


def _resume_action(driver: WebDriver, filename: str, names: set[str]) -> tuple[WebElement, bool]:
    """
    Bind one overflow or delete control to the row containing exactly one saved resume.

    Args:
        driver (WebDriver): Browser displaying LinkedIn's application settings.
        filename (str): Exact saved resume that should be removed.
        names (set[str]): All visible saved resume filenames used to reject page-level controls.

    Returns:
        tuple[WebElement, bool]: Control and whether it opens an overflow menu.

    Raises:
        BrowserError: No unique filename row or delete control can be identified safely.
    """
    literal = _xpath_literal(filename)
    stem_literal = _xpath_literal(filename.removesuffix(".pdf"))
    predicate = f"normalize-space(.)={literal} or normalize-space(.)={stem_literal}"
    selector = (
        f"//*[self::main or @role='main']//*[({predicate}) and not(self::input) "
        "and not(ancestor-or-self::*[@role='alert' or @role='status' or @role='dialog' or self::dialog])]"
    )
    labels = [element for element in driver.find_elements(By.XPATH, selector) if element.is_displayed()]

    if not labels:
        raise BrowserWaitError(f"LinkedIn no longer shows the saved resume {filename}.")

    other_names = {name.casefold() for name in names if name != filename}
    actions: dict[tuple[str, bool], tuple[WebElement, bool]] = {}

    # Climb from the exact filename until a small containing row has one relevant action.
    for label in labels:
        ancestor = label

        for _ in range(8):
            ancestor = ancestor.find_element(By.XPATH, "..")
            row_text = " ".join(ancestor.text.split()).casefold()

            if filename.casefold() not in row_text or any(name in row_text for name in other_names):
                continue

            candidates = []

            for control in ancestor.find_elements(By.CSS_SELECTOR, "button, [role='button'], a"):
                if not control.is_displayed() or not control.is_enabled():
                    continue

                name = _action_name(control)

                if re.search(r"\b(delete|remove)\b", name):
                    candidates.append((control, False))
                elif re.search(r"\b(more|option|options|action|actions)\b", name):
                    candidates.append((control, True))

            if len(candidates) > 1:
                raise BrowserError(f"LinkedIn shows multiple remove controls for {filename}; no resume was deleted.")

            if candidates:
                control, opens_menu = candidates[0]
                actions[(control.id, opens_menu)] = (control, opens_menu)
                break

    if len(actions) != 1:
        raise BrowserError(
            f"Could not identify one LinkedIn delete menu for {filename}. The new resume is saved; no older resume was deleted."
        )

    return next(iter(actions.values()))


def _delete_menu_item(driver: WebDriver) -> WebElement | Literal[False]:
    """
    Find the Delete command in LinkedIn's opened resume menu.

    Args:
        driver (WebDriver): Browser after opening one saved resume's action menu.

    Returns:
        WebElement | Literal[False]: Unique visible delete command, or False while the menu opens.

    Raises:
        BrowserError: Multiple delete commands are visible.
    """
    selector = "[role='menu'] button, [role='menu'] [role='menuitem'], [role='menuitem'], [role='menu'] a"
    matches = [
        element
        for element in driver.find_elements(By.CSS_SELECTOR, selector)
        if element.is_displayed() and re.search(r"\b(delete|remove)\b", _action_name(element))
    ]

    if len(matches) > 1:
        raise BrowserError("LinkedIn shows multiple delete menu items; no saved resume was deleted.")

    return matches[0] if matches else False


def _delete_confirmation(driver: WebDriver) -> WebElement | Literal[False]:
    """
    Identify an explicit Delete confirmation without matching unrelated page controls.

    Args:
        driver (WebDriver): Browser after selecting Delete from a resume menu.

    Returns:
        WebElement | Literal[False]: Unique delete confirmation, or False when LinkedIn deletes immediately.

    Raises:
        BrowserError: A confirmation dialog is ambiguous or offers no explicit delete action.
    """
    dialogs = [dialog for dialog in driver.find_elements(By.CSS_SELECTOR, "[role='dialog'], dialog[open]") if dialog.is_displayed()]

    if not dialogs:
        return False

    if len(dialogs) > 1:
        raise BrowserError("LinkedIn shows multiple confirmation dialogs; no saved resume was deleted.")

    controls = [
        element
        for element in dialogs[0].find_elements(By.CSS_SELECTOR, "button, [role='button'], [role='menuitem']")
        if element.is_displayed() and re.search(r"\b(delete|remove)\b", _action_name(element))
    ]

    if len(controls) != 1:
        raise BrowserError("LinkedIn's resume deletion confirmation is ambiguous; no saved resume was deleted.")

    return controls[0]


def _delete_saved_resume(driver: WebDriver, config: Config, filename: str) -> None:
    """
    Delete one older saved resume, then confirm its absence from freshly loaded settings.

    Args:
        driver (WebDriver): Authenticated browser that owns the LinkedIn profile.
        config (Config): Bounded browser retry settings.
        filename (str): Saved resume selected for deletion; the new release PDF is never passed here.

    Returns:
        None: The named saved resume is confirmed absent.

    Raises:
        BrowserError: The delete action cannot be safely bound or LinkedIn does not confirm removal.
    """
    policy = config.capture
    retry_selenium(lambda: resume_settings._settings(driver, config), policy)
    names = retry_selenium(lambda: _saved_resume_names(driver), policy)

    if filename not in names:
        return

    control, opens_menu = retry_selenium(lambda: _resume_action(driver, filename, names), policy)

    # Click each destructive control once. A lost response is reconciled by a fresh read below.
    try:
        control.click()

        if opens_menu:
            item = WebDriverWait(driver, policy.page_timeout_seconds).until(
                _delete_menu_item,
                message="LinkedIn did not expose Delete for this saved resume.",
            )
            item.click()

        confirmation = _delete_confirmation(driver)

        if confirmation:
            confirmation.click()
    except WebDriverException:
        _LOGGER.warning("LinkedIn resume deletion response was uncertain; checking saved resumes without clicking again")

    def confirm_deleted() -> None:
        """
        Verify a deletion after reloading server-backed application settings.

        Returns:
            None: LinkedIn no longer lists the selected filename.

        Raises:
            BrowserWaitError: LinkedIn still lists the selected resume.
        """
        resume_settings._settings(driver, config)

        if filename in _saved_resume_names(driver):
            raise BrowserWaitError(f"LinkedIn still lists the saved resume {filename}.")

    try:
        retry_selenium(confirm_deleted, policy)
    except WebDriverException as error:
        raise BrowserError(
            f"Could not confirm removal of {filename}. The new resume remains saved; inspect LinkedIn's resume list before retrying."
        ) from error

    _LOGGER.info("Removed an older LinkedIn saved resume")


def _replace_existing_resumes(driver: WebDriver, config: Config, keep_filename: str) -> None:
    """
    Remove every other saved resume after the new release PDF has been confirmed.

    Args:
        driver (WebDriver): Authenticated browser that owns the LinkedIn profile.
        config (Config): Bounded browser retry settings.
        keep_filename (str): Exact newly published PDF to preserve.

    Returns:
        None: The saved-resume list contains no other files.

    Raises:
        BrowserError: A saved file cannot be safely identified or removed.
    """
    policy = config.capture
    retry_selenium(lambda: resume_settings._settings(driver, config), policy)
    names = retry_selenium(lambda: _saved_resume_names(driver), policy)

    # Never delete prior files unless the verified current release is visible in the same saved-resume list.
    if keep_filename not in names:
        raise BrowserError("The new release PDF is not visible in LinkedIn's saved-resume list; no previous resume was deleted.")

    # LinkedIn currently allows only a few saved resumes; this bound also prevents a page that keeps changing from looping forever.
    for _ in range(max(1, len(names) + 1)):
        older = sorted(names - {keep_filename})

        if not older:
            _LOGGER.info("LinkedIn saved resumes now contain only the current release PDF")
            return

        _delete_saved_resume(driver, config, older[0])
        retry_selenium(lambda: resume_settings._settings(driver, config), policy)
        names = retry_selenium(lambda: _saved_resume_names(driver), policy)

    if names - {keep_filename}:
        raise BrowserError("LinkedIn's saved-resume list kept changing; older resumes may remain. Inspect it before retrying.")
