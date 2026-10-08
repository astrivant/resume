"""
Define the common contract for failures explicitly raised by resumeme.
"""

from __future__ import annotations

__all__ = ["ResumemeError"]


class ResumemeError(Exception):
    """
    Identify a package failure while preserving its message and chained cause.

    Domain subclasses retain their previous built-in or Selenium base so callers
    can adopt this common boundary without changing existing handlers or retries.
    """
