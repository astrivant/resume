"""
Verify website visibility and portable local or public contact icons.
"""

from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest
import requests
import yaml
from attrs import evolve
from jsonschema import ValidationError
from PIL import Image
from requests.adapters import HTTPAdapter

from resumeme.compiler.asts.profile import Entry, Link, Media, Profile, Section
from resumeme.compiler.pipeline import render_profile
from resumeme.config import Config, GitHub, LinkedIn, Style, load_config
from resumeme.exceptions import ConfigurationError, MediaError, ProfileError

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch


def _profile() -> Profile:
    """
    Represent a flattened LinkedIn contact dialog with separate social identity links.

    Returns:
        Profile: A captured website and email without downloaded illustrations.
    """
    website = Link("linktr.ee", "https://linktr.ee/example-person")
    contact = Entry("Website", ["linktr.ee (Other)", "Email", "alex@example.org"], links=[website])
    return Profile("example-person", "Alex", sections=[Section("contact", "Contact info", [contact])])


@pytest.mark.parametrize("icon", ["missing.png", "https://example.org/favicon.ico"])
@pytest.mark.parametrize("visibility", ["default", "no-contact", "no-website"])
def test_unused_icons_require_no_files_or_requests(tmp_path: Path, monkeypatch: MonkeyPatch, icon: str, visibility: str) -> None:
    """
    Filter hidden websites before resolving icons or captured media, including for custom templates.

    Args:
        tmp_path (Path): Isolated render root.
        monkeypatch (MonkeyPatch): Scoped network boundary replacement.
        icon (str): Missing local path or remote resource that must not be read.
        visibility (str): Default field visibility, disabled section, or absent field.

    Returns:
        None: Website text and media cannot survive filtering, while enabled social and email links remain usable.
    """
    fetch = Mock(side_effect=AssertionError("Unused icon must not be fetched"))
    monkeypatch.setattr("resumeme.compiler.backends.latex.assets.fetch_public", fetch)
    profile = _profile()
    original = repr(profile)
    config = Config(
        LinkedIn(profile.username),
        github=GitHub(username="example-person"),
        style=Style(display_websites=visibility != "default", website_icon=icon),
    )

    if visibility == "no-contact":
        config = evolve(config, section_order=["about"])
    elif visibility == "no-website":
        profile = evolve(profile, sections=[Section("contact", "Contact info", [Entry("Email", ["alex@example.org"])])])
        original = repr(profile)
    else:
        # An unavailable image owned by the hidden website must not reach asset staging either.
        entry = evolve(profile.sections[0].entries[0], images=[Media("https://example.org/missing.png", alt="Website")])
        profile = evolve(profile, sections=[evolve(profile.sections[0], entries=[entry])])
        original = repr(profile)

    source = render_profile(profile, config, tmp_path).read_text()
    assert "linktr.ee" not in source
    assert ("mailto:alex@example.org" in source) is (visibility != "no-contact")
    assert ("https://github.com/example-person" in source) is (visibility != "no-contact")
    assert ("https://www.linkedin.com/in/example-person" in source) is (visibility != "no-contact")
    custom = tmp_path / "contact.tex.j2"
    custom.write_text("((( profile.sections )))|((( website_icon )))")
    source = render_profile(profile, evolve(config, template=custom.name), tmp_path).read_text()
    assert "linktr.ee" not in source and source.endswith("|None")
    assert repr(profile) == original
    fetch.assert_not_called()


