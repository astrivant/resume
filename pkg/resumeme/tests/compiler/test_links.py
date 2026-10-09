"""
Exercise prose URL discovery, captured link metadata, and offline hyperlink rendering.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from attrs import evolve

from resumeme.cli import main
from resumeme.compiler.asts.links import discover_profile_links, text_links
from resumeme.compiler.asts.parsing import parse_profile
from resumeme.compiler.asts.profile import Entry, Link, Profile, Section, load_profile, save_profile
from resumeme.compiler.backends.latex.escaping import latex_linked_text
from resumeme.compiler.pipeline import render_profile
from resumeme.config import Config, Experience, JobSelector, LinkedIn

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch


@pytest.mark.parametrize(
    ("text", "labels", "urls"),
    [
        (
            "See (https://example.org/wiki/Tool_(software)).",
            ["https://example.org/wiki/Tool_(software)"],
            ["https://example.org/wiki/Tool_(software)"],
        ),
        ("www.example.org/a?x=1&y=2#intro, next.", ["www.example.org/a?x=1&y=2#intro"], ["https://www.example.org/a?x=1&y=2#intro"]),
        (
            "https://example.org/one; https://example.org/two!",
            ["https://example.org/one", "https://example.org/two"],
            ["https://example.org/one", "https://example.org/two"],
        ),
        ("https://user:password@example.org https://example.org/{unsafe} javascript:alert(1) user@www.example.org", [], []),
    ],
)
def test_text_url_boundaries_preserve_prose(text: str, labels: list[str], urls: list[str]) -> None:
    """
    Keep URL punctuation distinct from sentence punctuation and reject unsafe references.

    Args:
        text (str): Captured prose.
        labels (list[str]): Expected exact display spans.
        urls (list[str]): Expected normalized HTTP destinations.

    Returns:
        None: Detection retains valid query strings and balanced parentheses without including surrounding punctuation.
    """
    matches = text_links(text)
    assert [text[start:end] for start, end, _ in matches] == labels
    assert [link.url for _, _, link in matches] == urls


def test_capture_and_saved_snapshots_discover_the_same_links() -> None:
    """
    Discover plain URLs in intro and entry text while retaining explicit anchor labels and nested roles.

    Returns:
        None: Discovery is idempotent, preserves source text, and does not duplicate existing anchors.
    """
    html = """<main><section><h1>Alex</h1><p>Portfolio: www.example.org.</p></section>
    <section><h2>About</h2><p>Built https://example.org/tool.</p>
    <a href="https://example.org/tool">Project name</a></section></main>"""
    profile = parse_profile(html, "example-person")
    assert profile.links == [Link("www.example.org", "https://www.example.org")]
    assert profile.sections[0].entries[0].links == [Link("Project name", "https://example.org/tool")]
    role = Entry("Engineer", ["See https://example.org/role."])
    profile = evolve(profile, sections=[Section("experience", "Experience", [Entry("Company", positions=[role])])])
    discovered = discover_profile_links(profile)
    assert discover_profile_links(discovered) == discovered
    assert discovered.intro == profile.intro
    assert discovered.sections[0].entries[0].positions[0].links == [Link("https://example.org/role", "https://example.org/role")]
    assert not role.links


def test_resolved_links_round_trip_and_render_offline(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Render redirected links within prose and preserve their original URLs in the portable snapshot.

    Args:
        tmp_path (Path): Isolated snapshot and LaTeX output directory.
        monkeypatch (MonkeyPatch): Records accidental network access during rendering.

    Returns:
        None: Titles and resolved destinations survive validation, and all link creation is offline.
    """
    original = "https://lnkd.in/example"
    destination = "https://example.org/project?x=1&y=2#intro"
    link = Link(original, original, resolved_url=destination, title="Project & documentation")
    profile = Profile("example-person", "Alex", sections=[Section("about", "About", [Entry(f"See {original}.", links=[link])])])
    snapshot = tmp_path / "profile.json"
    save_profile(profile, snapshot)
    assert load_profile(snapshot, profile.username) == profile
    fetch = MagicMock(side_effect=AssertionError("Offline rendering must not fetch links"))
    monkeypatch.setattr("requests.Session.get", fetch)
    source = render_profile(profile, Config(LinkedIn(profile.username)), tmp_path).read_text()
    assert r"\href{https://example.org/project?x=1\&y=2\#intro}" in source
    assert r"Project \& documentation" in source
    assert original in source.replace(r"\allowbreak{}", "")
    assert latex_linked_text(r"Plain \input{bad} & text", []) == r"Plain \textbackslash{}input\{bad\} \& text"
    fetch.assert_not_called()


def test_discovered_role_links_respect_job_exclusions(tmp_path: Path) -> None:
    """
    Discover role ownership before filtering older snapshots with only prose URLs.

    Args:
        tmp_path (Path): Isolated rendering directory.

    Returns:
        None: Hidden role URLs never reappear through their parent company's generated link list.
    """
    roles = [Entry("Staff", ["https://example.org/kept"]), Entry("Intern", ["https://example.org/hidden"])]
    group = Entry("Company", [line for role in roles for line in [role.title, *role.paragraphs]], positions=roles)
    profile = Profile("example-person", "Alex", sections=[Section("experience", "Experience", [group])])
    config = Config(LinkedIn(profile.username), experience=Experience(disable=[JobSelector(title="Intern")]), project_filter=None)
    source = render_profile(profile, config, tmp_path).read_text()
    assert "https://example.org/kept" in source
    assert "hidden" not in source


@pytest.mark.parametrize("incomplete", [False, True])
def test_enrich_uses_the_saved_snapshot_without_browser_login(tmp_path: Path, monkeypatch: MonkeyPatch, incomplete: bool) -> None:
    """
    Enrich existing captures while preserving the accepted snapshot when remote inspection fails.

    Args:
        tmp_path (Path): Isolated configuration and snapshot directory.
        monkeypatch (MonkeyPatch): Replaces browser and media boundaries.
        incomplete (bool): Whether inspection records an unresolved remote resource.

    Returns:
        None: Successful metadata is saved, while failures leave the original snapshot and retain diagnostics.
    """
    config = tmp_path / "resumeme.config.yaml"
    config.write_text("linkedin:\n  username: example-person\n", encoding="utf-8")
    profile = Profile("example-person", "Alex", intro=["https://example.org"])
    snapshot = tmp_path / "data/profile.json"
    save_profile(profile, snapshot)
    enriched = evolve(discover_profile_links(profile), warnings=["Link unavailable"] if incomplete else [])
    media = MagicMock(return_value=enriched)
    browser = MagicMock(side_effect=AssertionError("Enrichment must not start Firefox"))
    monkeypatch.setattr("resumeme.cli.cache_media", media)
    monkeypatch.setattr("resumeme.cli.capture_profile", browser)
    assert main(["--config", str(config), "enrich"]) == (2 if incomplete else 0)
    assert load_profile(snapshot, profile.username) == (profile if incomplete else enriched)
    assert (tmp_path / ".cache/capture/profile.json").exists() is incomplete
    browser.assert_not_called()
    media.assert_called_once()
