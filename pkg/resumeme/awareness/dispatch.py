"""
Accept authenticated GitHub dispatches without executing code from the data branch.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from resumeme.awareness.bundle import validate_bundle
from resumeme.awareness.models import BUNDLE_PATH, MAX_BUNDLE_BYTES, selected_figures
from resumeme.config.loading import load_config, project_path
from resumeme.exceptions import PublicationError

if TYPE_CHECKING:
    from resumeme.config import Config


def receive(config: Config, root: Path, event: object, repository: str, actor: str) -> None:
    """
    Verify local opt-in, sender, immutable commit, and digest before replacing accepted input.

    Args:
        config (Config): Default-branch configuration controlling publication.
        root (Path): Trusted checkout, never the incoming data branch.
        event (object): GitHub-provided repository_dispatch event.
        repository (str): GitHub-provided destination owner/repository.
        actor (str): GitHub-provided authenticated triggering login.

    Returns:
        None: A complete verified bundle replaces data/awareness.json atomically.

    Raises:
        PublicationError: Authorization, event fields, transport, or digest verification fails.
    """
    if not config.awareness.enabled or actor.casefold() not in {name.casefold() for name in config.awareness.allowed_actors}:
        raise PublicationError("Awareness dispatch requires automation.awareness.enabled and an allowed GitHub actor.")

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+", repository):
        raise PublicationError("Invalid GitHub repository identity.")

    if not isinstance(event, dict) or event.get("action") != "witful-awareness":
        raise PublicationError("Expected a witful-awareness repository dispatch.")

    sender = event.get("sender")
    payload = event.get("client_payload")

    if not isinstance(sender, dict) or sender.get("login") != actor or not isinstance(payload, dict):
        raise PublicationError("Dispatch sender or payload is inconsistent with GitHub's event context.")

    if set(payload) != {"version", "commit", "sha256"} or type(payload.get("version")) is not int or payload["version"] != 1:
        raise PublicationError("Unsupported awareness dispatch schema.")

    commit, expected = payload["commit"], payload["sha256"]

    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise PublicationError("Awareness dispatch requires a full immutable Git commit.")

    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise PublicationError("Awareness dispatch requires a SHA-256 bundle digest.")

    # Repository, host, and data path come from trusted code/context, not from an arbitrary webhook URL.
    try:
        result = subprocess.run(
            [
                "gh",
                "api",
                "--hostname",
                "github.com",
                f"repos/{repository}/contents/awareness.json?ref={commit}",
                "-H",
                "Accept: application/vnd.github.raw+json",
                "-H",
                "X-GitHub-Api-Version: 2026-03-10",
            ],
            capture_output=True,
            timeout=90,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PublicationError("Could not retrieve the awareness bundle from GitHub; retry this job.") from error

    content = result.stdout

    if result.returncode or len(content) > MAX_BUNDLE_BYTES or hashlib.sha256(content).hexdigest() != expected:
        raise PublicationError("GitHub awareness download failed or its SHA-256 does not match the dispatch.")

    available = {figure.id for figure in validate_bundle(content)}

    if not set(selected_figures(config.appendices.awareness)) <= available:
        raise PublicationError("The pushed bundle lacks an enabled appendix figure; publish all enabled figures together.")

    target = project_path(root, BUNDLE_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = project_path(root, BUNDLE_PATH + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(target)


def main() -> None:
    """
    Consume only GitHub's dispatcher context in the existing main pipeline.

    Returns:
        None: The accepted figure input is written or the job fails visibly.
    """
    if os.environ.get("GITHUB_EVENT_NAME") != "repository_dispatch":
        raise PublicationError("Awareness receive runs only for repository_dispatch.")
    root = Path.cwd()
    receive(
        load_config(root / "resumeme.config.yaml"),
        root,
        json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text()),
        os.environ["GITHUB_REPOSITORY"],
        os.environ["GITHUB_ACTOR"],
    )
