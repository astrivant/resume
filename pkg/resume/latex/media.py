"""
Distinguish identity images from content previews when mapping LinkedIn media to print.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from typing import Literal

    from resume.models import Media

__all__ = ["image_role", "is_header_photo"]


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
