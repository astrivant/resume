"""
Classify visible LinkedIn verification prompts without collecting or logging their private contents.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal

from selenium.webdriver.common.by import By

if TYPE_CHECKING:
    from selenium.webdriver.remote.webdriver import WebDriver

__all__ = ["LoginChallenge", "login_challenge"]

type LoginChallenge = Literal["approval", "mfa", "captcha", "denied", "expired", "unknown"]

_CODE_INPUTS = (
    'input[autocomplete~="one-time-code"], input[name="pin"], input[name="otp"], '
    'input[name="verificationCode"], input#input__phone_verification_pin, input#input__email_verification_pin'
)
_CAPTCHA = 'iframe[src*="recaptcha"], iframe[src*="hcaptcha"], iframe[title*="CAPTCHA"], input[name="captcha"]'
_CODE_TEXT = re.compile(
    r"\b(?:enter|type|provide)\b.{0,80}\b"
    r"(?:verification|security|authentication|authenticator|six[ -]digit|6[ -]digit|sms)\b.{0,40}\bcode\b"
    r"|\benter (?:the |a )?code (?:from|sent|we sent)\b"
)
_APP_TEXT = re.compile(
    r"\b(?:check|open) (?:your |the )?linkedin (?:mobile )?app\b"
    r"|\byes,? it's me\b"
    r"|\bsent\b.{0,60}\bnotification\b.{0,100}\b(?:linkedin app|mobile device|signed[ -]in device)\b"
)
_DENIED_TEXT = re.compile(r"\b(?:sign[ -]in|login|approval) (?:request )?(?:was |has been )?(?:denied|rejected|declined)\b")
_EXPIRED_TEXT = re.compile(r"\b(?:request|approval|notification) (?:has |is |was )?expired\b")


def login_challenge(driver: WebDriver) -> LoginChallenge:
    """
    Identify app approval separately from code entry, CAPTCHA, and ended approval requests.

    Args:
        driver (WebDriver): Browser already verified by the caller to be on a LinkedIn challenge route.

    Returns:
        LoginChallenge: Recognized visible prompt, or unknown when no supported evidence is present.

    Raises:
        NoSuchElementException: The page body is not ready for observation.
        StaleElementReferenceException: The page changed while reading its controls; the caller may poll again.
    """

    # Visible code inputs take priority over app-approval instructions or alternate-method links elsewhere on the page.
    if any(control.is_displayed() for control in driver.find_elements(By.CSS_SELECTOR, _CODE_INPUTS)):
        return "mfa"

    if any(frame.is_displayed() for frame in driver.find_elements(By.CSS_SELECTOR, _CAPTCHA)):
        return "captcha"

    # Selenium's rendered body text excludes hidden alternatives; retain only the classification outside this function.
    text = " ".join(driver.find_element(By.TAG_NAME, "body").text.casefold().replace("\u2019", "'").split())

    if _CODE_TEXT.search(text):
        return "mfa"

    if re.search(r"\b(?:complete|solve)\b.{0,40}\bcaptcha\b|\b(?:verify|prove) (?:that )?you(?:'re| are) (?:a )?human\b", text):
        return "captcha"

    if _DENIED_TEXT.search(text):
        return "denied"

    if _EXPIRED_TEXT.search(text):
        return "expired"

    return "approval" if _APP_TEXT.search(text) else "unknown"
