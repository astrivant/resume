"""
Verify Pages publication paths, public content, and deployment guards without contacting GitHub.
"""

from __future__ import annotations

import os
import runpy
import subprocess
from typing import TYPE_CHECKING
from urllib.parse import urljoin

import pytest
import yaml
from attrs import evolve
from bs4 import BeautifulSoup
from jsonschema import ValidationError
from pypdf import PdfWriter

from resumeme.cli import main
from resumeme.compiler.asts.profile import Entry, Profile, Section, save_profile
from resumeme.config import Config, GitHub, LinkedIn, Output, Pages, Readme, Style, load_config
from resumeme.github.pages import build_site
from resumeme.tests.paths import REPOSITORY_ROOT

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("path", ["/", "/cv/", "/career/my-resume.v2/"])
def test_site_uses_relative_links_and_only_publishes_the_accepted_pdf(tmp_path: Path, path: str) -> None:
    """
    Serve the same document from custom-domain roots and project-site subdirectories without leaking captured fields.

    Args:
        tmp_path (Path): Isolated checkout with a nondefault PDF destination.
        path (str): Configured directory inside the Pages artifact.

    Returns:
        None: Only index.html and the unchanged PDF are staged, with escaped identity and portable links.
    """
    profile = Profile(
        "example",
        'Example <script>alert("name")</script>',
        headline="Hidden headline",
        sections=[Section("contact", "Contact", entries=[Entry("secret@example.org")])],
    )
    config = Config(
        LinkedIn("example"),
        output=Output(pdf="documents/cv.pdf"),
        pages=Pages(path=path),
        github=GitHub("example-github"),
        readme=Readme(introduction='<script>alert("intro")</script>'),
        style=Style(theme="custom", themes={"custom": {"accent": "245135", "name_color": "6B2737"}}),
    )
    pdf = tmp_path / config.output.pdf
    pdf.parent.mkdir()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.write(pdf)
    original = pdf.read_bytes()
    index = build_site(profile, config, tmp_path, "fork-owner/my-resume")
    assert index == tmp_path / ".cache/pages" / path.strip("/") / "index.html"
    assert index.with_name("resume.pdf").read_bytes() == original == pdf.read_bytes()
    assert sorted(file.name for file in (tmp_path / ".cache/pages").rglob("*") if file.is_file()) == ["index.html", "resume.pdf"]
    document = BeautifulSoup(index.read_text(), "html.parser")
    assert not document.find_all("script")
    assert document.h1 is not None and profile.name in document.h1.get_text()
    assert "Hidden headline" not in document.get_text() and "secret@example.org" not in document.get_text()
    assert "#245135" in index.read_text() and "#6B2737" in index.read_text()
    assert document.find("a", href="https://github.com/fork-owner/my-resume/releases") is not None
    assert document.find("a", href="https://github.com/example-github") is not None
    assert document.find("a", download=True) is not None
    assert document.find("object", data="./resume.pdf", type="application/pdf") is not None

    # Directory URLs and explicit index URLs resolve beside the PDF at either kind of Pages base URL.
    for base in ("https://resume.example.org", "https://example.github.io/project"):
        for suffix in ("", "index.html"):
            assert urljoin(base + path + suffix, "./resume.pdf") == base + path + "resume.pdf"

    # Repeated builds are stable, and moving to another directory removes the prior public location.
    first = index.read_bytes()
    assert build_site(profile, config, tmp_path, "fork-owner/my-resume").read_bytes() == first
    moved = build_site(profile, evolve(config, pages=Pages(path="/moved/")), tmp_path, "fork-owner/my-resume")
    assert moved.exists() and not index.exists()


@pytest.mark.parametrize("invalid", ["owner", "warnings", "pdf", "empty", "repository"])
def test_site_rejects_incomplete_inputs_without_replacing_the_previous_preview(tmp_path: Path, invalid: str) -> None:
    """
    Fail before replacing a previously generated site when accepted inputs cannot be established.

    Args:
        tmp_path (Path): Isolated checkout and prior generated page.
        invalid (str): Broken ownership, capture, document, or repository condition.

    Returns:
        None: Invalid input leaves the prior site intact and cannot publish inherited profile content.
    """
    profile = Profile("other" if invalid == "owner" else "example", "Example", warnings=["incomplete"] if invalid == "warnings" else [])
    pdf = tmp_path / "resume.pdf"
    writer = PdfWriter()

    if invalid != "empty":
        writer.add_blank_page(width=612, height=792)

    writer.write(pdf)

    if invalid == "pdf":
        pdf.write_bytes(b"%PDF-broken")

    previous = tmp_path / ".cache/pages/index.html"
    previous.parent.mkdir(parents=True)
    previous.write_text("Prior site")

    with pytest.raises(ValueError):
        build_site(profile, Config(LinkedIn("example")), tmp_path, "https://bad.example" if invalid == "repository" else "owner/repo")

    assert previous.read_text() == "Prior site"


@pytest.mark.parametrize(
    "settings",
    [
        {"path": "../escape/"},
        {"path": "/../escape/"},
        {"path": "/cv/../../"},
        {"path": "https://example.org/"},
        {"path": "/cv?raw/"},
        {"path": "/cv/#fragment/"},
        {"path": "/\n"},
        {"path": "/cv"},
        {"path": "/%2e%2e/"},
        {"custom_domain": "https://resume.example.org"},
        {"custom_domain": "resume.example.org/path"},
        {"enabled": "true"},
        {"unknown": True},
    ],
)
def test_pages_config_rejects_unsafe_or_ambiguous_paths(tmp_path: Path, settings: dict[str, str | bool]) -> None:
    """
    Reject path traversal and hostname/configuration typos before staging files or emitting Actions outputs.

    Args:
        tmp_path (Path): Isolated YAML configuration.
        settings (dict[str, str | bool]): Invalid Pages settings.

    Returns:
        None: Schema validation rejects the input.
    """
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"linkedin": {"username": "example"}, "pages": settings}))

    with pytest.raises(ValidationError):
        load_config(path)


