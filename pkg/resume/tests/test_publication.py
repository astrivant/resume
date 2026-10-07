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
    (root / "resume.reference.yaml").write_text("linkedin:\n  username: example-person\n", encoding="utf-8")
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
