"""
Stage the configured PDF at a stable artifact path shared by build and deploy.
"""

from __future__ import annotations

import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

from resumeme.config import load_config, project_path
from resumeme.github.company_artifacts import stage_companies

# Decouple user-configurable output paths from the artifact name expected by signing and deploy stages.
config = load_config(Path("resumeme.config.yaml"))
artifact = Path(".cache/publication/resume.pdf")
source = project_path(Path.cwd(), config.output.pdf)

if not source.read_bytes().startswith(b"%PDF-"):
    raise ValueError("The build did not produce a valid PDF for publication.")

artifact.parent.mkdir(parents=True, exist_ok=True)
shutil.copyfile(source, artifact)

# Use the completed PDF's timestamp even if staging crosses midnight; deploy retries retain this artifact-owned UTC date.
brewed_on = datetime.fromtimestamp(source.stat().st_mtime, UTC).date()
artifact.with_name("brew-date.txt").write_text(brewed_on.isoformat() + "\n", encoding="ascii")
stage_companies(Path.cwd(), config, artifact.parent, generated=os.environ.get("USE_CODEX_SUMMARY") == "true")
