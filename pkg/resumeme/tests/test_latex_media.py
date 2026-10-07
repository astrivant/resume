"""
Protect the distinction between profile portraits, organization branding, and content previews.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PIL import Image

from resumeme.config import Config, LinkedIn
from resumeme.latex.media import employer_badge, image_role
from resumeme.latex.rendering import render_profile
from resumeme.models import Entry, Link, Media, Profile, Section

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
        else [company + " · Full-time", "2020 - Present", "- Built systems"]
    )
    entry = Entry(company if grouped else "Engineer", paragraphs, [Link(company, url)], [logo])
    assert employer_badge(entry) == (-1 if grouped else 0, logo)
    profile = Profile("example-person", "Alex", sections=[Section("experience", "Experience", [entry])])
    path = render_profile(profile, Config(LinkedIn(profile.username)), tmp_path)
    body = path.read_text().split(r"\begin{document}", 1)[1]
    image_path = "assets/" + next((path.parent / "assets").glob("*.png")).name
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


@pytest.mark.parametrize("logo_state", ["missing", "unlinked", "linked"])
@pytest.mark.parametrize("resolved", [False, True])
def test_company_reference_is_replaced_only_by_a_clickable_logo(tmp_path: Path, logo_state: str, resolved: bool) -> None:
    """
    Avoid duplicate employer references without losing the destination when its logo cannot supply a link.

    Args:
        tmp_path (Path): Isolated rendering and asset directory.
        logo_state (str): Whether an employer logo is absent, decorative, or clickable.
        resolved (bool): Whether capture resolved the original company reference to a different destination.

    Returns:
        None: The employer destination appears once, as either a linked logo or its retained text reference.
    """
    Image.new("RGB", (20, 20), "blue").save(tmp_path / "logo.png")
    company_url = "https://www.linkedin.com/company/example/"
    destination = "https://www.linkedin.com/company/resolved/" if resolved else company_url
    logo = Media("https://example.org/logo.png", alt="Example Co logo", path="logo.png", link=company_url if logo_state == "linked" else "")
    entry = Entry(
        "Engineer",
        ["Example Co", "2020 - Present"],
        links=[Link(company_url, company_url, resolved_url=destination)],
        images=[] if logo_state == "missing" else [logo],
    )
    profile = Profile("example-person", "Alex", sections=[Section("experience", "Experience", [entry])])
    source = render_profile(profile, Config(LinkedIn(profile.username)), tmp_path).read_text()
    assert source.count(r"\href{" + destination + "}") == 1
    assert (r"\allowbreak{}company/" in source) is (logo_state != "linked")
    assert len(entry.links) == 1
