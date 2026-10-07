"""
Load a strict configuration with paths anchored to its own directory.
"""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import TypedDict

import cattrs
import yaml
from attrs import field, frozen
from jsonschema import Draft202012Validator, FormatChecker

__all__ = ["Capture", "Config", "Experience", "JobSelector", "LinkedIn", "Output", "Style", "StyleOverrides", "load_config", "project_path"]


@frozen
class LinkedIn:
    """
    Identify the profile owner without storing authentication material.

    Attributes:
        username (str): Owner slug from the LinkedIn profile URL.
    """

    username: str


@frozen
class Capture:
    """
    Bound page loading, pagination, preview downloads, and transient retries.

    Attributes:
        page_timeout_seconds (int): Browser and HTTP request timeout.
        max_scrolls (int): Maximum expansion iterations per page.
        max_pages_per_section (int): Maximum detail pages before capture fails.
        fetch_link_previews (bool): Whether to inspect external destinations, page titles, and project previews.
        retry_attempts (int): Total attempts for transient browser and HTTP failures.
        retry_backoff_seconds (int): Initial retry delay, doubled after every failed attempt.
        retry_max_backoff_seconds (int): Maximum exponential retry delay.
    """

    page_timeout_seconds: int = 30
    max_scrolls: int = 60
    max_pages_per_section: int = 30
    fetch_link_previews: bool = True
    retry_attempts: int = 5
    retry_backoff_seconds: int = 10
    retry_max_backoff_seconds: int = 300


@frozen
class JobSelector:
    """
    Match jobs by exact title, employer, or both, ignoring case and extra whitespace.

    Attributes:
        title (str | None): Job title to match, or any title when omitted.
        company (str | None): Employer name to match, or any employer when omitted.
    """

    title: str | None = None
    company: str | None = None


@frozen
class Experience:
    """
    Select jobs for display without changing the captured employment history.

    Attributes:
        disable (list[JobSelector]): Exclusions applied before the date window.
        last_years (int | None): Include jobs overlapping this many trailing calendar years, or all dates when omitted.
        as_of (str | None): ISO date fixing the window's endpoint; otherwise use the current UTC date.
    """

    disable: list[JobSelector] = field(factory=list)
    last_years: int | None = None
    as_of: str | None = None


@frozen
class Output:
    """
    Keep portable inputs and generated outputs beneath the configuration root.

    Attributes:
        profile (str): Snapshot JSON path.
        assets (str): Downloaded PNG directory.
        tex (str): Generated LaTeX path.
        pdf (str): Final PDF path used locally and for the CI commit.
    """

    profile: str = "data/profile.json"
    assets: str = "data/assets"
    tex: str = "tex/resume.tex"
    pdf: str = "resume.pdf"


class StyleOverrides(TypedDict, total=False):
    """
    Define the optional style fields that an inline theme may override.

    Attributes:
        paper (str): A4 or letter paper name.
        accent (str): Six-digit hexadecimal hyperlink color.
        background (str): Six-digit hexadecimal page background color.
        font_size (int): Body font size in points.
        show_header_photo (bool): Whether to display the profile cover photo.
        skills_word_cloud (bool): Whether to replace the Skills list with a cloud.
        ink (str): Six-digit hexadecimal body text color.
        name_color (str): Six-digit hexadecimal profile name color.
        heading_color (str): Six-digit hexadecimal section heading color.
        entry_color (str): Six-digit hexadecimal entry heading color.
        skill_colors (tuple[str, ...]): Nonempty palette of six-digit hexadecimal cloud colors.
    """

    paper: str
    accent: str
    background: str
    font_size: int
    show_header_photo: bool
    skills_word_cloud: bool
    ink: str
    name_color: str
    heading_color: str
    entry_color: str
    skill_colors: tuple[str, ...]


