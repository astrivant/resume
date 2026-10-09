"""
Verify encrypted browser-state reuse, archive boundaries, and SSH-based secret setup without live services.
"""

from __future__ import annotations

import io
import os
import signal
import subprocess
import sys
import tarfile
from typing import TYPE_CHECKING

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from resumeme.exceptions import SessionCacheError
from resumeme.linkedin.retrying import is_retryable_linkedin_exit_status
from resumeme.linkedin.session_cache import CacheKeys, archive_profile, open_archive, restore_profile, seal_archive
from resumeme.tests.paths import REPOSITORY_ROOT

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch

_ROOT = REPOSITORY_ROOT


@pytest.mark.parametrize(
    ("status", "expected"),
    [(75, True), (-signal.SIGABRT, True), (-signal.SIGBUS, True), (-signal.SIGSEGV, True), (2, False), (-signal.SIGTERM, False)],
)
def test_retry_classifier_accepts_only_transient_exit_types(status: int, expected: bool) -> None:
    """
    Retry only the explicit transient browser code and driver crash signals, never cancellation.

    Args:
        status (int): Child process result, negative for signal termination.
        expected (bool): Expected classification.

    Returns:
        None: Failure classification is deterministic and independent of runner state.
    """
    assert is_retryable_linkedin_exit_status(status) is expected


@pytest.fixture(scope="module")
def keys() -> CacheKeys:
    """
    Generate one synthetic cache identity per test worker.

    Returns:
        CacheKeys: RSA-3072 encryption and authentication keys used only for temporary test data.
    """
    private = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    return CacheKeys(private, private.public_key())


def _secrets(keys: CacheKeys) -> dict[str, str]:
    """
    Serialize a synthetic identity as the three Actions secrets.

    Args:
        keys (CacheKeys): In-memory test identity.

    Returns:
        dict[str, str]: Encrypted private PEM, public PEM, and the test-only decryption password.
    """
    return {
        "RESUMEME_CACHE_PRIVATE_KEY": keys.private.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.BestAvailableEncryption(b"synthetic-password")
        ).decode(),
        "RESUMEME_CACHE_PUBLIC_KEY": keys.public.public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode(),
        "RESUMEME_CACHE_KEY_PASSWORD": "synthetic-password",
    }


def test_session_cache_namespaces_are_separate_for_firefox_and_chrome(tmp_path: Path, keys: CacheKeys) -> None:
    """
    Give each browser engine its own encrypted Actions cache key and restore prefix.

    Args:
        tmp_path (Path): Isolated config checkouts and output files.
        keys (CacheKeys): Synthetic Actions cache encryption identity.

    Returns:
        None: Firefox and Chrome prepare distinct cache paths while preserving the same key fingerprint.
    """
    prepared: dict[str, str] = {}

    for browser in ("firefox", "chrome"):
        checkout = tmp_path / browser
        checkout.mkdir()
        (checkout / "resumeme.config.yaml").write_text(
            f"linkedin: {{username: example-person}}\ncapture: {{browser: {browser}}}\n", encoding="utf-8"
        )
        output = checkout / "github-output.txt"
        environment = {
            **os.environ,
            **_secrets(keys),
            "GITHUB_OUTPUT": str(output),
            "GITHUB_REPOSITORY": "example/resumeme",
            "GITHUB_RUN_ID": "123",
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_JOB": "capture-bootstrap",
        }
        result = subprocess.run(
            [sys.executable, str(_ROOT / "scripts/ci/linkedin-session.py"), "prepare"],
            cwd=checkout,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stdout + result.stderr
        prepared[browser] = output.read_text(encoding="utf-8")

    assert "resumeme-session-v2-firefox-" in prepared["firefox"]
    assert "resumeme-session-v2-chrome-" in prepared["chrome"]
    assert prepared["firefox"] != prepared["chrome"]


def test_envelope_is_randomized_authenticated_and_context_bound(keys: CacheKeys) -> None:
    """
    Protect both confidentiality and cache provenance instead of accepting arbitrary public-key ciphertext.

    Args:
        keys (CacheKeys): Synthetic key pair.

    Returns:
        None: Round trips succeed and mutations, wrong owners, and forged signatures are rejected.
    """
    data, context = b"private-session-cookie", b"owner/repo|profile|firefox|Linux"
    encrypted = seal_archive(data, keys, context)
    assert data not in encrypted and encrypted != seal_archive(data, keys, context)
    assert open_archive(encrypted, keys, context) == data

    for damaged in (b"", encrypted[:-1], encrypted[:-1] + bytes([encrypted[-1] ^ 1]), encrypted[:80] + b"x" + encrypted[81:]):
        with pytest.raises(SessionCacheError):
            open_archive(damaged, keys, context)

    with pytest.raises(SessionCacheError, match="authentication failed"):
        open_archive(encrypted, keys, b"another/profile")


def test_pem_password_and_key_correspondence_are_checked(keys: CacheKeys) -> None:
    """
    Reject incorrect passwords, mismatched keys, and weak RSA identities before caching starts.

    Args:
        keys (CacheKeys): Valid cache identity.

    Returns:
        None: Only the complete matching strong PEM pair is accepted.
    """
    secrets = _secrets(keys)
    private, public = (secrets[name].encode() for name in ("RESUMEME_CACHE_PRIVATE_KEY", "RESUMEME_CACHE_PUBLIC_KEY"))
    assert CacheKeys.from_pem(private, public, b"synthetic-password").fingerprint() == keys.fingerprint()

    with pytest.raises(SessionCacheError, match="Cannot read"):
        CacheKeys.from_pem(private, public, b"wrong-password")

    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    wrong = other.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)

    with pytest.raises(SessionCacheError, match="must match"):
        CacheKeys.from_pem(private, wrong, b"synthetic-password")


