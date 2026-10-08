"""
Share the canonical public signing identity between releases and LinkedIn.
"""

from __future__ import annotations

import hashlib
import subprocess
from typing import TYPE_CHECKING

from resumeme.exceptions import SigningError

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["public_key_fingerprint"]


def public_key_fingerprint(public_key: Path) -> str:
    """
    Hash a public key's canonical DER encoding independently of PEM formatting.

    Args:
        public_key (Path): Cosign public key PEM, never the private signing key.

    Returns:
        str: SHA256 followed by a colon and the lowercase hexadecimal digest.

    Raises:
        SigningError: OpenSSL cannot parse the supplied public key.
    """

    # Some OpenSSL-compatible implementations accept private PEMs despite -pubin; reject those before invoking the tool.
    lines = public_key.read_bytes().strip().splitlines()

    if not lines or lines[0] != b"-----BEGIN PUBLIC KEY-----" or lines[-1] != b"-----END PUBLIC KEY-----":
        raise SigningError("Expected a Cosign public key PEM, not a private key or fingerprint file.")

    # Match the encoding used in release provenance; textual PEM hashes change with line wrapping.
    result = subprocess.run(
        ["openssl", "pkey", "-pubin", "-in", str(public_key), "-outform", "DER"],
        capture_output=True,
        check=False,
        timeout=30,
    )

    if result.returncode:
        raise SigningError("Cannot read the Cosign public key; supply the release's cosign.pub file.")

    return "SHA256:" + hashlib.sha256(result.stdout).hexdigest()
