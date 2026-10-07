"""
Load a strict configuration with paths anchored to its own directory.
"""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

import cattrs
import yaml
from attrs import field, frozen
from jsonschema import Draft202012Validator

__all__ = ["Capture", "Config", "LinkedIn", "Output", "Style", "load_config", "project_path"]


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
        fetch_link_previews (bool): Whether to request external project previews.
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


@frozen
class Style:
    """
    Expose the small set of print choices that do not change profile content.

    Attributes:
        paper (str): A4 or letter paper name.
        accent (str): Six-digit hexadecimal link and accent color.
        background (str): Six-digit hexadecimal page background color.
        font_size (int): Body font size in points.
        show_header_photo (bool): Whether to display the profile's cover/background photo.
        skills_word_cloud (bool): Replace the Skills list with a cloud weighted by references and endorsements.
    """

    paper: str = "a4"
    accent: str = "0A66C2"
    background: str = "F3F2EF"
    font_size: int = 10
    show_header_photo: bool = True
    skills_word_cloud: bool = True


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
    """

    linkedin: LinkedIn
    capture: Capture = field(factory=Capture)
    output: Output = field(factory=Output)
    style: Style = field(factory=Style)
    template: str | None = None
    disable: list[str] = field(factory=list)


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
        ValueError: An output or template path escapes the project directory.
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    schema = json.loads(files("resume").joinpath("resources/config.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(raw)
    config = cattrs.Converter(forbid_extra_keys=True).structure(raw, Config)
    paths = [config.output.profile, config.output.assets, config.output.tex, config.output.pdf]
    if config.template:
        paths.append(config.template)
    resolved = [project_path(path.resolve().parent, value) for value in paths]
    if len(resolved) != len(set(resolved)):
        raise ValueError("Input, output, and template paths must be distinct.")
    return config
