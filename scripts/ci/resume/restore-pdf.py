"""
Restore a verified unsigned build and stage its configured output.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from resumeme.config import load_config, project_path
from resumeme.github.companies.artifacts import restore_companies

# Resolve the destination from this source commit's config, while consuming the stable cross-job artifact filename.
config = load_config(Path("resumeme.config.yaml"))
artifact = Path(".cache/publication/resume.pdf")
release_names = (
    "resume.pdf",
    "resume.pdf.sig",
    "resume.pdf.sigstore.json",
    "cosign.pub",
    "key-fingerprint.txt",
    "source.json",
    "SHA256SUMS",
    "SHA256SUMS.sigstore.json",
)
release_files = (*(f"output/release/{name}" for name in release_names), *release_names[1:])

if not artifact.read_bytes().startswith(b"%PDF-"):
    raise ValueError("The downloaded artifact is not a PDF.")

destination = project_path(Path.cwd(), config.output.pdf)
companies = restore_companies(Path.cwd(), config, artifact.parent)
destination.parent.mkdir(parents=True, exist_ok=True)
shutil.copyfile(artifact, destination)

# Remove the generated bundle and legacy root sidecars; unrelated files under output/ remain untouched.
subprocess.run(["git", "rm", "--ignore-unmatch", "--", *release_files], check=True)

# Restrict the bot commit to explicit generated PDFs; cached source text and incidental files are not publication inputs.
subprocess.run(["git", "add", "--", config.output.pdf, *companies], check=True)
