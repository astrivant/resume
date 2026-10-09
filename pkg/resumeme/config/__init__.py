"""
Expose typed configuration models and validated loading operations.
"""

from __future__ import annotations

from resumeme.config.loading import company_config, load_config, project_path
from resumeme.config.models import (
    Capture,
    Codex,
    CodexSkills,
    CompanyTarget,
    Config,
    Education,
    EducationSelector,
    Experience,
    GitHub,
    GitHubContributions,
    JobSelector,
    LinkedIn,
    LinkedInResume,
    Logging,
    Output,
    Ownership,
    Pages,
    Projects,
    ProjectSelector,
    Readme,
    Style,
    StyleOverrides,
)

__all__ = [
    "Capture",
    "Codex",
    "CodexSkills",
    "CompanyTarget",
    "Config",
    "Education",
    "EducationSelector",
    "Experience",
    "GitHub",
    "GitHubContributions",
    "JobSelector",
    "LinkedIn",
    "LinkedInResume",
    "Logging",
    "Output",
    "Ownership",
    "Pages",
    "ProjectSelector",
    "Projects",
    "Readme",
    "Style",
    "StyleOverrides",
    "company_config",
    "load_config",
    "project_path",
]
