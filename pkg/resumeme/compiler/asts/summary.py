"""
Validate generated copy and bind it to the profile evidence used for generation.
"""

from __future__ import annotations

import json
from importlib.resources import files
from typing import TYPE_CHECKING

import cattrs
from attrs import frozen
from jsonschema import Draft202012Validator

from resumeme.compiler.constants.backend import AST_PACKAGE, SUMMARY_SCHEMA
from resumeme.config import CompanyTarget
from resumeme.exceptions import SummaryError

if TYPE_CHECKING:
    from pathlib import Path

    from resumeme.config import Codex

__all__ = ["CompanyEvidence", "Summary", "load_summary", "summary_schema"]


@frozen
class CompanyEvidence:
    """
    Keep employer requirements separate from the applicant's professional history.

    Attributes:
        target (CompanyTarget): Configured employer, job URL, and per-target preferences.
        company (str): Captured or explicitly supplied company background.
        job (str): Captured or explicitly supplied job description.
    """

    target: CompanyTarget
    company: str
    job: str


@frozen
class Summary:
    """
    Hold two plain-text replacements with their owner and input fingerprint.

    Attributes:
        username (str): LinkedIn profile owner.
        source_digest (str): SHA-256 of the supplied evidence and summary settings.
        about (str): Concise About paragraph; empty preserves the captured About section.
        headline (str): Short portrait caption; empty preserves the original header behavior.
    """

    username: str
    source_digest: str
    about: str
    headline: str


def summary_schema() -> dict[str, object]:
    """
    Load the packaged contract shared by Codex and the offline compiler.

    Returns:
        dict[str, object]: A fresh JSON Schema document.
    """
    schema: dict[str, object] = json.loads(files(AST_PACKAGE).joinpath(SUMMARY_SCHEMA).read_text(encoding="utf-8"))
    return schema


def load_summary(path: Path, *, username: str, source_digest: str, settings: Codex) -> Summary:
    """
    Reject malformed, oversized, disabled, or stale generated copy before rendering.

    Args:
        path (Path): Explicit summary artifact; never discovered implicitly.
        username (str): Expected source profile owner.
        source_digest (str): Fingerprint of the current generation input.
        settings (Codex): Enablement and word limits from the local configuration.

    Returns:
        Summary: Validated plain-text replacement fields.

    Raises:
        SummaryError: Generation is disabled, ownership or inputs differ, or a word limit is exceeded.
        jsonschema.ValidationError: The artifact does not satisfy the summary contract.
    """
    if not settings.enabled:
        raise SummaryError("Set codex.enabled: true before supplying a generated summary.")

    raw = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator(summary_schema()).validate(raw)
    result = cattrs.Converter(forbid_extra_keys=True).structure(raw, Summary)

    # A fork or changed context must generate new copy rather than inheriting another owner's résumé text.
    if result.username != username or result.source_digest != source_digest:
        raise SummaryError("Summary inputs changed or the owner differs. Generate a new Codex summary for this profile and config.")

    for label, value, maximum in (
        ("About", result.about, settings.about_max_words),
        ("Headline", result.headline, settings.headline_max_words),
    ):
        if len(value.split()) > maximum:
            raise SummaryError(f"Generated {label} exceeds its {maximum}-word limit. Regenerate the summary.")

    return result
