"""
Verify project consolidation, destination identity, and exclusion boundaries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from attrs import evolve

from resumeme.compiler.asts.profile import Entry, Link, Media, Profile, Section
from resumeme.compiler.constants.sections import DEFAULT_SECTION_ORDER
from resumeme.compiler.passes.projects.consolidation import consolidate_projects
from resumeme.compiler.pipeline import render_profile
from resumeme.config import Config, Experience, JobSelector, LinkedIn

if TYPE_CHECKING:
    from pathlib import Path


def test_projects_merge_resolved_aliases_and_keep_role_and_featured_context() -> None:
    """
    Prefer explicit project details and combine repeated links from roles and posts.

    Returns:
        None: One project retains its description, affiliations, and preview without mutating capture.
    """
    destination = "https://github.com/example/tool"
    original = Link("Tool", "https://lnkd.in/tool", destination + "/", "GitHub - example/tool: Build things")
    preview = Media("https://example.org/tool.png", path="tool.png", link=original.url)
    logo = Media("https://example.org/logo.png", alt="Company logo", path="logo.png")
    post = Link("Post", "https://www.linkedin.com/feed/update/123")
    featured = Entry("Post", ["Read https://lnkd.in/tool"], [post, original], [evolve(preview, link=post.url)])
    role = Entry("Staff Engineer", ["Example", "Built the deployment system.", "Tool"], [original], [logo, preview])
    project = Entry("tool", ["Detailed project description."], [Link(destination, destination)], [evolve(preview, link=destination)])
    profile = Profile(
        "example-person",
        "Alex",
        sections=[
            Section("featured", "Featured", [featured]),
            Section("experience", "Experience", [role]),
            Section("projects", "Projects", [project]),
        ],
    )
    result, references = consolidate_projects(profile, enabled=True)
    sections = {section.key: section for section in result.sections}
    projects = sections["projects"].entries
    assert len(projects) == 1
    assert projects[0].title == "tool"
    assert projects[0].paragraphs == ["Detailed project description.", "Featured project", "Associated with Staff Engineer"]
    assert len(projects[0].links) == len(projects[0].images) == 1
    assert sections["experience"].entries[0].paragraphs == ["Example", "Built the deployment system."]
    assert sections["experience"].entries[0].images == [logo]
    assert sections["featured"].entries[0].paragraphs == featured.paragraphs
    assert sections["featured"].entries[0].images == []
    assert original in references
    assert role.images == [logo, preview]
    assert featured.images == [evolve(preview, link=post.url)]


def test_project_identity_keeps_subpages_and_ambiguous_names_distinct() -> None:
    """
    Avoid merging different repositories, documentation pages, or ambiguous URL-less records.

    Returns:
        None: Exact resolved aliases merge while meaningful paths and query parameters remain distinct.
    """
    urls = [
        "https://example.org/tool",
        "https://example.org/tool/guide",
        "https://other.example.org/tool",
        "https://example.org/tool?edition=2",
    ]
    entries = [Entry("Tool", links=[Link(url, url)]) for url in urls]
    entries += [Entry("Tool"), Entry("Tool", links=[Link("Alias", "https://lnkd.in/tool", urls[0] + "/#readme")])]
    profile = Profile("example-person", "Alex", sections=[Section("projects", "Projects", entries)])
    result, _ = consolidate_projects(profile, enabled=True)
    assert len(result.sections[0].entries) == 5


def test_url_less_projects_merge_only_unambiguous_observed_names() -> None:
    """
    Connect an explicit project without a link to its captured repository attachment.

    Returns:
        None: The observed destination enriches the existing project rather than creating a duplicate.
    """
    url = "https://github.com/example/tool"
    profile = Profile(
        "example-person",
        "Alex",
        sections=[
            Section("projects", "Projects", [Entry("Tool", ["Original description"])]),
            Section("experience", "Experience", [Entry("Engineer", links=[Link("Build things", url)])]),
        ],
    )
    result, _ = consolidate_projects(profile, enabled=True)
    assert len(result.sections[0].entries) == 1
    assert result.sections[0].entries[0].title == "Tool"
    assert result.sections[0].entries[0].links[0].url == url


def test_shared_linkedin_viewer_does_not_merge_different_attachments() -> None:
    """
    Keep attachments distinct when LinkedIn provides only a shared role viewer URL.

    Returns:
        None: Both projects survive without fabricated external links.
    """
    viewer = "https://www.linkedin.com/in/example/overlay/Position/123/treasury/"
    images = [Media(f"https://example.org/{name}.png", alt=f"Thumbnail for {name}", link=viewer) for name in ["First", "Second"]]
    profile = Profile("example-person", "Alex", sections=[Section("experience", "Experience", [Entry("Engineer", images=images)])])
    result, _ = consolidate_projects(profile, enabled=True)
    projects = result.sections[-1].entries
    assert [entry.title for entry in projects] == ["First", "Second"]
    assert [entry.links[0].url for entry in projects] == [viewer, viewer]
    assert result.sections[0].entries[0].images == []


@pytest.mark.parametrize("disabled", [[], ["projects"], ["experience"], ["featured"]])
def test_consolidated_projects_respect_sections_and_grouped_job_exclusions(tmp_path: Path, disabled: list[str]) -> None:
    """
    Filter source ownership before moving attachments into custom or packaged output.

    Args:
        tmp_path (Path): Isolated rendering directory.
        disabled (list[str]): Whole-section exclusions applied before consolidation.

    Returns:
        None: Hidden jobs never reappear and disabling Projects suppresses relocated cards.
    """
    roles = [
        Entry("Staff", ["Visible prose https://lnkd.in/kept"], [Link("Kept project", "https://lnkd.in/kept", "https://example.org/kept")]),
        Entry("Intern", ["Hidden role"], [Link("Hidden project", "https://example.org/hidden")]),
    ]
    group = Entry(
        "Company",
        [line for role in roles for line in [role.title, *role.paragraphs]],
        [link for role in roles for link in role.links],
        positions=roles,
    )
    featured = Entry("Featured narrative", links=[Link("Featured attachment", "https://example.org/featured")])
    profile = Profile(
        "example-person", "Alex", sections=[Section("experience", "Experience", [group]), Section("featured", "Featured", [featured])]
    )
    config = Config(
        LinkedIn(profile.username),
        section_order=[key for key in DEFAULT_SECTION_ORDER if key not in (disabled)],
        experience=Experience(disable=[JobSelector(title="Intern")]),
        project_filter=None,
    )
    source = render_profile(profile, config, tmp_path).read_text()
    assert "Hidden" not in source
    assert (r"\sectiontitle{Projects}" in source) is ("projects" not in disabled)

    if "projects" in disabled:
        assert "Kept project" not in source
        assert "Featured attachment" not in source
        assert r"\href{https://example.org/kept}" in source
    elif "experience" in disabled:
        assert "Kept project" not in source
    else:
        # Featured precedes Experience in the default order, but an excluded section consumes no destination index.
        index = 0 if "featured" in disabled else 1
        assert source.count(rf"Associated with Staff at \hyperlink{{resumeme-section-{index}-job-0-0}}{{\companytext{{Company}}}}") == 1

    if "featured" in disabled:
        assert "Featured attachment" not in source


def test_empty_profile_does_not_gain_an_empty_projects_section() -> None:
    """
    Preserve the minimal-profile base case without introducing empty sections.

    Returns:
        None: An empty profile has neither projects nor relocated references.
    """
    profile = Profile("example-person", "Alex")
    assert consolidate_projects(profile, enabled=True) == (profile, [])


def test_duplicate_project_sections_preserve_distinct_descriptions_and_employers() -> None:
    """
    Consolidate repeated section observations while retaining all project descriptions and job affiliations.

    Returns:
        None: One Projects section contains the shared destination with both descriptions and its employer.
    """
    url = "https://example.org/tool"
    profile = Profile(
        "example-person",
        "Alex",
        sections=[
            Section("projects", "Projects", [Entry("Tool", links=[Link("First description", url)])]),
            Section("projects", "Projects", [Entry("Tool", links=[Link("Second description", url)])]),
            Section(
                "experience", "Experience", [Entry("Engineer", ["Example Co. \u00b7 Full-time", "2024 - Present"], [Link("Tool", url)])]
            ),
        ],
    )
    result, _ = consolidate_projects(profile, enabled=True)
    projects = [section for section in result.sections if section.key == "projects"]
    assert len(projects) == 1
    assert len(projects[0].entries) == 1
    project = projects[0].entries[0]
    assert project.links[0].label == "First description"
    assert "Second description" in project.paragraphs
    assert "Associated with Engineer at Example Co." in project.paragraphs


@pytest.mark.parametrize("custom", [False, True])
def test_disabled_projects_do_not_stage_relocated_missing_images(tmp_path: Path, custom: bool) -> None:
    """
    Keep disabled project attachments out of asset validation and custom-template views.

    Args:
        tmp_path (Path): Temporary render root.
        custom (bool): Whether to inspect the shared custom-template view.

    Returns:
        None: Missing hidden imagery causes no build failure or output leak.
    """
    link = Link("Hidden attachment", "https://example.org/hidden")
    role = Entry("Engineer", ["Visible description"], [link], [Media("https://example.org/missing.png", link=link.url)])
    profile = Profile("example-person", "Alex", sections=[Section("experience", "Experience", [role])])
    config = Config(LinkedIn(profile.username), section_order=[key for key in DEFAULT_SECTION_ORDER if key not in (["projects"])])

    if custom:
        (tmp_path / "custom.tex.j2").write_text("((( profile )))", encoding="utf-8")
        config = evolve(config, template="custom.tex.j2")

    source = render_profile(profile, config, tmp_path).read_text()
    assert "Visible description" in source
    assert "Hidden attachment" not in source
    assert "missing.png" not in source
    assert not list((tmp_path / "tex/assets").iterdir())
