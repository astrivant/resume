"""
Verify parent/child heading deduplication preserves section content and destinations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PIL import Image

from resumeme.compiler.asts.profile import Entry, Link, Media, Profile, Section
from resumeme.compiler.constants.sections import DEFAULT_SECTION_ORDER
from resumeme.compiler.passes.headings import distinct_heading
from resumeme.compiler.pipeline import render_profile
from resumeme.config import Config, LinkedIn, Style

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("child", "parent", "duplicate"),
    [
        ("Languages", "Languages", True),
        ("  LANGUAGES\u00a0", "Languages", True),
        ("Independent\n studies", "Independent studies", True),
        ("\uff2c\uff41\uff4e\uff47\uff55\uff41\uff47\uff45\uff53", "Languages", True),
        ("Café", "Cafe\u0301", True),
        ("English", "Languages", False),
        ("Languages used professionally", "Languages", False),
        ("C++", "C", False),
        ("Languages", "Spoken languages", False),
    ],
)
def test_heading_comparison_uses_immediate_parent_text(child: str, parent: str, duplicate: bool) -> None:
    """
    Ignore presentation differences without treating partial matches or related names as duplicates.

    Args:
        child (str): Captured entry title.
        parent (str): Parent's visible section heading.
        duplicate (bool): Whether only presentation differences separate the two titles.

    Returns:
        None: Equivalent headings disappear and distinct titles retain their original spelling.
    """
    assert distinct_heading(child, parent) == ("" if duplicate else child)


@pytest.mark.parametrize("key", ["languages", "organizations", "projects", "experience", "about"])
def test_duplicate_headings_keep_body_images_and_links(tmp_path: Path, key: str) -> None:
    """
    Apply the rule to ordinary sections, project cards, company headings, and About prose.

    Args:
        tmp_path (Path): Isolated rendering directory.
        key (str): Section layout under test.

    Returns:
        None: Only the repeated heading disappears; the parent, body, media, and original references survive.
    """
    title = key.title()
    Image.new("RGB", (20, 20), "blue").save(tmp_path / "image.png")
    url = "https://www.linkedin.com/company/experience/" if key == "experience" else "https://example.org/reference"
    media = Media(
        "https://example.org/image.png",
        alt=f"{title} logo" if key == "experience" else "Illustration",
        path="image.png",
        link=url,
    )
    paragraphs = ["Retained details", title, "- Useful bullet"]
    entry = Entry(title, paragraphs, links=[Link("More details", url)], images=[media])
    profile = Profile("example-person", "Alex", sections=[Section(key, title, [entry])])
    config = Config(LinkedIn(profile.username), style=Style(show_table_of_contents=False), project_filter=None)
    text = render_profile(profile, config, tmp_path).read_text().split(r"\begin{document}", 1)[1]
    assert text.count(rf"\sectiontitle{{{title}}}") == 1

    # Deduplication is scoped to the section; the sidebar can independently repeat the current employer's logo.
    identity, text = text.split(rf"\sectiontitle{{{title}}}", 1)
    assert identity.count(r"\includegraphics[") == int(key == "experience")
    assert r"\entrytitle{" not in text
    assert "Retained details" in text
    assert text.count(rf"\profileparagraph{{{title}}}") == 1
    assert r"\profilebullet{0}{Useful bullet}" in text
    assert text.count(r"\includegraphics[") == 1
    assert rf"\href{{{url}}}" in text
    assert entry.title == title
    assert entry.paragraphs == paragraphs
    assert entry.images == [media]


def test_suppressed_project_heading_retains_destination_without_preview(tmp_path: Path) -> None:
    """
    Keep a project's only link when its usual linked heading is redundant.

    Args:
        tmp_path (Path): Isolated rendering directory.

    Returns:
        None: Reference rows still carry destinations that have no heading or image to represent them.
    """
    url = "https://example.org/portfolio"
    project = Entry("Projects", ["A collection of tools"], links=[Link("Portfolio", url)])
    profile = Profile("example-person", "Alex", sections=[Section("projects", "Projects", [project])])
    text = (
        render_profile(profile, Config(LinkedIn(profile.username), project_filter=None), tmp_path)
        .read_text()
        .split(r"\begin{document}", 1)[1]
    )
    assert r"\entrytitle{" not in text
    assert rf"\href{{{url}}}{{Portfolio}}" in text
    assert "A collection of tools" in text


def test_sibling_headings_are_not_globally_deduplicated(tmp_path: Path) -> None:
    """
    Keep repeated entry titles when their immediate parent has a different name.

    Args:
        tmp_path (Path): Isolated rendering directory.

    Returns:
        None: Two distinct records can share a title and neither is confused with a section key.
    """
    profile = Profile(
        "example-person",
        "Alex",
        sections=[Section("languages", "Spoken languages", [Entry("Languages", ["English"]), Entry("Languages", ["French"])])],
    )
    text = render_profile(profile, Config(LinkedIn(profile.username)), tmp_path).read_text()
    assert text.count(r"\entrytitle{Languages}") == 2
    assert "English" in text and "French" in text


@pytest.mark.parametrize("disabled", [False, True])
def test_custom_templates_can_apply_the_rule_after_section_filtering(tmp_path: Path, disabled: bool) -> None:
    """
    Expose the same heading comparison to custom templates while preserving raw entry identity.

    Args:
        tmp_path (Path): Isolated rendering directory.
        disabled (bool): Whether the Languages section is hidden by configuration.

    Returns:
        None: Visible duplicate titles filter to empty, and disabled sections never reach the custom template.
    """
    (tmp_path / "custom.tex.j2").write_text(
        "((* for section in profile.sections *))((* for entry in section.entries *))"
        "((( entry.title|distinct_heading(section.title) )))|((( entry.title )))|((( entry.paragraphs[0] )))"
        "((* endfor *))((* endfor *))",
        encoding="utf-8",
    )
    profile = Profile("example-person", "Alex", sections=[Section("languages", "Languages", [Entry("Languages", ["English"])])])
    config = Config(
        LinkedIn(profile.username),
        template="custom.tex.j2",
        section_order=[key for key in DEFAULT_SECTION_ORDER if key not in (["languages"] if disabled else [])],
    )
    text = render_profile(profile, config, tmp_path).read_text()
    assert text == ("" if disabled else "|Languages|English")
