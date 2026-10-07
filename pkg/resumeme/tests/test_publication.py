"""
Exercise publication retries against isolated local Git repositories without GitHub writes.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("matching_revision", [False, True])
def test_container_publication_uses_only_the_verified_archive(tmp_path: Path, matching_revision: bool) -> None:
    """
    Publish both tag aliases from the tested image and reject an unrelated archive before pushing.

    Args:
        tmp_path (Path): Isolated command recorder and workflow summary.
        matching_revision (bool): Whether the archive belongs to the verified source commit.

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
    tags = ["ghcr.io/example/resumeme:v1.0.0", f"ghcr.io/example/resumeme:sha-{source}"]
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
        cwd=Path(__file__).resolve().parents[3],
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
def test_publication_resumes_only_for_the_identical_generated_commit(tmp_path: Path, advanced: bool) -> None:
    """
    Resume a release after a successful PDF push while rejecting unrelated source changes.

    Args:
        tmp_path (Path): Isolated repository and bare remote directory.
        advanced (bool): Whether a source change supersedes the completed PDF commit.

    Returns:
        None: Reruns neither create duplicate PDF commits nor release obsolete source.
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
    project = Path(__file__).resolve().parents[3]

    for relative in ["scripts/ci/publish.sh", "scripts/ci/restore-pdf.py", "scripts/tooling/retry.sh"]:
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(project / relative, destination)

    (root / "resumeme.config.yaml").write_text("linkedin:\n  username: example-person\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "source")
    source = _git(root, "rev-parse", "HEAD")
    _git(root, "push", "origin", "HEAD:main")
    artifact = root / ".cache/publication/resume.pdf"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"%PDF-1.7\nfixture")
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
        RETRY_BACKOFF_SECONDS="0",
    )
    subprocess.run(["bash", "scripts/ci/publish.sh"], cwd=root, env=environment, capture_output=True, text=True, check=True)
    published = _git(remote, "rev-parse", "main")
    assert published != source
    assert output.read_text() == f"published-sha={published}\n"

    # Model a new user commit arriving after the first PDF publication; a retry must not publish that older build as current.
    if advanced:
        (root / "source-change.txt").write_text("New source invalidates the previous artifact.", encoding="utf-8")
        _git(root, "add", "source-change.txt")
        _git(root, "commit", "-m", "new source")
        _git(root, "push", "origin", "HEAD:main")

    expected_head = _git(remote, "rev-parse", "main")
    _git(root, "checkout", "--detach", source)
    output.write_text("", encoding="utf-8")
    subprocess.run(["bash", "scripts/ci/publish.sh"], cwd=root, env=environment, capture_output=True, text=True, check=True)
    assert _git(remote, "rev-parse", "main") == expected_head
    assert output.read_text() == ("" if advanced else f"published-sha={published}\n")


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
        PUBLISHED_SHA="b" * 40,
        RETRY_BACKOFF_SECONDS="0",
    )
    subprocess.run(
        ["bash", "scripts/tooling/retry.sh", "bash", "scripts/release/create-draft.sh", "resume-fixture", str(tmp_path / "notes")],
        cwd=Path(__file__).resolve().parents[3],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    assert state.read_text() == "created\n"


@pytest.mark.parametrize("existing", ["missing", "manual", "managed"])
def test_container_notes_preserve_content_and_recover_lost_responses(tmp_path: Path, existing: str) -> None:
    """
    Publish exact pull references once while preserving existing notes across uncertain writes.

    Args:
        tmp_path (Path): Fake GitHub CLI and persisted release body.
        existing (str): Initial release state, with missing, manual, or previously managed notes.

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
    writes = tmp_path / "writes"
    environment = dict(
        os.environ,
        PATH=f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
        RELEASE_TAG="release/v1.0.0",
        IMAGE_TAGS="\n".join(tags),
        RELEASE_BODY=str(state),
        RELEASE_WRITES=str(writes),
        RETRY_BACKOFF_SECONDS="0",
    )
    subprocess.run(
        ["bash", "scripts/tooling/retry.sh", "bash", "scripts/release/publish-container-notes.sh"],
        cwd=Path(__file__).resolve().parents[3],
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
        cwd=Path(__file__).resolve().parents[3],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert error in result.stderr
    assert calls.read_text().splitlines() == ["release view v1.0.0 --json body --jq .body"] * (2 if "503" in error else 1)
