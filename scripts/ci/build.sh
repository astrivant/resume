#!/usr/bin/env bash
# Build distributable packages and stage the configured PDF for publication.
set -euo pipefail
poetry build
poetry run resume build
poetry run python scripts/ci/stage-pdf.py
