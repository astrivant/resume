"""
Verify phrase-aware skill scoring, endorsement weights, exclusions, and deterministic graphics.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from attrs import evolve
from PIL import Image

from resumeme.compiler.asts.profile import Entry, Link, Profile, Section, Skill
from resumeme.compiler.asts.skills import endorsement_count
from resumeme.compiler.pipeline import render_profile
from resumeme.config import Capture, Config, LinkedIn
from resumeme.linkedin.browser import parse_detail_after_expansion
from resumeme.visualization.skills import SkillScore, endorsement_colors, render_skill_cloud, skill_scores

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch


def test_endorsement_colors_use_relative_counts_not_references_or_spelling() -> None:
    """
    Map zero, intermediate, and maximum endorsements to ordered palette stops.

    Returns:
        None: Equal endorsement counts share a color and reference-heavy skills do not acquire a stronger endorsement color.
    """
    scores = {
        "References only": SkillScore(100, 0),
        "One quarter": SkillScore(1, 1),
        "One half": SkillScore(1, 2),
        "Another half": SkillScore(40, 2),
        "Maximum": SkillScore(1, 4),
    }
    colors = endorsement_colors(scores, ("808080", "404040", "000000"))
    assert colors == {
        "References only": "#808080",
        "One quarter": "#606060",
        "One half": "#404040",
        "Another half": "#404040",
        "Maximum": "#000000",
    }
    assert endorsement_colors(dict(reversed(list(scores.items()))), ("808080", "404040", "000000")) == colors


def test_missing_endorsements_and_single_color_palettes_remain_defined() -> None:
    """
    Handle empty, zero-endorsement, and explicitly monochrome skill clouds.

    Returns:
        None: Zero counts use the low stop and a single stop applies to every endorsement level.
    """
    scores = {"Python": SkillScore(4, 0), "Rust": SkillScore(1, 0)}
    assert endorsement_colors(scores, ("808080", "202020")) == {"Python": "#808080", "Rust": "#808080"}
    assert endorsement_colors({"Python": SkillScore(4, 9), "Rust": SkillScore(1, 0)}, ("6B2737",)) == {
        "Python": "#6b2737",
        "Rust": "#6b2737",
    }
    assert endorsement_colors({}, ("808080", "202020")) == {}


def test_scores_combine_references_tags_and_endorsements() -> None:
    """
    Count declarations and references once while adding twice the largest endorsement total.

    Returns:
        None: Duplicate endorsement displays, mirrored link labels, and job tags do not inflate scores.
    """
    profile = Profile(
        "example-person",
        "Alex",
        intro=["Python engineer · #DevOps"],
        sections=[
            Section("skills", "Skills", [Entry("Python", ["3 endorsements", "3 endorsements"]), Entry("PYTHON", ["2 endorsements"])]),
            Section(
                "experience",
                "Experience",
                [
                    Entry(
                        "Engineer",
                        ["Python and pythonic systems"],
                        [Link("Python and pythonic systems", "https://example.org")],
                        skills=[Skill("Python"), Skill("Rust")],
                    )
                ],
            ),
            Section("projects", "Projects", [Entry("Rust and RUST tools")]),
        ],
    )
    scores = skill_scores(profile)
    assert scores["Python"] == SkillScore(references=3, endorsements=3)
    assert scores["Python"].weight == 9
    assert scores["Rust"] == SkillScore(references=3, endorsements=0)
    assert scores["DevOps"] == SkillScore(references=1, endorsements=0)
    assert set(scores) == {"Python", "Rust", "DevOps"}


def test_multiword_and_punctuated_skills_remain_distinct() -> None:
    """
    Match complete skill phrases without counting prefixes or splitting language names.

    Returns:
        None: C, C++, C#, Java, JavaScript, and multiword phrases retain separate frequencies.
    """
    names = ["C", "C++", "C#", "Java", "JavaScript", ".NET", "Machine Learning"]
    profile = Profile(
        "example-person",
        "Alex",
        intro=["C++ and C# on .NET; JavaScript and machine learning. JavaScripted isn't JavaScript."],
        sections=[Section("skills", "Skills", [Entry(name) for name in names])],
    )
    scores = skill_scores(profile)
    assert scores["C"].references == scores["Java"].references == 1
    assert scores["C++"].references == scores["C#"].references == scores[".NET"].references == 2
    assert scores["JavaScript"].references == 3
    assert scores["Machine Learning"].references == 2


def test_endorsement_total_ignores_dates_and_uses_visible_lower_bound() -> None:
    """
    Read only displayed endorsement totals and avoid inventing counts behind a plus suffix.

    Returns:
        None: Repeated and unrelated numbers do not increase the observed endorsement total.
    """
    assert endorsement_count(["2025", "4 experiences", "99+ endorsements", "99+ endorsements"]) == 99
    assert endorsement_count(["1,234 endorsements", "Endorsed by 50 colleagues"]) == 1234
    assert endorsement_count(["Endorsed by a colleague", "5 experiences"]) == 0


def test_virtualized_skill_snapshots_keep_the_largest_endorsement_total(monkeypatch: MonkeyPatch) -> None:
    """
    Merge repeated skill observations without summing totals or losing an earlier count.

    Args:
        monkeypatch (MonkeyPatch): Replaces browser expansion with deterministic HTML observations.

    Returns:
        None: The merged skill retains the highest visible count across virtualized snapshots.
    """
    snapshots = [
        '<main><h2>Skills</h2><li class="artdeco-list__item"><p>Python</p>'
        f'<button aria-label="{count} endorsements">Endorse</button></li></main>'
        for count in [5, 1]
    ]
    monkeypatch.setattr("resumeme.linkedin.browser._expand", MagicMock(return_value=snapshots))
    section = parse_detail_after_expansion(MagicMock(), "skills", "Skills", Capture())
    assert section.entries[0].skills == [Skill("Python", 5)]


def test_section_exclusions_apply_before_cloud_scoring(tmp_path: Path) -> None:
    """
    Keep hidden sections out of both the image and its score manifest, including section aliases.

    Args:
        tmp_path (Path): Temporary output directory.

    Returns:
        None: A hidden certification contributes no skill, reference, endorsement, or rendered text.
    """
    profile = Profile(
        "example-person",
        "Alex",
        sections=[
            Section("skills", "Skills", [Entry("Python", skills=[Skill("Python", 2)])]),
            Section(
                "licenses-certifications", "Licenses & certifications", [Entry("Python certificate", skills=[Skill("Secret tooling", 100)])]
            ),
        ],
    )
    config = Config(LinkedIn("example-person"), disable=["licenses-and-certifications"])
    source = render_profile(profile, config, tmp_path)
    scores = json.loads((source.parent / "skills.weights.json").read_text())
    assert scores == {"Python": {"references": 1, "endorsements": 2, "weight": 5}}
    assert "Secret tooling" not in source.read_text()
    assert profile.sections[1].entries[0].skills == [Skill("Secret tooling", 100)]
    render_profile(profile, evolve(config, disable=["skills", "certifications"]), tmp_path)
    assert json.loads((source.parent / "skills.weights.json").read_text()) == {}
    assert not list((source.parent / "assets").glob("skills-*.png"))
    assert "assets/skills-" not in source.read_text()


def test_cloud_can_be_replaced_by_the_original_skills_list(tmp_path: Path) -> None:
    """
    Retain the text rendering option without requiring another capture.

    Args:
        tmp_path (Path): Temporary project directory.

    Returns:
        None: The disabled cloud leaves the original skill list and endorsement text visible.
    """
    profile = Profile("example-person", "Alex", sections=[Section("skills", "Skills", [Entry("Python", ["3 endorsements"])])])
    config = Config(LinkedIn("example-person"))
    source = render_profile(profile, evolve(config, style=evolve(config.style, skills_word_cloud=False)), tmp_path)
    assert "3 endorsements" in source.read_text()
    assert "assets/skills-" not in source.read_text()


def test_tags_can_generate_a_cloud_without_a_skills_section(tmp_path: Path) -> None:
    """
    Aggregate explicit job tags on sparse profiles without adding unrelated prose as skills.

    Args:
        tmp_path (Path): Temporary project directory.

    Returns:
        None: An enabled generated Skills card appears only when there are known skills or hashtags.
    """
    profile = Profile("example-person", "Alex", sections=[Section("experience", "Experience", [Entry("Engineer", skills=[Skill("Rust")])])])
    config = Config(LinkedIn("example-person"))
    source = render_profile(profile, config, tmp_path)
    assert "assets/skills-" in source.read_text()
    assert r"\sectiontitle{Skills}" in source.read_text()
    render_profile(profile, evolve(config, disable=["skills"]), tmp_path)
    assert r"\sectiontitle{Skills}" not in source.read_text()


def test_cloud_pixels_and_scores_are_reproducible(tmp_path: Path) -> None:
    """
    Render every label with stable pixels and an auditable sidecar without a graphical display.

    Args:
        tmp_path (Path): Temporary TeX directory.

    Returns:
        None: Repeated generation produces identical PNG bytes and the expected score manifest.
    """
    (tmp_path / "assets").mkdir()
    scores = {"Python": SkillScore(4, 3), "Machine Learning": SkillScore(2, 0), "C++": SkillScore(1, 1)}
    image_path = render_skill_cloud(scores, tmp_path)
    assert image_path is not None
    original = (tmp_path / image_path).read_bytes()
    assert render_skill_cloud(scores, tmp_path) == image_path
    assert (tmp_path / image_path).read_bytes() == original

    with Image.open(tmp_path / image_path) as image:
        assert image.size == (1800, 800)
        assert image.getextrema() != ((255, 255), (255, 255), (255, 255))

    assert json.loads((tmp_path / "skills.weights.json").read_text())["Python"]["weight"] == 10


def test_cloud_limits_display_to_twenty_skills_and_preserves_all_scores(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Select the strongest twenty labels with stable ties while retaining the complete audit manifest.

    Args:
        tmp_path (Path): Temporary TeX directory.
        monkeypatch (MonkeyPatch): Replaces the layout engine to inspect its selected labels.

    Returns:
        None: Endorsements affect selection, input order does not break ties, and omitted scores remain available.
    """

    # Reverse the input names and append the strongest skills so selection cannot depend on insertion order.
    scores = {f"Skill {index:02}": SkillScore(1, 0) for index in reversed(range(25))}
    scores["Endorsed"] = SkillScore(1, 2)
    scores["Referenced"] = SkillScore(4, 0)
    original = scores.copy()
    expected = ["Endorsed", "Referenced", *(f"Skill {index:02}" for index in range(18))]
    (tmp_path / "assets").mkdir()

    # Report a complete twenty-label layout; the renderer must accept it without retrying for the seven intentionally omitted skills.
    factory = MagicMock()
    cloud = factory.return_value
    cloud.generate_from_frequencies.return_value = cloud
    cloud.layout_ = [object() for _ in expected]
    cloud.to_image.return_value = Image.new("RGB", (1800, 800), "white")
    monkeypatch.setattr("resumeme.visualization.skills.WordCloud", factory)
    image_path = render_skill_cloud(scores, tmp_path)
    assert image_path is not None
    assert (tmp_path / image_path).is_file()
    factory.assert_called_once()
    cloud.generate_from_frequencies.assert_called_once()
    assert factory.call_args.kwargs["max_words"] == 20
    color = factory.call_args.kwargs["color_func"]
    assert color("Endorsed") == "#363636"
    assert color("Referenced") == "#777777"
    assert list(cloud.generate_from_frequencies.call_args.args[0]) == expected
    assert scores == original

    # Capping the visual must not discard evidence or change the scoring formula in the sidecar.
    manifest = json.loads((tmp_path / "skills.weights.json").read_text())
    assert set(manifest) == set(scores)
    assert manifest["Endorsed"]["weight"] == 5
    assert manifest["Skill 24"] == {"references": 1, "endorsements": 0, "weight": 1}