@pytest.mark.parametrize("format_name", ["PNG", "JPEG", "ICO"])
@pytest.mark.parametrize("remote", [False, True])
def test_icons_normalize_into_safe_inline_pngs(tmp_path: Path, monkeypatch: MonkeyPatch, format_name: str, remote: bool) -> None:
    """
    Decode images by content and preserve a single stable asset across repeated website rows and rendering.

    Args:
        tmp_path (Path): Isolated config and asset root.
        monkeypatch (MonkeyPatch): Scoped public download replacement.
        format_name (str): Encoded raster format, including ICO favicons.
        remote (bool): Whether the image comes from HTTP instead of a local path.

    Returns:
        None: The template embeds a hashed PNG with social-icon dimensions and downloads use bounded credential-free retries.
    """
    buffer = BytesIO()
    Image.new("RGB", (32, 32), "green").save(buffer, format=format_name)
    reference = "https://example.org/icon?size=32&format=image" if remote else "website.image"
    config_path = tmp_path / "resumeme.config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "linkedin": {"username": "example-person"},
                "style": {
                    "display_websites": True,
                    "website_icon": reference,
                },
            }
        )
    )
    config = load_config(config_path)

    def fetch(session: requests.Session, url: str, timeout: int) -> tuple[bytes, str]:
        """
        Serve icon bytes while asserting the public transport contract.

        Args:
            session (requests.Session): Dedicated unauthenticated HTTP client.
            url (str): Exact configured URL, including its query parameters.
            timeout (int): Configured connect and read timeout.

        Returns:
            tuple[bytes, str]: Image content and final URL.
        """
        assert remote and url == reference
        assert not session.trust_env and session.auth is None and not session.cookies
        assert timeout == config.capture.page_timeout_seconds

        for scheme in ("http://", "https://"):
            adapter = session.get_adapter(scheme)
            assert isinstance(adapter, HTTPAdapter)
            assert adapter.max_retries.total == config.capture.retry_attempts - 1
            assert adapter.max_retries.allowed_methods == frozenset({"GET"})
            assert adapter.max_retries.backoff_factor == config.capture.retry_backoff_seconds
            assert adapter.max_retries.backoff_max == config.capture.retry_max_backoff_seconds
            assert 429 in (adapter.max_retries.status_forcelist or ())

        return buffer.getvalue(), url

    mocked_fetch = Mock(side_effect=fetch)
    monkeypatch.setattr("resumeme.compiler.backends.latex.assets.fetch_public", mocked_fetch)

    if not remote:
        (tmp_path / reference).write_bytes(buffer.getvalue())

    profile = _profile()
    source = render_profile(profile, config, tmp_path).read_text()
    assets = list((tmp_path / "tex" / "assets").glob("*.png"))
    assert len(assets) == 1 and len(assets[0].stem) == 64

    with Image.open(assets[0]) as normalized:
        assert normalized.format == "PNG" and normalized.mode == "RGBA"
        assert normalized.size == (32, 32)
        normalized.verify()

    assert rf"\includegraphics[width=1em,height=1em,keepaspectratio]{{assets/{assets[0].name}}}" in source
    assert source.index(assets[0].name) < source.index(r"\textbf{Website}")
    assert reference not in source
    assert source.count("https://linktr.ee/example-person") == 1
    assert "mailto:alex@example.org" in source
    assert mocked_fetch.call_count == int(remote)


@pytest.mark.parametrize("failure", ["missing", "invalid", "http", "private"])
def test_enabled_icon_failures_are_actionable(tmp_path: Path, monkeypatch: MonkeyPatch, failure: str) -> None:
    """
    Fail explicitly when requested branding cannot be read instead of silently dropping it.

    Args:
        tmp_path (Path): Isolated render root.
        monkeypatch (MonkeyPatch): Scoped transport failure replacement.
        failure (str): Missing file, invalid image, HTTP error, or rejected private address.

    Returns:
        None: All expected asset failures become package errors naming the configuration setting.
    """
    reference = "missing.png"

    if failure == "invalid":
        (tmp_path / reference).write_bytes(b"<html>Not an icon</html>")
    elif failure in {"http", "private"}:
        reference = "https://example.org/favicon.ico"
        error = requests.HTTPError("unavailable") if failure == "http" else MediaError("private networks")
        monkeypatch.setattr("resumeme.compiler.backends.latex.assets.fetch_public", Mock(side_effect=error))

    config = Config(LinkedIn("example-person"), style=Style(display_websites=True, website_icon=reference))

    with pytest.raises(ProfileError, match="style.website_icon"):
        render_profile(_profile(), config, tmp_path)


@pytest.mark.parametrize("display", [False, True])
def test_website_theme_overrides_visibility_and_icon(tmp_path: Path, display: bool) -> None:
    """
    Resolve website settings through the existing theme precedence before staging any assets.

    Args:
        tmp_path (Path): Isolated configuration directory.
        display (bool): Theme value opposing the base visibility.

    Returns:
        None: Theme overrides can show or hide websites and clear an inherited icon.
    """
    path = tmp_path / "resumeme.config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "linkedin": {"username": "example-person"},
                "style": {
                    "display_websites": not display,
                    "website_icon": "missing.png",
                    "theme": "custom",
                    "themes": {"custom": {"display_websites": display, "website_icon": None}},
                },
            }
        )
    )
    source = render_profile(_profile(), load_config(path), tmp_path).read_text()
    assert ("https://linktr.ee/example-person" in source) is display


@pytest.mark.parametrize("theme", [False, True])
@pytest.mark.parametrize(
    "settings",
    [
        {"display_websites": "false"},
        {"website_icon": True},
        {"website_icon": "../outside.png"},
        {"website_icon": "file:///tmp/website.png"},
        {"website_icon": "https://user:pass@example.org/icon"},
        {"website_icon": "https://example.org:bad/icon"},
    ],
)
def test_website_configuration_rejects_invalid_settings(tmp_path: Path, theme: bool, settings: dict[str, str | bool]) -> None:
    """
    Apply strict field types and path or URL validation equally to base and theme settings.

    Args:
        tmp_path (Path): Isolated configuration directory.
        theme (bool): Whether the invalid value belongs to a theme override.
        settings (dict[str, str | bool]): Invalid website setting.

    Returns:
        None: Invalid settings are rejected before rendering or downloading.
    """
    path = tmp_path / "resumeme.config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "linkedin": {"username": "example-person"},
                "style": {
                    "theme": "custom",
                    "themes": {"custom": settings},
                }
                if theme
                else settings,
            }
        )
    )

    with pytest.raises((ValidationError, ConfigurationError)):
        load_config(path)
