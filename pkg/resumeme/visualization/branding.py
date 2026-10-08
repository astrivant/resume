"""
Compose a reproducible coffee-stained project logo for each published source revision.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from PIL import Image, ImageEnhance, ImageOps
from PIL.PngImagePlugin import PngInfo

if TYPE_CHECKING:
    from datetime import date
    from pathlib import Path

__all__ = ["render_brew_badge", "render_logo"]

_SIZE = 768
_MAX_STAINS = 5
_STAIN_FADE = 0.6


def render_brew_badge(output: Path, brewed_on: date) -> None:
    """
    Render a local SVG date badge using the project's coffee palette.

    Args:
        output (Path): Destination SVG; parent directories are created as needed.
        brewed_on (date): UTC calendar date recorded with the published PDF artifact.

    Returns:
        None: A deterministic, accessible badge is written without external image requests.
    """
    label = f"Brew date: {brewed_on.isoformat()} (UTC)"

    # Fixed date formatting keeps the badge width stable across builds; the README owns the clickable PDF destination.
    content = f"""<svg xmlns="http://www.w3.org/2000/svg" width="220" height="28" viewBox="0 0 220 28" role="img" aria-labelledby="title">
  <title id="title">{label}</title>
  <defs><clipPath id="badge"><rect width="220" height="28" rx="4"/></clipPath></defs>
  <g clip-path="url(#badge)">
    <rect width="220" height="28" fill="#6B2737"/>
    <rect x="90" width="130" height="28" fill="#F7EADD"/>
  </g>
  <g font-family="Verdana,DejaVu Sans,sans-serif" font-size="11" text-anchor="middle">
    <text x="45" y="18" fill="#FFFFFF">Brew date:</text>
    <text x="155" y="18" fill="#363636">{brewed_on.isoformat()}</text>
  </g>
</svg>
"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")


def render_logo(assets: Path, output: Path, seed: str, *, previous: Path | None = None) -> None:
    """
    Layer a fresh coffee stain over fading recent impressions without changing the underlying mark.

    Args:
        assets (Path): Directory containing linkedin-base.png and coffee-ring.png source layers.
        output (Path): Destination PNG; parent directories are created and an existing output is replaced.
        seed (str): Source revision determining the stain's orientation, proportions, position, and density.
        previous (Path | None): Prior logo containing stain history; absent files or None start a new history.

    Returns:
        None: A composed logo is written without modifying either source layer or contacting an image service.

    Raises:
        ValueError: The seed is empty, saved history is invalid, or the stain has no visible pixels.
        OSError: Source layers cannot be read or the destination cannot be written.
    """
    if not seed:
        raise ValueError("A nonempty source revision is required for reproducible coffee stains.")

    # Derive variation from content rather than time or run number, so a publication retry has the same Git tree.
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    history = list(dict.fromkeys([seed, *_stain_history(previous)]))[:_MAX_STAINS]
    visible = history[: 2 + digest[11] % (_MAX_STAINS - 1)]

    with Image.open(assets / "linkedin-base.png") as source:
        base = source.convert("RGBA").resize((_SIZE, _SIZE), Image.Resampling.LANCZOS)

    # Mute the mark beneath the coffee while leaving the overlay's color and density independent of the base fade.
    base = ImageEnhance.Color(base).enhance(0.8)
    base.putalpha(base.getchannel("A").point([round(value * 0.8) for value in range(256)]))

    with Image.open(assets / "coffee-ring.png") as source:
        stain = source.convert("RGBA")

    # Trim transparent padding before transforming the stain; only the coffee moves, never the blue mark or lettering.
    bounds = stain.getbbox()

    if bounds is None:
        raise ValueError("The coffee overlay must contain visible pixels.")

    stain = stain.crop(bounds)

    # Recompose immutable layers oldest first; old rings fade independently while the newest ring stays prominent.
    for age in reversed(range(len(visible))):
        base.alpha_composite(_coffee_layer(stain, visible[age], age))

    # Retain five actual revisions even when fewer rings are visible, so a later draw can show a longer recent trail.
    metadata = PngInfo()
    metadata.add_text("resumeme.source", seed)
    metadata.add_text("resumeme.stains", json.dumps(history))
    output.parent.mkdir(parents=True, exist_ok=True)
    base.save(output, format="PNG", pnginfo=metadata, optimize=True)


