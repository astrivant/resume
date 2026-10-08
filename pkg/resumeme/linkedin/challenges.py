"""
Classify visible LinkedIn verification prompts without collecting or logging their private contents.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal

from attrs import frozen
from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException
from selenium.webdriver.common.by import By

if TYPE_CHECKING:
    from selenium.webdriver.remote.webdriver import WebDriver

__all__ = ["ChallengeObservation", "LoginChallenge", "login_challenge", "observe_challenge"]

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


@frozen
class ChallengeObservation:
    """
    Retain only allowlisted evidence and counts from a private authentication page.

    Attributes:
        kind (LoginChallenge): Recognized challenge category.
        evidence (str): Static detector name, never page text or a selector extracted from the page.
        visible_inputs (int): Count of displayed input controls.
        visible_frames (int): Count of displayed frames, useful for identifying embedded prompts.
        readable (bool): Whether the rendered page was available during this observation.
    """

    kind: LoginChallenge = "unknown"
    evidence: str = "none"
    visible_inputs: int = 0
    visible_frames: int = 0
    readable: bool = False

    def summary(self) -> str:
        """
        Format safe diagnostics for default-level failures without exporting page contents.

        Returns:
            str: Classification, detector name, visibility counts, and observation availability.
        """
        return (
            f"kind={self.kind}, evidence={self.evidence}, readable={str(self.readable).lower()}, "
            f"visible_inputs={self.visible_inputs}, visible_frames={self.visible_frames}"
        )


def login_challenge(driver: WebDriver) -> LoginChallenge:
    """
    Identify app approval separately from code entry, CAPTCHA, and ended approval requests.

    Args:
        driver (WebDriver): Browser already verified by the caller to be on a LinkedIn challenge route.

    Returns:
        LoginChallenge: Recognized visible prompt, or unknown when no supported evidence is present.

    """
    return observe_challenge(driver).kind


def observe_challenge(driver: WebDriver) -> ChallengeObservation:
    """
    Classify visible verification evidence and retain safe diagnostics even while the page is changing.

    Args:
        driver (WebDriver): Browser already verified by the caller to be on a LinkedIn challenge route.

    Returns:
        ChallengeObservation: A recognized prompt or an unknown observation without any raw account data.
    """
    inputs = frames = 0

    # Only counts and fixed detector names leave this function; input values, text, URLs, and cookies are never retained.
    try:
        inputs = sum(control.is_displayed() for control in driver.find_elements(By.CSS_SELECTOR, "input"))
        frames = sum(frame.is_displayed() for frame in driver.find_elements(By.CSS_SELECTOR, "iframe"))

        if any(control.is_displayed() for control in driver.find_elements(By.CSS_SELECTOR, _CODE_INPUTS)):
            return ChallengeObservation("mfa", "code_input", inputs, frames, True)

        if any(frame.is_displayed() for frame in driver.find_elements(By.CSS_SELECTOR, _CAPTCHA)):
            return ChallengeObservation("captcha", "captcha_control", inputs, frames, True)

        text = " ".join(driver.find_element(By.TAG_NAME, "body").text.casefold().replace("\u2019", "'").split())
    except (NoSuchElementException, StaleElementReferenceException):
        return ChallengeObservation(visible_inputs=inputs, visible_frames=frames)

    # Visible code entry wins over alternative app links; unrecognized wording receives the bounded fallback wait.
    if _CODE_TEXT.search(text):
        return ChallengeObservation("mfa", "code_prompt", inputs, frames, True)

    if re.search(r"\b(?:complete|solve)\b.{0,40}\bcaptcha\b|\b(?:verify|prove) (?:that )?you(?:'re| are) (?:a )?human\b", text):
        return ChallengeObservation("captcha", "captcha_prompt", inputs, frames, True)

    if _DENIED_TEXT.search(text):
        return ChallengeObservation("denied", "denied_prompt", inputs, frames, True)

    if _EXPIRED_TEXT.search(text):
        return ChallengeObservation("expired", "expired_prompt", inputs, frames, True)

    if _APP_TEXT.search(text):
        return ChallengeObservation("approval", "app_prompt", inputs, frames, True)

    return ChallengeObservation(visible_inputs=inputs, visible_frames=frames, readable=True)
