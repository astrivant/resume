"""
Validate body typography and optional About panels without changing profile content.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml
from jsonschema import ValidationError

from resumeme.compiler.asts.profile import Entry, Profile, Section
from resumeme.compiler.passes.themes import resolve_style
from resumeme.compiler.pipeline import render_profile
from resumeme.config import Config, LinkedIn, Style, load_config

if TYPE_CHECKING:
    from pathlib import Path


def test_body_style_defaults_and_theme_overrides(tmp_path: Path) -> None:
    """
    Preserve compact defaults while allowing themes to select independent typography and shading.

    Args:
        tmp_path (Path): Isolated configuration directory.

    Returns:
        None: Theme resolution applies all three settings without mutating the base style.
    """
    path = tmp_path / "resumeme.config.yaml"
    path.write_text(
        "linkedin: {username: example-person}\n"
        "style:\n  theme: airy\n  themes:\n"
        "    airy: {line_height: 1.15, paragraph_spacing: 7.5, about_background: F0F4F7}\n"
    )
    base = load_config(path).style
    resolved = resolve_style(base)
    assert (base.line_height, base.paragraph_spacing, base.about_background) == (1.0, 3.0, None)
    assert (resolved.line_height, resolved.paragraph_spacing, resolved.about_background) == (1.15, 7.5, "F0F4F7")
    assert base == Style(theme="airy", themes=base.themes)


@pytest.mark.parametrize(
    ("field", "value"),
    [("line_height", value) for value in (0, 0.99, 2.01, True, "1.1", None)]
    + [("paragraph_spacing", value) for value in (-1, 24.01, True, "6pt", None)]
    + [("about_background", value) for value in ("#F0F4F7", "F0F", "blue", "GGGGGG", True, 123456)],
)
@pytest.mark.parametrize("theme", [False, True])
def test_invalid_body_style_rejected(tmp_path: Path, field: str, value: object, theme: bool) -> None:
    """
    Reject invalid dimensions and unsafe color syntax in base styles and theme overrides.

    Args:
        tmp_path (Path): Isolated configuration directory.
        field (str): Style field under validation.
        value (object): Invalid configured value.
        theme (bool): Whether the override belongs to a named theme.

    Returns:
        None: Invalid input fails schema validation before reaching LaTeX.
    """
    override = {field: value}
    style = {"themes": {"custom": override}} if theme else override
    path = tmp_path / "resumeme.config.yaml"
    path.write_text(yaml.safe_dump({"linkedin": {"username": "example-person"}, "style": style}))

    with pytest.raises(ValidationError):
        load_config(path)


@pytest.mark.parametrize("background", [None, "F0F4F7"])
@pytest.mark.parametrize("visible", [False, True])
def test_about_panel_preserves_content_and_section_visibility(tmp_path: Path, background: str | None, visible: bool) -> None:
    """
    Keep panel decoration subordinate to section filtering and preserve paragraph boundaries.

    Args:
        tmp_path (Path): Isolated rendering directory.
        background (str | None): Optional panel color.
        visible (bool): Whether About is enabled in section order.

    Returns:
        None: Enabled About text appears once, hidden About leaves no panel, and source paragraphs remain unchanged.
    """
    paragraphs = ["Build dependable systems.", "Help engineering teams deliver."]
    profile = Profile("example-person", "Alex Example", sections=[Section("about", "About", [Entry(paragraphs=paragraphs)])])
    config = Config(
        LinkedIn(profile.username),
        section_order=["about"] if visible else [],
        style=Style(line_height=1.1, paragraph_spacing=6, about_background=background),
    )
    source = render_profile(profile, config, tmp_path).read_text()
    body = source.split(r"\begin{document}", 1)[1]
    assert body.count(r"\begin{aboutpanel}") == int(visible and background is not None)
    assert body.count(r"\end{aboutpanel}") == int(visible and background is not None)

    for paragraph in paragraphs:
        assert body.count(paragraph) == int(visible)

    assert profile.sections[0].entries[0].paragraphs == paragraphs
