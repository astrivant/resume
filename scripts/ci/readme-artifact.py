"""
Stage or restore the fork's personal README alongside its verified PDF artifact.
"""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

from resumeme.config import load_config
from resumeme.github.readme import personal_readme, restore_readme, stage_readme

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("command", choices=("stage", "restore"))
arguments = parser.parse_args()
root = Path.cwd()
config = load_config(root / "resumeme.config.yaml")
enabled = personal_readme(config, os.environ.get("RESUMEME_REPOSITORY_FORK") == "true")

# Both stages resolve the same source config and event flag; missing fork artifacts fail instead of retaining inherited branding.
if enabled:
    if arguments.command == "stage":
        stage_readme(root, config, os.environ.get("GITHUB_REPOSITORY", ""))
    else:
        paths = restore_readme(root, config)
        subprocess.run(["git", "add", "--", *paths], check=True)

# Publish uses this explicit result to keep coffee-stain branding only for project READMEs.
print("resume" if enabled else "project")
