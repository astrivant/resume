"""
Verify profile-column configuration and content preservation across first-page layouts.
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
    from typing import Literal


def test_profile_column_defaults_left_and_supports_theme_override(tmp_path: Path) -> None:
    """
    Preserve the original default while applying an explicitly selected right-side theme.

    Args:
        tmp_path (Path): Isolated configuration directory.

    Returns:
        None: Theme precedence changes effective placement without mutating the base style.
    """
    path = tmp_path / "resumeme.config.yaml"
    path.write_text(
        "linkedin:\n  username: example-person\nstyle:\n  theme: floating\n  themes:\n    floating:\n      profile_column_side: right\n"
    )
    style = load_config(path).style
    assert style.profile_column_side == "left"
    assert resolve_style(style).profile_column_side == "right"
    assert style.profile_column_side == "left"


@pytest.mark.parametrize("side", ["center", "Right", True, None])
@pytest.mark.parametrize("theme", [False, True])
def test_profile_column_rejects_invalid_base_and_theme_values(tmp_path: Path, side: str | bool | None, theme: bool) -> None:
    """
    Reject unsupported placements before generating a PDF.

    Args:
        tmp_path (Path): Temporary configuration root.
        side (str | bool | None): Invalid column placement.
        theme (bool): Whether to put the invalid value in a theme override.

    Returns:
        None: Base and theme configuration use the same strict enum.
    """
    path = tmp_path / "resumeme.config.yaml"
    override = {"profile_column_side": side}
    style = {"themes": {"custom": override}} if theme else override
    path.write_text(yaml.safe_dump({"linkedin": {"username": "example-person"}, "style": style}))

    with pytest.raises(ValidationError):
        load_config(path)


@pytest.mark.parametrize("side", ["left", "right"])
@pytest.mark.parametrize("contact_first", [False, True])
def test_both_layouts_preserve_visible_content_and_navigation(tmp_path: Path, side: Literal["left", "right"], contact_first: bool) -> None:
    """
    Keep header, contact placement, section links, and ordered body content in either layout.

    Args:
        tmp_path (Path): Isolated template rendering directory.
        side (Literal["left", "right"]): Selected profile-column position.
        contact_first (bool): Whether Contact belongs with the profile or later in the body.

    Returns:
        None: Each enabled section appears once and hidden profile text stays excluded.
    """
    profile = Profile(
        "example-person",
        "Alex Example",
        intro=["Engineer at Example", "Boston, MA"],
        sections=[
            Section("about", "About", [Entry("About evidence")]),
            Section("contact", "Contact", [Entry("Contact evidence")]),
            Section("experience", "Experience", [Entry("Engineer", ["2020 - Present", "Delivered systems"])]),
        ],
    )
    order = ["contact", "about", "experience"] if contact_first else ["about", "experience", "contact"]
    config = Config(LinkedIn(profile.username), style=Style(profile_column_side=side), section_order=order)
    source = render_profile(profile, config, tmp_path).read_text().split(r"\begin{document}", 1)[1]
    assert source.count("Alex Example") == 1
    assert source.count("About evidence") == 1
    assert source.count("Contact evidence") == 1
    assert source.count("Delivered systems") == 1
    assert "Engineer at Example" not in source
    before, after = source.split(r"\framebreak", 1)
    assert ("Contact evidence" in before) is contact_first
    assert ("Contact evidence" in after) is not contact_first

    for index, title in enumerate(["Contact", "About", "Experience"] if contact_first else ["About", "Experience", "Contact"]):
        assert source.count(rf"\hypertarget{{resumeme-section-{index}}}") == 1
        assert rf"\hyperlink{{resumeme-section-{index}}}{{{title}}}" in source


@pytest.mark.parametrize("side", ["left", "right"])
def test_minimal_profile_needs_no_empty_body_frame(tmp_path: Path, side: Literal["left", "right"]) -> None:
    """
    Render a name and profile link without manufacturing sections or an extra page break.

    Args:
        tmp_path (Path): Isolated rendering directory.
        side (Literal["left", "right"]): Selected profile-column position.

    Returns:
        None: A profile with no sections remains valid in either layout.
    """
    profile = Profile("example-person", "Alex")
    source = render_profile(profile, Config(LinkedIn(profile.username), style=Style(profile_column_side=side)), tmp_path).read_text()
    body = source.split(r"\begin{document}", 1)[1]
    assert r"\framebreak" not in body
    assert "LinkedIn profile" in body
    assert "Contents" not in body