def test_profile_archive_excludes_links_and_runtime_files(tmp_path: Path, keys: CacheKeys) -> None:
    """
    Restore regular profile state while excluding browser locks and disposable caches.

    Args:
        tmp_path (Path): Private temporary profile roots.
        keys (CacheKeys): Cache identity.

    Returns:
        None: Nested cookies survive an encrypted round trip and unrelated files never enter the archive.
    """
    source = tmp_path / "source"
    source.mkdir()
    (source / "cookies.sqlite").write_bytes(b"cookie-value")
    (source / "lock").write_text("runtime lock")
    (source / "link").symlink_to(tmp_path)
    (source / "cache2").mkdir()
    (source / "cache2/entry").write_text("disposable")
    (source / "storage").mkdir()
    (source / "storage/session").write_text("session-value")
    destination = tmp_path / "restored"
    restore_profile(open_archive(seal_archive(archive_profile(source), keys, b"context"), keys, b"context"), destination)
    assert (destination / "cookies.sqlite").read_bytes() == b"cookie-value"
    assert (destination / "storage/session").read_text() == "session-value"
    assert {path.name for path in destination.iterdir()} == {"cookies.sqlite", "storage"}
    assert (destination / "cookies.sqlite").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("name,kind", [("../escape", "file"), ("/escape", "file"), ("link", "link"), ("file", "duplicate")])
def test_unsafe_archive_is_rejected_before_extraction(tmp_path: Path, name: str, kind: str) -> None:
    """
    Reject traversal, links, and duplicate members even in an authenticated archive.

    Args:
        tmp_path (Path): Empty extraction workspace.
        name (str): Unsafe archive name.
        kind (str): Member behavior under test.

    Returns:
        None: Validation fails before any file or directory is extracted.
    """
    buffer = io.BytesIO()

    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        member = tarfile.TarInfo(name)

        if kind == "link":
            member.type, member.linkname = tarfile.SYMTYPE, "../escape"

        archive.addfile(member)

        if kind == "duplicate":
            archive.addfile(member)

    with pytest.raises(SessionCacheError, match="unsafe archive"):
        restore_profile(buffer.getvalue(), tmp_path / "profile")

    assert list(tmp_path.iterdir()) == []


