"""
Distinguish identity images from content previews when mapping LinkedIn media to print.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from resumeme.compiler.asts.dates import employment_period

if TYPE_CHECKING:
    from typing import Literal

    from resumeme.compiler.asts.profile import Entry, Media

__all__ = ["employer_badge", "image_role", "is_header_photo"]


def employer_badge(entry: Entry) -> tuple[int, Media] | None:
    """
    Associate an employer logo with the company heading or first employer line.

    Args:
        entry (Entry): Visible employment entry with staged images and optional grouped roles.

    Returns:
        tuple[int, Media] | None: Company text index (-1 for the heading, 0 for the first paragraph) and logo, or no safe match.
    """
    logos = [image for image in entry.images if image_role(image) == "logo"]

    if not logos:
        return None

    # Explicit company groups and legacy flattened groups put the employer in the heading, above their individual roles.
    dates = [index for index, line in enumerate(entry.paragraphs) if employment_period(line)]

    if entry.positions or len(dates) > 1:
        return -1, logos[0]

    for image in logos:
        company = image.alt.casefold().removesuffix(" logo").strip()

        if company and company == entry.title.strip().casefold():
            return -1, image

        if entry.paragraphs and company and company == entry.paragraphs[0].split("·", 1)[0].strip().casefold():
            return 0, image

    # Standalone jobs place their employer immediately before the employment dates; undated or absent names stay unchanged.
    return (0, logos[0]) if dates and dates[0] == 1 else None


def is_header_photo(image: Media) -> bool:
    """
    Recognize a cover photo even when LinkedIn omits its accessible label.

    Args:
        image (Media): Captured image reference.

    Returns:
        bool: Whether the label or source path identifies a cover/background photo.
    """
    label = image.alt.casefold()
    return "background" in label or "cover" in label or "profile-displaybackgroundimage" in urlsplit(image.url).path.casefold()


def image_role(image: Media, *, header: bool = False) -> Literal["cover", "portrait", "logo", "icon", "preview"]:
    """
    Infer an image's visual role from source metadata rather than downloaded pixel dimensions.

    Args:
        image (Media): Original URL, accessible label, and optional click destination.
        header (bool): Whether an otherwise unclassified image belongs to the profile header.

    Returns:
        Literal["cover", "portrait", "logo", "icon", "preview"]: Presentation role; body images default to uncropped previews.
    """

    # LinkedIn serves logos and portraits at the same resolution; natural pixel size cannot establish their importance.
    path = urlsplit(image.url).path.casefold()
    label = image.alt.casefold().strip()

    if is_header_photo(image):
        return "cover"

    # Favicon paths often contain "logos", so recognize these small site icons before organization branding.
    if "favicon" in path or "apple-touch-icon" in path or label in {"favicon", "site icon"}:
        return "icon"

    if "profile-displayphoto" in path or label in {"profile photo", "profile picture", "portrait"}:
        return "portrait"

    if any(marker in path for marker in ("company-logo", "school-logo", "organization-logo")):
        return "logo"

    # A preview may depict a logo or link to a company; its attachment role still takes precedence over that destination.
    if label.startswith("thumbnail") or any(marker in path for marker in ("articleshare", "profile-treasury", "feedshare")):
        return "preview"

    if label == "logo" or label.endswith(" logo") or path.rsplit("/", 1)[-1].startswith("logo."):
        return "logo"

    if urlsplit(image.link).path.casefold().startswith(("/company/", "/school/")):
        return "logo"

    # Older captures lack explicit portrait labels; retain the header fallback after excluding known secondary images.
    return "portrait" if header else "preview"
