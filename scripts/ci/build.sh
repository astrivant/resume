#!/usr/bin/env bash
# Build distributable packages and stage the configured PDF for publication.
set -euo pipefail
# Build distributable code and the configured document before handing a stable PDF path to the signing stage.
poetry build
poetry run resume build
poetry run python scripts/ci/stage-pdf.py
