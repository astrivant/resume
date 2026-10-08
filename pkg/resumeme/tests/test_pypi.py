"""
Verify PyPI release boundaries and transient retries without accessing credentials or a registry.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tomllib
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

    (tmp_path / "pyproject.toml").write_text('[project]\nname = "resumeme"\nversion = "0.1.0"\nrequires-python = ">=3.13"\n')
    shutil.copyfile(repository / "poetry.lock", tmp_path / "poetry.lock")
    (tmp_path / "package-version").write_text("0.1.0\n")
    poetry = tmp_path / "poetry"
    poetry.write_text(
        "#!/usr/bin/env bash\n"
        'printf "%s\\n" "$*" >> calls\n'
        'if [[ "$*" == "version --short" ]]; then cat package-version; exit 0; fi\n'
        'if [[ "$1" == "version" ]]; then printf "%s\\n" "$2" > package-version; exit 0; fi\n'
        'if [[ "$*" != "publish --no-interaction --skip-existing" ]]; then exit 64; fi\n'
        'if [[ "${SIMULATE_RETRY:-false}" == true && ! -e failed-once ]]; then\n'
        '    touch failed-once; echo "HTTP 503 Service Unavailable" >&2; exit 1\n'
        "fi\n"
    )
    poetry.chmod(0o700)
    return tmp_path


@pytest.mark.parametrize(
    "tag,expected",
    [
        ("", "0.1.0"),
        ("v0.0.2", "0.0.2"),
        ("v0.2.0", "0.2.0"),
        ("v0.2.0rc1", "0.2.0rc1"),
        ("v0.2.0b1.dev2", "0.2.0b1.dev2"),
        ("v0.2.0.post1", "0.2.0.post1"),
        ("resume-snapshot", None),
        ("vpatch", None),
        ("v0.2", None),
        ("v0.2.0garbage", None),
        ("v0.1.0; exit 0", None),
        ("v0.1.0\ntouch injected", None),
    ],
)
def test_release_tag_sets_package_metadata(publication: Path, tag: str, expected: str | None) -> None:
    """
    Apply tag versions with real Poetry while preserving dependencies and rejecting invalid input.

    Args:
        publication (Path): Isolated project metadata and the actual release script.
        tag (str): Optional version tag passed through an environment variable.
        expected (str | None): Expected distribution version, or None when validation must fail.

    Returns:
        None: Tags control package metadata; branch builds, invalid tags, and the dependency lock remain unchanged.
    """
    original = (publication / "pyproject.toml").read_bytes()
    lock = (publication / "poetry.lock").read_bytes()

    # Keep the real Poetry on PATH to check its metadata rewrite rather than reproducing it in a stub.
    result = subprocess.run(
        ["bash", "scripts/release/package-version.sh"],
        cwd=publication,
        env=dict(os.environ, RELEASE_TAG=tag),
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is (expected is not None), result.stderr
    metadata = tomllib.loads((publication / "pyproject.toml").read_text())
    assert metadata["project"]["version"] == (expected or "0.1.0")
    assert (publication / "poetry.lock").read_bytes() == lock
    assert not (publication / "calls").exists()
    assert not (publication / "injected").exists()

    if expected is not None:
        assert result.stdout.strip() == expected

    if not tag or expected is None:
        assert (publication / "pyproject.toml").read_bytes() == original


@pytest.mark.parametrize("version", ["0.0.2", "0.2.0rc1"])
@pytest.mark.parametrize("failure", ["", "token", "tag", "wheel", "sdist", "wrong-version", "retry"])
def test_pypi_upload_requires_complete_verified_release(publication: Path, failure: str, version: str) -> None:
    """
    Require credentials and both distributions before publishing, then safely retry transport failures.

    Args:
        publication (Path): Isolated release root with synthetic distributions.
        failure (str): Missing prerequisite or simulated transient upload failure.
        version (str): Stable or prerelease version differing from the committed metadata.

    Returns:
        None: Uploads never rebuild packages, disclose the token, or start with an incomplete release.
    """
    environment = dict(
        os.environ,
        PATH=f"{publication}{os.pathsep}{os.environ['PATH']}",
        POETRY_PYPI_TOKEN_PYPI="" if failure == "token" else "test-token-never-print",
        RELEASE_TAG="" if failure == "tag" else f"v{version}",
        RETRY_BACKOFF_SECONDS="0",
        RETRY_ATTEMPTS="2",
        SIMULATE_RETRY=str(failure == "retry").lower(),
    )

    # Publication consumes the tag's built artifacts, not an older pair matching the source checkout's version.
    if failure != "wrong-version":
        for artifact in (publication / "dist").iterdir():
            artifact.rename(artifact.with_name(artifact.name.replace("0.1.0", version)))

    # Both halves of a release must exist before its first upload, even when one artifact would otherwise succeed.
    if failure in {"wheel", "sdist"}:
        filename = f"resumeme-{version}-py3-none-any.whl" if failure == "wheel" else f"resumeme-{version}.tar.gz"
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

    if successful:
        assert calls[:2] == [f"version {version}", "version --short"]
