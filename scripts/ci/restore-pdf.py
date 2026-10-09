"""
Restore a verified unsigned build and stage its configured output.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from resumeme.config import load_config, project_path
from resumeme.github.company_artifacts import restore_companies

# Resolve the destination from this source commit's config, while consuming the stable cross-job artifact filename.
config = load_config(Path("resumeme.config.yaml"))
artifact = Path(".cache/publication/resume.pdf")
release_files = (
    "resume.pdf.sig",
    "resume.pdf.sigstore.json",
    "cosign.pub",
    "key-fingerprint.txt",
    "source.json",
    "SHA256SUMS",
    "SHA256SUMS.sigstore.json",
)

if not artifact.read_bytes().startswith(b"%PDF-"):
    raise ValueError("The downloaded artifact is not a PDF.")

destination = project_path(Path.cwd(), config.output.pdf)
companies = restore_companies(Path.cwd(), config, artifact.parent)
destination.parent.mkdir(parents=True, exist_ok=True)
shutil.copyfile(artifact, destination)

# New branch builds are unsigned, so remove any tracked signatures that would no longer match the replaced PDF.
subprocess.run(["git", "rm", "--ignore-unmatch", "--", *release_files], check=True)

# Restrict the bot commit to explicit generated PDFs; cached source text and incidental files are not publication inputs.
subprocess.run(["git", "add", "--", config.output.pdf, *companies], check=True)
