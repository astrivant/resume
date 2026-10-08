"""
Prepare filtered summary evidence and apply validated generated résumé copy.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from attrs import asdict, evolve

from resumeme.compiler.asts.profile import Entry, Section
from resumeme.compiler.asts.sections import section_key
from resumeme.compiler.passes.progression import experience_layout
from resumeme.compiler.passes.projects import consolidate_projects
from resumeme.compiler.passes.visibility import visible_profile

if TYPE_CHECKING:
    from resumeme.compiler.asts.profile import Profile
    from resumeme.compiler.asts.summary import CompanyEvidence, Summary
    from resumeme.config import Config

__all__ = ["apply_summary", "summary_digest", "summary_evidence"]


def _entry_evidence(entry: Entry) -> dict[str, object]:
    """
    Retain professional text and skills while omitting images and link metadata.

    Args:
        entry (Entry): Visible source entry or nested role.

    Returns:
        dict[str, object]: JSON-serializable facts with nested ownership preserved.
    """
    return {
        "title": entry.title,
        "paragraphs": entry.paragraphs,
        "skills": [skill.name for skill in entry.skills],
        "positions": [_entry_evidence(position) for position in entry.positions],
    }


def summary_evidence(profile: Profile, config: Config, company: CompanyEvidence | None = None) -> dict[str, object]:
    """
    Prepare the filtered professional profile and explicit user context for Codex.

    Args:
        profile (Profile): Original validated capture.
        config (Config): Visibility rules and summary settings.
        company (CompanyEvidence | None): Employer requirements for one variant, separate from the applicant's evidence.

    Returns:
        dict[str, object]: Professional evidence without contact blocks, remote assets, or credentials.
    """
    visible = visible_profile(profile, config)
    visible, _ = consolidate_projects(
        visible,
        enabled="projects" in {section_key(key) for key in config.section_order},
        project_filter=config.project_filter,
        include=config.projects.include,
        exclude=config.projects.exclude,
    )

    # Company groups retain their role boundaries without repeating each child's description in the parent.
    # Skills contribute labels only: reverse association rows can mention roles hidden by the employment filter.
    evidence: dict[str, object] = {
        "username": profile.username,
        "name": profile.name,
        "context": config.codex.context,
        "model": config.codex.model,
        "about_max_words": config.codex.about_max_words,
        "headline_max_words": config.codex.headline_max_words,
        "sections": [
            {
                "key": section.key,
                "entries": [
                    _entry_evidence(
                        experience_layout(entry)
                        if section.key == "experience"
                        else Entry(entry.title, skills=entry.skills)
                        if section.key == "skills"
                        else entry
                    )
                    for entry in section.entries
                ],
            }
            for section in visible.sections
            if section.key != "contact"
        ],
    }

    # Explicit reasoning changes invalidate generated copy; leaving it unset preserves existing default-based artifacts.
    if config.codex.reasoning_effort is not None:
        evidence["reasoning_effort"] = config.codex.reasoning_effort

    # Generic evidence deliberately excludes the target list, so adding employers cannot alter the generic summary.
    if company is not None:
        evidence["employer"] = asdict(company)

    return evidence


def summary_digest(profile: Profile, config: Config, company: CompanyEvidence | None = None) -> str:
    """
    Fingerprint the complete generation input independently of JSON formatting.

    Args:
        profile (Profile): Original validated capture.
        config (Config): Visibility and summary settings used for generation.
        company (CompanyEvidence | None): Exact company/job evidence for this variant, or None for generic copy.

    Returns:
        str: Hexadecimal SHA-256 used to reject stale or cross-owner summaries.
    """
    encoded = json.dumps(summary_evidence(profile, config, company), sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def apply_summary(profile: Profile, summary: Summary, *, about_enabled: bool) -> Profile:
    """
    Replace or add About without mutating captured facts or restoring excluded sections.

    Args:
        profile (Profile): Display profile after visibility filtering.
        summary (Summary): Validated summary for the original source snapshot.
        about_enabled (bool): Whether section exclusions permit About to appear.

    Returns:
        Profile: Display copy; an empty generated paragraph leaves the source copy intact.
    """
    if not about_enabled or not summary.about.strip():
        return profile

    replacement = Section("about", "About", [Entry(paragraphs=[" ".join(summary.about.split())])])
    sections = [replacement if section.key == "about" else section for section in profile.sections]

    if not any(section.key == "about" for section in sections):
        sections.append(replacement)

    return evolve(profile, sections=sections)
