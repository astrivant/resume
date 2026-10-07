"""
Validate packaged schemas and any owner snapshot present in this checkout.
"""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from resume.config import load_config, project_path
from resume.models import load_profile

for schema_path in Path("pkg/resume/resources").glob("*.schema.json"):
    Draft202012Validator.check_schema(json.loads(schema_path.read_text(encoding="utf-8")))
configuration = load_config(Path("resume.reference.yaml"))
snapshot = project_path(Path.cwd(), configuration.output.profile)
if snapshot.exists():
    load_profile(snapshot, configuration.linkedin.username)
else:
    print("Configuration is valid; no local profile snapshot yet. Run `resume capture` before building.")
