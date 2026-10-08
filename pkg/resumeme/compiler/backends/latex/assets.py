"""
Normalize configured website icons into portable LaTeX assets.
"""

from __future__ import annotations

import hashlib
from io import BytesIO
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import requests
from PIL import Image
from requests.adapters import HTTPAdapter

from resumeme.config import project_path
from resumeme.exceptions import MediaError, ProfileError
from resumeme.linkedin.media import _ExponentialRetry, fetch_public

if TYPE_CHECKING:
    from pathlib import Path

    from resumeme.config import Config

__all__ = ["stage_website_icon"]


def stage_website_icon(reference: str, config: Config, root: Path, directory: Path) -> str:
    """
    Decode a local image or public favicon into a content-addressed PNG beside the generated TeX.

    Args:
        reference (str): Configuration-relative raster path or direct public HTTP(S) image URL.
        config (Config): Existing capture timeout and exponential retry settings.
        root (Path): Configuration directory containing permitted local icons.
        directory (Path): Existing assets directory alongside generated TeX.

    Returns:
        str: Safe relative PNG path for templates, independent of the original filename or URL.

    Raises:
        ProfileError: An enabled icon cannot be read, downloaded, or decoded as a raster image.
        ConfigurationError: A local path escapes the configuration directory.
    """

    try:
        # Public icon downloads use the same credential isolation, redirect validation, limits, and retries as captured media.
        if urlsplit(reference).scheme in {"http", "https"}:
            with requests.Session() as session:
                session.trust_env = False
                session.headers["User-Agent"] = "resumeme/0.1 (public website icon)"
                policy = _ExponentialRetry(
                    total=config.capture.retry_attempts - 1,
                    backoff_factor=config.capture.retry_backoff_seconds,
                    backoff_max=config.capture.retry_max_backoff_seconds,
                    status_forcelist=(429, 500, 502, 503, 504),
                    allowed_methods=frozenset({"GET"}),
                    respect_retry_after_header=True,
                    retry_after_max=config.capture.retry_max_backoff_seconds,
                )
                session.mount("https://", HTTPAdapter(max_retries=policy))
                session.mount("http://", HTTPAdapter(max_retries=policy))
                body, _ = fetch_public(session, reference, config.capture.page_timeout_seconds)
        else:
            body = project_path(root, reference).read_bytes()

        # Decode by content, including ICO favicons; retain transparency and select the first frame of animated raster images.
        with Image.open(BytesIO(body)) as icon:
            buffer = BytesIO()
            icon.convert("RGBA").save(buffer, format="PNG")
    except (requests.RequestException, OSError, MediaError, Image.DecompressionBombError) as error:
        raise ProfileError(
            "Unable to load style.website_icon. Use a readable local image or a direct public image/favicon URL "
            "(PNG, JPEG, WebP, or ICO); HTML pages and SVG are not supported."
        ) from error

    # Hash normalized content so identical icons share an asset and source URLs never become TeX filenames.
    content = buffer.getvalue()
    name = hashlib.sha256(content).hexdigest() + ".png"
    (directory / name).write_bytes(content)
    return f"assets/{name}"
