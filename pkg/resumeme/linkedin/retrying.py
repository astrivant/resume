"""
Retry transient operations with explicit bounds and injectable waiting.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, TypeVar

from resumeme.exceptions import ConfigurationError

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["retry"]
_T = TypeVar("_T")
_LOGGER = logging.getLogger(__name__)


def retry(  # noqa: UP047 - pydocstyle 6.3 cannot parse PEP 695 function headers.
    operation: Callable[[], _T], *, attempts: int, backoff: float, exceptions: tuple[type[Exception], ...], max_backoff: float = 300
) -> _T:
    """
    Retry only the declared transient exceptions with capped exponential delays.

    Args:
        operation (Callable[[], _T]): Idempotent operation or complete isolated read.
        attempts (int): Total attempts, including the initial call.
        backoff (float): Initial delay in seconds, doubled after each failure.
        exceptions (tuple[type[Exception], ...]): Failure classes safe to retry.
        max_backoff (float): Maximum delay between attempts.

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
