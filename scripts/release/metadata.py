"""
Record immutable build provenance and the public key's DER SHA-256 fingerprint.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from resume.latex.compilation import tex_image

directory = Path(sys.argv[1])
# Fingerprint the canonical key encoding so PEM line wrapping cannot change the identity shown in release notes.
public_der = subprocess.run(
    ["openssl", "pkey", "-pubin", "-in", str(directory / "cosign.pub"), "-outform", "DER"],
    capture_output=True,
    check=True,
).stdout
fingerprint = hashlib.sha256(public_der).hexdigest()
(directory / "key-fingerprint.txt").write_text(f"SHA256:{fingerprint}\n", encoding="utf-8")
# Bind provenance to immutable source and compiler references instead of mutable branch names or image tags.
metadata = {"source_commit": os.environ["SOURCE_SHA"], "tex_image": tex_image(), "public_key_sha256_der": fingerprint}
(directory / "source.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
