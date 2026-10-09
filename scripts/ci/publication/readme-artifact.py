"""
Stage or restore the fork's personal README alongside its verified PDF artifact.
"""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

from resumeme.config import load_config, project_path
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

# An alternate Markdown output leaves the root project README and its coffee branding active.
replaces_readme = enabled and project_path(root, config.readme.output) == (root / "README.md").resolve()
print("resume" if replaces_readme else "project")
