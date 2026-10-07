"""
Verify reproducible logo variants without modifying their source layers or calling an image service.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from resumeme.visualization.branding import render_logo


def test_logo_changes_visible_stain_but_repeats_the_same_revision(tmp_path: Path) -> None:
    """
    Produce visibly different, transparent logos across revisions and byte-identical retry output.

    Args:
        tmp_path (Path): Isolated generated logo directory.

    Returns:
        None: Revision-dependent image content is reproducible and neither source image is changed.
    """
    assets = Path(__file__).resolve().parents[3] / "docs/assets/branding"
    layers = [assets / "linkedin-base.png", assets / "coffee-ring.png"]
    before = [hashlib.sha256(path.read_bytes()).digest() for path in layers]
    first, retry, next_revision = (tmp_path / name for name in ("first.png", "retry.png", "next.png"))
    render_logo(assets, first, "a" * 40)
    render_logo(assets, retry, "a" * 40)
    render_logo(assets, next_revision, "b" * 40)
    assert first.read_bytes() == retry.read_bytes()
    assert [hashlib.sha256(path.read_bytes()).digest() for path in layers] == before

    # Compare decoded pixels as well as provenance: a different metadata string alone is not a new coffee stain.
    with Image.open(first) as one, Image.open(next_revision) as two:
        assert one.mode == two.mode == "RGBA"
        assert one.size == two.size == (768, 768)
        assert one.info["resumeme.source"] == "a" * 40
        assert two.info["resumeme.source"] == "b" * 40
        assert ImageChops.difference(one, two).convert("RGB").getbbox() is not None

        # The transparent outer margin allows the README mark to sit on either a light or dark page.
        for image in (one, two):
            alpha = image.getchannel("A")
            assert alpha.getextrema()[0] == 0
            assert alpha.getpixel((0, 0)) == 0
            assert alpha.getpixel((767, 767)) == 0

            # Unstained parts of the mark have 80% opacity; overlapping coffee adds density without making the base opaque.
            histogram = alpha.histogram()
            assert histogram[204] > 0
            assert any(histogram[205:255])
            assert histogram[255] == 0


def test_logo_rejects_missing_seed_before_writing(tmp_path: Path) -> None:
    """
    Require a stable revision instead of silently falling back to nondeterministic output.

    Args:
        tmp_path (Path): Isolated absent input and output paths.

    Returns:
        None: Invalid invocation leaves the output untouched.
    """
    output = tmp_path / "logo.png"

    with pytest.raises(ValueError, match="source revision"):
        render_logo(tmp_path, output, "")

    assert not output.exists()
