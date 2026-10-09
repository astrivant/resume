"""
Verify evidence-backed skill expansion, visibility, and scoring at the compiler boundary.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from resumeme.compiler.asts.profile import Entry, Link, Profile, Section, Skill
from resumeme.compiler.asts.skills import skill_labels
from resumeme.compiler.constants.sections import DEFAULT_SECTION_ORDER
from resumeme.compiler.passes.skills import expand_skill_summaries
from resumeme.compiler.pipeline import render_profile
from resumeme.config import Config, LinkedIn, Style
from resumeme.visualization.skills import SkillScore, skill_scores

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import LogCaptureFixture


@pytest.mark.parametrize(
    "summary",
    ["Python, Bash and +2 skills", "Python, Bash, +2 skills", "Python, Bash + 2 skills", "Python, Bash and \uff0b2\u00a0SKILLS"],
)
def test_reverse_associations_expand_summary_and_link(summary: str) -> None:
    """
    Recover hidden project skills from complete, uniquely matched reverse associations.

    Args:
        summary (str): Collapsed LinkedIn summary with punctuation or Unicode spacing variations.

    Returns:
        None: Names appear once, links retain destinations, and the source and second pass remain stable.
    """
    project = Entry("pass-operator", paragraphs=[summary], links=[Link(summary, "https://example.org/skills")])
    profile = Profile(
        "example-person",
        "Alex",
        sections=[
            Section("projects", "Projects", [project]),
            Section(
                "skills",
                "Skills",
                [
                    Entry("Information Security", ["PASS-OPERATOR"]),
                    Entry("Kubernetes", ["pass-operator"], skills=[Skill("Kubernetes", 3)]),
                    Entry("kubernetes", ["pass-operator"], skills=[Skill("kubernetes", 1)]),
                    Entry("Unrelated", ["Used pass-operator during another project"]),
                ],
            ),
        ],
    )
    expanded = expand_skill_summaries(profile)
    entry = expanded.sections[0].entries[0]
    expected = "Python, Bash, Information Security, Kubernetes"
    assert entry.paragraphs == [expected]
    assert entry.links == [Link(expected, "https://example.org/skills")]
    assert entry.skills == [Skill("Python"), Skill("Bash"), Skill("Information Security"), Skill("Kubernetes", 3)]
    assert skill_scores(expanded)["Kubernetes"] == SkillScore(2, 3)
    assert project.paragraphs == [summary]
    assert project.skills == []
    assert expand_skill_summaries(expanded) == expanded
    assert skill_labels(summary) == [Skill("Python"), Skill("Bash")]


@pytest.mark.parametrize("summary", ["Python and +1 skill", "Skills: Python and +1 skill", "+2 skills", "Python and +1 more skill"])
def test_structured_tags_expand_any_section(summary: str) -> None:
    """
    Support optional profile sections and count-only summaries without a Skills section.

    Args:
        summary (str): Collapsed singular, plural, labeled, or count-only row.

    Returns:
        None: Only recorded tags supply names, with the optional Skills prefix retained.
    """
    profile = Profile(
        "example-person",
        "Alex",
        sections=[Section("education", "Education", [Entry("School", [summary], skills=[Skill("Python"), Skill("C++")])])],
    )
    expanded = expand_skill_summaries(profile).sections[0].entries[0]
    assert expanded.paragraphs == [("Skills: " if summary.startswith("Skills:") else "") + "Python, C++"]


def test_incomplete_and_ambiguous_evidence_stays_explicit(caplog: LogCaptureFixture) -> None:
    """
    Reject title collisions and unrelated skills instead of guessing missing names.

    Args:
        caplog (LogCaptureFixture): Captures actionable incomplete-summary diagnostics.

    Returns:
        None: The original count remains when captured names cannot account for the remainder.
    """
    summary = "Python and +2 skills"
    profile = Profile(
        "example-person",
        "Alex",
        sections=[
            Section("projects", "Projects", [Entry("Shared", [summary], skills=[Skill("Python"), Skill("C++")]), Entry("Shared")]),
            Section("skills", "Skills", [Entry("Kubernetes", ["Shared"]), Entry("Unrelated")]),
        ],
    )
    expanded = expand_skill_summaries(profile)
    assert expanded.sections[0].entries[0].paragraphs == [summary]
    assert "only 1 of 2 hidden names captured" in caplog.text
    assert Skill("Kubernetes") not in expanded.sections[0].entries[0].skills


def test_grouped_jobs_keep_tags_out_of_descriptions() -> None:
    """
    Rewrite nested employment consistently without leaking one role's skills into another.

    Returns:
        None: Structured and flattened prose omit tag rows while role ownership survives.
    """
    first = Entry("Senior", ["Python and +1 skill"], skills=[Skill("Python"), Skill("Leadership")])
    second = Entry("Junior", ["C++ and +1 skill"], skills=[Skill("C++"), Skill("Testing")])
    company = Entry("Company", [first.title, *first.paragraphs, second.title, *second.paragraphs], positions=[first, second])
    profile = Profile("example-person", "Alex", sections=[Section("experience", "Experience", [company])])
    expanded = expand_skill_summaries(profile).sections[0].entries[0]
    assert expanded.paragraphs == ["Senior", "Junior"]
    assert [position.paragraphs for position in expanded.positions] == [[], []]
    assert expanded.positions[0].skills == first.skills
    assert expanded.positions[1].skills == second.skills
    assert company.paragraphs == ["Senior", "Python and +1 skill", "Junior", "C++ and +1 skill"]


def test_minimal_profile_and_unrelated_counts_remain_unchanged() -> None:
    """
    Leave ordinary prose, endorsement totals, and non-skill summaries outside this pass.

    Returns:
        None: No-op profiles require neither optional sections nor synthetic skill declarations.
    """
    profile = Profile("example-person", "Alex")
    assert expand_skill_summaries(profile) == profile
    paragraphs = ["Used +2 skills in a workshop", "99+ endorsements", "2 experiences at Company and 1 other company", "C++"]
    profile.sections.append(Section("about", "About", [Entry("About", paragraphs)]))
    assert expand_skill_summaries(profile) == profile


def test_pipeline_expands_before_scoring_and_honors_visibility(tmp_path: Path) -> None:
    """
    Integrate project expansion with section exclusions, cloud weights, and template emission.

    Args:
        tmp_path (Path): Isolated output directory for rendered source and score manifests.

    Returns:
        None: Expanded names contribute to the cloud without appearing in tiles; hidden sections remain excluded.
    """
    profile = Profile(
        "example-person",
        "Alex",
        sections=[
            Section("projects", "Projects", [Entry("Demo", ["Python and +1 skill"])]),
            Section("skills", "Skills", [Entry("Testing", ["Demo"])]),
            Section("certifications", "Certifications", [Entry("Private", ["Python and +1 skill"], skills=[Skill("Private skill", 100)])]),
        ],
    )
    config = Config(
        LinkedIn("example-person"),
        section_order=[key for key in DEFAULT_SECTION_ORDER if key not in (["certifications"])],
        project_filter=None,
    )
    source = render_profile(profile, config, tmp_path)
    assert "Python, Testing" not in source.read_text()
    assert "+1 skill" not in source.read_text()
    scores = json.loads((source.parent / "skills.weights.json").read_text())
    assert scores["Testing"] == {"references": 2, "endorsements": 0, "weight": 2}
    assert "Private skill" not in scores

    # Excluding the lookup section cannot resurrect its names, even when ordinary project content stays visible.
    config = Config(
        LinkedIn("example-person"),
        section_order=[key for key in DEFAULT_SECTION_ORDER if key not in (["skills", "certifications"])],
        style=Style(skills_word_cloud=False),
        project_filter=None,
    )
    source = render_profile(profile, config, tmp_path)
    assert "Python and +1 skill" not in source.read_text()
    assert "Testing" not in source.read_text()
