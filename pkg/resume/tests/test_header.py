"""
Verify optional connection metadata and concise first-page identity rendering.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml
from attrs import evolve
from jsonschema import ValidationError

from resume.config import Config, LinkedIn, Style, load_config
from resume.latex.header import prepare_header
from resume.latex.rendering import render_profile
from resume.models import Entry, Link, Profile, Section

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("show_count", [False, True])
@pytest.mark.parametrize("show_link", [False, True])
def test_connection_display_flags_are_independent(tmp_path: Path, show_count: bool, show_link: bool) -> None:
    """
    Render a count, a concise link, both together, or neither without duplicate metadata.

    Args:
        tmp_path (Path): Isolated rendering root.
        show_count (bool): Whether the captured count should appear.
        show_link (bool): Whether the captured connections destination should appear.

    Returns:
        None: The packaged template honors both flags and leaves the source profile intact.
    """
    connections = "https://www.linkedin.com/mynetwork/invite-connect/connections/"
    duplicate = "https://www.linkedin.com/in/example-person/?isSelfProfile=true"
    profile = Profile(
        "example-person",
        "Alex",
        intro=["Staff engineer", "Contact info", "214 connections"],
        links=[Link(duplicate, duplicate), Link("214 connections", connections)],
        sections=[Section("contact", "Contact info", [Entry("Private contact block")])],
    )
    config = Config(
        LinkedIn(profile.username),
        style=Style(show_connection_count=show_count, show_connection_link=show_link),
        disable=["contact"],
    )
    source = render_profile(profile, config, tmp_path).read_text().split(r"\begin{document}", 1)[1]
    assert source.count("214 connections") == int(show_count)
    assert (connections in source) is show_link
    assert source.count(r"\textbf{LinkedIn profile}") == 1
    assert "isSelfProfile" not in source
    assert "Private contact block" not in source
    assert "Contact info" not in source

    if show_link:
        label = "214 connections" if show_count else "Connections"
        assert rf"\href{{{connections}}}{{{label}}}" in source
    elif not show_count:
        # With contact disabled, the default identity column really ends at the primary profile link.
        tail = source.split(r"\textbf{LinkedIn profile}}\par", 1)[1]
        assert tail.strip() == r"\par\addvspace{12pt}" + "\n\n\\end{document}"

    assert profile.intro[-1] == "214 connections"
    assert len(profile.links) == 2


@pytest.mark.parametrize(
    ("intro", "expected"),
    [
        (["500+ connections"], "500+ connections"),
        (["1,234", "connections"], "1,234 connections"),
        (["1.2K connections"], "1.2K connections"),
        ([], ""),
    ],
)
def test_connection_labels_handle_missing_and_split_captures(intro: list[str], expected: str) -> None:
    """
    Handle count text split across DOM nodes without fabricating absent metadata.

    Args:
        intro (list[str]): Captured header lines.
        expected (str): Observed count label, or empty for a minimal profile.

    Returns:
        None: Only connection metadata is extracted; ordinary identity prose remains intact.
    """
    profile = Profile("example-person", "Alex", intro=["Building connections across teams", *intro])
    visible, count, url = prepare_header(profile, Style(show_connection_count=True, show_connection_link=True))
    assert visible.intro == ["Building connections across teams"]
    assert count == expected
    assert url == ""


def test_header_themes_custom_templates_and_inline_links_share_visibility(tmp_path: Path) -> None:
    """
    Apply theme overrides and clean custom-template data while retaining resolved prose links.

    Args:
        tmp_path (Path): Temporary configuration and template root.

    Returns:
        None: Optional count and URL follow theme precedence, and inline external references stay clickable.
    """
    path = tmp_path / "resume.config.yaml"
    path.write_text(
        "linkedin:\n  username: example-person\nstyle:\n  theme: compact\n"
        "  show_connection_count: true\n  themes:\n    compact:\n"
        "      show_connection_count: false\n      show_connection_link: true\n",
        encoding="utf-8",
    )
    config = load_config(path)
    destination = "https://www.linkedin.com/mynetwork/invite-connect/connections/"
    profile = Profile(
        "example-person",
        "Alex",
        intro=["See https://lnkd.in/portfolio", "214 connections"],
        links=[Link("Portfolio", "https://lnkd.in/portfolio", "https://example.org/portfolio"), Link("214 connections", destination)],
    )
    source = render_profile(profile, config, tmp_path).read_text()
    assert r"\href{https://example.org/portfolio}" in source
    assert "214 connections" not in source
    assert rf"\href{{{destination}}}{{Connections}}" in source
    custom = tmp_path / "custom.tex.j2"
    custom.write_text("((( profile.intro )))|((( profile.links )))|((( connection_count )))|((( connection_url )))", encoding="utf-8")
    text = render_profile(profile, evolve(config, template=custom.name), tmp_path).read_text()
    assert "214 connections" not in text
    assert text.endswith(f"|[]||{destination}")


@pytest.mark.parametrize("name", ["show_connection_count", "show_connection_link"])
@pytest.mark.parametrize("theme", [False, True])
def test_connection_settings_require_booleans(tmp_path: Path, name: str, theme: bool) -> None:
    """
    Reject string booleans in both base style and inline theme settings.

    Args:
        tmp_path (Path): Temporary configuration directory.
        name (str): Connection setting under validation.
        theme (bool): Whether the invalid value is inside a theme.

    Returns:
        None: Invalid style data fails schema validation before rendering.
    """
    override = {name: "false"}
    style = {"themes": {"custom": override}} if theme else override
    path = tmp_path / "resume.config.yaml"
    path.write_text(yaml.safe_dump({"linkedin": {"username": "example-person"}, "style": style}), encoding="utf-8")

    with pytest.raises(ValidationError):
        load_config(path)
