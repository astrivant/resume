"""
Record immutable build provenance and the public key's DER SHA-256 fingerprint.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from resumeme.compiler.backends.latex.compilation import tex_image
from resumeme.signing import public_key_fingerprint

directory = Path(sys.argv[1])

# Fingerprint the canonical key encoding so PEM line wrapping cannot change the identity shown in release notes.
fingerprint = public_key_fingerprint(directory / "cosign.pub")
(directory / "key-fingerprint.txt").write_text(f"{fingerprint}\n", encoding="utf-8")

# Bind provenance to immutable source and compiler references instead of mutable branch names or image tags.
metadata = {
    "source_commit": os.environ["SOURCE_SHA"],
    "tex_image": tex_image(),
    "public_key_sha256_der": fingerprint.removeprefix("SHA256:"),
}
(directory / "source.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
