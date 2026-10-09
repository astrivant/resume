#!/usr/bin/env bash
# Compile and stage the configured PDF and preview for publication.
set -euo pipefail

# Match the independently built package version when rendering a tagged resume, retaining locked dependencies.
bash scripts/release/package-version.sh

# A requested artifact must exist and validate; a missing file must never silently fall back to captured prose.
summary_args=()
if [[ "${USE_CODEX_SUMMARY:-false}" == true ]]; then
    summary_args+=(--summary .cache/codex/summary.json)
    summary_args+=(--company-summaries .cache/codex/companies)
fi

poetry run resumeme build "${summary_args[@]}"
poetry run python scripts/ci/resume/stage-pdf.py

# Personal fork landing pages travel with the exact PDF that passed this build.
poetry run python scripts/ci/publication/readme-artifact.py stage
