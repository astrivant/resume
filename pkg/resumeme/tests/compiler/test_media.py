"""
Verify bounded credential-free media retrieval and visible asset failures.
"""

from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, Mock

import pytest
import requests
from attrs import evolve
from PIL import Image

from resumeme.compiler.asts.parsing import parse_detail
from resumeme.compiler.asts.profile import Entry, Link, Media, Profile, Section
from resumeme.compiler.passes.experience import filter_experience
from resumeme.config import Config, Experience, JobSelector, LinkedIn
from resumeme.linkedin.media import cache_media, fetch_public

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

    monkeypatch.setattr("resumeme.linkedin.media._validate_remote", validate)
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

    monkeypatch.setattr("resumeme.linkedin.media.fetch_public", fetch)
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
    monkeypatch.setattr("resumeme.linkedin.media.fetch_public", fetch)
    profile = Profile("example-person", "Alex Example", images=[Media("https://example.org/image", path="captured.png")])
    result = cache_media(profile, Config(LinkedIn("example-person")), tmp_path)
    assert result.images == profile.images
    assert not result.warnings
    fetch.assert_not_called()


def test_grouped_role_media_retains_ownership_and_reuses_downloads(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Cache nested role images once and remove only media owned by an excluded role.

    Args:
        tmp_path (Path): Temporary project directory.
        monkeypatch (MonkeyPatch): Scoped replacement for network fetching.

    Returns:
        None: Parent and role image paths agree and shared illustrations survive filtering.
    """
    buffer = BytesIO()
    Image.new("RGB", (20, 20), "blue").save(buffer, format="PNG")
    fetched: list[str] = []

    def fetch(session: requests.Session, url: str, timeout: int) -> tuple[bytes, str]:
        """
        Return deterministic media while counting actual requests.

        Args:
            session (requests.Session): Dedicated media client.
            url (str): Image source.
            timeout (int): Bounded request timeout.

        Returns:
            tuple[bytes, str]: Synthetic PNG bytes and source URL.
        """
        fetched.append(url)
        return buffer.getvalue(), url

    monkeypatch.setattr("resumeme.linkedin.media.fetch_public", fetch)
    html = """<main><ul><li class="artdeco-list__item"><p>Example</p><ul>
        <li><p>Staff</p><p>2020 - Present</p><img src="https://example.org/shared.png"></li>
        <li><p>Junior</p><p>2010 - 2019</p><img src="https://example.org/shared.png">
        <img src="https://example.org/old.png"></li></ul></li></ul></main>"""
    profile = Profile("example-person", "Alex", sections=[parse_detail(html, "experience", "Experience")])
    config = Config(LinkedIn(profile.username))
    result = cache_media(profile, evolve(config, capture=evolve(config.capture, fetch_link_previews=False)), tmp_path)
    assert fetched == ["https://example.org/shared.png", "https://example.org/old.png"]
    group = result.sections[0].entries[0]
    assert group.images[0].path == group.positions[0].images[0].path == group.positions[1].images[0].path
    assert (tmp_path / group.positions[0].images[0].path).is_file()
    selected = filter_experience([group], Experience(disable=[JobSelector(title="Junior")]))[0]
    assert [image.url for image in selected.images] == ["https://example.org/shared.png"]
    assert selected.positions == group.positions[:1]


def test_link_inspection_reuses_metadata_and_previews_across_profile_blocks(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Resolve short links once while retaining original text, per-occurrence labels, and role ownership.

    Args:
        tmp_path (Path): Temporary asset directory.
        monkeypatch (MonkeyPatch): Replaces remote fetching with a redirected page and its image.

    Returns:
        None: Intro, section, and role references share metadata and bytes without crawling other page links.
    """
    original = "https://lnkd.in/example"
    destination = "https://example.org/projects/tool/"
    buffer = BytesIO()
    Image.new("RGB", (30, 20), "blue").save(buffer, format="PNG")
    fetched: list[str] = []

    def fetch(session: requests.Session, url: str, timeout: int) -> tuple[bytes, str]:
        """
        Return only the linked page and its declared preview, failing on unexpected crawling.

        Args:
            session (requests.Session): Dedicated unauthenticated media session.
            url (str): Requested reference.
            timeout (int): Request deadline.

        Returns:
            tuple[bytes, str]: Page or image bytes and the observed final URL.
        """
        assert not session.trust_env
        fetched.append(url)

        if url == original:
            return (
                b'<html><head><base href="/assets/"><meta property="og:title" content="Tool &amp; docs">'
                b'<meta property="og:image" content="preview.png"></head><body>'
                b'<a href="https://example.org/do-not-crawl">More</a></body></html>',
                destination,
            )

        assert url == "https://example.org/assets/preview.png"
        return buffer.getvalue(), url

    monkeypatch.setattr("resumeme.linkedin.media.fetch_public", fetch)
    role = Entry("Engineer", [f"Built {original}."])
    entry = Entry("Company", links=[Link("Our project", original)], positions=[role])
    profile = Profile("example-person", "Alex", intro=[f"Portfolio: {original}."], sections=[Section("experience", "Experience", [entry])])
    result = cache_media(profile, Config(LinkedIn(profile.username)), tmp_path)
    assert fetched == [original, "https://example.org/assets/preview.png"]
    assert result.intro == profile.intro
    assert result.links == [Link(original, original, destination, "Tool & docs")]
    updated = result.sections[0].entries[0]
    assert updated.links == [Link("Our project", original, destination, "Tool & docs")]
    assert updated.positions[0].links == result.links
    assert updated.positions[0].images[0].path == result.images[0].path == updated.images[0].path
    assert result.images[0].link == original
    assert (tmp_path / result.images[0].path).read_bytes().startswith(b"\x89PNG")
    assert not result.warnings


@pytest.mark.parametrize("cycle", [False, True])
def test_linkedin_exit_pages_resolve_explicit_destinations_and_replace_placeholder_icons(
    tmp_path: Path, monkeypatch: MonkeyPatch, cycle: bool
) -> None:
    """
    Follow LinkedIn's HTTP-200 short-link exit control while bounding loops and upgrading legacy previews.

    Args:
        tmp_path (Path): Temporary image cache.
        monkeypatch (MonkeyPatch): Replaces HTTP responses with public exit-page markup.
        cycle (bool): Whether the exit control points back to itself.

    Returns:
        None: External pages supply titles and icons, while cyclic links remain unresolved with a warning.
    """
    original = "https://lnkd.in/example"
    destination = "https://example.org/tool"
    buffer = BytesIO()
    Image.new("RGB", (20, 20), "blue").save(buffer, format="PNG")
    Image.new("RGB", (20, 20), "red").save(tmp_path / "placeholder.png")
    fetched: list[str] = []

    def fetch(session: requests.Session, url: str, timeout: int) -> tuple[bytes, str]:
        """
        Serve an exit page, the target HTML, and its explicit relative icon.

        Args:
            session (requests.Session): Unauthenticated request client.
            url (str): Requested URL.
            timeout (int): Configured request bound.

        Returns:
            tuple[bytes, str]: Synthetic response bytes and observed URL.
        """
        fetched.append(url)

        if url == original:
            target = original if cycle else destination
            return (
                f'<html><head><title>LinkedIn</title></head><body><a data-tracking-control-name="external_url_click" href="{target}">'
                'Continue</a><a href="https://www.linkedin.com/help">Help</a></body></html>'
            ).encode(), url

        if url == destination:
            return b'<html><head><title>Actual project</title><link rel="icon" href="/icon.png"></head></html>', url

        assert url == "https://example.org/icon.png"
        return buffer.getvalue(), url

    monkeypatch.setattr("resumeme.linkedin.media.fetch_public", fetch)
    placeholder = Media("https://static.licdn.com/icon.png", original, "placeholder.png", original)
    profile = Profile("example-person", "Alex", intro=[original], images=[placeholder])
    result = cache_media(profile, Config(LinkedIn(profile.username)), tmp_path)

    if cycle:
        assert fetched == [original]
        assert result.links == [Link(original, original)]
        assert result.images == [placeholder]
        assert len(result.warnings) == 1
    else:
        assert fetched == [original, destination, "https://example.org/icon.png"]
        assert result.links == [Link(original, original, destination, "Actual project")]
        assert len(result.images) == 1
        assert result.images[0].url == "https://example.org/icon.png"
        assert not result.warnings


@pytest.mark.parametrize("previews_enabled", [False, True])
def test_contact_links_and_disabled_previews_do_not_trigger_inspection(
    tmp_path: Path, monkeypatch: MonkeyPatch, previews_enabled: bool
) -> None:
    """
    Keep URL discovery independent of optional network inspection and contact metadata.

    Args:
        tmp_path (Path): Temporary project directory.
        monkeypatch (MonkeyPatch): Records unexpected network calls.
        previews_enabled (bool): Whether project previews are enabled for non-contact sections.

    Returns:
        None: Contact URLs remain clickable without requests, and disabling previews still discovers prose links.
    """
    fetch = MagicMock(side_effect=AssertionError("No inspection expected"))
    monkeypatch.setattr("resumeme.linkedin.media.fetch_public", fetch)
    section = "contact" if previews_enabled else "about"
    profile = Profile("example-person", "Alex", sections=[Section(section, section, [Entry("Website: www.example.org.")])])
    config = Config(LinkedIn(profile.username))
    result = cache_media(profile, evolve(config, capture=evolve(config.capture, fetch_link_previews=previews_enabled)), tmp_path)
    assert result.sections[0].entries[0].links == [Link("www.example.org", "https://www.example.org")]
    assert not result.warnings
    fetch.assert_not_called()


@pytest.mark.parametrize("failure", [False, True])
def test_direct_downloads_and_unavailable_pages_retain_the_original_reference(
    tmp_path: Path, monkeypatch: MonkeyPatch, failure: bool
) -> None:
    """
    Resolve binary downloads without invented icons and retain failed references with diagnostics.

    Args:
        tmp_path (Path): Temporary project directory.
        monkeypatch (MonkeyPatch): Replaces the network boundary.
        failure (bool): Whether fetching the destination fails instead of returning a PDF.

    Returns:
        None: Binary links resolve without preview images, and failed inspection leaves the captured reference intact.
    """
    original = "https://example.org/download"
    destination = "https://example.org/report.pdf"
    fetch = MagicMock(side_effect=requests.HTTPError("unavailable")) if failure else MagicMock(return_value=(b"%PDF-1.7\n", destination))
    monkeypatch.setattr("resumeme.linkedin.media.fetch_public", fetch)
    profile = Profile("example-person", "Alex", intro=[original], links=[Link("Report", original)])
    result = cache_media(profile, Config(LinkedIn(profile.username)), tmp_path)
    assert result.links == [Link("Report", original, "" if failure else destination)]
    assert not result.images
    assert len(result.warnings) == int(failure)
    fetch.assert_called_once()
