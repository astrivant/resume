"""
Verify school and qualification exclusions across configuration and compiler consumers.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from attrs import evolve
from jsonschema import ValidationError

from resumeme.compiler.asts.parsing import parse_detail
from resumeme.compiler.asts.profile import Entry, Link, Media, Profile, Section, Skill
from resumeme.compiler.passes.education import filter_education
from resumeme.compiler.passes.summary import summary_digest, summary_evidence
from resumeme.compiler.passes.visibility import visible_profile
from resumeme.compiler.pipeline import render_profile
from resumeme.config import Config, Education, EducationSelector, LinkedIn, load_config
from resumeme.visualization.skills import skill_scores

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    "selector,retained",
    [
        (EducationSelector(school=" example  UNIVERSITY "), [2]),
        (EducationSelector(degree="associate's degree"), [1]),
        (EducationSelector(major="mathematics"), [1]),
        (EducationSelector(school="Example University", major="Mathematics"), [1, 2]),
        (EducationSelector(school="Example University", degree="Bachelor of Science", major="Physics"), [0, 2]),
        (EducationSelector(school="Other School", degree="Bachelor of Science"), [0, 1, 2]),
        (EducationSelector(school="University"), [0, 1, 2]),
        (EducationSelector(major="Math"), [0, 1, 2]),
        (EducationSelector(degree="Associate\u2019s Degree, Mathematics"), [1]),
    ],
)
def test_selectors_match_complete_fields(selector: EducationSelector, retained: list[int]) -> None:
    """
    Combine selector fields without confusing substring matches or degrees at different schools.

    Args:
        selector (EducationSelector): Literal school or qualification exclusion.
        retained (list[int]): Expected source indices after filtering.

    Returns:
        None: Matching entries are removed in full and remaining records retain their order and identity.
    """
    entries = [
        Entry("Example University", ["Associate\u2019s Degree, Mathematics", "2015 \u2013 2016"]),
        Entry("Example University", ["Bachelor of Science, Physics", "2016 \u2013 2020"]),
        Entry("Other School", ["Associate\u2019s Degree, Mathematics", "2015 \u2013 2016"]),
    ]
    selected = filter_education(entries, Education(disable=[selector]))
    assert selected == [entries[index] for index in retained]

    for entry, index in zip(selected, retained, strict=True):
        assert entry is entries[index]


@pytest.mark.parametrize(
    "paragraphs,selector,excluded",
    [
        ([], EducationSelector(degree="Bachelor"), False),
        ([], EducationSelector(school="Example"), True),
        (["2013 \u2013 2014", "Physics"], EducationSelector(major="Physics"), False),
        (["2013 \u2013 2014"], EducationSelector(degree="2013 \u2013 2014"), False),
        (["Physics"], EducationSelector(major="Physics"), True),
        (["Bachelor"], EducationSelector(degree="Bachelor"), True),
        (["BSc, Physics\n2013 \u2013 2014"], EducationSelector(major="Physics"), True),
        (["BSc, Physics", "Research in Mathematics"], EducationSelector(major="Mathematics"), False),
        (["BSc, Physics, Astronomy"], EducationSelector(major="Physics, Astronomy"), True),
        (["BSc, Physics, Astronomy"], EducationSelector(major="Astronomy"), False),
    ],
)
def test_qualification_boundaries_are_conservative(paragraphs: list[str], selector: EducationSelector, excluded: bool) -> None:
    """
    Match only the leading qualification metadata, preserving absent fields and descriptive text boundaries.

    Args:
        paragraphs (list[str]): Captured metadata and optional prose.
        selector (EducationSelector): Requested degree, major, or school exclusion.
        excluded (bool): Whether the metadata justifies removing the entry.

    Returns:
        None: Missing fields and body mentions do not accidentally exclude education.
    """
    entry = Entry("Example", paragraphs)
    assert filter_education([entry], Education(disable=[selector])) == ([] if excluded else [entry])


def test_capture_and_multiple_exclusions() -> None:
    """
    Apply alternative selectors to metadata produced by the existing HTML parser.

    Returns:
        None: Either matching selector removes its school without changing the captured section.
    """
    section = parse_detail(
        """<main><ul class="pvs-list">
        <li><div>Example University</div><div>Associate\u2019s Degree, Mathematics</div><div>2015 \u2013 2016</div></li>
        <li><div>Other School</div><div>BSc, Physics</div><div>2016 \u2013 2020</div></li>
        </ul></main>""",
        "education",
        "Education",
    )
    assert len(section.entries) == 2
    settings = Education(disable=[EducationSelector(degree="Associate's Degree"), EducationSelector(school="Other School")])
    assert filter_education(section.entries, settings) == []
    assert len(section.entries) == 2
    assert filter_education([], settings) == []
    assert filter_education(section.entries, Education()) == section.entries


def test_exclusions_reach_rendering_assets_skills_and_summaries(tmp_path: Path) -> None:
    """
    Keep excluded education out of every consumer while preserving the original snapshot.

    Args:
        tmp_path (Path): Isolated rendering directory; excluded remote images deliberately have no local files.

    Returns:
        None: Filters affect both template paths and generation evidence without modifying independent experience.
    """
    hidden = Entry(
        "Hidden School",
        ["BSc, Private Major", "Private academic history"],
        links=[Link("Hidden project", "https://github.com/example/hidden")],
        images=[Media("https://example.org/missing-school.png")],
        skills=[Skill("PrivateSkill", 9)],
    )
    shown = Entry("Visible School", ["BA, History"])
    job = Entry("Engineer", ["Hidden School \u00b7 Full-time", "2020 \u2013 Present"])
    profile = Profile(
        "example-person",
        "Alex",
        sections=[Section("education", "Education", [hidden, shown]), Section("experience", "Experience", [job])],
    )
    config = Config(LinkedIn(profile.username), education=Education(disable=[EducationSelector(school="Hidden School")]))
    visible = visible_profile(profile, config)
    assert visible.sections[0].entries == [shown]
    assert visible.sections[1].entries == [job]
    assert "PrivateSkill" not in skill_scores(visible)
    evidence = json.dumps(summary_evidence(profile, config))
    assert "Private academic history" not in evidence
    assert "PrivateSkill" not in evidence
    assert summary_digest(profile, config) != summary_digest(profile, evolve(config, education=Education()))

    # Missing excluded assets must not block either the packaged template or a caller's custom template.
    custom = tmp_path / "custom.tex.j2"
    custom.write_text("((( profile.sections )))", encoding="utf-8")

    for template in (None, custom.name):
        source = render_profile(profile, evolve(config, template=template), tmp_path).read_text()
        assert "Visible School" in source
        assert "Private Major" not in source
        assert "example/hidden" not in source
        assert "PrivateSkill" not in source

    # Re-enabling remains lossless because filtering never edits the stored entry or its associated media.
    assert profile.sections[0].entries == [hidden, shown]
    assert visible_profile(profile, evolve(config, education=Education())).sections[0].entries == [hidden, shown]


def test_empty_and_disabled_sections_leave_no_heading_or_navigation(tmp_path: Path) -> None:
    """
    Treat minimal profiles and fully filtered education as ordinary empty sections.

    Args:
        tmp_path (Path): Temporary generated source directory.

    Returns:
        None: Empty education never introduces a heading, contents entry, or rendering failure.
    """
    config = Config(LinkedIn("example-person"), education=Education(disable=[EducationSelector(school="Example")]))

    for entries in ([], [Entry("Example")]):
        profile = Profile("example-person", "Alex", sections=[Section("education", "Education", entries)])
        source = render_profile(profile, config, tmp_path).read_text()
        assert "Education" not in source

    hidden = evolve(config, section_order=["about"], education=Education())
    assert visible_profile(profile, hidden).sections == []


@pytest.mark.parametrize(
    "settings",
    [
        "null",
        "{disable: true}",
        "{disable: [Example]}",
        "{disable: [{}]}",
        "{disable: [{school: ' '}]}",
        "{disable: [{degree: null}]}",
        "{disable: [{major: false}]}",
        "{disable: [{university: Example}]}",
        "{disable: [{school: Example}, {school: Example}]}",
        "{last_years: 5}",
    ],
)
def test_invalid_education_configuration_is_rejected(tmp_path: Path, settings: str) -> None:
    """
    Reject ambiguous, mistyped, or unknown education filters at the configuration boundary.

    Args:
        tmp_path (Path): Temporary configuration root.
        settings (str): Invalid YAML education value.

    Returns:
        None: Configuration errors fail before filtering or asset processing begins.
    """
    path = tmp_path / "resumeme.config.yaml"
    path.write_text(f"linkedin:\n  username: example-person\neducation: {settings}\n", encoding="utf-8")

    with pytest.raises(ValidationError):
        load_config(path)


def test_education_config_defaults_and_roundtrip(tmp_path: Path) -> None:
    """
    Preserve username-only defaults and load selectors through the strict schema and attrs converter.

    Args:
        tmp_path (Path): Temporary configuration root.

    Returns:
        None: Education stays visible by default and documented selectors retain their field values.
    """
    path = tmp_path / "resumeme.config.yaml"
    path.write_text("linkedin:\n  username: example-person\n", encoding="utf-8")
    assert load_config(path).education == Education()

    with path.open("a", encoding="utf-8") as stream:
        stream.write("education:\n  disable:\n    - school: Example\n    - degree: Bachelor's Degree\n      major: Physics\n")

    assert load_config(path).education == Education(
        [EducationSelector(school="Example"), EducationSelector(degree="Bachelor's Degree", major="Physics")]
    )
