"""
Reconcile the two public ownership lines without rewriting personal About text.
"""

from __future__ import annotations

import os
import re
import subprocess
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from resumeme.exceptions import SigningError

if TYPE_CHECKING:
    from pathlib import Path

    from resumeme.config import Ownership

__all__ = ["ownership_block", "reconcile_about", "release_destination"]

_REPOSITORY = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+")
_FINGERPRINT = re.compile(r"SHA256:[a-f0-9]{64}")
_MANAGED = re.compile(r"^resume signature: SHA256:[a-f0-9]{64}\r?\nreleases: https://[^\s]+$", re.MULTILINE)
_LABEL = re.compile(r"^(?:resume signature|releases):", re.MULTILINE | re.IGNORECASE)


def release_destination(settings: Ownership, root: Path, *, allow_missing: bool = False) -> str:
    """
    Resolve the fork's release URL without inferring repository ownership from a profile name.

    Args:
        settings (Ownership): Repository override and optional user-managed short link.
        root (Path): Checkout used to discover origin outside Actions.
        allow_missing (bool): Permit ordinary local builds without a configured repository or installed Git.

    Returns:
        str: HTTPS destination, or an empty string when discovery is optional and no repository exists.

    Raises:
        SigningError: No GitHub repository can be identified or the URL is unsafe for plain text.
    """

    # A supplied short link is an explicit destination; no shortening service or credential is required.
    if settings.releases_url is not None:
        location = urlsplit(settings.releases_url)

        if (
            location.scheme != "https"
            or not location.hostname
            or location.username is not None
            or location.password is not None
            or any(character.isspace() or ord(character) < 32 for character in settings.releases_url)
        ):
            raise SigningError("linkedin.ownership.releases_url must be an HTTPS URL without credentials or whitespace.")

        return settings.releases_url

    repository = settings.repository or os.environ.get("GITHUB_REPOSITORY")

    if not repository:
        # Installed builds can run without Git; publishing still requires an explicit or discoverable destination.
        try:
            result = subprocess.run(
                ["git", "-C", str(root), "remote", "get-url", "origin"], capture_output=True, text=True, check=False, timeout=10
            )
        except FileNotFoundError:
            repository = ""
        else:
            origin = result.stdout.strip()
            match = re.fullmatch(r"(?:git@github\.com:|https://github\.com/|ssh://git@github\.com/)([^\s]+)", origin)
            repository = match.group(1).removesuffix(".git") if result.returncode == 0 and match else ""

    if not repository and allow_missing:
        return ""

    if not _REPOSITORY.fullmatch(repository) or repository.split("/")[-1] in {".", ".."}:
        raise SigningError("Set linkedin.ownership.repository to OWNER/REPO, or configure a GitHub origin remote.")

    return f"https://github.com/{repository}/releases"


def ownership_block(fingerprint: str, releases_url: str) -> str:
    """
    Format a signing identity using the same fingerprint shown on releases.

    Args:
        fingerprint (str): Canonical DER SHA-256 public key fingerprint.
        releases_url (str): Validated one-line HTTPS release destination.

    Returns:
        str: Two public lines containing no authentication or private key material.

    Raises:
        SigningError: The fingerprint does not match the canonical release format.
    """
    if not _FINGERPRINT.fullmatch(fingerprint):
        raise SigningError("Expected a SHA256 fingerprint of the public key's DER encoding.")

    return f"resume signature: {fingerprint}\nreleases: {releases_url}"


def reconcile_about(current: str, block: str) -> str:
    """
    Append or replace one recognized ownership block, retaining all surrounding text.

    Args:
        current (str): Fresh text read from LinkedIn's About editor.
        block (str): New two-line ownership block.

    Returns:
        str: Complete replacement text, identical on repeat runs with the same identity.

    Raises:
        SigningError: Existing ownership labels are incomplete, duplicated, or manually reformatted.
    """
    matches = list(_MANAGED.finditer(current))
    labels = list(_LABEL.finditer(current))

    # Stop on ambiguous edits rather than deleting a paragraph that merely resembles our managed block.
    if labels and (len(matches) != 1 or len(labels) != 2):
        raise SigningError(
            "About contains ambiguous ownership lines. Keep exactly one 'resume signature:' / 'releases:' pair or remove it."
        )

    if matches:
        match = matches[0]
        return current[: match.start()] + block + current[match.end() :]

    separator = "" if not current or current.endswith("\n\n") else "\n" if current.endswith("\n") else "\n\n"
    return current + separator + block
