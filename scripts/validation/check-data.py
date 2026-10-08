"""
Validate packaged schemas and any owner snapshot present in this checkout.
"""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from resumeme.compiler.asts.profile import load_profile
from resumeme.compiler.backends.latex.compilation import tex_image
from resumeme.config import load_config, project_path

# Check the schemas themselves before trusting them to validate this checkout's config and snapshot.
for schema_path in Path("pkg/resumeme/compiler/asts/resources").glob("*.schema.json"):
    Draft202012Validator.check_schema(json.loads(schema_path.read_text(encoding="utf-8")))

# Docker and installed Python clients must not drift onto different TeX distributions during dependency updates.
if f"FROM {tex_image()} AS texlive" not in Path("Dockerfile").read_text(encoding="utf-8").splitlines():
    raise ValueError("Dockerfile and pkg/resumeme/compiler/backends/latex/resources/toolchain.json must pin the same TeX image.")

# Validate the copyable base independently; its placeholder username must never be compared with the owner's snapshot.
load_config(Path("resumeme.config.ref.yaml"))

configuration = load_config(Path("resumeme.config.yaml"))
snapshot = project_path(Path.cwd(), configuration.output.profile)

# A fresh fork can validate its setup before first capture; an existing snapshot must also pass ownership validation.
if snapshot.exists():
    load_profile(snapshot, configuration.linkedin.username)
else:
    print("Configuration is valid; no local profile snapshot yet. Run `resumeme capture` before building.")
