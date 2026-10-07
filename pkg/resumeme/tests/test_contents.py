"""
Verify contents links follow the visible document and respect style overrides.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
import yaml
from jsonschema import ValidationError

from resumeme.config import Config, Experience, JobSelector, LinkedIn, load_config
from resumeme.latex.rendering import render_profile
from resumeme.models import Entry, Link, Profile, Section, Skill

if TYPE_CHECKING:
    from pathlib import Path


def test_contents_follow_visible_sections_in_display_order(tmp_path: Path) -> None:
    """
    Keep default navigation aligned with filtered sections and their real headings.

    Args:
        tmp_path (Path): Isolated rendering directory.

    Returns:
        None: Only visible sections have links, with unique safe destinations even for repeated keys.
    """
    profile = Profile(
        "example-person",
        "Alex",
        sections=[
            Section("education", "Education", [Entry("University")]),
            Section("interests", "Interests", [Entry("Hidden interest")]),
            Section("experience", "Experience", [Entry("Hidden role")]),
            Section("about", "About", [Entry("Profile narrative")]),
            Section("empty", "Empty section"),
            Section("contact", "Contact info", [Entry("Website")]),
            Section("custom}", "Research & writing", [Entry("First note")]),
            Section("custom}", "Research & writing", [Entry("Second note")]),
        ],
    )
    config = Config(
        LinkedIn(profile.username),
        disable=["interests"],
        experience=Experience(disable=[JobSelector(title="Hidden role")]),
    )
    text = render_profile(profile, config, tmp_path).read_text()
    links = re.findall(r"\\hyperlink\{(resumeme-section-\d+)\}\{([^}]*)\}", text)
    expected = ["Contact info", "About", "Education", r"Research \& writing", r"Research \& writing"]
    assert [title for _, title in links] == expected
    assert len({anchor for anchor, _ in links}) == len(expected)
    assert [title for title in re.findall(r"\\sectiontitle\{([^}]*)\}", text)] == expected

    # Every link targets a single heading, after the contents and before that heading's content.
    for anchor, title in links:
        target = rf"\hypertarget{{{anchor}}}{{}}"
        assert text.count(target) == 1
        assert text.index(rf"\hyperlink{{{anchor}}}") < text.index(target)
        assert text.index(target) < text.index(rf"\sectiontitle{{{title}}}", text.index(target))

    contents = text.index(r"\bfseries Contents}")
    assert text.index(r"\textbf{LinkedIn profile}") < contents < text.index(r"\sectiontitle{Contact info}")
    assert all(label not in text for label in ("Interests", "Hidden role", "Empty section"))
    assert len(profile.sections) == 8


@pytest.mark.parametrize("disabled", [False, True])
def test_contents_include_generated_sections_only_when_visible(tmp_path: Path, disabled: bool) -> None:
    """
    Include consolidated project cards and generated skill clouds after content processing.

    Args:
        tmp_path (Path): Isolated rendering directory.
        disabled (bool): Whether Projects and Skills are excluded from the document.

    Returns:
        None: Generated sections have matching links and destinations only when rendered.
    """
    role = Entry("Engineer", links=[Link("Build tool", "https://example.org/tool")], skills=[Skill("Python", 3)])
    profile = Profile("example-person", "Alex", sections=[Section("experience", "Experience", [role])])
    config = Config(LinkedIn(profile.username), disable=["projects", "skills"] if disabled else [])
    text = render_profile(profile, config, tmp_path).read_text()
    labels = re.findall(r"\\hyperlink\{resumeme-section-\d+\}\{([^}]*)\}", text)
    assert labels == (["Experience"] if disabled else ["Experience", "Projects", "Skills"])
    assert len(re.findall(r"\\hypertarget\{resumeme-section-\d+\}", text)) == len(labels)


@pytest.mark.parametrize("base, override, visible", [(None, None, True), (False, None, False), (True, False, False), (False, True, True)])
def test_contents_style_default_and_theme_precedence(tmp_path: Path, base: bool | None, override: bool | None, visible: bool) -> None:
    """
    Honor boolean configuration and theme precedence without hiding the actual sections.

    Args:
        tmp_path (Path): Isolated configuration directory.
        base (bool | None): Base visibility or None to use the default.
        override (bool | None): Theme visibility or None to omit a selected theme.
        visible (bool): Expected effective contents visibility.

    Returns:
        None: The contents flag defaults to true and only controls navigation.
    """
    style: dict[str, object] = {}

    if base is not None:
        style["show_table_of_contents"] = base

    if override is not None:
        style.update(theme="custom", themes={"custom": {"show_table_of_contents": override}})

    path = tmp_path / "resumeme.config.yaml"
    path.write_text(yaml.safe_dump({"linkedin": {"username": "example-person"}, "style": style}), encoding="utf-8")
    config = load_config(path)
    assert config.style.show_table_of_contents == (True if base is None else base)
    profile = Profile("example-person", "Alex", sections=[Section("about", "About", [Entry("Profile narrative")])])
    text = render_profile(profile, config, tmp_path).read_text()
    assert (r"\bfseries Contents}" in text) is visible
    assert (r"\hyperlink{" in text) is visible
    assert r"\sectiontitle{About}" in text
    assert "Profile narrative" in text


@pytest.mark.parametrize("theme", [False, True])
def test_contents_config_rejects_string_booleans(tmp_path: Path, theme: bool) -> None:
    """
    Reject ambiguous string settings in both base style and inline themes.

    Args:
        tmp_path (Path): Isolated configuration directory.
        theme (bool): Whether to put the invalid setting in a theme.

    Returns:
        None: Validation fails before a string can silently enable navigation.
    """
    override = {"show_table_of_contents": "false"}
    style = {"themes": {"custom": override}} if theme else override
    path = tmp_path / "resumeme.config.yaml"
    path.write_text(yaml.safe_dump({"linkedin": {"username": "example-person"}, "style": style}), encoding="utf-8")

    with pytest.raises(ValidationError):
        load_config(path)


@pytest.mark.parametrize("disabled", [False, True])
def test_header_only_profiles_have_no_empty_contents(tmp_path: Path, disabled: bool) -> None:
    """
    Omit navigation when no sections survive filtering or no sections were captured.

    Args:
        tmp_path (Path): Isolated rendering directory.
        disabled (bool): Whether to exercise exclusion instead of an absent section.

    Returns:
        None: Minimal profiles contain neither empty contents nor dangling links.
    """
    sections = [Section("about", "About", [Entry("Hidden narrative")])] if disabled else []
    profile = Profile("example-person", "Alex", sections=sections)
    config = Config(LinkedIn(profile.username), disable=["about"])
    text = render_profile(profile, config, tmp_path).read_text()
    assert r"\bfseries Contents}" not in text
    assert r"\hyperlink{" not in text
    assert r"\hypertarget{" not in text
