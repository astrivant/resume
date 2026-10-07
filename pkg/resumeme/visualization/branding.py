"""
Compose a reproducible coffee-stained project logo for each published source revision.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from PIL import Image, ImageEnhance, ImageOps
from PIL.PngImagePlugin import PngInfo

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["render_logo"]

_SIZE = 768


def render_logo(assets: Path, output: Path, seed: str) -> None:
    """
    Vary the coffee overlay while preserving the underlying mark and transparent background.

    Args:
        assets (Path): Directory containing linkedin-base.png and coffee-ring.png source layers.
        output (Path): Destination PNG; parent directories are created and an existing output is replaced.
        seed (str): Source revision determining the stain's orientation, proportions, position, and density.

    Returns:
        None: A composed logo is written without modifying either source layer or contacting an image service.

    Raises:
        ValueError: The seed is empty or the stain has no visible pixels.
        OSError: Source layers cannot be read or the destination cannot be written.
    """
    if not seed:
        raise ValueError("A nonempty source revision is required for reproducible coffee stains.")

    # Derive variation from content rather than time or run number, so a publication retry has the same Git tree.
    digest = hashlib.sha256(seed.encode("utf-8")).digest()

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
    opacity = 0.65 + 0.25 * digest[7] / 255
    stain.putalpha(stain.getchannel("A").point([round(value * opacity) for value in range(256)]))

    # Choose a corner with a little positional variation; keep the ring off center so it reads as a stain rather than a border.
    margin = round(_SIZE * 0.025)
    x = margin + round((_SIZE - width - 2 * margin) * 0.1 * digest[8] / 255)
    y = margin + round((_SIZE - height - 2 * margin) * 0.1 * digest[9] / 255)

    if digest[10] & 1:
        x = _SIZE - width - x

    if digest[10] & 2:
        y = _SIZE - height - y

    base.alpha_composite(stain, (x, y))

    # Record the input revision without timestamps; locked Pillow versions produce byte-identical retry artifacts.
    metadata = PngInfo()
    metadata.add_text("resumeme.source", seed)
    output.parent.mkdir(parents=True, exist_ok=True)
    base.save(output, format="PNG", pnginfo=metadata, optimize=True)