def _stain_history(previous: Path | None) -> list[str]:
    """
    Read recent revisions from the prior PNG, including the original single-stain metadata.

    Args:
        previous (Path | None): Existing published logo, or None to start without prior stains.

    Returns:
        list[str]: At most five unique revisions, newest first.

    Raises:
        ValueError: Stored history is malformed or inconsistent with its source revision.
        OSError: An existing logo cannot be opened.
    """
    if previous is None or not previous.exists():
        return []

    with Image.open(previous) as image:
        encoded: object = image.info.get("resumeme.stains")
        source: object = image.info.get("resumeme.source")

    # Previously generated logos retain their one recorded impression; unversioned artwork starts a fresh history.
    if encoded is None:
        return [source] if isinstance(source, str) and source else []

    if not isinstance(encoded, str):
        raise ValueError("Coffee stain history must be a JSON list of source revisions.")

    values: object = json.loads(encoded)

    if not isinstance(values, list) or not 1 <= len(values) <= _MAX_STAINS:
        raise ValueError("Coffee stain history must contain one to five source revisions.")

    history: list[str] = []

    for value in values:
        if not isinstance(value, str) or not value or value in history:
            raise ValueError("Coffee stain history must contain unique, nonempty source revisions.")

        history.append(value)

    if history[0] != source:
        raise ValueError("The newest coffee stain must match the logo's source revision.")

    return history


def _coffee_layer(stain: Image.Image, seed: str, age: int) -> Image.Image:
    """
    Recreate a revision's original coffee impression at an opacity determined by its age.

    Args:
        stain (Image.Image): Cropped RGBA source layer; the caller retains ownership and it is not modified.
        seed (str): Revision fixing this impression's geometry and color.
        age (int): Number of newer revisions, zero for the fresh stain.

    Returns:
        Image.Image: Transparent logo-sized RGBA layer with the transformed, faded impression.
    """
    digest = hashlib.sha256(seed.encode("utf-8")).digest()

    if digest[0] & 1:
        stain = ImageOps.mirror(stain)

    angle = int.from_bytes(digest[1:3]) * 360 / 65536
    stain = stain.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
    stain = stain.crop(stain.getbbox())

    # A slightly smaller cup impression leaves room for a clear offset without clipping the ring or its droplets.
    width = round(_SIZE * (0.65 + 0.08 * digest[3] / 255))
    height = round(_SIZE * (0.65 + 0.08 * digest[4] / 255))
    stain = stain.resize((width, height), Image.Resampling.LANCZOS)
    stain = ImageEnhance.Color(stain).enhance(0.7 + 0.3 * digest[5] / 255)
    stain = ImageEnhance.Brightness(stain).enhance(0.8 + 0.2 * digest[6] / 255)
    opacity = (0.65 + 0.25 * digest[7] / 255) * _STAIN_FADE**age
    stain.putalpha(stain.getchannel("A").point([round(value * opacity) for value in range(256)]))

    # Choose a corner with a little positional variation; keep the ring off center so it reads as a stain rather than a border.
    margin = round(_SIZE * 0.025)
    x = margin + round((_SIZE - width - 2 * margin) * 0.1 * digest[8] / 255)
    y = margin + round((_SIZE - height - 2 * margin) * 0.1 * digest[9] / 255)

    if digest[10] & 1:
        x = _SIZE - width - x

    if digest[10] & 2:
        y = _SIZE - height - y

    layer = Image.new("RGBA", (_SIZE, _SIZE))
    layer.alpha_composite(stain, (x, y))
    return layer
