"""
Verify project-to-employment links resolve to retained role headings and safe unique destinations.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest

from resumeme.compiler.asts.profile import Entry, Profile, Section
from resumeme.compiler.constants.sections import DEFAULT_SECTION_ORDER
from resumeme.compiler.passes.navigation import experience_navigation
from resumeme.compiler.pipeline import render_profile
from resumeme.config import Config, Experience, JobSelector, LinkedIn

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("structured", [False, True])
def test_grouped_and_standalone_targets_follow_rendered_paths(structured: bool) -> None:
    """
    Use the same nested paths for structured roles and older flattened company groups.

    Args:
        structured (bool): Whether the company has explicit captured position boundaries.

    Returns:
        None: Company and specific role links resolve without requiring a logo or modifying the snapshot.
    """
    current = Entry("Staff Engineer", ["2022 - Present", "Led delivery"])
    previous = Entry("Engineer", ["2020 - 2022", "Built systems"])
    group = Entry(
        "Example & Co.",
        ["Full-time", current.title, *current.paragraphs, previous.title, *previous.paragraphs],
        positions=[current, previous] if structured else [],
    )
    other = Entry("Engineer", ["Other Company \u00b7 Full-time", "2024 - Present"])
    navigation = experience_navigation([("resumeme-section-0", Section("experience", "Experience", [group, other]))])
    assert navigation.destination("  EXAMPLE & CO ") == "resumeme-section-0-job-0"
    assert navigation.destination("Example & Co.", ["Engineer"]) == "resumeme-section-0-job-0-1"
    assert navigation.destination("Other Company", ["Engineer"]) == "resumeme-section-0-job-1"
    assert navigation.destination("Example & Co.", ["Missing role"]) == ""
    assert navigation.association("Associated with Engineer") is None
    assert navigation.association("Associated with Staff Engineer") == ("Associated with ", "Staff Engineer", "resumeme-section-0-job-0-0")
    assert group.positions == ([current, previous] if structured else [])


@pytest.mark.parametrize("disabled", ["none", "role", "company", "section"])
def test_projects_link_only_to_visible_employment(tmp_path: Path, disabled: str) -> None:
    """
    Link explicit project affiliations without redirecting excluded roles to a different retained job.

    Args:
        tmp_path (Path): Isolated template output directory.
        disabled (str): Visibility rule applied before navigation is built.

    Returns:
        None: Every emitted link has one matching anchor; hidden jobs produce plain association text.
    """
    roles = [Entry("Lead Engineer", ["2022 - Present"]), Entry("Engineer", ["2020 - 2022"])]
    group = Entry("Example & Co.", [line for role in roles for line in [role.title, *role.paragraphs]], positions=roles)
    project = Entry("Tool", ["Associated with Engineer at Example & Co."])
    profile = Profile(
        "example-person", "Alex", sections=[Section("experience", "Experience", [group]), Section("projects", "Projects", [project])]
    )
    selectors = (
        [JobSelector(title="Engineer")] if disabled == "role" else [JobSelector(company="Example & Co.")] if disabled == "company" else []
    )
    config = Config(
        LinkedIn(profile.username),
        section_order=[key for key in DEFAULT_SECTION_ORDER if key not in (["experience"] if disabled == "section" else [])],
        experience=Experience(disable=selectors),
        project_filter=None,
    )
    source = render_profile(profile, config, tmp_path).read_text()
    projects = source.split(r"\projectrow[", 1)[1]
    target = "resumeme-section-0-job-0-1"
    expected = rf"Associated with Engineer at \hyperlink{{{target}}}{{\companytext{{Example \& Co.}}}}"
    assert (expected in projects) is (disabled == "none")

    if disabled == "none":
        assert rf"\roletitle{{\hypertarget{{{target}}}{{}}Engineer}}" in source
    else:
        assert r"\hyperlink{" not in projects
        assert r"Associated with Engineer at Example \& Co." in projects

    # Check actual targets rather than assuming that a correctly formed link points to a rendered role.
    anchors = re.findall(r"\\hypertarget\{([^}]+)\}", source)
    assert len(anchors) == len(set(anchors))
    assert all(target in anchors for target in re.findall(r"\\hyperlink\{([^}]+)\}", source))


def test_repeated_titles_and_suppressed_headings_keep_unique_destinations(tmp_path: Path) -> None:
    """
    Keep anchors independent of title spelling and retain them when a nested heading is deduplicated.

    Args:
        tmp_path (Path): Isolated rendering directory.

    Returns:
        None: Repeated roles use distinct paths and a suppressed company heading remains a valid destination.
    """
    roles = [Entry("Engineer", ["One \u00b7 Full-time", "2022 - Present"]), Entry("Engineer", ["Two \u00b7 Full-time", "2020 - 2022"])]
    group = Entry("Experience", ["Engineer", "2018 - 2020", "Engineer", "2016 - 2018"])
    project = Entry("Tool", ["Associated with Experience", "Associated with Engineer at Two"])
    profile = Profile(
        "example-person",
        "Alex",
        sections=[Section("experience", "Experience", [*roles, group]), Section("projects", "Projects", [project])],
    )
    source = render_profile(profile, Config(LinkedIn(profile.username), project_filter=None), tmp_path).read_text()
    projects = source.split(r"\projectrow[", 1)[1]
    assert r"\hyperlink{resumeme-section-0-job-2}{\companytext{Experience}}" in projects
    assert r"\hyperlink{resumeme-section-0-job-1}{\companytext{Two}}" in projects
    anchors = re.findall(r"\\hypertarget\{(resumeme-section-0-job-[^}]+)\}", source)
    assert len(anchors) == len(set(anchors)) == 5


def test_continuation_pages_link_back_to_contents(tmp_path: Path) -> None:
    """
    Add a footer shortcut on continuation pages that targets the first-page Contents heading.

    Args:
        tmp_path (Path): Isolated template output directory.

    Returns:
        None: The continuation footer uses the same internal destination as the visible Contents list.
    """
    profile = Profile(
        "example-person",
        "Alex",
        sections=[Section("experience", "Experience", [Entry("Engineer", ["2022 - Present", "Built systems."])])],
    )
    source = render_profile(profile, Config(LinkedIn(profile.username)), tmp_path).read_text()

    assert r"\AddToHook{shipout/foreground}{\resumemeindexfooter}" in source
    assert r"\ifnum\value{page}>1\relax" in source
    assert r"\hyperlink{resumeme-contents}{Index}" in source
    assert r"\hypertarget{resumeme-contents}{}" in source
