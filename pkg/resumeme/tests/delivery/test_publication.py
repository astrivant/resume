"""
Exercise publication retries against isolated local Git repositories without GitHub writes.
"""

from __future__ import annotations

import hashlib
import json
import os
import runpy
import shlex
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import yaml
from PIL import Image

from resumeme.compiler.asts.profile import Entry, Media, Profile, Section, save_profile
from resumeme.tests.paths import REPOSITORY_ROOT

if TYPE_CHECKING:
    from pathlib import Path


def test_pdf_artifact_carries_utc_build_date_across_midnight(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Stage the completed PDF's UTC date independently of the staging clock or runner timezone.

    Args:
        tmp_path (Path): Temporary checkout with a configured PDF destination.
        monkeypatch (pytest.MonkeyPatch): Scoped working directory for the real artifact staging script.

    Returns:
        None: The transferred date matches the PDF's completion timestamp and its bytes remain intact.
    """
    script = REPOSITORY_ROOT / "scripts/ci/stage-pdf.py"
    (tmp_path / "resumeme.config.yaml").write_text("linkedin: {username: example}\noutput: {pdf: documents/cv.pdf}\n")
    pdf = tmp_path / "documents/cv.pdf"
    pdf.parent.mkdir()
    pdf.write_bytes(b"%PDF-1.7\nfixture")
    completed = datetime(2026, 1, 2, 23, 59, tzinfo=UTC).timestamp()
    os.utime(pdf, (completed, completed))
    monkeypatch.chdir(tmp_path)
    runpy.run_path(str(script))
    assert (tmp_path / ".cache/publication/resume.pdf").read_bytes() == pdf.read_bytes()
    assert (tmp_path / ".cache/publication/brew-date.txt").read_text() == "2026-01-02\n"


def test_unsigned_main_build_removes_signatures_for_the_replaced_pdf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Remove stale release signatures when a routine branch build replaces the tagged PDF.

    Args:
        tmp_path (Path): Temporary checkout containing a tracked signed PDF and its sidecars.
        monkeypatch (pytest.MonkeyPatch): Scoped working directory for the publication restore script.

    Returns:
        None: The new unsigned PDF is staged and verification files for its predecessor are removed.
    """
    _git(tmp_path, "init", "--initial-branch=main")
    _git(tmp_path, "config", "user.name", "Fixture")
    _git(tmp_path, "config", "user.email", "fixture@example.org")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    (tmp_path / "resumeme.config.yaml").write_text("linkedin: {username: example-person}\n", encoding="utf-8")
    release_files = [
        "resume.pdf.sig",
        "resume.pdf.sigstore.json",
        "cosign.pub",
        "key-fingerprint.txt",
        "source.json",
        "SHA256SUMS",
        "SHA256SUMS.sigstore.json",
    ]
    (tmp_path / "resume.pdf").write_bytes(b"%PDF-1.7\nold signed build")

    for filename in release_files:
        (tmp_path / filename).write_text("old verification material\n", encoding="utf-8")

    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "signed release")
    artifact = tmp_path / ".cache/publication/resume.pdf"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"%PDF-1.7\nnew unsigned build")
    monkeypatch.chdir(tmp_path)
    runpy.run_path(str(REPOSITORY_ROOT / "scripts/ci/restore-pdf.py"))

    staged = _git(tmp_path, "diff", "--cached", "--name-status").splitlines()
    assert staged == sorted([*(f"D\t{name}" for name in release_files), "M\tresume.pdf"], key=lambda item: item.split("\t")[1])


