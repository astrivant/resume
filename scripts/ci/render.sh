#!/usr/bin/env bash
# Render the exact summary artifact selected for the PDF build before TeXtidote inspects the document.
set -euo pipefail

summary_args=()

if [[ "${USE_CODEX_SUMMARY:-false}" == true ]]; then
    summary_args+=(--summary .cache/codex/summary.json)
fi

poetry run resumeme render "${summary_args[@]}"
poetry run python scripts/ci/prepare-textidote.py
