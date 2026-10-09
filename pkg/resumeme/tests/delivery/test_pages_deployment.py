"""
Verify Pages artifact identity, authenticated deployment boundaries, and live publication checks offline.
"""

from __future__ import annotations

import json
import os
import subprocess
from hashlib import sha256
from pathlib import Path

import pytest
import yaml

from resumeme.tests.paths import REPOSITORY_ROOT


@pytest.fixture
def commands(tmp_path: Path) -> dict[str, str]:
    """
    Replace only external deployment commands with deterministic local test doubles.

    Args:
        tmp_path (Path): Private command, response, and audit directory.

    Returns:
        dict[str, str]: Environment for executing production shell scripts without network access.
    """
    fixture = REPOSITORY_ROOT / "pkg/resumeme/tests/fixtures/pages-command.sh"

    for name in ("git", "gh", "curl", "sleep"):
        command = tmp_path / name
        command.write_bytes(fixture.read_bytes())
        command.chmod(0o700)

    return dict(
        os.environ,
        PATH=f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
        PAGES_TEST_ROOT=str(tmp_path),
        PAGES_TEST_HEAD="a" * 40,
        PAGES_TEST_MODE="deploy",
        PAGES_TEST_STATUS="succeed",
        PUBLISHED_SHA="a" * 40,
        GITHUB_SHA="b" * 40,
        GITHUB_REPOSITORY="example/resume",
        GITHUB_EVENT_NAME="push",
        PAGES_ARTIFACT_ID="12345",
        GH_TOKEN="synthetic-github-token",
        ACTIONS_ID_TOKEN_REQUEST_URL="https://oidc.example.test/token",
        ACTIONS_ID_TOKEN_REQUEST_TOKEN="synthetic-request-token",
        RETRY_BACKOFF_SECONDS="0",
    )


@pytest.mark.parametrize("status", ["succeed", "deployment_content_failed", "transport"])
def test_pages_deploys_the_accepted_commit_and_cleans_up_credentials(commands: dict[str, str], status: str) -> None:
    """
    Keep a tag's publication distinct from a branch build sharing its triggering SHA.

    Args:
        commands (dict[str, str]): Isolated GitHub API and OIDC simulation.
        status (str): Successful, terminal, or transient deployment response.

    Returns:
        None: Exact artifact/commit identity survives submission and temporary credentials are removed on every outcome.
    """
    commands["PAGES_TEST_STATUS"] = status
    result = subprocess.run(
        ["bash", "scripts/ci/pages/pages-deploy.sh"], cwd=REPOSITORY_ROOT, env=commands, capture_output=True, text=True, check=False
    )
    root = Path(commands["PAGES_TEST_ROOT"])
    assert (result.returncode == 0) is (status == "succeed")
    assert json.loads((root / "submitted.json").read_text()) == {
        "artifact_id": 12345,
        "pages_build_version": commands["PUBLISHED_SHA"],
        "oidc_token": "synthetic-oidc-token",
    }
    assert commands["GITHUB_SHA"] != commands["PUBLISHED_SHA"]
    assert not Path((root / "temporary").read_text().strip()).parent.exists()
    assert (root / "cancelled").exists() is (status == "transport")

    # OIDC is registered with Actions masking; neither authentication header is emitted in diagnostics or command arguments.
    assert result.stdout.count("synthetic-oidc-token") == 1
    assert "::add-mask::synthetic-oidc-token" in result.stdout
    diagnostics = result.stdout + result.stderr + (root / "calls").read_text()
    assert "synthetic-request-token" not in diagnostics and "synthetic-github-token" not in diagnostics


