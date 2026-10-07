"""
Verify name and affiliation selection across project consolidation and its consumers.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
import yaml
from attrs import evolve
from jsonschema import ValidationError

from resumeme.compiler.asts.profile import Entry, Link, Media, Profile, Section, Skill
from resumeme.compiler.constants.links import DEFAULT_PROJECT_FILTER
from resumeme.compiler.passes.projects import consolidate_projects
from resumeme.compiler.passes.summary import summary_digest, summary_evidence
from resumeme.compiler.pipeline import render_profile
from resumeme.config import Config, LinkedIn, Projects, ProjectSelector, load_config

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("include", [None, [], [{"name": "Tool"}], [{"name": "Tool", "affiliation": "Example Co."}]])
def test_project_include_configuration(tmp_path: Path, include: list[dict[str, str]] | None) -> None:
    """
    Load explicit selectors while retaining existing behavior for minimal configurations.

    Args:
        tmp_path (Path): Isolated configuration directory.
        include (list[dict[str, str]] | None): Valid serialized selection.

    Returns:
        None: Null and omission keep all names; a list structures typed selectors without coercion.
    """
    path = tmp_path / "resumeme.config.yaml"
    path.write_text("linkedin: {username: example-person}\n", encoding="utf-8")
    assert load_config(path).projects == Projects()
    path.write_text(yaml.safe_dump({"linkedin": {"username": "example-person"}, "projects": {"include": include}}), encoding="utf-8")
    config = load_config(path)
    assert config.projects.include == (None if include is None else [ProjectSelector(**item) for item in include])
    assert config.project_filter == DEFAULT_PROJECT_FILTER


@pytest.mark.parametrize(
    "include",
    [
        False,
        "Tool",
        ["Tool"],
        [{}],
        [{"affiliation": "Acme"}],
        [{"name": " "}],
        [{"name": 3}],
        [{"name": "Tool", "affiliation": " "}],
        [{"name": "Tool", "affiliation": None}],
        [{"name": "Tool", "company": "Acme"}],
    ],
)
def test_invalid_project_selectors_fail_schema_validation(tmp_path: Path, include: object) -> None:
    """
    Reject empty selectors, unknown fields, and coerced or ambiguous values.

    Args:
        tmp_path (Path): Isolated configuration directory.
        include (object): Invalid serialized selector or collection.

    Returns:
        None: Invalid values fail before rendering rather than silently broadening selection.
    """
    path = tmp_path / "resumeme.config.yaml"
    path.write_text(yaml.safe_dump({"linkedin": {"username": "example-person"}, "projects": {"include": include}}), encoding="utf-8")

    with pytest.raises(ValidationError):
        load_config(path)


@pytest.mark.parametrize("linked", [False, True])
@pytest.mark.parametrize("affiliation", [None, "  second   COMPANY. "])
def test_same_name_projects_keep_distinct_company_identity(linked: bool, affiliation: str | None) -> None:
    """
    Select a complete name and optional organization without combining unrelated descriptions.

    Args:
        linked (bool): Whether projects have distinct source URLs or are both unlinked.
        affiliation (str | None): Optional company restriction; omission includes both namesakes.

    Returns:
        None: Name matching ignores case and whitespace, while affiliation narrows the selection exactly.
    """
    entries = [
        Entry(
            "Deployment platform",
            [f"Associated with {company} Company", f"{company} description"],
            [Link("Source", f"https://github.com/{company}/platform")] if linked else [],
        )
        for company in ["First", "Second"]
    ]
    entries.append(Entry("Deployment platform extra", ["Associated with Second Company"]))
    profile = Profile("example-person", "Alex", sections=[Section("projects", "Projects", entries)])
    selected, _ = consolidate_projects(profile, enabled=True, include=[ProjectSelector(" deployment   PLATFORM ", affiliation)])
    expected = entries[:2] if affiliation is None else entries[1:2]
    assert selected.sections[0].entries == expected
    assert profile.sections[0].entries == entries


def test_affiliation_guides_unlinked_descriptions_to_the_correct_role_attachment() -> None:
    """
    Enrich same-named projects at separate companies before applying both selectors and URL filters.

    Returns:
        None: The selected project retains its own explicit description, role provenance, and source link only.
    """
    roles = [
        Entry("Engineer", [f"{company} \u00b7 Full-time", "2024 - Present"], [Link("Tool", f"https://github.com/{company}/tool")])
        for company in ["First", "Second"]
    ]
    profile = Profile(
        "example-person",
        "Alex",
        sections=[
            Section(
                "projects",
                "Projects",
                [Entry("tool", [f"Associated with {company}", f"{company} description"]) for company in ["First", "Second"]],
            ),
            Section("experience", "Experience", roles),
        ],
    )
    selected, _ = consolidate_projects(
        profile, enabled=True, project_filter=DEFAULT_PROJECT_FILTER, include=[ProjectSelector("tool", "Second")]
    )
    project = selected.sections[0].entries[0]
    assert project.paragraphs == ["Associated with Second", "Second description", "Associated with Engineer at Second"]
    assert project.links[0].url == "https://github.com/Second/tool"
    rejected, _ = consolidate_projects(profile, enabled=True, project_filter=r"/First/", include=[ProjectSelector("tool", "Second")])
    assert not any(section.key == "projects" for section in rejected.sections)


def test_grouped_role_affiliations_survive_featured_deduplication() -> None:
    """
    Match organizations learned from grouped employment while retaining shared Featured evidence.

    Returns:
        None: A resolved URL still identifies one project even when multiple companies or posts reference it.
    """
    url = "https://github.com/example/tool"
    role = Entry("Staff Engineer", links=[Link("Tool", url)])
    profile = Profile(
        "example-person",
        "Alex",
        sections=[
            Section(
                "experience",
                "Experience",
                [Entry(company, [role.title], links=role.links, positions=[role]) for company in ["First Company", "Second Company"]],
            ),
            Section("featured", "Featured", [Entry("Post", ["Ordinary post text"], [Link("Tool", "https://lnkd.in/tool", url)])]),
        ],
    )
    selected, _ = consolidate_projects(profile, enabled=True, include=[ProjectSelector("tool", "Second Company")])
    projects = next(section.entries for section in selected.sections if section.key == "projects")
    assert len(projects) == 1
    assert projects[0].paragraphs == [
        "Associated with Staff Engineer at First Company",
        "Associated with Staff Engineer at Second Company",
        "Featured project",
    ]
    assert len(projects[0].links) == 1


def test_unknown_affiliation_and_prose_cannot_join_or_select_different_employers() -> None:
    """
    Leave ambiguous descriptions unassigned instead of guessing their company from a mention.

    Returns:
        None: A selector needs captured association evidence and an unknown title cannot bridge companies.
    """
    entries = [
        Entry("Tool", ["First Company and Second Company used this tool."]),
        Entry("Tool", ["Associated with First Company"]),
        Entry("Tool", ["Associated with Second Company"]),
    ]
    profile = Profile("example-person", "Alex", sections=[Section("projects", "Projects", entries)])
    selected, _ = consolidate_projects(profile, enabled=True, include=[ProjectSelector("Tool", "First Company")])
    assert selected.sections[0].entries == entries[1:2]
    unchanged, _ = consolidate_projects(profile, enabled=True)
    assert unchanged.sections[0].entries == entries


@pytest.mark.parametrize("custom", [False, True])
def test_selection_precedes_media_skills_navigation_and_summary(tmp_path: Path, custom: bool) -> None:
    """
    Keep excluded project content out of rendering and summary evidence without changing source snapshots.

    Args:
        tmp_path (Path): Isolated render directory.
        custom (bool): Whether to inspect a custom-template profile or the packaged LaTeX.

    Returns:
        None: Excluded tiles do not stage missing images, contribute skill scores, or enter generated summaries.
    """
    kept = Entry("Tool", ["Associated with Kept Company", "Selected description"], [Link("Source", "https://github.com/kept/tool")])
    excluded = Entry(
        "Tool",
        ["Associated with Excluded Company", "Excluded description"],
        [Link("Source", "https://github.com/excluded/tool")],
        [Media("https://example.org/missing.png")],
        [Skill("Excludedskill", 20)],
    )
    profile = Profile("example-person", "Alex", sections=[Section("projects", "Projects", [kept, excluded])])
    config = Config(LinkedIn(profile.username), projects=Projects(include=[ProjectSelector("Tool", "Kept Company")]))

    if custom:
        (tmp_path / "custom.tex.j2").write_text("((( profile )))", encoding="utf-8")
        config = evolve(config, template="custom.tex.j2")

    source = render_profile(profile, config, tmp_path).read_text()
    assert "Selected description" in source
    assert "Excluded" not in source
    assert not list((tmp_path / "tex/assets").iterdir())
    assert json.loads((tmp_path / "tex/skills.weights.json").read_text()) == {}
    evidence = json.dumps(summary_evidence(profile, config))
    assert "Selected description" in evidence and "Excluded" not in evidence
    assert summary_digest(profile, config) != summary_digest(profile, evolve(config, projects=Projects()))
    assert profile.sections[0].entries == [kept, excluded]

    # An explicit empty list suppresses the section and contents entry, including custom-template inputs.
    source = render_profile(profile, evolve(config, projects=Projects(include=[])), tmp_path).read_text()
    assert "Tool" not in source and "Selected description" not in source
    assert "{Projects}" not in source


def test_selection_never_reenables_the_projects_section() -> None:
    """
    Respect section visibility even when a configured selector matches an existing project.

    Returns:
        None: Disabled and minimal profiles remain valid without an empty Projects section.
    """
    profile = Profile("example-person", "Alex", sections=[Section("projects", "Projects", [Entry("Tool")])])
    selected, _ = consolidate_projects(profile, enabled=False, include=[ProjectSelector("Tool")])
    assert selected.sections == []
    minimal = Profile("example-person", "Alex")
    assert consolidate_projects(minimal, enabled=True, include=[ProjectSelector("Tool")]) == (minimal, [])
