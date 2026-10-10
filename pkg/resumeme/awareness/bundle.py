"""
Validate versioned PNG bundles and stage only explicitly enabled appendix figures.
"""

from __future__ import annotations

import base64
import hashlib
import json
import warnings
from importlib.resources import files
from io import BytesIO
from typing import TYPE_CHECKING

from attrs import frozen
from jsonschema import Draft202012Validator
from PIL import Image, UnidentifiedImageError

from resumeme.awareness.models import (
    BUNDLE_PATH,
    FIGURE_DESCRIPTIONS,
    FIGURE_LABELS,
    FIGURES,
    MAX_BUNDLE_BYTES,
    MAX_IMAGE_BYTES,
    selected_figures,
)
from resumeme.config.loading import project_path
from resumeme.exceptions import RenderingError

if TYPE_CHECKING:
    from pathlib import Path

    from resumeme.config import Config


@frozen
class Figure:
    """
    Hold decoded data after schema, catalog, hash, and raster validation.

    Attributes:
        id (str): Catalog identifier.
        title (str): Plain caption escaped by the LaTeX backend.
        png (bytes): Verified PNG bytes.
    """

    id: str
    title: str
    png: bytes


def validate_bundle(content: bytes) -> tuple[Figure, ...]:
    """
    Reject malformed, duplicate, oversized, or mismatched images before filesystem writes.

    Args:
        content (bytes): Complete JSON bundle from local data or authenticated GitHub storage.

    Returns:
        tuple[Figure, ...]: Validated ordered figures.

    Raises:
        RenderingError: The bundle violates size, identity, digest, or PNG constraints.
        jsonschema.ValidationError: Its versioned wire fields do not match the schema.
    """
    if len(content) > MAX_BUNDLE_BYTES:
        raise RenderingError("Awareness bundle exceeds the 8 MiB limit.")

    value = json.loads(content)
    schema = json.loads(files("resumeme.compiler.asts.resources").joinpath("awareness.schema.json").read_text())
    Draft202012Validator(schema).validate(value)
    figures = []
    seen: set[str] = set()

    for item in value["figures"]:
        key = item["id"]

        if key in seen or FIGURES.get(key) != item["group"]:
            raise RenderingError("Awareness figure IDs must be unique and match their catalog groups.")

        seen.add(key)
        image = base64.b64decode(item["png"], validate=True)

        if len(image) > MAX_IMAGE_BYTES or hashlib.sha256(image).hexdigest() != item["sha256"]:
            raise RenderingError("Awareness PNG size or SHA-256 does not match its manifest.")

        # Decode once with a bounded pixel count; LaTeX only receives normalized raster files, never arbitrary source.
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)

                with Image.open(BytesIO(image)) as raster:
                    if raster.format != "PNG" or raster.width * raster.height > 16_000_000 or getattr(raster, "n_frames", 1) != 1:
                        raise RenderingError("Awareness figures must be single-frame PNGs with at most 16 million pixels.")
                    raster.verify()
        except (UnidentifiedImageError, OSError, Image.DecompressionBombWarning, Image.DecompressionBombError) as error:
            raise RenderingError("Awareness figure is not a valid bounded PNG.") from error

        figures.append(Figure(key, item["title"], image))

    return tuple(figures)


def stage_figures(config: Config, root: Path, directory: Path) -> list[dict[str, str]]:
    """
    Create deterministic compiler assets only when figures are explicitly selected.

    Args:
        config (Config): Validated document configuration.
        root (Path): Configuration directory containing the accepted bundle.
        directory (Path): Compiler output directory receiving normalized PNGs.

    Returns:
        list[dict[str, str]]: Selected titles, short purpose labels, explanations, IDs, and safe relative image paths.

    Raises:
        RenderingError: Enabled figures have no matching accepted bundle data.
    """
    selected = selected_figures(config.appendices.awareness)

    if not selected:
        return []

    path = project_path(root, BUNDLE_PATH)

    if not path.is_file():
        raise RenderingError("Enabled awareness figures require data/awareness.json; run witful awareness push or copy a reviewed bundle.")

    available = {figure.id: figure for figure in validate_bundle(path.read_bytes())}

    if not set(selected) <= available.keys():
        raise RenderingError(
            "The awareness bundle is missing an enabled figure; publish it or disable it in document.appendices.awareness."
        )

    output = []
    assets = directory / "awareness"
    assets.mkdir(parents=True, exist_ok=True)

    for key in selected:
        figure = available[key]
        target = assets / f"{key}.png"

        # Re-encode to omit image metadata and retain only decoded pixels in the final document assets.
        with Image.open(BytesIO(figure.png)) as raster:
            raster.convert("RGB").save(target, format="PNG")

        output.append(
            {
                "id": key,
                "title": figure.title,
                "label": FIGURE_LABELS[key],
                "description": FIGURE_DESCRIPTIONS[key],
                "path": f"awareness/{key}.png",
            }
        )

    return output
