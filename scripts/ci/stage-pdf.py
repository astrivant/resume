"""
Stage the configured PDF at a stable artifact path shared by build and deploy.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from resumeme.config import load_config, project_path

# Decouple user-configurable output paths from the artifact name expected by signing and deploy stages.
config = load_config(Path("resumeme.config.yaml"))
artifact = Path(".cache/publication/resume.pdf")
artifact.parent.mkdir(parents=True, exist_ok=True)
shutil.copyfile(project_path(Path.cwd(), config.output.pdf), artifact)
