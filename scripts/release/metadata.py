"""
Record immutable build provenance and the public key's DER SHA-256 fingerprint.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import quote

from resumeme.compiler.backends.latex.compilation import tex_image
from resumeme.compiler.backends.pdf import release_footer
from resumeme.config import Ownership
from resumeme.linkedin.identity import release_destination
from resumeme.signing import public_key_fingerprint

directory = Path(sys.argv[1])

# Fingerprint the canonical key encoding so PEM line wrapping cannot change the identity shown in release notes.
fingerprint = public_key_fingerprint(directory / "cosign.pub")
(directory / "key-fingerprint.txt").write_text(f"{fingerprint}\n", encoding="utf-8")

# Link the actual publishing repository and tag, independent of an optional About short link or local repository override.
repository = os.environ["GITHUB_REPOSITORY"]
tag = os.environ["RELEASE_TAG"]

if not tag:
    raise ValueError("RELEASE_TAG must identify the release being signed.")

releases = release_destination(Ownership(repository=repository), Path.cwd())
release_url = f"{releases}/tag/{quote(tag, safe='')}"
pdf = directory / "resume.pdf"
pending = directory / "resume.pending.pdf"
pending.write_bytes(release_footer(pdf.read_bytes(), release_url, fingerprint))
pending.replace(pdf)

# Bind provenance to immutable source and compiler references instead of mutable branch names or image tags.
metadata = {
    "source_commit": os.environ["SOURCE_SHA"],
    "tex_image": tex_image(),
    "public_key_sha256_der": fingerprint.removeprefix("SHA256:"),
    "release_url": release_url,
}
(directory / "source.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
