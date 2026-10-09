"""
Verify authenticated cross-tag timing feedback without GitHub or LinkedIn access.
"""

from __future__ import annotations

import io
import runpy
import subprocess
import sys
import zipfile
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from cryptography.hazmat.primitives.asymmetric import rsa

from resumeme.linkedin.capture.feedback import TimingFeedback
from resumeme.linkedin.capture.timings import CaptureTimings, decode_timings, encode_timings
from resumeme.linkedin.session.cache import CacheKeys
from resumeme.tests.paths import REPOSITORY_ROOT

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch


def test_encrypted_feedback_round_trip_and_invalid_cache_fallback(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Transport timing state as ciphertext and fall back to cold planning when the envelope is tampered with.

    Args:
        tmp_path (Path): Isolated runner checkout and feedback files.
        monkeypatch (MonkeyPatch): Supplies synthetic keys and mocked GitHub artifact responses.

    Returns:
        None: Only ciphertext is uploaded, state round-trips intact, and invalid history is discarded.
    """
    script = REPOSITORY_ROOT / "scripts/ci/linkedin/capture-timings.py"
    monkeypatch.chdir(tmp_path)
    (tmp_path / "resumeme.config.yaml").write_text("linkedin: {username: example-person}\n")
    private = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    keys = CacheKeys(private, private.public_key())
    monkeypatch.setattr(CacheKeys, "from_pem", lambda *args: keys)

    for name, value in {
        "RESUMEME_CACHE_PRIVATE_KEY": "fixture",
        "RESUMEME_CACHE_PUBLIC_KEY": "fixture",
        "GITHUB_OUTPUT": str(tmp_path / "output"),
        "GITHUB_REPOSITORY": "example/resume",
        "GITHUB_RUN_ID": "42",
        "CAPTURE_RUNNER": '["ubuntu-24.04"]',
    }.items():
        monkeypatch.setenv(name, value)

    path = tmp_path / ".cache/capture/timings.json"
    path.parent.mkdir(parents=True)
    timings = CaptureTimings("example-person", "firefox", {"detail:skills": 50.0}, feedback={"detail:skills": TimingFeedback(45, 5, 2, 3)})
    path.write_bytes(encode_timings(timings))
    monkeypatch.setattr(sys, "argv", [str(script), "seal"])
    runpy.run_path(str(script), run_name="__main__")
    ciphertext = (tmp_path / ".cache/capture-timings/timings.bin").read_bytes()
    assert b"example-person" not in ciphertext
    assert b"detail:skills" not in ciphertext
    path.unlink()

    # Simulate the artifact API's ZIP without extracting arbitrary paths to disk.
    data = io.BytesIO()

    with zipfile.ZipFile(data, "w") as bundle:
        bundle.writestr("timings.bin", ciphertext)

    api = MagicMock(side_effect=[subprocess.CompletedProcess([], 0, "123\n"), subprocess.CompletedProcess([], 0, data.getvalue())])
    monkeypatch.setattr(subprocess, "run", api)
    monkeypatch.setattr(sys, "argv", [str(script), "restore"])
    runpy.run_path(str(script), run_name="__main__")
    assert decode_timings(path.read_bytes()) == timings
    query = api.call_args_list[0].args[0]
    assert "name=resumeme-capture-timings-v1-" in " ".join(query)
    assert ".workflow_run.id != 42" in query[-1]
    assert "max_by(.created_at)" in query[-1]

    damaged = io.BytesIO()

    with zipfile.ZipFile(damaged, "w") as bundle:
        bundle.writestr("timings.bin", ciphertext[:-1] + bytes([ciphertext[-1] ^ 1]))

    api.side_effect = [subprocess.CompletedProcess([], 0, "123\n"), subprocess.CompletedProcess([], 0, damaged.getvalue())]
    runpy.run_path(str(script), run_name="__main__")
    assert not path.exists()

    # A missing artifact and an API failure both remain optional cold starts, including on a fresh runner.
    api.side_effect = [subprocess.CompletedProcess([], 0, "")]
    runpy.run_path(str(script), run_name="__main__")
    assert not path.exists()
    api.side_effect = subprocess.CalledProcessError(1, ["gh", "api"])
    runpy.run_path(str(script), run_name="__main__")
    assert not path.exists()