@pytest.mark.parametrize("matching_revision", [False, True])
@pytest.mark.parametrize("image", ["ghcr.io/example/resumeme", "emmeowzing/resumeme"])
def test_container_publication_uses_only_the_verified_archive(tmp_path: Path, matching_revision: bool, image: str) -> None:
    """
    Publish both tag aliases from the tested image and reject an unrelated archive before pushing.

    Args:
        tmp_path (Path): Isolated command recorder and workflow summary.
        matching_revision (bool): Whether the archive belongs to the verified source commit.
        image (str): GHCR or Docker Hub destination receiving both aliases.

    Returns:
        None: Publishing never rebuilds an image or pushes a mismatched source revision.
    """

    # Replace Docker at the command boundary so publication sequencing is tested without contacting a daemon or registry.
    docker = tmp_path / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        'printf "%s\\n" "$*" >>"$DOCKER_CALLS"\n'
        'if [[ "$1" == image && "$2" == inspect ]]; then printf "%s\\n" "$ARCHIVE_REVISION"; fi\n',
        encoding="utf-8",
    )
    docker.chmod(0o700)
    source = "a" * 40
    tags = [f"{image}:v1.0.0", f"{image}:sha-{source}"]
    environment = dict(
        os.environ,
        PATH=f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
        SOURCE_SHA=source,
        IMAGE_TAGS="\n".join(tags),
        ARCHIVE_REVISION=source if matching_revision else "b" * 40,
        DOCKER_CALLS=str(tmp_path / "calls"),
        GITHUB_STEP_SUMMARY=str(tmp_path / "summary"),
    )
    result = subprocess.run(
        ["bash", "scripts/ci/publish-container.sh"],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    calls = (tmp_path / "calls").read_text().splitlines()
    assert calls[0] == "load --input .cache/container/resumeme.tar.gz"
    assert not any(call.startswith("build") for call in calls)

    if matching_revision:
        assert result.returncode == 0
        assert [call for call in calls if call.startswith("push ")] == [f"push {tag}" for tag in tags]
        assert (tmp_path / "summary").read_text() == "".join(f"- Published {tag}\n" for tag in tags)
    else:
        assert result.returncode != 0
        assert "does not match" in result.stderr
        assert not any(call.startswith(("push ", "tag ")) for call in calls)


def test_dockerhub_publication_is_upstream_tag_only() -> None:
    """
    Guard the upstream namespace and organization secret while forks retain their GHCR path.

    Returns:
        None: Docker Hub cannot run for forks or branch events and uses the verified image and source aliases.
    """
    workflows = REPOSITORY_ROOT / ".github/workflows"
    pipeline = yaml.safe_load((workflows / "ci.yml").read_text())
    stage = yaml.safe_load((workflows / "stage-container.yml").read_text())
    caller = pipeline["jobs"]["container-stage"]
    hub = stage["jobs"]["dockerhub"]
    assert caller["needs"] == ["source", "verified"]
    assert caller["secrets"]["DOCKER_HUB_TOKEN_EMMEOWZING"] == "${{ secrets.DOCKER_HUB_TOKEN_EMMEOWZING }}"
    assert stage[True]["workflow_call"]["secrets"]["DOCKER_HUB_TOKEN_EMMEOWZING"]["required"] is False

    # A secret existing on a fork must not be enough to unlock the upstream Docker Hub destination.
    assert " ".join(hub["if"].split()) == (
        "github.repository == 'astrivant/resumeme' && github.event.repository.fork == false && "
        "github.event_name == 'push' && startsWith(github.ref, 'refs/tags/')"
    )
    metadata = next(step for step in hub["steps"] if step.get("id") == "metadata")
    assert metadata["with"]["images"] == "emmeowzing/resumeme"
    assert metadata["with"]["flavor"] == "latest=false"
    assert metadata["with"]["tags"].splitlines() == ["type=ref,event=tag", "type=raw,value=sha-${{ inputs.sha }}"]
    login = next(step for step in hub["steps"] if step.get("uses", "").startswith("docker/login-action@"))
    assert login["with"] == {
        "registry": "docker.io",
        "username": "emmeowzing",
        "password": "${{ secrets.DOCKER_HUB_TOKEN_EMMEOWZING }}",
    }
    assert any(step.get("with", {}).get("name") == "resumeme-container" for step in hub["steps"])
    publisher = next(step for step in hub["steps"] if step.get("run") == "bash scripts/ci/publish-container.sh")
    assert publisher["env"]["SOURCE_SHA"] == "${{ inputs.sha }}"
    assert not any(step.get("uses", "").startswith("docker/build-push-action@") for step in hub["steps"])

    # One notes job waits for both destinations; each registry contributes references only after a successful push.
    notes_caller = pipeline["jobs"]["container-notes-stage"]
    notes = yaml.safe_load((workflows / "stage-container-notes.yml").read_text())["jobs"]["notes"]
    assert notes_caller["needs"] == ["source", "container-stage", "release-stage"]
    assert "!cancelled()" in notes_caller["if"]
    assert "needs.release-stage.result == 'success'" in notes_caller["if"]
    assert notes["steps"][-1]["env"]["IMAGE_TAGS"] == "${{ inputs.image-tags }}"

    for registry, output in (("publish", "ghcr-tags"), ("dockerhub", "dockerhub-tags")):
        value = stage[True]["workflow_call"]["outputs"][output]["value"]
        assert value == "${{ jobs." + registry + ".outputs.tags }}"
        assert (
            stage["jobs"][registry]["outputs"]["tags"] == "${{ steps.publish.outcome == 'success' && steps.metadata.outputs.tags || '' }}"
        )
        push = next(step for step in stage["jobs"][registry]["steps"] if step.get("id") == "publish")
        assert push["run"] == "bash scripts/ci/publish-container.sh"
        assert f"needs.container-stage.outputs.{output}" in notes_caller["with"]["image-tags"]
        assert f"needs.container-stage.outputs.{output} != ''" in notes_caller["if"]


def _git(root: Path, *arguments: str) -> str:
    """
    Run Git inside a temporary test repository.

    Args:
        root (Path): Fixture repository directory.
        *arguments (str): Git command arguments.

    Returns:
        str: Trimmed command output.
    """
    return subprocess.run(["git", "-C", str(root), *arguments], check=True, capture_output=True, text=True).stdout.strip()


@pytest.mark.parametrize("advanced", [False, True])
@pytest.mark.parametrize("refresh", [False, True])
@pytest.mark.parametrize("fork, readme_output", [(False, None), (True, "README.md"), (False, "FORK_EXAMPLE.md")])
@pytest.mark.parametrize("publication_token", [False, True])
def test_publication_resumes_only_for_the_identical_generated_commit(
    tmp_path: Path, advanced: bool, refresh: bool, fork: bool, readme_output: str | None, publication_token: bool
) -> None:
    """
    Reproduce a PDF and logo publication on retries while rejecting unrelated source changes.

    Args:
        tmp_path (Path): Isolated repository and bare remote directory.
        advanced (bool): Whether a source change supersedes the completed PDF commit.
        refresh (bool): Whether publication also includes a newly captured profile and media.
        fork (bool): Whether the generated README replaces project branding on this repository.
        readme_output (str | None): Generated Markdown destination, or None to retain only project branding.
        publication_token (bool): Whether a bypass-capable token requires a trailer preventing recursive PDF publication.

    Returns:
        None: Reruns preserve the published tree; only changed resume inputs create a fresh logo and commit.
    """

    # Use a real local remote to exercise fast-forward and rerun behavior without granting tests access to GitHub writes.
    root = tmp_path / "checkout"
    remote = tmp_path / "remote.git"
    root.mkdir()
    remote.mkdir()
    _git(remote, "init", "--bare", "--initial-branch=main")
    _git(root, "init", "--initial-branch=main")
    _git(root, "config", "user.name", "Fixture")
    _git(root, "config", "user.email", "fixture@example.org")
    _git(root, "config", "commit.gpgsign", "false")
    _git(root, "remote", "add", "origin", str(remote))
    project = REPOSITORY_ROOT

    for relative in [
        "scripts/ci/publish.sh",
        "scripts/ci/restore-pdf.py",
        "scripts/ci/readme-artifact.py",
        "scripts/ci/profile-artifact.py",
        "scripts/ci/refresh-logo.py",
        "scripts/tooling/retry.sh",
        "docs/assets/branding/linkedin-base.png",
        "docs/assets/branding/coffee-ring.png",
    ]:
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(project / relative, destination)

    configuration = "linkedin:\n  username: example-person\n"

    if readme_output and not fork:
        configuration += f"readme:\n  mode: resume\n  output: {readme_output}\n"

    (root / "resumeme.config.yaml").write_text(configuration, encoding="utf-8")
    (root / "README.md").write_text(
        "# Project\n\n<!-- resumeme:branding:start -->\nInitial branding\n<!-- resumeme:branding:end -->\n\nCustom introduction\n"
    )
    _git(root, "add", ".")
    _git(root, "commit", "-m", "source")
    source = _git(root, "rev-parse", "HEAD")
    _git(root, "push", "origin", "HEAD:main")
    artifact = root / ".cache/publication/resume.pdf"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"%PDF-1.7\nfixture")
    artifact.with_name("brew-date.txt").write_text("2026-01-02\n", encoding="ascii")

    # Build artifacts arrive together; publication must stage the configured Markdown path and preview.
    if readme_output:
        bundle = artifact.parent / "readme"
        bundle.mkdir()
        (bundle / "README.md").write_text("# Fresh owner - Résumé\n", encoding="utf-8")
        (bundle / "pdf.sha256").write_text(hashlib.sha256(artifact.read_bytes()).hexdigest())
        Image.new("RGB", (20, 30), "white").save(bundle / "resume-preview.png")

    snapshot = root / "data/profile.json"
    image = root / "data/assets/logo.png"
    profile = Profile(
        "example-person",
        "Fresh owner",
        sections=[
            Section("experience", "Experience", [Entry(images=[Media("https://example.org/logo.png", path="data/assets/logo.png")])])
        ],
    )

    if refresh:
        save_profile(profile, snapshot)
        image.parent.mkdir(parents=True)
        image.write_bytes(b"captured image")

    # Unrelated browser state must never be staged along with the monthly capture.
    (root / ".cache/cookies.sqlite").write_bytes(b"private browser state")
    bin_directory = tmp_path / "bin"
    bin_directory.mkdir()
    poetry = bin_directory / "poetry"
    poetry.write_text(f'#!/usr/bin/env bash\nshift 2\nexec {shlex.quote(sys.executable)} "$@"\n', encoding="utf-8")
    poetry.chmod(0o700)
    output = tmp_path / "output"
    environment = dict(
        os.environ,
        PATH=f"{bin_directory}{os.pathsep}{os.environ['PATH']}",
        SOURCE_SHA=source,
        GITHUB_OUTPUT=str(output),
        GITHUB_REF="refs/heads/main",
        GITHUB_EVENT_NAME="push",
        REFRESH_PROFILE=str(refresh).lower(),
        RESUMEME_REPOSITORY_FORK=str(fork).lower(),
        RESUMEME_PUBLISH_USES_TOKEN=str(publication_token).lower(),
        GITHUB_REPOSITORY="example/my-cv",
        RETRY_BACKOFF_SECONDS="0",
    )
    subprocess.run(["bash", "scripts/ci/publish.sh"], cwd=root, env=environment, capture_output=True, text=True, check=True)
    published = _git(remote, "rev-parse", "main")
    assert published != source
    message = _git(remote, "log", "-1", "--format=%B", "main")
    assert ("Resumeme-Publication: true" in message) is publication_token
    assert "[skip ci]" not in message
    assert output.read_text() == f"published-sha={published}\n"
    files = _git(remote, "diff-tree", "--no-commit-id", "--name-only", "-r", published).splitlines()
    expected_files = (
        ["README.md", "docs/assets/resume-preview.png", "resume.pdf"]
        if fork
        else ["README.md", "docs/assets/branding/resumeme-logo.png", "docs/assets/branding/brew-date.svg", "resume.pdf"]
    )

    if readme_output and not fork:
        expected_files.extend([readme_output, "docs/assets/resume-preview.png"])

    assert files == sorted(["data/assets/logo.png", "data/profile.json", *expected_files] if refresh else expected_files)

    if readme_output:
        assert (root / readme_output).read_text() == "# Fresh owner - Résumé\n"

    logo = root / ("docs/assets/resume-preview.png" if fork else "docs/assets/branding/resumeme-logo.png")
    published_logo = logo.read_bytes()

    if not fork:
        # Publication uses the artifact date even when Git's source date and the deploy clock differ from it.
        assert "2026-01-02" in (root / "docs/assets/branding/brew-date.svg").read_text()

        with Image.open(logo) as generated:
            assert json.loads(generated.info["resumeme.stains"]) == [source]

        markdown = (root / "README.md").read_text()
        assert 'href="./resume.pdf"' in markdown
        assert 'src="https://raw.githubusercontent.com/example/my-cv/main/docs/assets/branding/resumeme-logo.png"' in markdown
        assert 'src="https://raw.githubusercontent.com/example/my-cv/main/docs/assets/branding/brew-date.svg"' in markdown
        assert "Brew date 2026-01-02 (UTC)" in markdown
        assert markdown.endswith("Custom introduction\n")

    # Model a new user commit arriving after the first PDF publication; a retry must not publish that older build as current.
    if advanced:
        (root / "source-change.txt").write_text("New source invalidates the previous artifact.", encoding="utf-8")
        _git(root, "add", "source-change.txt")
        _git(root, "commit", "-m", "new source")
        _git(root, "push", "origin", "HEAD:main")

    expected_head = _git(remote, "rev-parse", "main")
    _git(root, "checkout", "--detach", source)

    if refresh:
        save_profile(profile, snapshot)
        image.parent.mkdir(parents=True, exist_ok=True)
        image.write_bytes(b"captured image")

    output.write_text("", encoding="utf-8")
    subprocess.run(["bash", "scripts/ci/publish.sh"], cwd=root, env=environment, capture_output=True, text=True, check=True)
    assert _git(remote, "rev-parse", "main") == expected_head
    assert output.read_text() == ("" if advanced else f"published-sha={published}\n")
    assert logo.read_bytes() == published_logo

    if not advanced:
        # Rebuilding the just-published revision with identical inputs must not make a logo-only commit.
        _git(root, "checkout", "--detach", published)
        environment["SOURCE_SHA"] = published
        output.write_text("", encoding="utf-8")
        subprocess.run(["bash", "scripts/ci/publish.sh"], cwd=root, env=environment, capture_output=True, text=True, check=True)
        assert _git(remote, "rev-parse", "main") == published
        assert output.read_text() == f"published-sha={published}\n"
        assert logo.read_bytes() == published_logo

        # A subsequent accepted PDF earns a new stain in the same atomic publication commit.
        artifact.write_bytes(b"%PDF-1.7\nupdated fixture")
        artifact.with_name("brew-date.txt").write_text("2026-02-03\n", encoding="ascii")

        if readme_output:
            (bundle / "pdf.sha256").write_text(hashlib.sha256(artifact.read_bytes()).hexdigest())
            Image.new("RGB", (20, 30), "green").save(bundle / "resume-preview.png")

        subprocess.run(["bash", "scripts/ci/publish.sh"], cwd=root, env=environment, capture_output=True, text=True, check=True)
        assert _git(remote, "rev-parse", "main") != published
        assert logo.read_bytes() != published_logo

        if not fork:
            assert "2026-02-03" in (root / "docs/assets/branding/brew-date.svg").read_text()

            # The next publication preserves the prior impression even though only the generated PNG crosses checkouts.
            with Image.open(logo) as generated:
                assert json.loads(generated.info["resumeme.stains"]) == [published, source]


