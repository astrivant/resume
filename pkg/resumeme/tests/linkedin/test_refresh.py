"""
Verify complete capture handoff and refresh event boundaries without LinkedIn or GitHub writes.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest
import yaml

from resumeme.compiler.asts.profile import Entry, Media, Profile, Section, save_profile
from resumeme.tests.paths import REPOSITORY_ROOT

if TYPE_CHECKING:
    from pathlib import Path


def _transfer(root: Path, mode: str) -> subprocess.CompletedProcess[str]:
    """
    Invoke the production profile-transfer script against a temporary checkout layout.

    Args:
        root (Path): Fixture configuration directory.
        mode (str): Requested transfer operation.

    Returns:
        subprocess.CompletedProcess[str]: Captured process outcome without registry or browser access.
    """
    script = REPOSITORY_ROOT / "scripts/ci/linkedin/profile-artifact.py"
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


def test_capture_artifact_redacts_profile_location_when_disabled(tmp_path: Path) -> None:
    """
    Remove the owner's location from the committed snapshot and transfer artifact when opted out.

    Args:
        tmp_path (Path): Temporary configured capture root.

    Returns:
        None: The artifact and staged source snapshot contain no personal location.
    """
    config = tmp_path / "resumeme.config.yaml"
    config.write_text("linkedin:\n  username: example-person\nstyle:\n  display_location: false\n")
    snapshot = tmp_path / "data/profile.json"
    profile = Profile("example-person", "Alex Example", intro=["Staff Engineer", "Atlanta Metropolitan Area"])
    save_profile(profile, snapshot)

    result = _transfer(tmp_path, "export")

    assert result.returncode == 0
    assert json.loads(snapshot.read_text(encoding="utf-8"))["intro"] == ["Staff Engineer"]
    assert json.loads((tmp_path / ".cache/refresh/profile.json").read_text(encoding="utf-8"))["intro"] == ["Staff Engineer"]


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
        ["bash", "scripts/ci/pipeline/source.sh"],
        cwd=REPOSITORY_ROOT,
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
    workflows = REPOSITORY_ROOT / ".github/workflows"
    pipeline = yaml.safe_load((workflows / "ci.yml").read_text())
    stages = {
        name: yaml.safe_load((workflows / f"stage-{name}.yml").read_text())
        for name in ("summary", "test", "documents", "resume", "skills", "skills-publish", "release")
    }
    source = pipeline["jobs"]["source"]
    assert source["outputs"]["refresh"] == "${{ steps.source.outputs.refresh }}"
    bootstrap = pipeline["jobs"]["capture-bootstrap"]
    assert "needs.source.outputs.refresh == 'true'" in bootstrap["if"]
    assert "github.event_name == 'push' && startsWith(github.ref, 'refs/tags/')" in bootstrap["if"]
    capture = next(step for step in bootstrap["steps"] if step.get("uses") == "./.github/actions/linkedin-session")
    assert capture["with"]["command"] == "capture-plan"
    aggregate = pipeline["jobs"]["capture"]
    assert aggregate["needs"] == ["source", "capture-bootstrap", "capture-shards"]
    assert any(step.get("run") == "poetry run resumeme --config resumeme.config.yaml aggregate" for step in aggregate["steps"])
    validation = next(step for step in aggregate["steps"] if "scripts/validation/check-data.py" in step.get("run", ""))
    export = next(step for step in aggregate["steps"] if "profile-artifact.py export" in step.get("run", ""))
    assert "resumeme --config resumeme.config.yaml validate" in validation["run"]
    assert aggregate["steps"].index(validation) < aggregate["steps"].index(export)
    assert "capture" in pipeline["jobs"]["summary-stage"]["needs"]
    assert "continue-on-error" not in source and "continue-on-error" not in capture

    # A fresh capture must reach every job that reads profile evidence, including optional tag-only skill publication.
    consumers = {
        "summary": ("prepare", "summary"),
        "documents": ("documents",),
        "resume": ("build",),
        "skills": ("generate",),
        "skills-publish": ("publish",),
    }

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
    assert "resume-stage" in pipeline["jobs"]["verified"]["needs"]
    assert "documents-stage" in pipeline["jobs"]["verified"]["needs"]
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
        for step in stages["resume"]["jobs"]["build"]["steps"]
        if step.get("uses", "").startswith("actions/upload-artifact@") and step.get("with", {}).get("name") == "resume-pdf"
    )
    assert build_upload["with"]["path"] == ".cache/publication/"


def test_live_capture_uses_six_read_only_browser_scoped_workers() -> None:
    """
    Require six workers to restore the seed session without racing cache writes.

    Returns:
        None: The selected browser cache is bootstrapped once, read by all workers, and merged before downstream stages.
    """
    pipeline = yaml.safe_load((REPOSITORY_ROOT / ".github/workflows/ci.yml").read_text())
    bootstrap = pipeline["jobs"]["capture-bootstrap"]
    workers = pipeline["jobs"]["capture-shards"]
    aggregator = pipeline["jobs"]["capture"]
    bootstrap_action = next(step for step in bootstrap["steps"] if step.get("uses") == "./.github/actions/linkedin-session")
    worker_action = next(step for step in workers["steps"] if step.get("uses") == "./.github/actions/linkedin-session")
    cache_action = yaml.safe_load((REPOSITORY_ROOT / ".github/actions/linkedin-session/action.yml").read_text())

    assert workers["strategy"]["matrix"]["shard"] == [1, 2, 3, 4, 5, 6]
    assert workers["needs"] == ["source", "capture-bootstrap"]
    assert bootstrap_action["with"]["command"] == "capture-plan"
    assert worker_action["with"]["command"] == "capture-shard"
    assert worker_action["with"]["save-cache"] == "false"
    assert "LINKEDIN_USERNAME" not in worker_action.get("env", {})
    assert "LINKEDIN_PASSWORD" not in worker_action.get("env", {})
    assert any(
        "RESUMEME_SESSION_CACHE_READ_ONLY" in step.get("env", {})
        for step in cache_action["runs"]["steps"]
        if isinstance(step.get("env"), dict)
    )
    assert any(step.get("run", "").endswith(" aggregate") for step in aggregator["steps"])

    # Historical timing feedback crosses tags through authenticated artifacts rather than tag-scoped Actions caches.
    timing_restore = next(step for step in bootstrap["steps"] if "capture-timings.py restore" in step.get("run", ""))
    timing_seal = next(step for step in aggregator["steps"] if "capture-timings.py seal" in step.get("run", ""))
    assert bootstrap["permissions"]["actions"] == "read"
    assert bootstrap["steps"].index(timing_restore) < bootstrap["steps"].index(bootstrap_action)
    validated = next(step for step in aggregator["steps"] if "scripts/validation/check-data.py" in step.get("run", ""))
    assert aggregator["steps"].index(validated) < aggregator["steps"].index(timing_seal)
    timing_upload = next(step for step in aggregator["steps"] if step.get("with", {}).get("path") == ".cache/capture-timings/timings.bin")
    assert timing_upload["with"]["retention-days"] == 90
    assert timing_upload["with"]["include-hidden-files"] is True


def test_tag_runs_share_a_workflow_level_concurrency_lane() -> None:
    """
    Hold each tag pipeline until the previous tag pipeline has completed.

    Returns:
        None: All tag refs resolve to one workflow concurrency group while PR cancellation remains enabled.
    """
    pipeline = yaml.safe_load((REPOSITORY_ROOT / ".github/workflows/ci.yml").read_text())
    concurrency = pipeline["concurrency"]
    group = " ".join(concurrency["group"].split())

    assert group == (
        "${{ startsWith(github.ref, 'refs/tags/') && 'resumeme-tag-pipeline' "
        "|| format('resumeme-{0}-{1}', github.event_name, github.event.pull_request.number || github.ref) }}"
    )
    assert concurrency["cancel-in-progress"] == "${{ github.event_name == 'pull_request' }}"


@pytest.mark.parametrize(
    ("refresh", "capture", "build", "accepted"),
    [
        (False, "skipped", "success", True),
        (True, "success", "success", True),
        (True, "skipped", "success", False),
        (True, "failure", "success", False),
        (True, "cancelled", "success", False),
        (False, "skipped", "failure", False),
        (False, "skipped", "cancelled", False),
        (True, "success", "skipped", False),
    ],
)
@pytest.mark.parametrize(
    "stage",
    [
        "source",
        "summary-stage",
        "test-stage",
        "security-stage",
        "readme-stage",
        "build-stage",
        "browser-e2e-stage",
        "documents-stage",
        "resume-stage",
    ],
)
def test_verification_gate_requires_requested_capture_and_successful_work(
    refresh: bool, capture: str, build: str, accepted: bool, stage: str
) -> None:
    """
    Execute the real verification gate for capture, browser parity, and ordinary saved-profile builds.

    Args:
        refresh (bool): Whether this event requires a fresh LinkedIn capture.
        capture (str): Capture job result supplied by Actions.
        build (str): Selected required job result supplied by Actions.
        accepted (bool): Whether publication is allowed for this combination.
        stage (str): Required source, test, browser, review, or build branch exercised independently.

    Returns:
        None: Failed or skipped required work blocks publication, while an intentionally omitted capture does not.
    """
    workflow = REPOSITORY_ROOT / ".github/workflows/ci.yml"
    jobs = yaml.safe_load(workflow.read_text())["jobs"]
    results: dict[str, dict[str, str | dict[str, str]]] = {
        "source": {"result": "success", "outputs": {"refresh": str(refresh).lower()}},
        "capture": {"result": capture},
        "summary-stage": {"result": "success"},
        "test-stage": {"result": "success"},
        "security-stage": {"result": "success"},
        "readme-stage": {"result": "success"},
        "build-stage": {"result": "success"},
        "browser-e2e-stage": {"result": "success"},
        "documents-stage": {"result": "success"},
        "resume-stage": {"result": "success"},
    }
    results[stage]["result"] = build
    result = subprocess.run(
        ["bash", "-c", jobs["verified"]["steps"][0]["run"]],
        env=dict(os.environ, RESULTS_JSON=json.dumps(results)),
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is accepted, result.stdout + result.stderr

    # Explicit status checks let branch publication proceed past the intentionally skipped capture ancestor.
    for consumer in (
        "summary-stage",
        "test-stage",
        "security-stage",
        "readme-stage",
        "build-stage",
        "browser-e2e-stage",
        "documents-stage",
        "resume-stage",
        "coverage-badge",
        "deploy-stage",
        "pages-stage",
    ):
        assert "!cancelled()" in jobs[consumer]["if"]


def test_independent_pipeline_work_has_no_profile_or_summary_barrier() -> None:
    """
    Keep source builds, evidence consumers, and publication branches parallel until their actual join points.

    Returns:
        None: Source-only builds start immediately, profile consumers fan out, and release mutation waits for its writers.
    """
    workflows = REPOSITORY_ROOT / ".github/workflows"
    jobs = yaml.safe_load((workflows / "ci.yml").read_text())["jobs"]
    assert jobs["summary-stage"]["needs"] == jobs["skills-stage"]["needs"] == ["source", "capture"]
    assert jobs["documents-stage"]["needs"] == jobs["resume-stage"]["needs"] == ["source", "summary-stage"]
    assert jobs["container-stage"]["needs"] == jobs["release-stage"]["needs"] == jobs["pypi-stage"]["needs"] == ["source", "verified"]
    assert jobs["container-notes-stage"]["needs"] == ["source", "container-stage", "release-stage"]
    assert jobs["skills-publish-stage"]["needs"] == ["source", "skills-stage", "release-stage"]

    # Source-only branches never restore a captured profile; nested coverage joins only the test shards it consumes.
    for stage in ("build", "test", "security", "readme", "browser-e2e"):
        caller = jobs[f"{stage}-stage"]
        assert caller["needs"] == "source"
        assert caller["with"] == {"sha": "${{ needs.source.outputs.sha }}"}
        reusable = yaml.safe_load((workflows / f"stage-{stage}.yml").read_text())
        assert set(reusable[True]) == {"workflow_call"}

        for name, job in reusable["jobs"].items():
            assert not any(step.get("uses") == "./.github/actions/restore-profile" for step in job["steps"])

            if (stage, name) == ("test", "coverage"):
                assert job["needs"] == "python"
                continue

            assert "needs" not in job
            checkout = job["steps"][0]
            assert checkout["with"]["ref"] == "${{ inputs.sha }}"
            assert not any(step.get("uses", "").startswith("actions/download-artifact@") for step in job["steps"])

    # Security feedback follows its producer, while coverage publication remains independent of the scanner.
    assert jobs["trivy-pr-comment"]["needs"] == ["source", "security-stage"]
    assert "needs.security-stage.result != 'cancelled'" in jobs["trivy-pr-comment"]["if"]
    assert "needs.security-stage.result != 'skipped'" in jobs["trivy-pr-comment"]["if"]
    assert jobs["coverage-badge"]["needs"] == ["source", "test-stage"]

    # The public required check must account for every branch before any release or main publication can start.
    assert set(jobs["verified"]["needs"]) == {
        "source",
        "capture",
        "summary-stage",
        "test-stage",
        "security-stage",
        "readme-stage",
        "build-stage",
        "browser-e2e-stage",
        "documents-stage",
        "resume-stage",
    }
