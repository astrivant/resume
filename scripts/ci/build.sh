#!/usr/bin/env bash
# Build distributable packages and stage the configured PDF for publication.
set -euo pipefail

# Apply the tag's package version before building the wheel and source archive, retaining locked dependencies.
bash scripts/release/package-version.sh

# Clean stale distributions before building the exact wheel and source archive that PyPI publication will consume.
poetry build --clean

# A requested artifact must exist and validate; a missing file must never silently fall back to captured prose.
summary_args=()
if [[ "${USE_CODEX_SUMMARY:-false}" == true ]]; then
    summary_args+=(--summary .cache/codex/summary.json)
    summary_args+=(--company-summaries .cache/codex/companies)
fi

poetry run resumeme build "${summary_args[@]}"
poetry run python scripts/ci/stage-pdf.py

# Personal fork landing pages travel with the exact PDF that passed this build.
poetry run python scripts/ci/readme-artifact.py stage
