#!/usr/bin/env bash
# Build distributable packages and stage the configured PDF for publication.
set -euo pipefail

# Build distributable code and the configured document before handing a stable PDF path to the signing stage.
poetry build

# A requested artifact must exist and validate; a missing file must never silently fall back to captured prose.
summary_args=()
if [[ "${USE_CODEX_SUMMARY:-false}" == true ]]; then
    summary_args+=(--summary .cache/codex/summary.json)
fi

poetry run resumeme build "${summary_args[@]}"
poetry run python scripts/ci/stage-pdf.py
