"""
Validate one matrix response and stage its canonical bundle for downstream consumers.
"""

from __future__ import annotations

import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

from resumeme.codex.companies import load_company
from resumeme.compiler.asts.profile import load_profile
from resumeme.compiler.asts.summary import load_summary
from resumeme.compiler.passes.context import resolve_dates
from resumeme.compiler.passes.summary import summary_digest
from resumeme.config import company_config, load_config, project_path

root = Path.cwd()
config = load_config(root / "resumeme.config.yaml")
profile = load_profile(project_path(root, config.output.profile), config.linkedin.username)
key = os.environ.get("SUMMARY_COMPANY", "")
target = next((item for item in config.codex.companies if item.key == key), None)

if key and target is None:
    raise ValueError("The selected company/job is absent from this source configuration.")

relative = f"companies/{key}" if target else ""
directory = project_path(root, f".cache/codex/{relative}")
company = load_company(directory / "company.json", target) if target else None
settings = resolve_dates(company_config(config, target, root=root) if target else config, today=datetime.now(UTC).date())
load_summary(
    directory / "summary.json", username=profile.username, source_digest=summary_digest(profile, settings, company), settings=settings.codex
)

# Transfer only validated JSON. Prompts and incidental runner state do not belong in the response artifact.
output = project_path(root, f".cache/summary-result/{relative}")
output.mkdir(parents=True, exist_ok=True)
shutil.copyfile(directory / "summary.json", output / "summary.json")

if company:
    shutil.copyfile(directory / "company.json", output / "company.json")