def test_draft_creation_recovers_a_lost_success_response(tmp_path: Path) -> None:
    """
    Reconcile an already-created draft when GitHub's successful response is lost.

    Args:
        tmp_path (Path): Fake CLI and server-state directory.

    Returns:
        None: Retrying succeeds without creating the release a second time.
    """
    command = tmp_path / "gh"
    command.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$1 $2" == 'release view' ]]; then
    if [[ -f "$DRAFT_STATE" ]]; then
        echo true
        exit 0
    fi
    echo 'release not found' >&2
    exit 1
fi
if [[ "$1 $2" == 'release create' ]]; then
    echo created >>"$DRAFT_STATE"
    echo 'HTTP 503: response lost after creating draft' >&2
    exit 1
fi
exit 2
""",
        encoding="utf-8",
    )
    command.chmod(0o700)
    state = tmp_path / "server-state"
    environment = dict(
        os.environ,
        PATH=f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
        DRAFT_STATE=str(state),
        SOURCE_SHA="a" * 40,
        RETRY_BACKOFF_SECONDS="0",
    )
    subprocess.run(
        ["bash", "scripts/tooling/retry.sh", "bash", "scripts/release/create-draft.sh", "resume-fixture", str(tmp_path / "notes")],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    assert state.read_text() == "created\n"


@pytest.mark.parametrize("matching_tag", [False, True])
def test_signed_release_uses_only_the_existing_selected_tag(tmp_path: Path, matching_tag: bool) -> None:
    """
    Publish on the user's tag and reject a tag that points to a different source revision.

    Args:
        tmp_path (Path): Local checkout, synthetic signing payload, and recording GitHub CLI.
        matching_tag (bool): Whether the chosen tag selects the verified source commit.

    Returns:
        None: The selected release receives the complete payload without creating an automatic source-SHA tag.
    """
    root = tmp_path / "checkout"
    root.mkdir()
    _git(root, "init", "--initial-branch=main")
    _git(root, "config", "user.name", "Fixture")
    _git(root, "config", "user.email", "fixture@example.org")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "source.txt").write_text("selected source")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "selected source")
    # Synthetic tags must not invoke a developer's globally configured signing agent.
    _git(root, "tag", "--no-sign", "resume-selected")

    if not matching_tag:
        (root / "source.txt").write_text("different source")
        _git(root, "commit", "-am", "advance source")

    source = _git(root, "rev-parse", "HEAD")
    repository = REPOSITORY_ROOT

    for relative in ("scripts/release/publish.sh", "scripts/release/create-draft.sh", "scripts/tooling/retry.sh"):
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repository / relative, destination)

    # Cryptographic verification is a separate boundary; this test exercises tag selection and release publication sequencing.
    (root / "scripts/release/verify.sh").write_text("#!/usr/bin/env bash\nexit 0\n")
    artifacts = root / ".cache/publication"
    artifacts.mkdir(parents=True)
    filenames = [
        "resume.pdf",
        "resume.pdf.sig",
        "resume.pdf.sigstore.json",
        "cosign.pub",
        "key-fingerprint.txt",
        "source.json",
        "SHA256SUMS",
        "SHA256SUMS.sigstore.json",
    ]

    for filename in filenames:
        (artifacts / filename).write_text("synthetic verified artifact")

    command = tmp_path / "gh"
    command.write_text(
        "#!/usr/bin/env bash\n"
        'printf "%s\\n" "$*" >>"$GH_CALLS"\n'
        'if [[ "$1 $2" == "release view" ]]; then echo "release not found" >&2; exit 1; fi\n'
        "exit 0\n"
    )
    command.chmod(0o700)
    calls = tmp_path / "calls"
    result = subprocess.run(
        ["bash", "scripts/release/publish.sh"],
        cwd=root,
        env=dict(
            os.environ,
            PATH=f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
            SOURCE_SHA=source,
            RELEASE_TAG="resume-selected",
            RUNNER_TEMP=str(tmp_path),
            GH_CALLS=str(calls),
            RETRY_BACKOFF_SECONDS="0",
        ),
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is matching_tag

    if not matching_tag:
        assert not calls.exists()
        return

    operations = calls.read_text().splitlines()
    assert operations[2].startswith("release create resume-selected --draft --verify-tag ")
    assert operations[3].startswith("release upload resume-selected ")
    assert all(f".cache/publication/{filename}" in operations[3] for filename in filenames)
    assert operations[4].startswith("release edit resume-selected --draft=false ")
    assert all(f"resume-{source}" not in operation for operation in operations)


@pytest.mark.parametrize("latest_release", [False, True])
@pytest.mark.parametrize("main_advanced", [False, True])
def test_tag_publication_commits_only_the_latest_signed_payload_to_main(tmp_path: Path, latest_release: bool, main_advanced: bool) -> None:
    """
    Apply this tag's verified release files to the latest main without replacing newer source.

    Args:
        tmp_path (Path): Isolated checkout, bare remote, signed payload, and fake GitHub CLI.
        latest_release (bool): Whether GitHub reports this tag as the latest release.
        main_advanced (bool): Whether another source commit replaced the tagged commit on main.

    Returns:
        None: The fresh profile publishes once, newer source survives, and stale releases leave main untouched.
    """
    root = tmp_path / "checkout"
    remote = tmp_path / "remote.git"
    root.mkdir()
    remote.mkdir()
    _git(remote, "init", "--bare", "--initial-branch=main")
    _git(root, "init", "--initial-branch=main")
    _git(root, "config", "user.name", "Fixture")
    _git(root, "config", "user.email", "fixture@example.org")
    _git(root, "config", "commit.gpgsign", "false")
    _git(root, "remote", "add", "origin", str(remote))
    (root / "resumeme.config.yaml").write_text("linkedin: {username: example}\n", encoding="utf-8")
    (root / "README.md").write_text("tag source README\n", encoding="utf-8")
    (root / "data").mkdir()
    (root / "data/profile.json").write_text('{"name": "Example"}\n', encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "tag source")
    source = _git(root, "rev-parse", "HEAD")
    _git(root, "tag", "--no-sign", "resume-selected")
    _git(root, "push", "origin", "HEAD:main")
    _git(root, "push", "origin", "refs/tags/resume-selected")

    if main_advanced:
        (root / "newer-source.txt").write_text("newer branch content\n", encoding="utf-8")
        (root / "README.md").write_text("newer main README\n", encoding="utf-8")
        _git(root, "add", "newer-source.txt")
        _git(root, "add", "README.md")
        _git(root, "commit", "-m", "newer source")
        _git(root, "push", "origin", "HEAD:main")
        _git(root, "checkout", "--detach", source)

    # The signed artifact is a run-scoped input and carries the immutable tagged-source identity.
    artifact_dir = root / ".cache/publication"
    artifact_dir.mkdir(parents=True)
    filenames = [
        "resume.pdf",
        "resume.pdf.sig",
        "resume.pdf.sigstore.json",
        "cosign.pub",
        "key-fingerprint.txt",
        "source.json",
        "SHA256SUMS",
        "SHA256SUMS.sigstore.json",
    ]

    for filename in filenames:
        (artifact_dir / filename).write_text(f"release artifact {filename}\n", encoding="utf-8")

    (artifact_dir / "source.json").write_text(json.dumps({"source_commit": source}) + "\n", encoding="utf-8")

    # Model the validated profile-stage input that the workflow stages before publishing the signed files.
    (root / "data/profile.json").write_text('{"name": "Captured Example"}\n', encoding="utf-8")
    _git(root, "add", "data/profile.json")
    (root / "README.md").write_text("tag resume preview\n", encoding="utf-8")
    _git(root, "add", "README.md")
    release_scripts = root / "scripts/release"
    release_scripts.mkdir(parents=True)
    shutil.copyfile(REPOSITORY_ROOT / "scripts/release/commit-main.sh", release_scripts / "commit-main.sh")
    retry = root / "scripts/tooling/retry.sh"
    retry.parent.mkdir(parents=True)
    shutil.copyfile(REPOSITORY_ROOT / "scripts/tooling/retry.sh", retry)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    gh = fake_bin / "gh"
    gh.write_text(
        "#!/usr/bin/env bash\n"
        '[[ "$*" == "release view --repo example/resume --json tagName --jq .tagName" ]]\n'
        f"printf '%s\\n' {'resume-selected' if latest_release else 'resume-newer'}\n",
        encoding="utf-8",
    )
    gh.chmod(0o700)
    output = tmp_path / "output"
    environment = dict(
        os.environ,
        PATH=f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        SOURCE_SHA=source,
        RELEASE_TAG="resume-selected",
        GITHUB_REPOSITORY="example/resume",
        GH_TOKEN="fixture-token",
        GITHUB_OUTPUT=str(output),
        RESUME_PUBLISH_USES_TOKEN="false",
        README_MODE="project",
        RETRY_BACKOFF_SECONDS="0",
    )

    def publish() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "scripts/release/commit-main.sh"],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    result = publish()
    assert result.returncode == 0, result.stdout + result.stderr
    published = _git(remote, "rev-parse", "main")

    if not latest_release:
        assert published != source if main_advanced else published == source
        assert not output.exists()
        return

    assert published != source
    if main_advanced:
        assert _git(remote, "show", "main:newer-source.txt") == "newer branch content"

    assert _git(remote, "show", "main:resume.pdf") == "release artifact resume.pdf"
    assert _git(remote, "show", "main:data/profile.json") == '{"name": "Captured Example"}'
    assert _git(remote, "show", "main:README.md") == ("newer main README" if main_advanced else "tag resume preview")
    assert _git(remote, "show", "main:key-fingerprint.txt") == "release artifact key-fingerprint.txt"
    assert "Resumeme-Signed-Release: resume-selected" in _git(remote, "log", "-1", "--format=%B", "main")
    assert output.read_text(encoding="utf-8") == f"published-sha={published}\n"
    changed_paths = [*filenames, "data/profile.json"]

    if not main_advanced:
        changed_paths.append("README.md")

    assert _git(remote, "diff-tree", "--no-commit-id", "--name-only", "-r", published).splitlines() == sorted(changed_paths)

    # A lost workflow response followed by retry must resolve to the same signed commit.
    _git(root, "reset", "--hard", source)
    (root / "data/profile.json").write_text('{"name": "Captured Example"}\n', encoding="utf-8")
    _git(root, "add", "data/profile.json")
    output.write_text("", encoding="utf-8")
    retry_result = publish()
    assert retry_result.returncode == 0, retry_result.stdout + retry_result.stderr
    assert _git(remote, "rev-parse", "main") == published
    assert output.read_text(encoding="utf-8") == f"published-sha={published}\n"


def test_tag_pipeline_publishes_verified_release_files_and_refreshes_pages() -> None:
    """
    Keep tag publication downstream of signing and connect its accepted main SHA to Pages.

    Returns:
        None: The commit stage consumes the signed release and profile artifacts; Pages deploys only its output SHA.
    """
    workflows = REPOSITORY_ROOT / ".github/workflows"
    pipeline = yaml.safe_load((workflows / "ci.yml").read_text())
    publish = yaml.safe_load((workflows / "stage-tag-publish.yml").read_text())
    assert pipeline["jobs"]["tag-publish-stage"]["needs"] == ["source", "release-stage"]
    assert pipeline["jobs"]["tag-publish-stage"]["with"]["sha"] == "${{ needs.source.outputs.sha }}"
    assert pipeline["jobs"]["tag-pages-stage"]["needs"] == "tag-publish-stage"
    assert pipeline["jobs"]["tag-pages-stage"]["with"]["sha"] == "${{ needs.tag-publish-stage.outputs.published-sha }}"
    job = publish["jobs"]["publish"]
    steps = job["steps"]
    signed = next(step for step in steps if step.get("with", {}).get("name") == "signed-resume")
    captured = next(step for step in steps if step.get("with", {}).get("name") == "resumeme-profile")
    verify = next(index for index, step in enumerate(steps) if step.get("run") == "bash scripts/release/verify.sh")
    stage_profile = next(index for index, step in enumerate(steps) if "profile-artifact.py stage" in step.get("run", ""))
    stage_readme = next(index for index, step in enumerate(steps) if "readme-artifact.py stage" in step.get("run", ""))
    restore_readme = next(index for index, step in enumerate(steps) if "readme-artifact.py restore" in step.get("run", ""))
    commit = next(index for index, step in enumerate(steps) if step.get("run") == "bash scripts/release/commit-main.sh")
    assert signed["with"]["path"] == ".cache/publication/"
    assert captured["with"]["path"] == ".cache/refresh/"
    restore_profile = next(index for index, step in enumerate(steps) if "profile-artifact.py restore" in step.get("run", ""))
    assert steps.index(signed) < verify < restore_profile < stage_profile < stage_readme < restore_readme < commit
    assert job["concurrency"]["group"] == "resumeme-pdf-main"


@pytest.mark.parametrize("existing", ["missing", "manual", "managed"])
@pytest.mark.parametrize("dockerhub", [False, True])
def test_container_notes_preserve_content_and_recover_lost_responses(tmp_path: Path, existing: str, dockerhub: bool) -> None:
    """
    Publish exact pull references once while preserving existing notes across uncertain writes.

    Args:
        tmp_path (Path): Fake GitHub CLI and persisted release body.
        existing (str): Initial release state, with missing, manual, or previously managed notes.
        dockerhub (bool): Include upstream Docker Hub aliases alongside GHCR's fork-compatible references.

    Returns:
        None: New and existing releases retain one current container section after retries.
    """

    # Model GitHub persisting a write but losing its response; the retry must read the committed body before writing again.
    command = tmp_path / "gh"
    command.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$1 $2" == 'release view' ]]; then
    if [[ -f "$RELEASE_BODY" ]]; then
        cat "$RELEASE_BODY"
        exit 0
    fi
    echo 'release not found' >&2
    exit 1
fi
printf '%s\n' "$*" >>"$RELEASE_WRITES"
while (( $# )); do
    if [[ "$1" == --notes-file ]]; then
        cp "$2" "$RELEASE_BODY"
        echo 'HTTP 503: response lost after saving release notes' >&2
        exit 1
    fi
    shift
done
exit 2
""",
        encoding="utf-8",
    )
    command.chmod(0o700)
    state = tmp_path / "body.md"
    before = "Existing notes with `backticks` and $(literal).\n\nSignature instructions."
    after = "\n\nMaintainer's trailing notes."

    if existing == "manual":
        state.write_text(before, encoding="utf-8")
    elif existing == "managed":
        state.write_text(
            f"{before}\n\n<!-- resume:container:start -->\nStale pull command.\n<!-- resume:container:end -->{after}",
            encoding="utf-8",
        )

    # Keep the original Git tag distinct from its normalized Docker alias, as metadata-action does for unsupported characters.
    tags = ["ghcr.io/example/resumeme:release-v1.0.0", f"ghcr.io/example/resumeme:sha-{'a' * 40}"]

    if dockerhub:
        tags.extend(["emmeowzing/resumeme:release-v1.0.0", f"emmeowzing/resumeme:sha-{'a' * 40}"])

    writes = tmp_path / "writes"
    environment = dict(
        os.environ,
        PATH=f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
        RELEASE_TAG="release/v1.0.0",
        IMAGE_TAGS="\n" + "\n".join(tags) + "\n",
        RELEASE_BODY=str(state),
        RELEASE_WRITES=str(writes),
        RETRY_BACKOFF_SECONDS="0",
    )
    subprocess.run(
        ["bash", "scripts/tooling/retry.sh", "bash", "scripts/release/publish-container-notes.sh"],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )

    # Each alias appears exactly once, and a retry that observes the successful write performs no further mutation.
    notes = state.read_text()
    assert notes.count("## Container image") == 1

    for tag in tags:
        assert notes.count(f"docker pull --platform linux/amd64 {tag}\n") == 1

    calls = writes.read_text().splitlines()
    assert len(calls) == 1

    if existing == "missing":
        assert calls[0].startswith("release create release/v1.0.0 --verify-tag --latest=false --title release/v1.0.0 --notes-file ")
    else:
        assert calls[0].startswith("release edit release/v1.0.0 --notes-file ")
        assert notes.startswith(before + "\n\n")

    if existing == "managed":
        assert "Stale pull command." not in notes
        assert notes.endswith(after + "\n")


