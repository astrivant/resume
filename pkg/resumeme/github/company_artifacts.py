"""
Transfer only the configured employer PDFs between CI build and repository publication.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from typing import TYPE_CHECKING

from resumeme.codex.companies import company_config
from resumeme.config import project_path
from resumeme.exceptions import PublicationError

if TYPE_CHECKING:
    from pathlib import Path

    from resumeme.config import Config

__all__ = ["restore_companies", "stage_companies"]


def stage_companies(root: Path, config: Config, artifact: Path, *, generated: bool) -> None:
    """
    Stage fresh variants with hashes, without discovering arbitrary PDFs or stale cached summaries.

    Args:
        root (Path): Source checkout after successful compilation.
        config (Config): Exact configuration used by the build.
        artifact (Path): Existing publication artifact directory.
        generated (bool): Whether this build explicitly consumed the generated summary matrix.

    Returns:
        None: A complete manifest and its selected PDFs are written under the publication artifact.

    Raises:
        PublicationError: A selected output is not a PDF.
    """
    files: list[dict[str, str]] = []

    for target in config.codex.companies if generated else []:
        relative = company_config(config, target).output.pdf
        content = project_path(root, relative).read_bytes()

        if not content.startswith(b"%PDF-"):
            raise PublicationError(f"The company output is not a PDF: {relative}")

        destination = project_path(artifact, relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        files.append({"key": target.key, "sha256": hashlib.sha256(content).hexdigest()})

    artifact.mkdir(parents=True, exist_ok=True)
    (artifact / "single-origin.json").write_text(json.dumps({"generated": generated, "files": files}, indent=2) + "\n", encoding="utf-8")


def restore_companies(root: Path, config: Config, artifact: Path) -> list[str]:
    """
    Validate the entire transferred target set before restoring any file for the bot commit.

    Args:
        root (Path): Checkout receiving the verified PDF set.
        config (Config): Source revision's company/job targets.
        artifact (Path): Downloaded publication artifact.

    Returns:
        list[str]: Explicit repository-relative PDF paths to stage with Git.

    Raises:
        PublicationError: Manifest entries, PDF headers, or content digests do not match the configured target set.
    """
    manifest = artifact / "single-origin.json"

    # Old generic-only artifacts remain valid for repositories with no company variants configured.
    if not manifest.is_file() and not config.codex.companies:
        return []

    raw: object = json.loads(manifest.read_text(encoding="utf-8"))

    if not isinstance(raw, dict) or set(raw) != {"generated", "files"} or not isinstance(raw["generated"], bool):
        raise PublicationError("Invalid single-origin publication manifest.")

    entries = raw["files"]
    expected = {target.key: company_config(config, target).output.pdf for target in config.codex.companies} if raw["generated"] else {}

    if not isinstance(entries, list) or len(entries) != len(expected):
        raise PublicationError("The company PDF artifact is incomplete.")

    selected: list[str] = []

    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"key", "sha256"} or not isinstance(entry["key"], str):
            raise PublicationError("Invalid company PDF manifest entry.")

        relative = expected.pop(entry["key"], None)

        if relative is None:
            raise PublicationError("The company PDF artifact includes an unknown or repeated target.")

        content = project_path(artifact, relative).read_bytes()

        if not content.startswith(b"%PDF-") or hashlib.sha256(content).hexdigest() != entry["sha256"]:
            raise PublicationError(f"The company PDF artifact failed verification: {relative}")

        selected.append(relative)

    # Only known PDFs cross the publication boundary; employer text, prompts, and incidental files stay in CI artifacts.
    for relative in selected:
        destination = project_path(root, relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(project_path(artifact, relative), destination)

    return selected
