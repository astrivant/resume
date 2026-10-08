"""
Verify complete capture handoff and refresh event boundaries without LinkedIn or GitHub writes.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

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
    ("event", "ref", "requested", "expected"),
    [
        ("schedule", "refs/heads/main", True, True),
        ("workflow_dispatch", "refs/heads/main", True, True),
        ("push", "refs/tags/v0.2.0", False, True),
        ("push", "refs/tags/resume-test", False, True),
        ("push", "refs/tags/resume-test", True, True),
        ("pull_request", "refs/heads/main", True, None),
        ("pull_request", "refs/tags/resume-test", True, None),
        ("push", "refs/heads/main", True, None),
        ("workflow_dispatch", "refs/heads/feature", True, None),
        ("workflow_dispatch", "refs/tags/resume-test", True, None),
        ("schedule", "refs/heads/feature", True, None),
        ("push", "refs/heads/main", False, False),
        ("push", "refs/heads/feature", False, False),
        ("pull_request", "refs/pull/123/merge", False, False),
        ("workflow_dispatch", "refs/heads/main", False, False),
    ],
)
def test_refresh_event_selection(tmp_path: Path, event: str, ref: str, requested: bool, expected: bool | None) -> None:
    """
    Capture on every tag push while retaining explicit refresh boundaries for branch events.

    Args:
        tmp_path (Path): GitHub output-file directory.
        event (str): Triggering GitHub event.
        ref (str): Event's repository reference.
        requested (bool): Whether the workflow explicitly requested a refresh.
        expected (bool | None): Capture decision, or None when this context must fail before exposing credentials.

    Returns:
        None: Tags refresh without an opt-in; ordinary builds reuse saved inputs and invalid refresh requests fail.
    """
    output = tmp_path / "output"
    result = subprocess.run(
        ["bash", "scripts/ci/source.sh"],
        cwd=Path(__file__).resolve().parents[3],
        env=dict(
            os.environ,
            REFRESH_PROFILE=str(requested).lower(),
            GITHUB_EVENT_NAME=event,
            GITHUB_REF=ref,
            GITHUB_OUTPUT=str(output),
        ),
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is (expected is not None)
    assert output.exists() is (expected is not None)

    if expected is not None:
        assert f"refresh={str(expected).lower()}\n" in output.read_text()


def test_tag_pipeline_propagates_capture_and_signs_the_current_build() -> None:
    """
    Keep refreshed evidence and the built PDF connected across independent CI checkouts.

    Returns:
        None: Consumers restore the same capture and release signs this run's verified artifact without restaging an older PDF.
    """
    workflows = Path(__file__).resolve().parents[3] / ".github/workflows"
    pipeline = yaml.safe_load((workflows / "ci.yml").read_text())
    stages = {
        name: yaml.safe_load((workflows / f"stage-{name}.yml").read_text()) for name in ("summary", "test", "build", "skills", "release")
    }
    source = pipeline["jobs"]["source"]
    assert source["outputs"]["refresh"] == "${{ steps.source.outputs.refresh }}"
    capture = next(step for step in source["steps"] if step.get("run") == "poetry run resumeme capture --headless")
    assert capture["if"] == "steps.source.outputs.refresh == 'true'"
    assert "continue-on-error" not in source and "continue-on-error" not in capture

    # A fresh capture must reach every job that reads profile evidence, including optional tag-only skill publication.
    consumers = {"summary": ("prepare", "summary"), "test": ("python", "documents"), "build": ("build",), "skills": ("generate", "publish")}

    for stage, jobs in consumers.items():
        assert pipeline["jobs"][f"{stage}-stage"]["with"]["refresh"] == "${{ needs.source.outputs.refresh == 'true' }}"

        for job in jobs:
            steps = stages[stage]["jobs"][job]["steps"]
            restore = next(step for step in steps if step.get("uses") == "./.github/actions/restore-profile")
            assert restore["with"]["refresh"] == "${{ inputs.refresh }}"
            assert "continue-on-error" not in restore
            assert steps.index(restore) < next(index for index, step in enumerate(steps) if "run" in step)

    # Enabled summaries must be regenerated from tag captures instead of disappearing from freshly built release PDFs.
    preparation = next(step for step in stages["summary"]["jobs"]["prepare"]["steps"] if step.get("id") == "prepare")
    assert " ".join(preparation["env"]["GENERATE_SUMMARY"].split()) == (
        "${{ (github.ref == 'refs/heads/main' && github.event_name != 'pull_request') || "
        "(github.event_name == 'push' && startsWith(github.ref, 'refs/tags/')) }}"
    )

    # Omitting run-id and repository binds the artifact download to this workflow run; a missing build must fail the release.
    assert pipeline["jobs"]["release-stage"]["needs"] == ["source", "verified"]
    assert "build-stage" in pipeline["jobs"]["verified"]["needs"]
    release = stages["release"]["jobs"]["release"]
    steps = release["steps"]
    download = next(step for step in steps if step.get("uses", "").startswith("actions/download-artifact@"))
    assert download["with"] == {"name": "resume-pdf", "path": ".cache/publication/"}
    assert "if" not in download and "continue-on-error" not in download and "continue-on-error" not in release
    assert not any("stage-pdf.py" in step.get("run", "") for step in steps)
    signing = next(index for index, step in enumerate(steps) if step.get("run") == "poetry run bash scripts/release/sign.sh")
    assert steps.index(download) < signing
    build_upload = next(
        step
        for step in stages["build"]["jobs"]["build"]["steps"]
        if step.get("uses", "").startswith("actions/upload-artifact@") and step.get("with", {}).get("name") == "resume-pdf"
    )
    assert build_upload["with"]["path"] == ".cache/publication/"