@frozen
class Style:
    """
    Expose the small set of print choices that do not change profile content.

    Attributes:
        paper (str): A4 or letter paper name.
        accent (str): Six-digit hexadecimal hyperlink color.
        background (str): Six-digit hexadecimal page background color.
        font_size (int): Body font size in points.
        show_header_photo (bool): Whether to display the profile's cover/background photo.
        skills_word_cloud (bool): Replace the Skills list with a cloud weighted by references and endorsements.
        ink (str): Six-digit hexadecimal body text color.
        name_color (str): Six-digit hexadecimal profile name color.
        heading_color (str): Six-digit hexadecimal section heading color.
        entry_color (str): Six-digit hexadecimal entry heading color.
        skill_colors (tuple[str, ...]): Nonempty palette of six-digit hexadecimal cloud colors.
        theme (str | None): Selected key in themes; None uses the base style unchanged.
        themes (dict[str, StyleOverrides]): Inline themes containing partial style overrides.
    """

    paper: str = "letter"
    accent: str = "0A66C2"
    background: str = "FFFFFF"
    font_size: int = 10
    show_header_photo: bool = True
    skills_word_cloud: bool = True
    ink: str = "191919"
    name_color: str = "191919"
    heading_color: str = "191919"
    entry_color: str = "191919"
    skill_colors: tuple[str, ...] = ("0A66C2",)
    theme: str | None = None
    themes: dict[str, StyleOverrides] = field(factory=dict)


@frozen
class Config:
    """
    Own validated values passed between the command line and pipeline stages.

    Attributes:
        linkedin (LinkedIn): Profile identity.
        capture (Capture): Browser and download limits.
        output (Output): Paths relative to the configuration directory.
        style (Style): Print presentation choices.
        template (str | None): Optional custom template path.
        disable (list[str]): Section keys omitted from rendered output while retaining the captured snapshot.
        experience (Experience): Job exclusions and optional employment date window.
    """

    linkedin: LinkedIn
    capture: Capture = field(factory=Capture)
    output: Output = field(factory=Output)
    style: Style = field(factory=Style)
    template: str | None = None
    disable: list[str] = field(factory=list)
    experience: Experience = field(factory=Experience)


def project_path(root: Path, value: str) -> Path:
    """
    Resolve a repository path and reject escapes, including existing symlinks.

    Args:
        root (Path): Configuration directory.
        value (str): Relative input or output path.

    Returns:
        Path: Absolute path beneath the root.

    Raises:
        ValueError: The path is absolute, points at the root, or escapes it.
    """

    # Resolve symlinks before checking containment; lexical '..' checks alone would allow existing links to escape.
    target = (root / value).resolve()

    if Path(value).is_absolute() or target == root.resolve() or not target.is_relative_to(root.resolve()):
        raise ValueError(f"Expected a path within the configuration directory: {value}")

    return target


def load_config(path: Path) -> Config:
    """
    Safely load YAML, reject unknown fields, and validate configured paths.

    Args:
        path (Path): User-maintained configuration file.

    Returns:
        Config: Schema-validated configuration with defaults applied.

    Raises:
        jsonschema.ValidationError: A value is invalid or a field is unknown.
        ValueError: A path escapes the project directory or the selected theme is not defined.
    """

    # Validate raw types before cattrs can coerce them, including real calendar dates for the job window.
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    schema = json.loads(files("resume").joinpath("resources/config.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(raw)
    config = cattrs.Converter(forbid_extra_keys=True).structure(raw, Config)

    # Reject selector typos even for validation-only commands; themes are user-defined, not a hard-coded registry.
    if config.style.theme is not None and config.style.theme not in config.style.themes:
        raise ValueError(f"Unknown style.theme {config.style.theme!r}; define it under style.themes or use null.")

    # Inputs, templates, and outputs share one root but must never resolve to the same file or directory.
    paths = [config.output.profile, config.output.assets, config.output.tex, config.output.pdf]

    if config.template:
        paths.append(config.template)

    resolved = [project_path(path.resolve().parent, value) for value in paths]

    if len(resolved) != len(set(resolved)):
        raise ValueError("Input, output, and template paths must be distinct.")

    return config
