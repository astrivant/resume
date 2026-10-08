"""
Prepare optional Codex inputs for main-branch or tag CI without reading the API key.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from resumeme.codex.companies import prepare_companies
from resumeme.codex.request import prepare_summary
from resumeme.compiler.asts.profile import load_profile
from resumeme.config import load_config, project_path
from resumeme.telemetry import logging_context

root = Path.cwd()
config = load_config(root / "resumeme.config.yaml")
enabled = config.codex.enabled and os.environ.get("GENERATE_SUMMARY") == "true"
matrix = [{"key": "generic", "company": "", "directory": ".cache/codex"}]

# Only the action receives the credential; this setup step sees its presence as a boolean.
if enabled:
    if os.environ.get("OPENAI_KEY_CONFIGURED") != "true":
        raise ValueError("codex.enabled requires the OPENAI_API_KEY repository secret. Configure it in Actions secrets.")

    profile = load_profile(project_path(root, config.output.profile), config.linkedin.username)

    # Employer requests use the same stdout diagnostics and verbosity as local CLI commands.
    with logging_context(os.environ.get("RESUMEME_LOG_LEVEL") or config.logging.level):
        prepare_summary(profile, config, root)
        prepare_companies(profile, config, root)

    # Matrix keys are artifact-safe; prompt paths and compiler outputs retain the readable company/job hierarchy.
    matrix.extend(
        {
            "key": "company-" + hashlib.sha256(target.key.encode("utf-8")).hexdigest()[:16],
            "company": target.key,
            "directory": f".cache/codex/companies/{target.key}",
        }
        for target in config.codex.companies
    )

with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
    output.write(f"enabled={str(enabled).lower()}\nmodel={config.codex.model or ''}\n")
    output.write(f"effort={config.codex.reasoning_effort or ''}\n")
    output.write("matrix=" + json.dumps({"include": matrix}) + "\n")