@pytest.mark.parametrize("override", [{"GITHUB_EVENT_NAME": "pull_request"}, {"PAGES_TEST_HEAD": "c" * 40}])
def test_pages_rejects_untrusted_or_mismatched_checkouts(commands: dict[str, str], override: dict[str, str]) -> None:
    """
    Reject invalid provenance before requesting a credential or submitting a deployment.

    Args:
        commands (dict[str, str]): Isolated command environment.
        override (dict[str, str]): Untrusted event or checkout different from the accepted commit.

    Returns:
        None: The deployment fails without requesting OIDC or publishing an artifact.
    """
    result = subprocess.run(
        ["bash", "scripts/ci/pages/pages-deploy.sh"],
        cwd=REPOSITORY_ROOT,
        env=commands | override,
        capture_output=True,
        text=True,
        check=False,
    )
    root = Path(commands["PAGES_TEST_ROOT"])
    assert result.returncode != 0
    assert not (root / "temporary").exists() and not (root / "submitted.json").exists()


@pytest.mark.parametrize(("mode", "downloads"), [("fresh", 1), ("propagation", 2), ("stale", 6)])
def test_live_verification_requires_matching_bytes_with_bounded_retries(commands: dict[str, str], mode: str, downloads: int) -> None:
    """
    Make stale public content a visible failure even after GitHub reports a successful deployment.

    Args:
        commands (dict[str, str]): Local HTTP download and sleep simulation.
        mode (str): Immediate match, delayed propagation, or persistently stale public PDF.
        downloads (int): Expected bounded number of public downloads.

    Returns:
        None: Only matching content passes, preserving configured subdirectories and reporting the verified hash.
    """
    root = Path(commands["PAGES_TEST_ROOT"])
    content = b"accepted PDF"
    (root / "resume.pdf").write_bytes(content)
    digest = sha256(content).hexdigest()
    environment = commands | {
        "PAGES_TEST_MODE": mode,
        "PAGES_URL": "https://example.test/project/cv/",
        "PDF_SHA256": digest,
        "GITHUB_STEP_SUMMARY": str(root / "summary"),
    }
    result = subprocess.run(
        ["bash", "scripts/ci/pages/pages-verify.sh"],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is (mode != "stale")
    calls = (root / "calls").read_text()
    assert calls.count("curl ") == downloads
    assert calls.count(f"https://example.test/project/cv/resume.pdf?sha256={digest}&attempt=") == downloads

    if mode == "stale":
        assert "public PDF does not match" in result.stderr
        assert not (root / "summary").exists()
        assert [line for line in calls.splitlines() if line.startswith("sleep ")] == [
            "sleep 5",
            "sleep 10",
            "sleep 20",
            "sleep 40",
            "sleep 60",
        ]
    else:
        assert digest in (root / "summary").read_text()


def test_pages_workflow_wires_artifact_identity_and_recovery_without_recapture() -> None:
    """
    Keep automatic branch/tag publication and recovery connected to the same verification path.

    Returns:
        None: Recovery is part of the existing pipeline and carries the exact uploaded artifact into deployment.
    """
    workflows = REPOSITORY_ROOT / ".github/workflows"
    pipeline = yaml.safe_load((workflows / "ci.yml").read_text())
    stage = yaml.safe_load((workflows / "stage-pages.yml").read_text())["jobs"]
    jobs = pipeline["jobs"]
    assert pipeline[True]["workflow_dispatch"]["inputs"]["pages_only"]["default"] is False
    assert "inputs.pages_only" in jobs["source"]["if"] and "inputs.pages_only" in jobs["verified"]["if"]
    recovery = jobs["pages-recovery-stage"]
    assert recovery["uses"] == jobs["tag-pages-stage"]["uses"] == jobs["pages-stage"]["uses"]
    assert "refs/heads/main" in recovery["if"] and "needs" not in recovery
    assert stage["prepare"]["outputs"]["artifact-id"] == "${{ steps.artifact.outputs.artifact_id }}"
    deployment = next(step for step in stage["deploy"]["steps"] if step.get("id") == "deployment")
    assert deployment["env"]["PUBLISHED_SHA"] == "${{ inputs.sha }}"
    assert deployment["env"]["PAGES_ARTIFACT_ID"] == "${{ needs.prepare.outputs.artifact-id }}"
    assert stage["deploy"]["steps"][-1]["env"]["PDF_SHA256"] == "${{ needs.prepare.outputs.pdf-sha256 }}"
