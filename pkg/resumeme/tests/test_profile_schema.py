"""
Exercise minimal, maximal, and unfamiliar profile content through schema and rendering.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from attrs import evolve
from jsonschema import ValidationError
from PIL import Image

from resumeme.compiler.asts.parsing import merge_profile_html, parse_detail, parse_profile
from resumeme.compiler.asts.profile import Entry, Profile, Section, Skill, load_profile, save_profile
from resumeme.compiler.asts.sections import SECTION_TITLES
from resumeme.compiler.pipeline import render_profile
from resumeme.config import Config, LinkedIn


@pytest.mark.parametrize("filename", ["profile-minimal.html", "profile-maximal.html"])
def test_profile_extremes_roundtrip_and_render(tmp_path: Path, filename: str) -> None:
    """
    Preserve both ends of the optional-section spectrum through capture parsing and rendering.

    Args:
        tmp_path (Path): Temporary project for the snapshot and generated artifacts.
        filename (str): Minimal or maximal synthetic browser fixture.

    Returns:
        None: Identity, sections, skills, and references survive without requiring optional content.
    """
    html = Path(__file__).with_name("fixtures").joinpath(filename).read_text(encoding="utf-8")
    profile = parse_profile(merge_profile_html([html]), "example-person")
    assert profile.name == "Alex Example"

    if filename == "profile-minimal.html":
        assert profile.sections == []
        assert profile.intro == []
    else:
        assert set(SECTION_TITLES) <= {section.key for section in profile.sections}
        assert "independent-studies" in {section.key for section in profile.sections}
        skills = next(section for section in profile.sections if section.key == "skills")
        assert [skill.endorsements for entry in skills.entries for skill in entry.skills] == [4, 2, 1, 99]
        job = next(section for section in profile.sections if section.key == "experience").entries[0]
        assert job.skills == [Skill("Python"), Skill("Leadership")]
        assert all("+3 skills" not in paragraph for paragraph in job.paragraphs)
        assert "Senior Engineer" in job.paragraphs
        assert "Unrelated Person" not in str(profile)

    Image.new("RGB", (10, 10), "blue").save(tmp_path / "image.png")
    profile = evolve(
        profile,
        images=[evolve(image, path="image.png") for image in profile.images],
        sections=[
            evolve(
                section,
                entries=[evolve(entry, images=[evolve(image, path="image.png") for image in entry.images]) for entry in section.entries],
            )
            for section in profile.sections
        ],
    )
    snapshot = tmp_path / "profile.json"
    save_profile(profile, snapshot)
    assert load_profile(snapshot, "example-person") == profile
    rendered = render_profile(profile, Config(LinkedIn("example-person")), tmp_path).read_text(encoding="utf-8")
    assert "Alex Example" in rendered

    if filename == "profile-minimal.html":
        assert r"\sectiontitle{" not in rendered.split(r"\begin{document}", 1)[1]
        assert json.loads((tmp_path / "tex/skills.weights.json").read_text()) == {}
    else:
        assert "SAMPLE-001" in rendered
        assert "SAMPLE-002" in rendered
        assert "future section remains readable" in rendered
        assert "assets/skills-" in rendered


def test_identity_only_json_uses_optional_defaults(tmp_path: Path) -> None:
    """
    Accept the base schema with no headline, photograph, sections, or schema-version field.

    Args:
        tmp_path (Path): Snapshot directory.

    Returns:
        None: Loading supplies empty optional containers and the supported schema version.
    """
    path = tmp_path / "profile.json"
    path.write_text('{"username": "example-person", "name": "Alex Example"}', encoding="utf-8")
    assert load_profile(path, "example-person") == Profile("example-person", "Alex Example")


@pytest.mark.parametrize("value", [-1, 1.5, "3", True])
def test_endorsement_schema_rejects_invalid_counts(tmp_path: Path, value: int | float | str | bool) -> None:
    """
    Reject fractional, negative, and coerced endorsement totals at the snapshot boundary.

    Args:
        tmp_path (Path): Snapshot directory.
        value (int | float | str | bool): Invalid endorsement total.

    Returns:
        None: Validation fails before skill scoring or rendering.
    """
    path = tmp_path / "profile.json"
    save_profile(
        Profile("example-person", "Alex", sections=[Section("skills", "Skills", [Entry("Python", skills=[Skill("Python")])])]), path
    )
    raw = json.loads(path.read_text())
    raw["sections"][0]["entries"][0]["skills"][0]["endorsements"] = value
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValidationError):
        load_profile(path, "example-person")


def test_explicit_empty_detail_state_is_valid() -> None:
    """
    Accept a loaded empty optional tab while retaining failure for an unparsed heading-only page.

    Returns:
        None: Empty recommendations are represented without manufacturing a text entry.
    """
    html = '<main><h2>Recommendations</h2><div class="artdeco-empty-state">No recommendations yet</div></main>'
    assert parse_detail(html, "recommendations", "Recommendations").entries == []

    with pytest.raises(ValueError):
        parse_detail("<main><h2>Recommendations</h2></main>", "recommendations", "Recommendations")


def test_header_without_section_wrapper_survives_scrolling() -> None:
    """
    Retain an otherwise empty profile in older markup without an introduction section wrapper.

    Returns:
        None: Virtualized snapshot merging retains the only visible identity.
    """
    html = "<main><h1>Alex Example</h1></main>"
    assert parse_profile(merge_profile_html([html]), "example-person") == Profile("example-person", "Alex Example")


def test_unwrapped_header_does_not_duplicate_optional_sections() -> None:
    """
    Keep section text out of the introduction so exclusions also remove it from skill scoring.

    Returns:
        None: A direct main heading retains only introduction text above its optional sections.
    """
    html = "<main><h1>Alex Example</h1><p>Engineer</p><section><h2>About</h2><p>Hidden #Rust</p></section></main>"
    profile = parse_profile(html, "example-person")
    assert profile.intro == ["Engineer"]
    assert profile.sections[0].entries[0].title == "Hidden #Rust"


def test_recommendation_toggle_controls_cannot_replace_recommendation_text() -> None:
    """
    Ignore generated toggle wrappers when meaningful recommendation cards lack stable attributes.

    Returns:
        None: Complete recommendation prose survives the generic content fallback.
    """
    html = '<main><p>Recommendations</p><div componentkey="a0d4cba4-831e-4617-9275-039b37a95e70">'
    html += '<label for="received">Received</label><input id="received" type="checkbox"><span>Off</span></div>'
    html += "<div><p>Sam Example</p><p>Colleague</p><p>Thoughtful engineering leadership.</p></div></main>"
    section = parse_detail(html, "recommendations", "Recommendations")
    assert section.entries[0].title == "Sam Example"
    assert "Off" not in str(section)
    assert "Thoughtful engineering leadership." in section.entries[0].paragraphs
