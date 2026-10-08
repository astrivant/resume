"""
Verify fork landing pages, artifact consistency, and explicit README overrides.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING
from xml.etree import ElementTree

import pytest
from jsonschema import ValidationError
from PIL import Image
from pypdf import PdfWriter

from resumeme.compiler.asts.profile import Profile, save_profile
from resumeme.config import Config, GitHub, LinkedIn, Output, Ownership, Readme, load_config
from resumeme.github.readme import PREVIEW_PATH, personal_readme, render_readme, restore_readme, stage_readme, update_project_branding

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch


@pytest.mark.parametrize("inline_badge", [False, True])
def test_project_brew_badge_preserves_custom_readme_and_links_configured_pdf(
    tmp_path: Path, monkeypatch: MonkeyPatch, inline_badge: bool
) -> None:
    """
    Replace only the marked branding with a local UTC date badge pointing at the configured resume.

    Args:
        tmp_path (Path): Temporary checkout with edited README content.
        monkeypatch (MonkeyPatch): Supplies the publishing fork's Actions identity.
        inline_badge (bool): Keep the date alongside custom badges or retain the legacy position beneath the logo.

    Returns:
        None: Repeated publication is byte-identical and later dates update the badge without losing surrounding text.
    """
    before, after = "# My project\r\n\r\n", "\r\n\r\nKeep **my** installation steps.\r\n"

    if inline_badge:
        before += "[![Custom badge](https://example.org/badge.svg)](https://example.org) "

    badge_region = "<!-- resumeme:brew-date:start -->old<!-- resumeme:brew-date:end -->\r\n\r\n" if inline_badge else ""
    path = tmp_path / "README.md"
    path.write_bytes((before + badge_region + "<!-- resumeme:branding:start -->old<!-- resumeme:branding:end -->" + after).encode())
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/my-cv")
    config = Config(LinkedIn("example", ownership=Ownership(repository="upstream/project")), output=Output(pdf="documents/cv.pdf"))
    update_project_branding(tmp_path, config, date(2026, 1, 2))
    markdown = path.read_bytes()
    assert markdown.startswith(before.encode())
    assert markdown.endswith(after.encode())
    assert b'href="./documents/cv.pdf"' in markdown
    assert b"Brew date: 2026-01-02 (UTC)" in markdown

    if inline_badge:
        assert markdown.index(b"example.org/badge.svg") < markdown.index(b"brew-date.svg") < markdown.index(b"resumeme-logo.png")
        assert b"<br>" not in markdown
    else:
        assert markdown.index(b"resumeme-logo.png") < markdown.index(b"<br>") < markdown.index(b"brew-date.svg")

    assert b'height="20"' in markdown
    assert markdown.count(b"brew-date.svg") == 1
    assert b'src="https://raw.githubusercontent.com/example/my-cv/main/docs/assets/branding/resumeme-logo.png"' in markdown
    assert b'src="https://raw.githubusercontent.com/example/my-cv/main/docs/assets/branding/brew-date.svg"' in markdown
    assert b"upstream/project" not in markdown
    badge = tmp_path / "docs/assets/branding/brew-date.svg"
    first = badge.read_bytes()
    svg = ElementTree.fromstring(first)
    assert svg.attrib["width"] == "158"
    assert svg.attrib["height"] == "20"
    assert svg.findtext("{http://www.w3.org/2000/svg}title") == "Brew date: 2026-01-02 (UTC)"
    assert "https://" not in first.decode()
    update_project_branding(tmp_path, config, date(2026, 1, 2))
    assert path.read_bytes() == markdown
    assert badge.read_bytes() == first
    update_project_branding(tmp_path, config, date(2026, 2, 3))
    assert "2026-02-03" in badge.read_text()
    assert "2026-01-02" not in path.read_text()


@pytest.mark.parametrize("markdown", [None, "# A personal README\n"])
def test_project_brew_badge_does_not_insert_branding_without_markers(tmp_path: Path, markdown: str | None) -> None:
    """
    Keep custom project READMEs opt-in while refreshing the reusable badge asset.

    Args:
        tmp_path (Path): Temporary publishing checkout.
        markdown (str | None): Unmarked content, or an absent README.

    Returns:
        None: README content is neither created nor rewritten without managed branding markers.
    """
    path = tmp_path / "README.md"

    if markdown is not None:
        path.write_text(markdown)

    update_project_branding(tmp_path, Config(LinkedIn("example")), date(2026, 1, 2))
    assert (path.read_text() if path.exists() else None) == markdown
    assert (tmp_path / "docs/assets/branding/brew-date.svg").exists()


@pytest.mark.parametrize(
    "markers",
    [
        "<!-- resumeme:branding:start -->",
        "<!-- resumeme:branding:end --><!-- resumeme:branding:start -->",
        "<!-- resumeme:branding:start --><!-- resumeme:branding:end --><!-- resumeme:branding:end -->",
        "<!-- resumeme:brew-date:start -->",
        "<!-- resumeme:brew-date:end --><!-- resumeme:brew-date:start -->",
        "<!-- resumeme:branding:start --><!-- resumeme:brew-date:start --><!-- resumeme:brew-date:end --><!-- resumeme:branding:end -->",
    ],
)
def test_invalid_branding_markers_fail_before_replacement(tmp_path: Path, markers: str) -> None:
    """
    Reject ambiguous block boundaries without dropping a user's README edits.

    Args:
        tmp_path (Path): Temporary checkout containing malformed markers.
        markers (str): Incomplete, reversed, or duplicated branding delimiters.

    Returns:
        None: Neither README nor SVG is replaced on invalid input.
    """
    path = tmp_path / "README.md"
    path.write_text(markers)

    with pytest.raises(ValueError, match="README branding"):
        update_project_branding(tmp_path, Config(LinkedIn("example")), date(2026, 1, 2))

    assert path.read_text() == markers
    assert not (tmp_path / "docs/assets/branding/brew-date.svg").exists()


@pytest.mark.parametrize("mode", ["auto", "project", "resume"])
@pytest.mark.parametrize("fork", [False, True])
def test_readme_mode_overrides_fork_detection(tmp_path: Path, mode: str, fork: bool) -> None:
    """
    Keep the upstream README while letting owners opt in or preserve manual content.

    Args:
        tmp_path (Path): Temporary configuration directory.
        mode (str): Public mode loaded through schema validation.
        fork (bool): Whether Actions reports a fork repository.

    Returns:
        None: Auto defaults to forks and explicit modes take precedence.
    """
    path = tmp_path / "resumeme.config.yaml"
    path.write_text(f"linkedin: {{username: example}}\nreadme: {{mode: {mode}}}\n", encoding="utf-8")
    config = load_config(path)
    assert personal_readme(config, fork) is (mode == "resume" or (mode == "auto" and fork))
    assert Config(LinkedIn("example")).readme == Readme()
    assert Readme().output == "README.md"


@pytest.mark.parametrize(
    "settings",
    [
        "mode: always",
        "introduction: 42",
        "introduction: ' '",
        "enabled: true",
        "output: null",
        "output: 42",
        "output: ''",
        "output: page.txt",
    ],
)
def test_invalid_readme_configuration_is_rejected(tmp_path: Path, settings: str) -> None:
    """
    Reject ambiguous modes, unknown fields, and non-text introductions.

    Args:
        tmp_path (Path): Temporary configuration directory.
        settings (str): Invalid YAML fragment.

    Returns:
        None: Invalid preferences fail validation before publication.
    """
    path = tmp_path / "resumeme.config.yaml"
    path.write_text(f"linkedin: {{username: example}}\nreadme: {{{settings}}}\n", encoding="utf-8")

    with pytest.raises(ValidationError):
        load_config(path)


def test_personal_readme_uses_only_selected_public_identity() -> None:
    """
    Support minimal profiles and escape names and introductions without revealing hidden metadata.

    Returns:
        None: Profile and artifact links target the fork and the configured PDF path.
    """
    profile = Profile("example", "Jane [Doe] <script>", intro=["hidden contact"], headline="hidden headline")
    config = Config(
        LinkedIn("example"),
        output=Output(pdf="documents/cv.pdf"),
        github=GitHub("example-dev"),
        readme=Readme(introduction="Platform & reliability \u2014 résumé\u2026\n<script>alert(1)</script>"),
    )
    markdown = render_readme(profile, config, "example/my-cv", 3)
    assert r"# Jane \[Doe\] &lt;script&gt; - Résumé" in markdown
    assert r"Platform &amp; reliability \- résumé\.\.\. &lt;script&gt;alert\(1\)&lt;/script&gt;" in markdown
    assert "./documents/cv.pdf" in markdown
    assert "PDF - 3 pages" in markdown
    assert f"](https://raw.githubusercontent.com/example/my-cv/main/{PREVIEW_PATH})" in markdown
    assert "https://github.com/example/my-cv/releases" in markdown
    assert "https://github.com/example-dev" in markdown
    assert "https://www.linkedin.com/in/example/" in markdown
    assert "hidden" not in markdown
    assert "<script>" not in markdown
    minimal = render_readme(Profile("example", "Jane"), Config(LinkedIn("example")), "example/my-cv", 1)
    assert "PDF - 1 page)" in minimal
    assert "[GitHub]" not in minimal


def test_nested_readme_links_resolve_from_its_destination() -> None:
    """
    Keep all repository links usable when the landing page is published below the repository root.

    Returns:
        None: Nested Markdown targets the same PDF, preview, config, and automation documentation.
    """
    config = Config(LinkedIn("example"), output=Output(pdf="documents/cv.pdf"), readme=Readme(output="docs/examples/resume.md"))
    markdown = render_readme(Profile("example", "Jane"), config, "example/cv", 2)
    assert markdown.count("](./../../documents/cv.pdf)") == 2
    assert "](https://raw.githubusercontent.com/example/cv/main/docs/assets/resume-preview.png)" in markdown
    assert "[Configuration](../../resumeme.config.yaml)" in markdown
    assert "[Automation](../automation.md)" in markdown


@pytest.mark.parametrize("output", ["../outside.md", "/tmp/outside.md", "data/profile.md"])
def test_readme_output_rejects_escapes_and_input_collisions(tmp_path: Path, output: str) -> None:
    """
    Validate Markdown destinations before capture, artifact staging, or publication.

    Args:
        tmp_path (Path): Configuration root used for containment checks.
        output (str): Escaping path or a path shared with the configured profile input.

    Returns:
        None: Invalid destinations fail configuration loading.
    """
    path = tmp_path / "resumeme.config.yaml"
    path.write_text(f"linkedin: {{username: example}}\noutput: {{profile: data/profile.md}}\nreadme: {{output: {output}}}\n")

    with pytest.raises(ValueError, match="within the configuration directory|paths must be distinct"):
        load_config(path)


def test_readme_rejects_a_snapshot_from_another_owner() -> None:
    """
    Prevent inherited upstream names from appearing under a new owner's links.

    Returns:
        None: Cross-owner rendering fails before producing Markdown.
    """
    with pytest.raises(ValueError, match="another LinkedIn owner"):
        render_readme(Profile("upstream", "Upstream owner"), Config(LinkedIn("fork-owner")), "fork-owner/resume", 1)


@pytest.mark.parametrize("damage", [None, "pdf", "preview", "markdown"])
@pytest.mark.parametrize("output", ["README.md", "FORK_EXAMPLE.md", "docs/examples/resume.md"])
def test_readme_bundle_is_bound_to_the_published_pdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str | None, output: str
) -> None:
    """
    Stage the complete fork presentation and reject stale or incomplete bundles before replacement.

    Args:
        tmp_path (Path): Isolated profile, artifact, and destination directory.
        monkeypatch (pytest.MonkeyPatch): Replace only the external Docker renderer.
        damage (str | None): Artifact to damage after staging, or None for successful restoration.
        output (str): Root or nested Markdown destination selected by the user.

    Returns:
        None: Valid publication is deterministic and rejected artifacts preserve the existing README and image.
    """
    config = Config(LinkedIn("example"), readme=Readme(output=output))
    artifact = tmp_path / ".cache/publication/resume.pdf"
    artifact.parent.mkdir(parents=True)
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_blank_page(width=612, height=792)
    writer.write(artifact)
    save_profile(Profile("example", "Example Person"), tmp_path / config.output.profile)

    def renderer(pdf: Path, output: Path) -> None:
        """
        Substitute a deterministic image while verifying the rasterizer receives the published document.

        Args:
            pdf (Path): Input selected by artifact preparation.
            output (Path): Scratch PNG path.

        Returns:
            None: A valid RGB preview stands in for Docker output.
        """
        assert pdf == artifact
        Image.new("RGB", (1224, 1584), "white").save(output)

    monkeypatch.setattr("resumeme.github.readme._render_preview", renderer)
    stage_readme(tmp_path, config, "example/cv")
    bundle = artifact.parent / "readme"
    before = {path.name: path.read_bytes() for path in bundle.iterdir()}
    stage_readme(tmp_path, config, "example/cv")
    assert before == {path.name: path.read_bytes() for path in bundle.iterdir()}
    assert "PDF - 2 pages" in (bundle / "README.md").read_text()

    # Reject inconsistent downloads before replacing either tracked file, while keeping all extra cache contents unselected.
    (tmp_path / "README.md").write_text("Original project README")
    destination = tmp_path / output
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("Original landing page")
    (tmp_path / PREVIEW_PATH).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / PREVIEW_PATH).write_bytes(b"original preview")
    (bundle / "cookies.sqlite").write_bytes(b"unrelated private state")

    if damage:
        target = {"pdf": artifact, "preview": bundle / "resume-preview.png", "markdown": bundle / "README.md"}[damage]
        target.unlink()

        if damage != "markdown":
            target.write_bytes(b"inconsistent artifact")

        with pytest.raises((ValueError, OSError)):
            restore_readme(tmp_path, config)

        assert destination.read_text() == "Original landing page"
        assert (tmp_path / PREVIEW_PATH).read_bytes() == b"original preview"
    else:
        assert restore_readme(tmp_path, config) == (output, PREVIEW_PATH)
        assert destination.read_bytes() == before["README.md"]
        assert (tmp_path / PREVIEW_PATH).read_bytes() == before["resume-preview.png"]
        assert not (tmp_path / "cookies.sqlite").exists()

    if output != "README.md":
        assert (tmp_path / "README.md").read_text() == "Original project README"
