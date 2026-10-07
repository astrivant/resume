#!/usr/bin/env bash
# Execute the same locked quality checks locally and in GitHub Actions.
set -euo pipefail

# Use the same hooks developers run locally so CI does not maintain a second lint or schema-validation policy.
poetry run pre-commit run --all-files --show-diff-on-failure

# Use the shared pytest-xdist worker settings and combine coverage from every worker into the CI report.
poetry run pytest --cov --cov-report=term-missing --cov-report=xml:.cache/coverage/coverage.xml
