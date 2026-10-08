"""
Transfer only the captured profile and its referenced media between verified CI stages.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from resumeme.compiler.asts.profile import load_profile
from resumeme.config import load_config, project_path

if TYPE_CHECKING:
    from collections.abc import Iterator

    from resumeme.compiler.asts.profile import Entry, Media


def entry_images(entries: list[Entry]) -> Iterator[Media]:
    """
    Include nested role previews when collecting the snapshot's owned media.

    Args:
        entries (list[Entry]): Captured entries with optional nested positions.

    Yields:
        Media: Every referenced image, including children of company groups.
    """
    for entry in entries:
        yield from entry.images
        yield from entry_images(entry.positions)


def transfer(mode: str, root: Path) -> None:
    """
    Export, restore, or stage a complete capture using configured paths and an explicit file allowlist.

    Args:
        mode (str): Export to job storage, restore from it, or stage restored inputs in Git.
        root (Path): Checkout containing resumeme.config.yaml.

    Returns:
        None: The requested files are copied or staged; browser sessions and diagnostics remain local.

    Raises:
        ValueError: Capture is incomplete, a media reference escapes the configured assets directory, or a file is missing.
    """
    config = load_config(root / "resumeme.config.yaml")
    artifact = root / ".cache/refresh"
    snapshot = project_path(root, config.output.profile)
    assets = project_path(root, config.output.assets)
    profile = load_profile(artifact / "profile.json" if mode == "restore" else snapshot, config.linkedin.username)

    if profile.warnings:
        raise ValueError("A profile refresh cannot publish an incomplete profile: " + "; ".join(profile.warnings))

    # The profile owns the file list; incidental assets, Firefox state, and diagnostic pages are never transferred.
    pairs = {(snapshot, artifact / "profile.json")}
    images = [*profile.images, *(image for section in profile.sections for image in entry_images(section.entries))]

    for image in images:
        if not image.path:
            raise ValueError("A captured image has no downloaded file.")

        path = project_path(root, image.path)

        if not path.is_relative_to(assets):
            raise ValueError("Captured media must reside under output.assets.")

        pairs.add((path, project_path(artifact, str(Path("assets") / path.relative_to(assets)))))

    # Validate the complete transfer before copying anything, so a missing media file cannot produce a partial publication.
    for local, stored in pairs:
        source = stored if mode == "restore" else local

        if not source.is_file() or source.is_symlink():
            raise ValueError(f"Missing captured input: {source}")

    if mode == "stage":
        subprocess.run(["git", "add", "--", *(str(local.relative_to(root)) for local, _ in sorted(pairs))], cwd=root, check=True)
        return

    for local, stored in sorted(pairs):
        source, destination = (stored, local) if mode == "restore" else (local, stored)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)


def main() -> None:
    """
    Select the transfer operation used by the calling CI stage.

    Returns:
        None: Requested profile transfer is complete.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("export", "restore", "stage"))
    args = parser.parse_args()
    transfer(args.mode, Path.cwd())


if __name__ == "__main__":
    main()
