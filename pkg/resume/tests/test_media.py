"""
Verify bounded credential-free media retrieval and visible asset failures.
"""

from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, Mock

import pytest
import requests
from PIL import Image

from resume.config import Config, LinkedIn
from resume.linkedin.media import cache_media, fetch_public
from resume.models import Media, Profile

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch


def test_private_network_media_is_rejected() -> None:
    """
    Prevent remote profile content from requesting loopback services.

    Returns:
        None: The request is rejected before HTTP transport.
    """
    with requests.Session() as session, pytest.raises(ValueError, match="private networks"):
        fetch_public(session, "http://127.0.0.1/internal", 1)


def test_redirects_are_revalidated_and_cookies_cleared(monkeypatch: MonkeyPatch) -> None:
    """
    Reject redirects to local hosts and remove response cookies before each request.

    Args:
        monkeypatch (MonkeyPatch): Scoped replacement for network boundaries.

    Returns:
        None: A local redirect never reaches the HTTP client.
    """
    checked: list[str] = []

    def validate(url: str) -> None:
        """
        Accept the first URL and reject its local redirect target.

        Args:
            url (str): URL being checked.

        Returns:
            None: The initial public URL is accepted.
        """
        checked.append(url)
        if "127.0.0.1" in url:
            raise ValueError("private networks")

    monkeypatch.setattr("resume.linkedin.media._validate_remote", validate)
    response = Mock()
    response.is_redirect = True
    response.headers = {"Location": "http://127.0.0.1/private"}
    session = MagicMock(spec=requests.Session)
    session.cookies = Mock()
    session.get.return_value.__enter__.return_value = response
    with pytest.raises(ValueError, match="private networks"):
        fetch_public(session, "https://example.org/image.png", 1)
    assert checked == ["https://example.org/image.png", "http://127.0.0.1/private"]
    session.get.assert_called_once()
    session.cookies.clear.assert_called_once()


def test_images_become_portable_pngs(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Cache valid images in a reproducible format while retaining broken references.

    Args:
        tmp_path (Path): Temporary project directory.
        monkeypatch (MonkeyPatch): Scoped replacement for remote fetching.

    Returns:
        None: Valid images are saved and failed images remain visible as warnings.
    """
    buffer = BytesIO()
    Image.new("RGB", (40, 20), "blue").save(buffer, format="JPEG")

    def fetch(session: requests.Session, url: str, timeout: int) -> tuple[bytes, str]:
        """
        Serve a synthetic image and simulate one broken remote reference.

        Args:
            session (requests.Session): Client whose credential policy is checked.
            url (str): Synthetic image URL.
            timeout (int): Configured bound on a request.

        Returns:
            tuple[bytes, str]: Synthetic image bytes and original URL.
        """
        assert session.trust_env is False
        assert timeout > 0
        if url.endswith("broken"):
            raise requests.HTTPError("unavailable")
        return buffer.getvalue(), url

    monkeypatch.setattr("resume.linkedin.media.fetch_public", fetch)
    profile = Profile("example-person", "Alex Example", images=[Media("https://example.org/image"), Media("https://example.org/broken")])
    result = cache_media(profile, Config(LinkedIn("example-person")), tmp_path)
    assert (tmp_path / result.images[0].path).read_bytes().startswith(b"\x89PNG")
    assert result.images[1].path == ""
    assert len(result.warnings) == 1


def test_download_recovery_reuses_recorded_assets(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Keep completed assets when recovering a snapshot after an interrupted download.

    Args:
        tmp_path (Path): Temporary project directory.
        monkeypatch (MonkeyPatch): Scoped request recorder.

    Returns:
        None: Existing captured media is reused without another network request.
    """
    Image.new("RGB", (20, 20), "blue").save(tmp_path / "captured.png")
    fetch = MagicMock()
    monkeypatch.setattr("resume.linkedin.media.fetch_public", fetch)
    profile = Profile("example-person", "Alex Example", images=[Media("https://example.org/image", path="captured.png")])
    result = cache_media(profile, Config(LinkedIn("example-person")), tmp_path)
    assert result.images == profile.images
    assert not result.warnings
    fetch.assert_not_called()
