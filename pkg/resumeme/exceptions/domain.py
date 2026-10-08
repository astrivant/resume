"""
Classify package failures by the input or pipeline responsibility that rejected them.
"""

from __future__ import annotations

from resumeme.exceptions.base import ResumemeError

__all__ = [
    "CompilationError",
    "ConfigurationError",
    "ContributionError",
    "MediaError",
    "ProfileError",
    "PublicationError",
    "RenderingError",
    "SessionCacheError",
    "SigningError",
    "SummaryError",
]


class CompilationError(ResumemeError, RuntimeError):
    """
    Report a failed LaTeX invocation or missing compiled PDF.
    """


class ConfigurationError(ResumemeError, ValueError):
    """
    Reject inconsistent configuration, paths, or operation settings.
    """


class ContributionError(ResumemeError, ValueError):
    """
    Reject incomplete, mismatched, or unrecognized GitHub contribution data.
    """


class MediaError(ResumemeError, ValueError):
    """
    Reject remote media destinations, redirect chains, or oversized downloads.
    """


class ProfileError(ResumemeError, ValueError):
    """
    Reject missing, incomplete, mismatched, or unrecognized captured profile data.
    """


class PublicationError(ResumemeError, ValueError):
    """
    Reject inconsistent README, Pages, or company resume publication artifacts.
    """


class RenderingError(ResumemeError, ValueError):
    """
    Reject inputs that cannot produce the requested graphic or PDF presentation.
    """


class SessionCacheError(ResumemeError, ValueError):
    """
    Reject invalid cache keys, unauthenticated ciphertext, or unsafe browser-state archives.
    """


class SigningError(ResumemeError, ValueError):
    """
    Reject signing identity inputs or an ambiguous LinkedIn ownership block.
    """


class SummaryError(ResumemeError, ValueError):
    """
    Reject summary or skill proposal inputs, evidence, or generated output.
    """