def test_job_wrapper_reuses_only_ciphertext_and_cleans_failed_runs(tmp_path: Path, keys: CacheKeys) -> None:
    """
    Carry an encrypted session across separate checkouts and keep the accepted cache intact after command failure.

    Args:
        tmp_path (Path): Simulated runner, checkouts, and persistent encrypted-cache directory.
        keys (CacheKeys): Synthetic Actions secrets.

    Returns:
        None: Plaintext exists only during the command, child processes receive no cache keys, and failure cannot overwrite the cache.
    """
    binary, runner = tmp_path / "bin", tmp_path / "runner"
    binary.mkdir()
    runner.mkdir()
    command = binary / "resumeme"
    command.write_text(
        f"#!{sys.executable}\nfrom __future__ import annotations\nimport os\nfrom pathlib import Path\n"
        "assert not any(name.startswith('RESUMEME_CACHE_') for name in os.environ)\n"
        "profile = Path(os.environ['RESUMEME_BROWSER_STATE_DIR']) / 'firefox'\n"
        "if os.environ.get('EXPECT_RESTORED'): assert (profile / 'cookies.sqlite').read_bytes() == b'private-cookie'\n"
        "profile.mkdir(parents=True, exist_ok=True)\n(profile / 'cookies.sqlite').write_bytes(b'private-cookie')\n"
        "raise SystemExit(int(os.environ.get('COMMAND_EXIT', '0')))\n"
    )
    command.chmod(0o700)
    environment = {
        **os.environ,
        **_secrets(keys),
        "PATH": str(binary) + os.pathsep + os.environ["PATH"],
        "RUNNER_TEMP": str(runner),
        "GITHUB_REPOSITORY": "example/resumeme",
        "RESUMEME_SESSION_CACHE_DIR": str(tmp_path / "ciphertext"),
    }

    for index, status in enumerate((0, 0, 2)):
        checkout = tmp_path / f"checkout-{index}"
        checkout.mkdir()
        (checkout / "resumeme.config.yaml").write_text("linkedin: {username: example-person}\n")
        environment["COMMAND_EXIT"] = str(status)

        if index == 1:
            environment["RESUMEME_SESSION_CACHE_READ_ONLY"] = "true"
        else:
            environment.pop("RESUMEME_SESSION_CACHE_READ_ONLY", None)

        if index:
            environment["EXPECT_RESTORED"] = "true"

        before = {path: path.read_bytes() for path in (tmp_path / "ciphertext").glob("*.bin")}
        result = subprocess.run(
            [sys.executable, str(_ROOT / "scripts/ci/linkedin-session.py"), "run"],
            cwd=checkout,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == status, result.stdout + result.stderr
        assert list(runner.iterdir()) == []
        assert not (checkout / ".cache/firefox").exists()
        after = {path: path.read_bytes() for path in (tmp_path / "ciphertext").glob("*.bin")}
        assert len(after) == 1 and all(b"private-cookie" not in data for data in after.values())

        if status:
            assert after == before

        if index == 1:
            assert after == before


@pytest.mark.parametrize(
    ("command_name", "statuses", "expected_status", "expected_attempts"),
    [
        ("capture", (75, 0), 0, 2),
        ("capture-plan", (75, 0), 0, 2),
        ("capture-shard", (75, 75, 0), 0, 3),
        ("publish-ownership", (75, 75, 0), 0, 3),
        ("publish-resume", (75, 75, 75, 75), 75, 4),
        ("publish-skills", (2, 0), 2, 1),
    ],
)
def test_linkedin_commands_retry_only_classified_failures_with_fresh_sessions(
    tmp_path: Path,
    keys: CacheKeys,
    command_name: str,
    statuses: tuple[int, ...],
    expected_status: int,
    expected_attempts: int,
) -> None:
    """
    Retry transient LinkedIn reads and writes three times at most with a new session for every attempt.

    Args:
        tmp_path (Path): Disposable checkout, runner temp, fake executable, and attempt counter.
        keys (CacheKeys): Synthetic pair required by distributed capture commands.
        command_name (str): LinkedIn command run through the encrypted-session wrapper.
        statuses (tuple[int, ...]): Exit status returned by the fake LinkedIn client on each invocation.
        expected_status (int): Final wrapper status after successful recovery or retry exhaustion.
        expected_attempts (int): Number of complete command sessions expected.

    Returns:
        None: Every LinkedIn command retries transient status 75, while permanent status 2 exits immediately.
    """
    binary, runner, checkout = tmp_path / "bin", tmp_path / "runner", tmp_path / "checkout"
    binary.mkdir()
    runner.mkdir()
    checkout.mkdir()
    counter = tmp_path / "attempts.txt"
    command = binary / "resumeme"
    command.write_text(
        f"#!{sys.executable}\nfrom pathlib import Path\nimport os\n"
        "counter = Path(os.environ['ATTEMPT_COUNTER'])\n"
        "attempt = int(counter.read_text()) + 1 if counter.exists() else 1\n"
        "counter.write_text(str(attempt))\n"
        "statuses = [int(value) for value in os.environ['ATTEMPT_STATUSES'].split(',')]\n"
        "raise SystemExit(statuses[min(attempt - 1, len(statuses) - 1)])\n"
    )
    command.chmod(0o700)
    (checkout / "resumeme.config.yaml").write_text(
        "linkedin: {username: example-person}\ncapture: {retry_backoff_seconds: 0, retry_max_backoff_seconds: 1}\n"
    )
    environment = {
        **os.environ,
        "PATH": str(binary) + os.pathsep + os.environ["PATH"],
        "RUNNER_TEMP": str(runner),
        "ATTEMPT_COUNTER": str(counter),
        "ATTEMPT_STATUSES": ",".join(str(status) for status in statuses),
        "RESUMEME_SESSION_CACHE_READ_ONLY": "true",
        **_secrets(keys),
    }

    if command_name == "capture-shard":
        environment["SESSION_SHARD_INDEX"] = "1"
        environment["SESSION_SHARD_COUNT"] = "6"

    result = subprocess.run(
        [sys.executable, str(_ROOT / "scripts/ci/linkedin-session.py"), "run", "--command", command_name],
        cwd=checkout,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == expected_status, result.stdout + result.stderr
    assert counter.read_text() == str(expected_attempts)
    assert list(runner.iterdir()) == []


def test_setup_script_generates_pem_and_uploads_secrets_without_printing_them(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Exercise real ssh-keygen and OpenSSL while replacing GitHub writes with private temporary files.

    Args:
        tmp_path (Path): Temporary backup, tools, and fake remote secret store.
        monkeypatch (MonkeyPatch): Isolates setup paths and replaces the GitHub CLI.

    Returns:
        None: The generated encrypted RSA PEM pair is valid, secrets are passed through stdin, and plaintext key files are removed.
    """
    binary, secrets = tmp_path / "bin", tmp_path / "secrets"
    binary.mkdir()
    secrets.mkdir()
    gh = binary / "gh"
    gh.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        "if [[ \"$1 $2\" == 'repo view' ]]; then echo example/resumeme;\n"
        "elif [[ \"$1 $2\" == 'secret set' && \"$4\" == '--repo' && \"$5\" == 'example/resumeme' ]]; then\n"
        'cat > "$FAKE_SECRET_STORE/$3";\nelse exit 3; fi\n'
    )
    gh.chmod(0o700)
    monkeypatch.setenv("PATH", str(binary) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("FAKE_SECRET_STORE", str(secrets))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    result = subprocess.run(
        ["bash", str(_ROOT / "scripts/ci/setup-session-cache.sh"), "--repo", "example/resumeme"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    loaded = CacheKeys.from_pem(
        (secrets / "RESUMEME_CACHE_PRIVATE_KEY").read_bytes(),
        (secrets / "RESUMEME_CACHE_PUBLIC_KEY").read_bytes(),
        (secrets / "RESUMEME_CACHE_KEY_PASSWORD").read_bytes(),
    )
    assert loaded.private.key_size == 3072
    assert "PRIVATE KEY" not in result.stdout + result.stderr
    assert not list((tmp_path / "data").rglob("plain.key*"))