def test_site_cli_previews_without_enabling_deployments_and_exports_validated_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Exercise the installed command's offline path independently of CI opt-in and contribution fetching.

    Args:
        tmp_path (Path): Isolated configuration, PDF, and owned snapshot.
        monkeypatch (pytest.MonkeyPatch): Isolated Actions output and checkout for the thin settings script.

    Returns:
        None: Local generation works without enabling publication; settings outputs preserve the deployment default.
    """
    path = tmp_path / "resumeme.config.yaml"
    path.write_text("linkedin: {username: example}\ngithub: {username: example, contributions: {enabled: true}}\n")
    assert load_config(path).pages == Pages()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.write(tmp_path / "resume.pdf")
    save_profile(Profile("example", "Example"), tmp_path / "data/profile.json")
    assert main(["--config", str(path), "site", "--repository", "fork-owner/resume"]) == 0
    assert (tmp_path / ".cache/pages/index.html").exists()

    # Emit only schema-validated settings; no capture or Pages API is touched when disabled.
    script = REPOSITORY_ROOT / "scripts/ci/pages/pages-settings.py"
    output = tmp_path / "outputs"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.chdir(tmp_path)
    runpy.run_path(str(script), run_name="__main__")
    assert output.read_text() == "enabled=false\npath=/\ncustom-domain=\n"


@pytest.mark.parametrize(
    ("base", "path", "domain", "success"),
    [
        ("https://resume.tiger-lily-plants.com", "/", "resume.tiger-lily-plants.com", True),
        ("https://example.github.io/resume/", "/career/cv/", "", True),
        ("https://example.github.io/resume/", "/", "resume.example.org", False),
    ],
)
def test_pages_destination_uses_github_metadata(tmp_path: Path, base: str, path: str, domain: str, success: bool) -> None:
    """
    Preserve project prefixes while rejecting an unexpected configured domain before deployment.

    Args:
        tmp_path (Path): Isolated Actions output path.
        base (str): GitHub's full Pages base URL.
        path (str): Validated directory inside that site.
        domain (str): Optional expected hostname.
        success (bool): Whether GitHub's hostname satisfies the configuration.

    Returns:
        None: The environment URL targets the exact configured path, or domain mismatch blocks deployment.
    """
    script = REPOSITORY_ROOT / "scripts/ci/pages/pages-destination.sh"
    output = tmp_path / "outputs"
    environment = dict(
        os.environ,
        PAGES_BASE_URL=base,
        PAGES_HOST=base.split("/")[2],
        PUBLICATION_PATH=path,
        EXPECTED_DOMAIN=domain,
        GITHUB_OUTPUT=str(output),
    )
    result = subprocess.run(["bash", str(script)], env=environment, capture_output=True, text=True, check=False)
    assert (result.returncode == 0) is success
    assert output.read_text() == f"url={base.rstrip('/')}{path}\n" if success else not output.exists()


@pytest.mark.parametrize(
    ("event", "ref", "head", "expected"),
    [
        ("push", "refs/heads/main", "accepted", "true"),
        ("schedule", "refs/heads/main", "newer", "false"),
        ("pull_request", "refs/heads/main", "accepted", None),
        ("push", "refs/tags/resume-1", "accepted", "true"),
    ],
)
def test_pages_deployment_guard_skips_stale_or_untrusted_runs(
    tmp_path: Path, event: str, ref: str, head: str, expected: str | None
) -> None:
    """
    Exercise the real deployment guard with a local fake CLI and no GitHub writes.

    Args:
        tmp_path (Path): Fake GitHub CLI and output directory.
        event (str): Workflow event type.
        ref (str): Workflow Git reference.
        head (str): Head returned by the simulated main-branch lookup.
        expected (str | None): Freshness output, or None when the event must be rejected.

    Returns:
        None: Only accepted default-branch commits can request a Pages deployment, including tag publications.
    """
    root = REPOSITORY_ROOT
    command = tmp_path / "gh"
    command.write_text(
        "#!/usr/bin/env bash\nset -eu\n"
        '[[ "$*" == "api repos/example/resume/git/ref/heads/main --jq .object.sha" ]]\n'
        'printf "%s\\n" "$FAKE_HEAD"\n'
    )
    command.chmod(0o700)
    output = tmp_path / "outputs"
    environment = dict(
        os.environ,
        PATH=f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
        GITHUB_REF=ref,
        GITHUB_EVENT_NAME=event,
        GITHUB_REPOSITORY="example/resume",
        PUBLISHED_SHA="accepted",
        FAKE_HEAD=head,
        GITHUB_OUTPUT=str(output),
        RETRY_BACKOFF_SECONDS="0",
    )
    result = subprocess.run(
        ["bash", "scripts/ci/pages/pages-current.sh"], cwd=root, env=environment, capture_output=True, text=True, check=False
    )
    assert (result.returncode == 0) is (expected is not None)
    assert output.read_text() == f"current={expected}\n" if expected is not None else not output.exists()
