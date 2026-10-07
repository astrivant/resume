"""
Prepare optional Codex inputs for trusted main-branch CI without reading the API key.
"""

from __future__ import annotations

import os
from pathlib import Path

from resumeme.codex.request import prepare_summary
from resumeme.compiler.asts.profile import load_profile
from resumeme.config import load_config, project_path

root = Path.cwd()
config = load_config(root / "resumeme.config.yaml")
enabled = config.codex.enabled and os.environ.get("GENERATE_SUMMARY") == "true"

# Only the action receives the credential; this setup step sees its presence as a boolean.
if enabled:
    if os.environ.get("OPENAI_KEY_CONFIGURED") != "true":
        raise ValueError("codex.enabled requires the OPENAI_API_KEY repository secret. Configure it in Actions secrets.")

    profile = load_profile(project_path(root, config.output.profile), config.linkedin.username)
    prepare_summary(profile, config, root)

with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
    output.write(f"enabled={str(enabled).lower()}\nmodel={config.codex.model or ''}\n")
