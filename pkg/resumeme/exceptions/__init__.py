"""
Expose all resumeme-defined exceptions from a stable import boundary.

Use ResumemeError to handle explicit package failures together, or catch a domain
class for a narrower operation. Exceptions originating in dependencies retain
their original types unless an operation already translates them with a cause.
"""

from __future__ import annotations

from resumeme.exceptions.base import ResumemeError
from resumeme.exceptions.browser import (
    BrowserElementError,
    BrowserError,
    BrowserLaunchError,
    BrowserTimeoutError,
    BrowserWaitError,
    BrowserWindowError,
)
from resumeme.exceptions.domain import (
    CompilationError,
    ConfigurationError,
    ContributionError,
    MediaError,
    ProfileError,
    PublicationError,
    RenderingError,
    SigningError,
    SummaryError,
)

__all__ = [
    "BrowserElementError",
    "BrowserError",
    "BrowserLaunchError",
    "BrowserTimeoutError",
    "BrowserWaitError",
    "BrowserWindowError",
    "CompilationError",
    "ConfigurationError",
    "ContributionError",
    "MediaError",
    "ProfileError",
    "PublicationError",
    "RenderingError",
    "ResumemeError",
    "SigningError",
    "SummaryError",
]
