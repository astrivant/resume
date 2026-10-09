"""
Retry transient operations with explicit bounds and injectable waiting.
"""

from __future__ import annotations

import logging
import signal
import time
from typing import TYPE_CHECKING, TypeVar

import requests
from selenium.common.exceptions import (
    InvalidArgumentException,
    InvalidSelectorException,
    InvalidSessionIdException,
    NoSuchWindowException,
    UnexpectedAlertPresentException,
    WebDriverException,
)

from resumeme.exceptions import BrowserTimeoutError, ConfigurationError, ResumeUploadConfirmationError

if TYPE_CHECKING:
    from collections.abc import Callable

    from resumeme.config import Capture

__all__ = [
    "is_retryable_linkedin_error",
    "is_retryable_linkedin_exit_status",
    "is_retryable_selenium_error",
    "retry",
    "retry_selenium",
]
_T = TypeVar("_T")
_LOGGER = logging.getLogger(__name__)
_NON_RETRYABLE_SELENIUM_ERRORS = (
    InvalidArgumentException,
    InvalidSelectorException,
    InvalidSessionIdException,
    NoSuchWindowException,
    UnexpectedAlertPresentException,
)
_RETRYABLE_PROCESS_SIGNALS = frozenset({signal.SIGABRT, signal.SIGBUS, signal.SIGSEGV})


def is_retryable_linkedin_exit_status(status: int) -> bool:
    """
    Classify the private transient-failure exit code and browser-driver crash signals.

    Args:
        status (int): CLI exit status, negative when a child process was terminated by a signal.

    Returns:
        bool: Whether a fresh LinkedIn browser session may retry this failed command.
    """
    return status == 75 or (status < 0 and -status in _RETRYABLE_PROCESS_SIGNALS)


def is_retryable_linkedin_error(error: Exception) -> bool:
    """
    Classify transient browser and HTTP failures while leaving account challenges and bad requests terminal.

    Args:
        error (Exception): Failure raised during a LinkedIn browser operation or related HTTP request.

    Returns:
        bool: Whether repeating the complete command in a fresh browser session may succeed.
    """
    # LinkedIn may have accepted the upload; the command already reconciled once, so another write is unsafe.
    if isinstance(error, ResumeUploadConfirmationError):
        return False

    if isinstance(error, BrowserTimeoutError):
        return True

    # A dead window/session stops same-driver retries, but a complete attempt creates a fresh WebDriver session.
    if isinstance(error, (InvalidSessionIdException, NoSuchWindowException)):
        return True

    if is_retryable_selenium_error(error):
        return True

    if isinstance(error, requests.exceptions.HTTPError):
        status = error.response.status_code if error.response is not None else None
        return status in {408, 429, 500, 502, 503, 504}

    # Invalid URL, redirect, certificate, and proxy failures need correction rather than another browser session.
    if isinstance(
        error,
        (
            requests.exceptions.InvalidURL,
            requests.exceptions.InvalidSchema,
            requests.exceptions.MissingSchema,
            requests.exceptions.TooManyRedirects,
            requests.exceptions.SSLError,
            requests.exceptions.ProxyError,
        ),
    ):
        return False

    return isinstance(error, requests.RequestException)


def retry(  # noqa: UP047 - pydocstyle 6.3 cannot parse PEP 695 function headers.
    operation: Callable[[], _T],
    *,
    attempts: int,
    backoff: float,
    exceptions: tuple[type[Exception], ...],
    max_backoff: float = 300,
    should_retry: Callable[[Exception], bool] | None = None,
) -> _T:
    """
    Retry only the declared transient exceptions with capped exponential delays.

    Args:
        operation (Callable[[], _T]): Idempotent operation or complete isolated read.
        attempts (int): Total attempts, including the initial call.
        backoff (float): Initial delay in seconds, doubled after each failure.
        exceptions (tuple[type[Exception], ...]): Failure classes safe to retry.
        max_backoff (float): Maximum delay between attempts.
        should_retry (Callable[[Exception], bool] | None): Optional filter for matched errors.

    Returns:
        _T: First successful result.

    Raises:
        ConfigurationError: Retry limits are invalid.
        Exception: The final transient failure or an undeclared failure is propagated.
    """

    if attempts < 1 or backoff < 0 or max_backoff < 0:
        raise ConfigurationError("Retries require at least one attempt and a nonnegative delay.")

    # Only caller-declared transient failures consume retries; programming errors and invalid content escape immediately.
    for attempt in range(attempts - 1):
        try:
            return operation()
        except exceptions as error:
            if should_retry is not None and not should_retry(error):
                raise

            delay = min(backoff * 2**attempt, max_backoff)
            _LOGGER.warning(
                "Retrying transient operation",
                extra={
                    "error.type": type(error).__name__,
                    "retry.attempt": attempt + 2,
                    "retry.limit": attempts,
                    "retry.delay_seconds": delay,
                },
            )
            time.sleep(delay)

    # Let the final failure retain its original exception and traceback instead of wrapping it in a generic retry error.
    return operation()


def retry_selenium(  # noqa: UP047 - pydocstyle 6.3 cannot parse PEP 695 function headers.
    operation: Callable[[], _T], settings: Capture
) -> _T:
    """
    Retry a read-only or state-reconciled Selenium operation using capture settings.

    Args:
        operation (Callable[[], _T]): Safe-to-repeat navigation, read, or reconciliation operation.
        settings (Capture): Configured attempt count and exponential delay bounds.

    Returns:
        _T: The first successful browser result.

    Raises:
        ConfigurationError: The retry settings are invalid.
        WebDriverException: The final browser failure, or a nonrecoverable Selenium error.
        Exception: Any failure outside Selenium that the operation raises.
    """
    return retry(
        operation,
        attempts=settings.retry_attempts,
        backoff=settings.retry_backoff_seconds,
        max_backoff=settings.retry_max_backoff_seconds,
        exceptions=(WebDriverException,),
        should_retry=is_retryable_selenium_error,
    )


def is_retryable_selenium_error(error: Exception) -> bool:
    """
    Classify browser errors whose operation can safely be attempted again.

    Args:
        error (Exception): Failure observed during a Selenium operation.

    Returns:
        bool: Whether the error is a recoverable WebDriver failure.
    """
    return isinstance(error, WebDriverException) and not isinstance(error, _NON_RETRYABLE_SELENIUM_ERRORS)
