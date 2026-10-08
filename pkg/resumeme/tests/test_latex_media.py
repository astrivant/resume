"""
Protect the distinction between profile portraits, organization branding, and content previews.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PIL import Image

from resumeme.compiler.asts.profile import Entry, Link, Media, Profile, Section
from resumeme.compiler.passes.media import employer_badge, image_role, school_badge
from resumeme.compiler.pipeline import render_profile
from resumeme.config import Config, LinkedIn, Style

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("image", "header", "expected"),
    [
        (Media("https://media.licdn.com/profile-displayphoto-scale_100_100/photo"), True, "portrait"),
        (Media("https://media.licdn.com/company-logo_100_100/company"), True, "logo"),
        (Media("https://media.licdn.com/school-logo_100_100/school"), True, "logo"),
        (Media("https://static.licdn.com/images/logos/favicons/v1/favicon.ico"), False, "icon"),
        (Media("https://example.org/apple-touch-icon.png"), False, "icon"),
        (Media("https://media.licdn.com/profile-displaybackgroundimage-shrink_200_800/cover"), True, "cover"),
        (Media("https://example.org/photo.png", alt="Cover photo"), True, "cover"),
        (Media("https://example.org/photo.png", alt="Alex Example"), True, "portrait"),
        (Media("https://example.org/illustration.png?logo=preview", alt="Illustration"), False, "preview"),
        (Media("https://example.org/photo.png", alt="Company logo"), False, "logo"),
        (Media("https://example.org/logo.png"), False, "logo"),
        (Media("https://example.org/photo.png", link="https://www.linkedin.com/company/example/"), False, "logo"),
        (
            Media("https://example.org/photo.png", alt="Thumbnail for Company logo", link="https://www.linkedin.com/company/example/"),
            False,
            "preview",
        ),
        (
            Media("https://media.licdn.com/articleshare-shrink_480/company", link="https://www.linkedin.com/company/example/"),
            False,
            "preview",
        ),
    ],
)
def test_image_role_preserves_visual_hierarchy(image: Media, header: bool, expected: str) -> None:
    """
    Use source semantics to avoid enlarging logos into portraits or shrinking linked illustrations into logos.

    Args:
        image (Media): Captured reference with representative LinkedIn or external metadata.
        header (bool): Whether the reference occurs in the profile header.
        expected (str): Presentation role supported by that metadata.

    Returns:
        None: Blank labels, overlapping URL markers, and preview destinations retain their intended role.
    """

    # Organization marks and portraits both arrive as 100-pixel downloads; their role must survive that ambiguity.
    assert image_role(image, header=header) == expected


@pytest.mark.parametrize("grouped", [False, True])
def test_employer_logos_render_once_beside_the_company_name(tmp_path: Path, grouped: bool) -> None:
    """
    Position employer logos at company names in standalone jobs and legacy grouped employment.

    Args:
        tmp_path (Path): Isolated assets and template root.
        grouped (bool): Whether the heading represents a company with multiple roles.

    Returns:
        None: The linked logo precedes the company name without a repeated image below the responsibilities.
    """
    Image.new("RGB", (20, 20), "blue").save(tmp_path / "logo.png")
    company = "Example & Company"
    url = "https://www.linkedin.com/company/example/"
    logo = Media("https://example.org/company-logo.png", alt=company + " LOGO", path="logo.png", link=url)
    paragraphs = (
        ["Full-time", "Engineer", "2020 - Present", "- Built systems", "Intern", "2019 - 2020"]
        if grouped
        else [company + " \u00b7 Full-time", "2020 - Present", "- Built systems"]
    )
    entry = Entry(company if grouped else "Engineer", paragraphs, [Link(company, url)], [logo])
    assert employer_badge(entry) == (-1 if grouped else 0, logo)
    profile = Profile("example-person", "Alex", sections=[Section("experience", "Experience", [entry])])
    path = render_profile(profile, Config(LinkedIn(profile.username)), tmp_path)
    body = path.read_text().split(r"\begin{document}", 1)[1]
    image_path = "assets/" + next((path.parent / "assets").glob("*.png")).name

    # The sidebar repeats the latest employer; Experience still owns exactly one logo beside its company heading.
    identity, body = body.split(r"\sectiontitle{Experience}", 1)
    assert identity.count(image_path) == 1
    assert body.count(image_path) == 1
    badge = body.index(r"\companyline{")
    assert badge < body.index(image_path) < body.index(r"Example \& Company") < body.index("Built systems")
    assert rf"\href{{{url}}}" in body[badge : body.index(image_path)]
    assert r"\profilebullet{0}{Built systems}" in body
    assert entry.images == [logo]


def test_structured_company_groups_and_missing_employer_metadata() -> None:
    """
    Use explicit company groups and leave ambiguous or missing branding untouched.

    Returns:
        None: Structured ownership wins, while an unknown company or absent logo does not acquire a guessed name.
    """
    logo = Media("https://example.org/logo.png")
    group = Entry("Example Company", images=[logo], positions=[Entry("Engineer")])
    assert employer_badge(group) == (-1, logo)
    assert employer_badge(Entry("Engineer", ["Example", "2020 - Present"])) is None
    assert employer_badge(Entry("Engineer", ["Responsibilities", "- Built systems"], images=[logo])) is None
    assert employer_badge(Entry("Engineer", ["Example", "2020 - Present"], images=[logo])) == (0, logo)


@pytest.mark.parametrize("grouped", [False, True])
@pytest.mark.parametrize("branded", [False, True])
def test_company_hierarchy_styles_names_without_promoting_role_or_body_text(tmp_path: Path, grouped: bool, branded: bool) -> None:
    """
    Apply themed company typography independently of logos while keeping job metadata and subheadings subordinate.

    Args:
        tmp_path (Path): Isolated template and asset root.
        grouped (bool): Whether the employer owns nested positions.
        branded (bool): Whether a captured logo is available for the employer.

    Returns:
        None: Only the employer name receives company typography, with effective theme values and intact role content.
    """
    Image.new("RGB", (20, 20), "blue").save(tmp_path / "logo.png")
    logo = Media("https://example.org/logo.png", alt="Example Co logo", path="logo.png", link="https://example.org/company")
    paragraphs = ["Full-time" if grouped else "Example Co \u00b7 Full-time", "2020 - Present", "Responsibilities", "- Build services"]
    job = Entry("Engineer", paragraphs)
    entry = (
        Entry("Example Co", [job.title, *paragraphs], positions=[job], images=[logo] if branded else [])
        if grouped
        else Entry("Engineer", paragraphs, images=[logo] if branded else [])
    )
    style = Style(theme="custom", themes={"custom": {"company_font_size": 14, "company_color": "6B2737"}})
    profile = Profile("example", "Example Person", sections=[Section("experience", "Experience", [entry])])
    source = render_profile(profile, Config(LinkedIn("example"), style=style), tmp_path).read_text()
    body = source.split(r"\begin{document}", 1)[1]
    assert r"\definecolor{companyname}{HTML}{6B2737}" in source
    assert r"\fontsize{14}{16.8}" in source
    assert r"\hypersetup{urlcolor=companyname,linkcolor=companyname}" in source
    assert r"\companytext{Example Co}" in body
    assert r"\companytext{Full-time}" not in body
    assert r"\companytext{Engineer}" not in body
    assert r"\profilesubheading{Responsibilities}" in body
    assert r"\profilebullet{0}{Build services}" in body
    assert r"\companyline{" in body if branded else r"\companyline{" not in body

    # Captured snapshots and configured base values remain available for future renders and different themes.
    assert job.paragraphs == paragraphs
    assert style.company_font_size == 13 and style.company_color == "191919"


@pytest.mark.parametrize("section_key", ["experience", "education"])
@pytest.mark.parametrize("logo_state", ["missing", "unlinked", "linked"])
@pytest.mark.parametrize("resolved", [False, True])
def test_organization_reference_is_replaced_only_by_a_clickable_logo(
    tmp_path: Path, section_key: str, logo_state: str, resolved: bool
) -> None:
    """
    Avoid duplicate organization references without losing the destination when its logo cannot supply a link.

    Args:
        tmp_path (Path): Isolated rendering and asset directory.
        section_key (str): Experience or education section owning the organization.
        logo_state (str): Whether an organization logo is absent, decorative, or clickable.
        resolved (bool): Whether capture resolved the original organization reference to a different destination.

    Returns:
        None: The section's organization destination appears once, as either a linked logo or its retained text reference.
    """
    Image.new("RGB", (20, 20), "blue").save(tmp_path / "logo.png")
    organization = "school" if section_key == "education" else "company"
    company_url = f"https://www.linkedin.com/{organization}/example/"
    destination = f"https://www.linkedin.com/{organization}/resolved/" if resolved else company_url
    logo = Media("https://example.org/logo.png", alt="Example Co logo", path="logo.png", link=company_url if logo_state == "linked" else "")
    entry = Entry(
        "Example Co" if section_key == "education" else "Engineer",
        ["Mathematics" if section_key == "education" else "Example Co", "2020 - Present"],
        links=[Link(company_url, company_url, resolved_url=destination)],
        images=[] if logo_state == "missing" else [logo],
    )
    profile = Profile("example-person", "Alex", sections=[Section(section_key, section_key.title(), [entry])])
    source = render_profile(profile, Config(LinkedIn(profile.username)), tmp_path).read_text()

    # An independent current-employer link in the identity column must not count as a duplicate section reference.
    source = source.split(rf"\sectiontitle{{{section_key.title()}}}", 1)[1]
    assert source.count(r"\href{" + destination + "}") == 1
    assert (r"\allowbreak{}" + organization + "/" in source) is (logo_state != "linked")
    assert len(entry.links) == 1


@pytest.mark.parametrize("named", [False, True])
def test_school_logo_precedes_school_heading_and_preserves_degree_and_other_links(tmp_path: Path, named: bool) -> None:
    """
    Keep school branding inline without relocating the degree, duplicating images, or hiding unrelated references.

    Args:
        tmp_path (Path): Isolated rendering and asset directory.
        named (bool): Whether LinkedIn supplied an accessible school name for its logo.

    Returns:
        None: School headings own one linked logo and retain their degree, dates, and additional references.
    """
    Image.new("RGB", (20, 20), "blue").save(tmp_path / "school.png")
    Image.new("RGB", (40, 20), "green").save(tmp_path / "campus.png")
    school = "Example & University"
    url = "https://www.linkedin.com/school/example/"
    logo = Media("https://media.licdn.com/company-logo_100_100/school", alt=school + " logo" if named else "", path="school.png", link=url)
    preview = Media("https://media.licdn.com/articleshare-shrink_480/campus", alt="Campus preview", path="campus.png")
    entry = Entry(
        school,
        ["BSc, Mathematics", "2015 - 2019"],
        [Link(url, url), Link("Research paper", "https://example.org/paper")],
        [preview, logo],
    )
    assert school_badge(entry) == (-1, logo)
    assert school_badge(Entry(school, images=[preview])) is None
    profile = Profile("example-person", "Alex", sections=[Section("education", "Education", [entry])])
    path = render_profile(profile, Config(LinkedIn(profile.username)), tmp_path)
    body = path.read_text().split(r"\begin{document}", 1)[1]
    logo_asset = next(
        asset for asset in (path.parent / "assets").glob("*.png") if asset.read_bytes() == (tmp_path / "school.png").read_bytes()
    )
    image_path = "assets/" + logo_asset.name

    # The logo and school share the heading row, followed by the complete degree and attendance dates.
    assert body.count(image_path) == 1
    assert body.index(r"\companyline{") < body.index(image_path) < body.index(r"Example \& University") < body.index("BSc, Mathematics")
    assert body.count(rf"\href{{{url}}}") == 1
    assert r"\allowbreak{}school/" not in body
    assert "2015 - 2019" in body
    assert r"\href{https://example.org/paper}{Research paper}" in body
    assert entry.images == [preview, logo]
