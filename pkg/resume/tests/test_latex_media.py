"""
Protect the distinction between profile portraits, organization branding, and content previews.
"""

from __future__ import annotations

import pytest

from resume.latex.media import image_role
from resume.models import Media


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