@pytest.mark.parametrize("error", ["HTTP 403: forbidden", "HTTP 503: temporarily unavailable"])
def test_container_notes_do_not_create_releases_after_failed_lookups(tmp_path: Path, error: str) -> None:
    """
    Distinguish unavailable release state from a confirmed absent release.

    Args:
        tmp_path (Path): Isolated GitHub command recorder.
        error (str): Authentication or transport failure reported during release lookup.

    Returns:
        None: Failed lookups never create or edit a release, even across transient retries.
    """

    # A lookup failure leaves release ownership unknown, so record every attempted command and deny all reads.
    command = tmp_path / "gh"
    command.write_text(
        '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >>"$GH_CALLS"\nprintf "%s\\n" "$GH_FAILURE" >&2\nexit 1\n',
        encoding="utf-8",
    )
    command.chmod(0o700)
    calls = tmp_path / "calls"
    environment = dict(
        os.environ,
        PATH=f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
        RELEASE_TAG="v1.0.0",
        IMAGE_TAGS="ghcr.io/example/resumeme:v1.0.0",
        GH_CALLS=str(calls),
        GH_FAILURE=error,
        RETRY_ATTEMPTS="2",
        RETRY_BACKOFF_SECONDS="0",
    )
    result = subprocess.run(
        ["bash", "scripts/tooling/retry.sh", "bash", "scripts/release/publish-container-notes.sh"],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert error in result.stderr
    assert calls.read_text().splitlines() == ["release view v1.0.0 --json body --jq .body"] * (2 if "503" in error else 1)
