"""
Verify inline project branding and reference deduplication without losing project descriptions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PIL import Image

from resumeme.compiler.asts.profile import Entry, Link, Media, Profile, Section
from resumeme.compiler.passes.project_layout import CompanyAffiliation, project_layout
from resumeme.compiler.pipeline import render_profile
from resumeme.config import Config, LinkedIn

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
    assert layout.companies == [CompanyAffiliation(company, ["Engineer"], inline)]
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
    assert layout.companies == []
    assert layout.entry.images == [logo]
    assert layout.title_url == ""
    assert project_layout(Entry("Minimal"), companies={}).entry == Entry("Minimal")


def test_company_rows_group_repeated_names_without_losing_distinct_roles() -> None:
    """
    Keep one row per observed company and preserve every distinct associated role in source order.

    Returns:
        None: Repeated branding is suppressed while unrelated or unrecognized associations remain intact.
    """
    first = Media("https://example.org/first.png", path="first.png")
    second = Media("https://example.org/second.png", path="second.png")
    lines = [
        "Associated with Example Co.",
        "Associated with Engineer at Example Co.",
        "Associated with engineer at EXAMPLE CO",
        "Associated with Lead Engineer at Example Co.",
        "Associated with Engineer at Second Company",
        "Associated with Independent Work",
    ]
    entry = Entry("Tool", lines)
    layout = project_layout(entry, companies={"example co": first, "second company": second})
    expected = [
        CompanyAffiliation("Example Co.", ["Engineer", "Lead Engineer"], first),
        CompanyAffiliation("Second Company", ["Engineer"], second),
    ]
    assert layout.companies == expected
    assert layout.metadata == lines
    assert lines[-1] not in layout.affiliations
    assert entry.paragraphs == lines

    # Computed presentation rows are independently owned; callers cannot mutate subsequent renders or saved metadata.
    layout.companies[0].roles.append("Unrelated role")
    assert layout.companies == expected


def test_project_company_logos_render_inline_and_references_remain_clickable(tmp_path: Path) -> None:
    """
    Render one logo/name row per company, followed by its associated roles, without duplicate gallery or link rows.

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
        ["Associated with Example Co.", "Associated with Engineer at Example Co.", "See " + source_url],
        links=[Link(source_url, source_url, project_url, "GitHub - example/tool: Build services")],
    )
    profile = Profile(
        "example-person", "Alex", sections=[Section("experience", "Experience", [job]), Section("projects", "Projects", [project])]
    )
    source = render_profile(profile, Config(LinkedIn(profile.username)), tmp_path).read_text()
    projects = source.split(r"\projectrow[", 1)[1]
    assert rf"\entrytitle{{\href{{{project_url}}}{{tool}}}}" in projects
    assert projects.count(r"\projectcompany{") == 1
    assert projects.count(r"\includegraphics[width=4mm,height=4mm,keepaspectratio]") == 1
    company_link = r"\hyperlink{resumeme-section-0-job-0}{Example Co.}"
    role_link = r"\hyperlink{resumeme-section-0-job-0}{Engineer}"
    assert projects.index(r"\projectcompany{") < projects.index(company_link) < projects.index(role_link)
    assert source.count(r"\hypertarget{resumeme-section-0-job-0}{}") == 1
    assert projects.count("Example Co.") == 1
    assert "Associated with" not in projects
    assert rf"\href{{{company_url}}}{{%" in projects
    assert "Build services" in projects
    assert "GitHub -" not in projects
    assert rf"See \href{{{project_url}}}" in projects
    assert not project.images

    # Hidden jobs cannot supply logos to otherwise visible projects.
    without_jobs = render_profile(profile, Config(LinkedIn(profile.username), disable=["experience"]), tmp_path).read_text()
    without_jobs = without_jobs.split(r"\projectrow[", 1)[1]
    assert r"\projectcompany{" not in without_jobs
    assert "Associated with Engineer at Example Co." in without_jobs
