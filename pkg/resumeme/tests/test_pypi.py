"""
Verify PyPI release boundaries and transient retries without accessing credentials or a registry.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def publication(tmp_path: Path) -> Path:
    """
    Supply isolated release scripts, distribution fixtures, and a recording Poetry executable.

    Args:
        tmp_path (Path): Temporary release root.

    Returns:
        Path: Working directory whose upload commands cannot reach PyPI.
    """
    repository = Path(__file__).resolve().parents[3]

    # Exercise the actual scripts while replacing only the command that owns the network boundary.
    for relative in ("scripts/release/package-version.sh", "scripts/release/publish-package.sh", "scripts/tooling/retry.sh"):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repository / relative, destination)

    (tmp_path / "dist").mkdir()

    for filename in ("resumeme-0.1.0-py3-none-any.whl", "resumeme-0.1.0.tar.gz"):
        (tmp_path / "dist" / filename).write_bytes(b"verified fixture")

    poetry = tmp_path / "poetry"
    poetry.write_text(
        "#!/usr/bin/env bash\n"
        'printf "%s\\n" "$*" >> calls\n'
        'if [[ "$*" == "version --short" ]]; then echo 0.1.0; exit 0; fi\n'
        'if [[ "$*" != "publish --no-interaction --skip-existing" ]]; then exit 64; fi\n'
        'if [[ "${SIMULATE_RETRY:-false}" == true && ! -e failed-once ]]; then\n'
        '    touch failed-once; echo "HTTP 503 Service Unavailable" >&2; exit 1\n'
        "fi\n"
    )
    poetry.chmod(0o700)
    return tmp_path


@pytest.mark.parametrize("tag", ["", "v0.1.0", "v0.2.0", "resume-snapshot", "v0.1.0; exit 0"])
def test_release_tag_must_match_committed_version(publication: Path, tag: str) -> None:
    """
    Accept ordinary builds and the exact package tag while rejecting unrelated release identifiers.

    Args:
        publication (Path): Isolated command boundary.
        tag (str): Optional version tag passed through an environment variable.

    Returns:
        None: Mismatched tags fail without rewriting metadata or invoking publication.
    """
    result = subprocess.run(
        ["bash", "scripts/release/package-version.sh"],
        cwd=publication,
        env=dict(os.environ, PATH=f"{publication}{os.pathsep}{os.environ['PATH']}", RELEASE_TAG=tag),
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is (tag in {"", "v0.1.0"})
    assert (publication / "calls").read_text().splitlines() == ["version --short"]


@pytest.mark.parametrize("failure", ["", "token", "tag", "wheel", "sdist", "retry"])
def test_pypi_upload_requires_complete_verified_release(publication: Path, failure: str) -> None:
    """
    Require credentials and both distributions before publishing, then safely retry transport failures.

    Args:
        publication (Path): Isolated release root with synthetic distributions.
        failure (str): Missing prerequisite or simulated transient upload failure.

    Returns:
        None: Uploads never rebuild packages, disclose the token, or start with an incomplete release.
    """
    environment = dict(
        os.environ,
        PATH=f"{publication}{os.pathsep}{os.environ['PATH']}",
        POETRY_PYPI_TOKEN_PYPI="" if failure == "token" else "test-token-never-print",
        RELEASE_TAG="" if failure == "tag" else "v0.1.0",
        RETRY_BACKOFF_SECONDS="0",
        RETRY_ATTEMPTS="2",
        SIMULATE_RETRY=str(failure == "retry").lower(),
    )

    # Both halves of a release must exist before its first upload, even when one artifact would otherwise succeed.
    if failure in {"wheel", "sdist"}:
        filename = "resumeme-0.1.0-py3-none-any.whl" if failure == "wheel" else "resumeme-0.1.0.tar.gz"
        (publication / "dist" / filename).unlink()

    result = subprocess.run(
        ["bash", "scripts/release/publish-package.sh"], cwd=publication, env=environment, capture_output=True, text=True, check=False
    )
    calls = (publication / "calls").read_text().splitlines() if (publication / "calls").exists() else []
    successful = failure in {"", "retry"}
    assert (result.returncode == 0) is successful
    assert "test-token-never-print" not in result.stdout + result.stderr
    assert not any("build" in call for call in calls)
    uploads = [call for call in calls if call.startswith("publish ")]
    assert len(uploads) == (2 if failure == "retry" else 1 if successful else 0)
