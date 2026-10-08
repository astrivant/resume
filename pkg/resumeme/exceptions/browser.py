"""
Keep browser failures compatible with existing startup, Selenium, and retry handlers.
"""

from __future__ import annotations

from selenium.common.exceptions import NoSuchElementException, NoSuchWindowException, TimeoutException

from resumeme.exceptions.base import ResumemeError

__all__ = [
    "BrowserElementError",
    "BrowserError",
    "BrowserLaunchError",
    "BrowserTimeoutError",
    "BrowserWaitError",
    "BrowserWindowError",
]


class BrowserError(ResumemeError, ValueError):
    """
    Reject unexpected LinkedIn state, authentication inputs, or unsafe profile updates.
    """


class BrowserLaunchError(ResumemeError, RuntimeError):
    """
    Report a browser application that failed to launch.
    """


class BrowserTimeoutError(ResumemeError, TimeoutError):
    """
    Report a local browser automation endpoint that did not become ready.
    """


class BrowserElementError(ResumemeError, NoSuchElementException):
    """
    Signal a missing browser element using Selenium's existing wait and retry contract.
    """


class BrowserWindowError(ResumemeError, NoSuchWindowException):
    """
    Signal a closed capture window using Selenium's existing cleanup and CLI contract.
    """


class BrowserWaitError(ResumemeError, TimeoutException):
    """
    Request another state observation through Selenium's existing timeout retry contract.
    """
