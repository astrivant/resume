"""
Retry transient operations with explicit bounds and injectable waiting.
"""

from __future__ import annotations

import sys
import time
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["retry"]
_T = TypeVar("_T")


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
        ValueError: Retry limits are invalid.
        Exception: The final transient failure or an undeclared failure is propagated.
    """
    if attempts < 1 or backoff < 0 or max_backoff < 0:
        raise ValueError("Retries require at least one attempt and a nonnegative delay.")
    # Only caller-declared transient failures consume retries; programming errors and invalid content escape immediately.
    for attempt in range(attempts - 1):
        try:
            return operation()
        except exceptions as error:
            delay = min(backoff * 2**attempt, max_backoff)
            print(f"{type(error).__name__}: retrying attempt {attempt + 2}/{attempts} in {delay:g}s.", file=sys.stderr, flush=True)
            time.sleep(delay)
    # Let the final failure retain its original exception and traceback instead of wrapping it in a generic retry error.
    return operation()
