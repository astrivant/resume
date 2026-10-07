"""
Verify inline theme precedence, shared validation, and rendering before visibility decisions.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
import yaml
from attrs import evolve
from jsonschema import ValidationError
from PIL import Image, ImageChops

from resume.config import Config, LinkedIn, Style, load_config
from resume.latex.rendering import render_profile
from resume.latex.themes import resolve_style
from resume.models import Entry, Media, Profile, Section, Skill
from resume.visualization.skills import SkillScore, render_skill_cloud

if TYPE_CHECKING:
    from pathlib import Path


def test_selected_theme_overrides_base_without_mutation(tmp_path: Path) -> None:
    """
    Accept arbitrary theme names and override only fields explicitly supplied by that theme.

    Args:
        tmp_path (Path): Temporary config location.

    Returns:
        None: Null uses the base style; named overrides win while omitted fields and the original config remain intact.
    """
    path = tmp_path / "resume.config.yaml"
    path.write_text(
        "linkedin:\n  username: example-person\nstyle:\n  accent: '112233'\n  font_size: 11\n"
        "  themes:\n    my-print-theme:\n      paper: a4\n      accent: 'A44813'\n"
        "      show_header_photo: false\n      skill_colors: ['6B2737', 'C44A11']\n",
        encoding="utf-8",
    )
    base = load_config(path).style
    assert base.theme is None
    assert resolve_style(base) == base
    selected = evolve(base, theme="my-print-theme")
    effective = resolve_style(selected)
    assert effective.paper == "a4"
    assert effective.accent == "A44813"
    assert effective.font_size == 11
    assert effective.show_header_photo is False
    assert effective.skill_colors == ("6B2737", "C44A11")
    assert selected.accent == "112233" and selected.paper == "letter"
    assert resolve_style(evolve(selected, theme=None)) == base


@pytest.mark.parametrize(
    "override",
    [
        {"font_size": 9},
        {"paper": "poster"},
        {"accent": "#A44813"},
        {"ink": None},
        {"show_header_photo": "false"},
        {"skill_colors": []},
        {"skill_colors": ["bogus"]},
        {"theme": "recursive"},
        {"themes": {}},
        {"disable": ["skills"]},
    ],
)
def test_inline_themes_share_base_style_validation(tmp_path: Path, override: dict[str, object]) -> None:
    """
    Reject invalid and recursive overrides even when a theme is not currently selected.

    Args:
        tmp_path (Path): Temporary config location.
        override (dict[str, object]): Invalid theme fragment.

    Returns:
        None: Invalid theme fields fail the same schema checks as ordinary style values.
    """
    path = tmp_path / "resume.config.yaml"
    path.write_text(
        yaml.safe_dump({"linkedin": {"username": "example-person"}, "style": {"themes": {"custom": override}}}), encoding="utf-8"
    )

    with pytest.raises(ValidationError):
        load_config(path)


def test_unknown_theme_fails_before_rendering(tmp_path: Path) -> None:
    """
    Reject unknown selectors in both YAML and programmatically constructed configs.

    Args:
        tmp_path (Path): Temporary config location.

    Returns:
        None: A typo cannot silently publish a resume with the wrong theme.
    """
    path = tmp_path / "resume.config.yaml"
    path.write_text("linkedin:\n  username: example-person\nstyle:\n  theme: missing\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Unknown style.theme"):
        load_config(path)

    with pytest.raises(ValueError, match="Unknown style.theme"):
        resolve_style(Style(theme="missing"))


def test_theme_visibility_and_custom_template_use_effective_style(tmp_path: Path) -> None:
    """
    Resolve theme toggles before media staging and cloud generation, including for custom templates.

    Args:
        tmp_path (Path): Temporary rendering workspace.

    Returns:
        None: Hidden media needs no download, disabled clouds stay disabled, and templates receive overridden values.
    """
    style = Style(
        theme="print",
        themes={"print": {"show_header_photo": False, "skills_word_cloud": False, "accent": "A44813", "paper": "a4"}},
    )
    profile = Profile(
        "example-person",
        "Alex",
        images=[Media("https://example.org/cover.png", alt="Cover photo")],
        sections=[Section("skills", "Skills", [Entry("Python", skills=[Skill("Python", 3)])])],
    )
    config = Config(LinkedIn("example-person"), style=style)
    source = render_profile(profile, config, tmp_path)
    text = source.read_text()
    assert "a4paper" in text and "{A44813}" in text
    assert "Python" in text and "skills-" not in text
    assert not list((source.parent / "assets").iterdir())
    assert profile.images[0].path == "" and config.style.show_header_photo is True

    # A custom template must see exactly the same resolved values and filtered profile as the packaged template.
    (tmp_path / "custom.tex.j2").write_text("((( style.accent )))|((( style.paper )))|((( profile.images|length )))", encoding="utf-8")
    custom = render_profile(profile, evolve(config, template="custom.tex.j2"), tmp_path)
    assert custom.read_text() == "A44813|a4|0"


def test_cloud_palette_changes_colors_without_changing_layout_or_scores(tmp_path: Path) -> None:
    """
    Keep theme changes deterministic and independent of skill strengths and word positions.

    Args:
        tmp_path (Path): Temporary generated-assets directory.

    Returns:
        None: Themed pixels change while background masks, score manifests, and repeated output remain stable.
    """
    (tmp_path / "assets").mkdir()
    scores = {"Python": SkillScore(4, 3), "Kubernetes": SkillScore(2, 1), "Terraform": SkillScore(1, 0)}
    original_path = render_skill_cloud(scores, tmp_path)
    assert original_path is not None

    with Image.open(tmp_path / original_path) as image:
        original = image.convert("RGB")

    manifest = (tmp_path / "skills.weights.json").read_bytes()
    themed_path = render_skill_cloud(scores, tmp_path, colors=("6B2737", "C44A11"))
    assert themed_path is not None and themed_path != original_path

    with Image.open(tmp_path / themed_path) as image:
        themed = image.convert("RGB")

    # Every palette channel stays below white, so the white-pixel mask captures geometry independently of hue.
    white = Image.new("RGB", original.size, "white")
    original_mask = ImageChops.difference(original, white).convert("L").point(lambda value: 255 if value else 0)
    themed_mask = ImageChops.difference(themed, white).convert("L").point(lambda value: 255 if value else 0)
    assert original_mask.tobytes() == themed_mask.tobytes()
    assert (tmp_path / "skills.weights.json").read_bytes() == manifest
    assert json.loads(manifest)["Python"]["weight"] == 10
    assert render_skill_cloud(scores, tmp_path, colors=("6B2737", "C44A11")) == themed_path
    colored_path = render_skill_cloud(scores, tmp_path, colors=("6B2737",), background="FFF8F0")
    assert colored_path is not None

    with Image.open(tmp_path / colored_path) as image:
        assert image.getpixel((0, 0)) == (255, 248, 240)
