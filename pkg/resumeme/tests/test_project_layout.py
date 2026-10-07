"""
Verify inline project branding and reference deduplication without losing project descriptions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PIL import Image

from resumeme.config import Config, LinkedIn
from resumeme.latex.project_layout import project_layout
from resumeme.latex.rendering import render_profile
from resumeme.models import Entry, Link, Media, Profile, Section

if TYPE_CHECKING:
    from pathlib import Path


def test_project_logos_match_names_and_preserve_unrepresented_links() -> None:
    """
    Move project-owned company branding inline and retain useful descriptions and distinct references.

    Returns:
        None: Source data survives while duplicate company/project references disappear only from the presentation copy.
    """
    company = "Example Co."
    company_url = "https://www.linkedin.com/company/example/"
    project_url = "https://github.com/example/tool"
    source_url = "https://lnkd.in/tool"
    logo = Media("https://example.org/logo.png", path="logo.png")
    known = Media(logo.url, alt=company + " logo", path=logo.path, link=company_url)
    preview = Media("https://example.org/preview.png", path="preview.png", link=project_url)
    guide = Link("Documentation", project_url + "/guide")
    entry = Entry(
        "tool",
        ["Associated with Example Co.", "Associated with Engineer at Example Co.", source_url, "Read " + source_url],
        [Link(source_url, source_url, project_url, "GitHub - example/tool: Build useful services"), Link(company, company_url), guide],
        [logo, preview],
    )
    layout = project_layout(entry, companies={"example co": known})
    inline = Media(logo.url, path=logo.path, link=company_url)
    assert layout.title_url == project_url
    assert layout.affiliations[entry.paragraphs[0]] == ("Associated with ", company, inline)
    assert layout.affiliations[entry.paragraphs[1]] == ("Associated with Engineer at ", company, inline)
    assert layout.entry.images == [preview]
    assert layout.entry.links == [guide]
    assert layout.entry.paragraphs == [*entry.paragraphs[:2], "Read " + source_url, "Build useful services"]
    assert entry.images == [logo, preview]
    assert len(entry.links) == 3
    assert source_url in entry.paragraphs


def test_ambiguous_or_missing_company_branding_does_not_acquire_a_guessed_logo() -> None:
    """
    Require an unambiguous association before assigning an unlabeled image to a company.

    Returns:
        None: Distinct companies, missing logos, and projects without links preserve their available source content.
    """
    logo = Media("https://example.org/logo.png", path="logo.png")
    entry = Entry("Tool", ["Associated with First Company", "Associated with Second Company"], images=[logo])
    layout = project_layout(entry, companies={})
    assert layout.affiliations == {}
    assert layout.entry.images == [logo]
    assert layout.title_url == ""
    assert project_layout(Entry("Minimal"), companies={}).entry == Entry("Minimal")


def test_project_company_logos_render_inline_and_references_remain_clickable(tmp_path: Path) -> None:
    """
    Reuse visible employer branding at the company-name position without repeating its gallery or link row.

    Args:
        tmp_path (Path): Isolated rendering and asset directory.

    Returns:
        None: The project title and inline logo remain linked, with useful text and resolved prose URLs preserved.
    """
    Image.new("RGB", (20, 20), "blue").save(tmp_path / "logo.png")
    company_url = "https://www.linkedin.com/company/example/"
    project_url = "https://github.com/example/tool"
    source_url = "https://lnkd.in/tool"
    logo = Media("https://example.org/logo.png", alt="Example Co. logo", path="logo.png", link=company_url)
    job = Entry("Engineer", ["Example Co. · Full-time", "2020 - Present"], images=[logo])
    project = Entry(
        "tool",
        ["Associated with Engineer at Example Co.", "See " + source_url],
        links=[Link(source_url, source_url, project_url, "GitHub - example/tool: Build services")],
    )
    profile = Profile(
        "example-person", "Alex", sections=[Section("experience", "Experience", [job]), Section("projects", "Projects", [project])]
    )
    source = render_profile(profile, Config(LinkedIn(profile.username)), tmp_path).read_text()
    projects = source.split(r"\projectrow[", 1)[1]
    assert rf"\entrytitle{{\href{{{project_url}}}{{tool}}}}" in projects
    assert projects.count(r"\inlinecompanylogo{") == 1
    assert projects.index("Associated with Engineer at") < projects.index(r"\inlinecompanylogo{") < projects.index("Example Co.")
    assert rf"\href{{{company_url}}}{{\inlinecompanylogo" in projects
    assert "Build services" in projects
    assert "GitHub -" not in projects
    assert rf"See \href{{{project_url}}}" in projects
    assert not project.images

    # Hidden jobs cannot supply logos to otherwise visible projects.
    without_jobs = render_profile(profile, Config(LinkedIn(profile.username), disable=["experience"]), tmp_path).read_text()
    assert r"\inlinecompanylogo{" not in without_jobs.split(r"\projectrow[", 1)[1]
