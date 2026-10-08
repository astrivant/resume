"""
Prepare or validate a skill proposal for the exact tag being processed by Actions.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from resumeme.codex.skills import load_skill_suggestions, prepare_skills
from resumeme.compiler.asts.profile import load_profile
from resumeme.config import load_config, project_path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("command", choices=("prepare", "validate"))
arguments = parser.parse_args()
root = Path.cwd()
config = load_config(root / "resumeme.config.yaml")
enabled = config.codex.skills.enabled
tag = os.environ.get("RELEASE_TAG", "")

# Only a tag push can prepare material for the action, even when this script is invoked independently of its workflow.
if os.environ.get("GITHUB_EVENT_NAME") != "push" or not tag or os.environ.get("GITHUB_REF") != f"refs/tags/{tag}":
    raise ValueError("Skill proposal CI requires a matching tag-push event.")

if enabled:
    profile = load_profile(project_path(root, config.output.profile), config.linkedin.username)

    if arguments.command == "prepare":
        if os.environ.get("OPENAI_KEY_CONFIGURED") != "true":
            raise ValueError("codex.skills.enabled requires the OPENAI_API_KEY repository secret.")

        prepare_skills(profile, config, root, tag)
    else:
        load_skill_suggestions(root / ".cache/codex/skills/skills.json", profile, config, root, tag)

if arguments.command == "prepare":
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        output.write(f"enabled={str(enabled).lower()}\npublish={str(enabled and config.codex.skills.publish).lower()}\n")
        output.write(f"model={config.codex.model or ''}\n")
