"""
Restore the verified artifact to the configured destination and stage only that file.
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

if not artifact.read_bytes().startswith(b"%PDF-"):
    raise ValueError("The downloaded artifact is not a PDF.")

destination = project_path(Path.cwd(), config.output.pdf)
companies = restore_companies(Path.cwd(), config, artifact.parent)
destination.parent.mkdir(parents=True, exist_ok=True)
shutil.copyfile(artifact, destination)

# Restrict the bot commit to explicit generated PDFs; cached source text and incidental files are not publication inputs.
subprocess.run(["git", "add", "--", config.output.pdf, *companies], check=True)
