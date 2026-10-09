"""
Verify source URL selection across configuration, consolidation, rendering, and summary evidence.
"""

from __future__ import annotations

import json
from importlib.resources import files
from typing import TYPE_CHECKING

import pytest
import yaml
from attrs import evolve
from jsonschema import ValidationError

from resumeme.compiler.asts.profile import Entry, Link, Media, Profile, Section, Skill
from resumeme.compiler.constants.backend import AST_PACKAGE, CONFIG_SCHEMA
from resumeme.compiler.constants.links import DEFAULT_PROJECT_FILTER
from resumeme.compiler.passes.projects.consolidation import consolidate_projects
from resumeme.compiler.passes.summary import summary_digest, summary_evidence
from resumeme.compiler.pipeline import render_profile
from resumeme.config import Config, LinkedIn, load_config

if TYPE_CHECKING:
    from pathlib import Path


def test_project_filter_defaults_agree_with_schema(tmp_path: Path) -> None:
    """
    Apply the GitHub default to minimal fork configurations and programmatic callers.

    Args:
        tmp_path (Path): Temporary configuration directory.

    Returns:
        None: Config loading, direct construction, and schema advertise the same expression.
    """
    path = tmp_path / "resumeme.config.yaml"
    path.write_text("linkedin:\n  username: example-person\n")
    schema = json.loads(files(AST_PACKAGE).joinpath(CONFIG_SCHEMA).read_text())
    assert load_config(path).project_filter == Config(LinkedIn("example-person")).project_filter == DEFAULT_PROJECT_FILTER
    assert schema["properties"]["project_filter"]["default"] == DEFAULT_PROJECT_FILTER


@pytest.mark.parametrize("value", [None, "", r"(?i)^https://gitlab\.com/team/", r"/tool(?:[/?#]|$)"])
def test_project_filter_accepts_regex_or_null(tmp_path: Path, value: str | None) -> None:
    """
    Preserve adopter regexes and the explicit opt-out without coercing either.

    Args:
        tmp_path (Path): Temporary configuration directory.
        value (str | None): Valid source URL selector.

    Returns:
        None: YAML loading preserves the configured expression or null.
    """
    path = tmp_path / "resumeme.config.yaml"
    path.write_text(yaml.safe_dump({"linkedin": {"username": "example-person"}, "project_filter": value}))
    assert load_config(path).project_filter == value


@pytest.mark.parametrize("value", ["[", "(?invalid)", 5, True, ["github.com"]])
def test_project_filter_rejects_invalid_values(tmp_path: Path, value: object) -> None:
    """
    Reject malformed patterns and non-string selectors before capture or rendering.

    Args:
        tmp_path (Path): Temporary configuration directory.
        value (object): Invalid pattern or type.

    Returns:
        None: Schema validation identifies the project_filter field as invalid.
    """
    path = tmp_path / "resumeme.config.yaml"
    path.write_text(yaml.safe_dump({"linkedin": {"username": "example-person"}, "project_filter": value}))

    with pytest.raises(ValidationError) as error:
        load_config(path)

    assert list(error.value.path) == ["project_filter"]


@pytest.mark.parametrize(
    ("url", "resolved", "keep"),
    [
        ("https://github.com/example/tool", "", True),
        ("HTTP://WWW.GITHUB.COM/example/tool", "", True),
        ("https://github.com", "", True),
        ("https://github.com?tab=repositories", "", True),
        ("https://github.com#readme", "", True),
        ("https://lnkd.in/tool", "https://github.com/example/tool", True),
        ("https://github.com/example/tool", "https://example.org/tool", False),
        ("https://github.com.evil.example/tool", "", False),
        ("https://github.com@evil.example/tool", "", False),
        ("https://example.org/github.com", "", False),
        ("https://example.org/?source=https://github.com", "", False),
        ("https://gitlab.com/example/tool", "", False),
    ],
)
def test_default_filter_matches_github_destinations(url: str, resolved: str, keep: bool) -> None:
    """
    Search observed destinations while excluding host lookalikes and redirects away from GitHub.

    Args:
        url (str): Captured source URL.
        resolved (str): Final inspected destination, empty when not inspected.
        keep (bool): Whether the GitHub default should include this project.

    Returns:
        None: The project survives only when its effective source URL matches.
    """
    entry = Entry("Tool", links=[Link("Source", url, resolved)])
    profile = Profile("example-person", "Alex", sections=[Section("projects", "Projects", [entry])])
    result, _ = consolidate_projects(profile, enabled=True, project_filter=DEFAULT_PROJECT_FILTER)
    assert bool(result.sections) is keep
    assert profile.sections[0].entries == [entry]


