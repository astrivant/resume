"""
Extract the detached PDF signature and hash the complete release payload.
"""

from __future__ import annotations

import base64
import hashlib
import json
import sys
from pathlib import Path

directory = Path(sys.argv[1])
bundle = json.loads((directory / "resume.pdf.sigstore.json").read_text(encoding="utf-8"))

# Reuse the bundle's PDF signature for the detached attachment and reject malformed base64 before publishing it.
signature = bundle["messageSignature"]["signature"]
base64.b64decode(signature, validate=True)
(directory / "resume.pdf.sig").write_text(signature + "\n", encoding="ascii")

# Enumerate the payload explicitly: the manifest and its later signature must not recursively include themselves.
names = ["resume.pdf", "resume.pdf.sig", "resume.pdf.sigstore.json", "cosign.pub", "key-fingerprint.txt", "source.json"]
checksums = [f"{hashlib.sha256((directory / name).read_bytes()).hexdigest()}  {name}\n" for name in names]
(directory / "SHA256SUMS").write_text("".join(checksums), encoding="ascii")
