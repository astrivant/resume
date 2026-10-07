"""
Verify complete capture handoff and refresh event boundaries without LinkedIn or GitHub writes.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from resumeme.compiler.asts.profile import Entry, Media, Profile, Section, save_profile


def _transfer(root: Path, mode: str) -> subprocess.CompletedProcess[str]:
    """
    Invoke the production profile-transfer script against a temporary checkout layout.

    Args:
        root (Path): Fixture configuration directory.
        mode (str): Requested transfer operation.

    Returns:
        subprocess.CompletedProcess[str]: Captured process outcome without registry or browser access.
    """
    script = Path(__file__).resolve().parents[3] / "scripts/ci/profile-artifact.py"
    return subprocess.run([sys.executable, str(script), mode], cwd=root, capture_output=True, text=True, check=False)


def test_capture_artifact_round_trip_preserves_nested_assets_only(tmp_path: Path) -> None:
    """
    Transfer a customized snapshot and nested-role image without including browser state or unrelated files.

    Args:
        tmp_path (Path): Temporary configured capture root.

    Returns:
        None: Restored data matches the accepted capture; no private browser or incidental file is exported.
    """
    config = tmp_path / "resumeme.config.yaml"
    config.write_text("linkedin:\n  username: example-person\noutput:\n  profile: inputs/owner.json\n  assets: inputs/images\n")
    image = tmp_path / "inputs/images/nested/logo.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"image fixture")
    media = Media("https://example.org/logo.png", path="inputs/images/nested/logo.png")
    profile = Profile(
        "example-person",
        "Fresh profile",
        sections=[Section("experience", "Experience", [Entry("Company", positions=[Entry(images=[media])])])],
    )
    snapshot = tmp_path / "inputs/owner.json"
    save_profile(profile, snapshot)
    original = snapshot.read_bytes()
    private = tmp_path / ".cache/firefox/cookies.sqlite"
    private.parent.mkdir(parents=True)
    private.write_bytes(b"must never leave the runner")
    (image.parent / "unused.png").write_bytes(b"unreferenced image")

    assert _transfer(tmp_path, "export").returncode == 0
    artifact = tmp_path / ".cache/refresh"
    assert sorted(str(path.relative_to(artifact)) for path in artifact.rglob("*") if path.is_file()) == [
        "assets/nested/logo.png",
        "profile.json",
    ]
    snapshot.write_bytes(b"old snapshot")
    image.unlink()
    assert _transfer(tmp_path, "restore").returncode == 0
    assert snapshot.read_bytes() == original
    assert image.read_bytes() == b"image fixture"
    assert private.read_bytes() == b"must never leave the runner"


@pytest.mark.parametrize("failure", ["warnings", "missing", "outside", "owner"])
def test_capture_restore_rejects_incomplete_or_unrelated_inputs(tmp_path: Path, failure: str) -> None:
    """
    Leave accepted inputs intact if a capture artifact is incomplete or violates its configured ownership.

    Args:
        tmp_path (Path): Fixture capture destination.
        failure (str): Invalid artifact boundary under test.

    Returns:
        None: No partial profile replacement occurs after validation fails.
    """
    (tmp_path / "resumeme.config.yaml").write_text("linkedin:\n  username: example-person\n")
    snapshot = tmp_path / "data/profile.json"
    snapshot.parent.mkdir()
    snapshot.write_bytes(b"accepted snapshot")
    profile = Profile(
        "someone-else" if failure == "owner" else "example-person",
        "Fresh profile",
        images=[Media("https://example.org/image.png", path="README.md" if failure == "outside" else "data/assets/image.png")],
        warnings=["Incomplete capture"] if failure == "warnings" else [],
    )
    save_profile(profile, tmp_path / ".cache/refresh/profile.json")
    result = _transfer(tmp_path, "restore")
    assert result.returncode != 0
    assert snapshot.read_bytes() == b"accepted snapshot"
    assert not (tmp_path / "data/assets/image.png").exists()


@pytest.mark.parametrize(
    ("event", "ref", "allowed"),
    [
        ("schedule", "refs/heads/main", True),
        ("workflow_dispatch", "refs/heads/main", True),
        ("pull_request", "refs/heads/main", False),
        ("push", "refs/heads/main", False),
        ("workflow_dispatch", "refs/heads/feature", False),
        ("push", "refs/tags/resume-test", False),
    ],
)
def test_refresh_requires_trusted_main_event(tmp_path: Path, event: str, ref: str, allowed: bool) -> None:
    """
    Reject inappropriate refresh contexts before setup can expose capture credentials.

    Args:
        tmp_path (Path): GitHub output-file directory.
        event (str): Triggering GitHub event.
        ref (str): Event's repository reference.
        allowed (bool): Whether this event can request fresh LinkedIn input.

    Returns:
        None: Only scheduled or explicitly requested main-branch refreshes produce a capture-enabled output.
    """
    output = tmp_path / "output"
    result = subprocess.run(
        ["bash", "scripts/ci/source.sh"],
        cwd=Path(__file__).resolve().parents[3],
        env=dict(os.environ, REFRESH_PROFILE="true", GITHUB_EVENT_NAME=event, GITHUB_REF=ref, GITHUB_OUTPUT=str(output)),
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is allowed
    assert output.exists() is allowed

    if allowed:
        assert "refresh=true" in output.read_text()
