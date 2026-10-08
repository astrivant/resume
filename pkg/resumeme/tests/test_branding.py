"""
Verify reproducible logo variants without modifying their source layers or calling an image service.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image, ImageChops
from PIL.PngImagePlugin import PngInfo

from resumeme.visualization.branding import _coffee_layer, render_logo


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


def test_recent_stains_survive_publications_and_retries_without_unbounded_history(tmp_path: Path) -> None:
    """
    Accumulate real revisions, evict the oldest, and avoid aging the trail on retries or previews.

    Args:
        tmp_path (Path): Isolated publication and preview outputs.

    Returns:
        None: The saved five-revision history and its pixels remain stable on a retry.
    """
    assets = Path(__file__).resolve().parents[3] / "docs/assets/branding"
    output = tmp_path / "logo.png"

    # Bootstrap from the metadata written by the original single-stain renderer.
    metadata = PngInfo()
    metadata.add_text("resumeme.source", "legacy")
    Image.new("RGBA", (1, 1)).save(output, pnginfo=metadata)
    revisions = ["legacy"]

    for index in range(6):
        seed = f"revision-{index}"
        render_logo(assets, output, seed, previous=output)
        revisions.insert(0, seed)

        with Image.open(output) as image:
            assert json.loads(image.info["resumeme.stains"]) == revisions[:5]

    # A retry may read the already-written output, while previews must leave the canonical image untouched.
    published = output.read_bytes()
    render_logo(assets, output, revisions[0], previous=output)
    assert output.read_bytes() == published
    preview = tmp_path / "preview.png"
    render_logo(assets, preview, revisions[0], previous=output)
    assert preview.read_bytes() == published
    render_logo(assets, preview, "next-revision", previous=output)
    assert preview.read_bytes() != published
    assert output.read_bytes() == published


@pytest.mark.parametrize(("seed", "count"), [("0", 2), ("h", 4), ("c", 3), ("d", 5)])
def test_logo_varies_recent_trail_length_and_composites_oldest_first(tmp_path: Path, seed: str, count: int) -> None:
    """
    Draw a bounded recent trail with the fresh stain on top, without forgetting temporarily hidden revisions.

    Args:
        tmp_path (Path): Isolated prior history and output paths.
        seed (str): Stable revision selecting a known trail length.
        count (int): Expected number of visible impressions for this revision.

    Returns:
        None: The chosen recent stains are layered oldest first and all five revisions remain available.
    """
    assets = Path(__file__).resolve().parents[3] / "docs/assets/branding"
    previous = tmp_path / "previous.png"
    history = ["prior-1", "prior-2", "prior-3", "prior-4", "prior-5"]
    metadata = PngInfo()
    metadata.add_text("resumeme.source", history[0])
    metadata.add_text("resumeme.stains", json.dumps(history))
    Image.new("RGBA", (1, 1)).save(previous, pnginfo=metadata)
    output = tmp_path / "logo.png"

    # Observe real layer rendering to verify both selection and depth order rather than only PNG metadata.
    with patch("resumeme.visualization.branding._coffee_layer", wraps=_coffee_layer) as layer:
        render_logo(assets, output, seed, previous=previous)
        assert [(call.args[1], call.args[2]) for call in layer.call_args_list] == [
            (revision, age) for age, revision in reversed(list(enumerate([seed, *history][:count])))
        ]

    with Image.open(output) as image:
        assert json.loads(image.info["resumeme.stains"]) == [seed, *history[:4]]


def test_older_stains_fade_without_moving_or_mutating_the_source() -> None:
    """
    Reduce an existing impression's alpha while preserving its placement and reusable source pixels.

    Returns:
        None: Every successive age is fainter and the source remains unchanged.
    """
    source = Image.new("RGBA", (20, 20), (100, 50, 20, 255))
    original = source.tobytes()
    fresh = _coffee_layer(source, "fixed-revision", 0).getchannel("A")

    for age in range(1, 5):
        faded = _coffee_layer(source, "fixed-revision", age).getchannel("A")
        assert ImageChops.subtract(faded, fresh).getbbox() is None
        previous_peak = fresh.getextrema()[1]
        assert isinstance(previous_peak, (int, float))
        assert faded.getextrema()[1] == pytest.approx(previous_peak * 0.6, abs=1)
        assert faded.getbbox() == fresh.getbbox()
        fresh = faded

    assert source.tobytes() == original


@pytest.mark.parametrize("history", ["not-json", "[]", '["prior", "prior"]', '["prior", 12]', '["wrong-source"]'])
def test_invalid_stain_history_does_not_replace_the_logo(tmp_path: Path, history: str) -> None:
    """
    Reject damaged provenance instead of silently discarding the published trail.

    Args:
        tmp_path (Path): Isolated published PNG.
        history (str): Invalid JSON history or inconsistent source metadata.

    Returns:
        None: Failure occurs before the existing output or source layers are modified.
    """
    output = tmp_path / "logo.png"
    metadata = PngInfo()
    metadata.add_text("resumeme.source", "prior")
    metadata.add_text("resumeme.stains", history)
    Image.new("RGBA", (1, 1)).save(output, pnginfo=metadata)
    original = output.read_bytes()

    with pytest.raises(ValueError):
        render_logo(tmp_path, output, "next", previous=output)

    assert output.read_bytes() == original