def test_filter_runs_after_merging_explicit_role_and_featured_projects() -> None:
    """
    Retain the full explicit description when a matching role or post attachment supplies the source URL.

    Returns:
        None: Consolidation enriches the unlinked entry before applying the custom repository filter.
    """
    url = "https://github.com/example/tool"
    link = Link("Tool", "https://lnkd.in/tool", url)
    profile = Profile(
        "example-person",
        "Alex",
        sections=[
            Section("projects", "Projects", [Entry("tool", ["Explicit description"]), Entry("Unlinked")]),
            Section("experience", "Experience", [Entry("Engineer", ["Narrative https://lnkd.in/tool"], [link])]),
            Section("featured", "Featured", [Entry("Post", ["Read https://lnkd.in/tool"], [link])]),
        ],
    )
    result, references = consolidate_projects(profile, enabled=True, project_filter=r"/example/tool$")
    projects = result.sections[0].entries
    assert len(projects) == 1
    assert projects[0].paragraphs == ["Explicit description", "Associated with Engineer", "Featured project"]
    assert result.sections[1].entries[0].paragraphs == profile.sections[1].entries[0].paragraphs
    assert result.sections[2].entries[0].paragraphs == profile.sections[2].entries[0].paragraphs
    assert link in references
    assert len(profile.sections[0].entries) == 2


def test_filter_uses_image_click_targets_but_not_assets_or_prose() -> None:
    """
    Count observed image destinations without mistaking GitHub-hosted logos or mentions for a project source.

    Returns:
        None: Linked previews qualify, unlinked assets do not, and null restores all entries.
    """
    url = "https://github.com/example/tool"
    entries = [
        Entry("Click target", images=[Media("https://cdn.example.org/image.png", link=url)]),
        Entry("Asset only", images=[Media(url + "/logo.png")]),
        Entry("Mention only", [f"Project hosted at {url}"]),
        Entry("Unlinked"),
    ]
    profile = Profile("example-person", "Alex", sections=[Section("projects", "Projects", entries)])
    result, _ = consolidate_projects(profile, enabled=True, project_filter=DEFAULT_PROJECT_FILTER)
    assert [entry.title for entry in result.sections[0].entries] == ["Click target"]
    unfiltered, _ = consolidate_projects(profile, enabled=True, project_filter=None)
    assert unfiltered.sections[0].entries == entries


def test_filter_does_not_restore_original_image_url_after_alias_deduplication() -> None:
    """
    Keep redirect resolution when multiple captured source links share one destination.

    Returns:
        None: A former GitHub source cannot bypass filtering through an image's original click target.
    """
    original = "https://github.com/example/old"
    destination = "https://example.org/tool"
    project = Entry(
        "Tool",
        links=[Link("Other alias", "https://lnkd.in/tool", destination), Link("Original", original, destination)],
        images=[Media("https://cdn.example.org/tool.png", link=original)],
    )
    profile = Profile("example-person", "Alex", sections=[Section("projects", "Projects", [project])])
    result, _ = consolidate_projects(profile, enabled=True, project_filter=DEFAULT_PROJECT_FILTER)
    assert result.sections == []


@pytest.mark.parametrize("custom", [False, True])
def test_filtered_projects_skip_media_skills_navigation_and_summary(tmp_path: Path, custom: bool) -> None:
    """
    Apply selection before downstream consumers while retaining ordinary narrative hyperlinks.

    Args:
        tmp_path (Path): Isolated render directory.
        custom (bool): Whether to inspect the custom-template profile instead of packaged LaTeX.

    Returns:
        None: Excluded tiles cannot leak content or fail media staging, and source data remains available.
    """
    link = Link("Excluded project", "https://lnkd.in/tool", "https://example.org/tool")
    project = Entry(
        "Excluded project",
        ["Excluded description"],
        [link],
        [Media("https://example.org/missing.png", link=link.url)],
        [Skill("Excludedskill", 20)],
    )
    profile = Profile(
        "example-person",
        "Alex",
        sections=[
            Section("projects", "Projects", [project]),
            Section("experience", "Experience", [Entry("Engineer", ["Narrative https://lnkd.in/tool"], [link])]),
            Section("featured", "Featured", [Entry("Post", ["Post https://lnkd.in/tool"], [link])]),
        ],
    )
    config = Config(LinkedIn(profile.username))

    if custom:
        (tmp_path / "custom.tex.j2").write_text("((( profile )))")
        config = evolve(config, template="custom.tex.j2")

    source = render_profile(profile, config, tmp_path).read_text()
    assert "Excluded" not in source and "missing.png" not in source
    assert "Narrative" in source and "Post" in source
    assert not list((tmp_path / "tex/assets").iterdir())

    if not custom:
        assert r"\sectiontitle{Projects}" not in source
        assert r"\sectiontitle{Skills}" not in source
        assert source.count(r"\href{https://example.org/tool}") == 2
        assert "{Projects}" not in source.split(r"\begin{document}", 1)[1]

    # Summary evidence follows the same selection, and changing the included projects invalidates a cached summary.
    evidence = json.dumps(summary_evidence(profile, config))
    assert "Excluded" not in evidence and "projects" not in evidence
    assert "Excluded description" in json.dumps(summary_evidence(profile, evolve(config, project_filter=None)))
    assert summary_digest(profile, config) != summary_digest(profile, evolve(config, project_filter=None))
    assert profile.sections[0].entries == [project]
