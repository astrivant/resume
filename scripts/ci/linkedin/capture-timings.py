"""
Transfer encrypted traversal feedback between pipeline runs, including different tags.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import subprocess
import zipfile
from pathlib import Path

import cattrs
from attrs import asdict

from resumeme.config import load_config
from resumeme.exceptions import SessionCacheError
from resumeme.linkedin.capture.timings import decode_timings, encode_timings
from resumeme.linkedin.session.cache import CacheKeys, open_archive, seal_archive

_TIMINGS = Path(".cache/capture/timings.json")
_ENCRYPTED = Path(".cache/capture-timings/timings.bin")


def restore(repository: str, name: str, keys: CacheKeys, context: bytes) -> None:
    """
    Restore the newest compatible feedback artifact without depending on tag-scoped caches.

    Args:
        repository (str): Current GitHub owner/repository.
        name (str): Opaque artifact name bound to the capture configuration and encryption key.
        keys (CacheKeys): Dedicated session-cache encryption identity.
        context (bytes): Expected repository, owner, browser, and runner context.

    Returns:
        None: Validated feedback is written locally, or a cold start is reported.

    Raises:
        subprocess.CalledProcessError: GitHub cannot list or download artifacts.
        SessionCacheError: The artifact fails authentication or decryption.
        ValueError: The decrypted timing model is invalid.
    """
    _TIMINGS.unlink(missing_ok=True)

    # Artifact lookup works across release tags; only the latest nonexpired artifact from another run is eligible.
    run_id = int(os.environ["GITHUB_RUN_ID"])
    query = f".artifacts | map(select(.expired == false and .workflow_run.id != {run_id})) | max_by(.created_at) | .id // empty"
    artifact_id = subprocess.run(
        [
            "gh",
            "api",
            "--method",
            "GET",
            f"repos/{repository}/actions/artifacts",
            "-f",
            f"name={name}",
            "-f",
            "per_page=100",
            "--jq",
            query,
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    ).stdout.strip()

    if not artifact_id:
        print("No previous capture timings; using the original profile-size distribution.")
        return

    # Read a single named member in memory; never extract an externally supplied ZIP into the checkout.
    archive = subprocess.run(
        ["gh", "api", f"repos/{repository}/actions/artifacts/{int(artifact_id)}/zip"],
        check=True,
        capture_output=True,
        timeout=60,
    ).stdout

    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        if bundle.getinfo("timings.bin").file_size > 1024 * 1024:
            raise ValueError("Capture timing artifact exceeds the 1 MiB limit.")

        timings = decode_timings(open_archive(bundle.read("timings.bin"), keys, context))

    _TIMINGS.parent.mkdir(parents=True, exist_ok=True)
    _TIMINGS.write_bytes(encode_timings(timings))
    print("Restored previous complete traversal timings for history-based adaptive scheduling.")


def main() -> None:
    """
    Restore feedback before planning or encrypt fresh feedback after validated aggregation.

    Returns:
        None: Only encrypted timing feedback is selected for cross-run artifact upload.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("restore", "seal"))
    args = parser.parse_args()
    config = load_config(Path("resumeme.config.yaml"))
    keys = CacheKeys.from_pem(
        os.environ["RESUMEME_CACHE_PRIVATE_KEY"].encode(),
        os.environ["RESUMEME_CACHE_PUBLIC_KEY"].encode(),
        os.environ.get("RESUMEME_CACHE_KEY_PASSWORD", "").encode() or None,
    )
    repository = os.environ["GITHUB_REPOSITORY"]

    # Compare actual browser work under the same settings and runner class; login and startup are excluded from observations.
    scope = {
        "version": 1,
        "repository": repository.casefold(),
        "username": config.linkedin.username.casefold(),
        "capture": asdict(config.capture),
        "runner": os.environ["CAPTURE_RUNNER"],
        "key": keys.fingerprint(),
    }
    context = json.dumps(scope, sort_keys=True).encode()
    name = "resumeme-capture-timings-v1-" + hashlib.sha256(context).hexdigest()

    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        output.write(f"artifact-name={name}\n")

    if args.command == "restore":
        try:
            restore(repository, name, keys, context)
        except (
            OSError,
            ValueError,
            KeyError,
            subprocess.SubprocessError,
            zipfile.BadZipFile,
            cattrs.BaseValidationError,
            SessionCacheError,
        ):
            # Feedback is advisory. Do not expose downloaded bytes, authentication material, or API error bodies in logs.
            _TIMINGS.unlink(missing_ok=True)
            print("::warning::Previous capture timings unavailable or invalid; using profile-size estimates.")
    else:
        timings = decode_timings(_TIMINGS.read_bytes())
        _ENCRYPTED.parent.mkdir(parents=True, exist_ok=True)
        _ENCRYPTED.write_bytes(seal_archive(encode_timings(timings), keys, context))
        print("Encrypted the latest complete traversal timings for the next pipeline run.")


if __name__ == "__main__":
    main()
