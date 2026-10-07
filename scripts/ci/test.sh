#!/usr/bin/env bash
# Execute the same locked quality checks locally and in GitHub Actions.
set -euo pipefail
poetry run pre-commit run --all-files --show-diff-on-failure
poetry run pytest --cov --cov-report=term-missing --cov-report=xml:.cache/coverage/coverage.xml
