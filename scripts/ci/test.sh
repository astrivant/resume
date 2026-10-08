#!/usr/bin/env bash
# Execute the same locked quality checks locally and in GitHub Actions.
set -euo pipefail

# CI runs checks once alongside the test matrix; the default retains the complete local verification command.
mode="${1:-all}"
if (($#)); then
    shift
fi
case "$mode" in
    all | checks | tests) ;;
    *)
        echo 'Usage: test.sh [all|checks|tests] [pytest arguments...]' >&2
        exit 64
        ;;
esac

# Use the same hooks developers run locally so CI does not maintain a second lint or schema-validation policy.
if [[ "$mode" != tests ]]; then
    poetry run pre-commit run --all-files --show-diff-on-failure
fi

# pytest-cov combines workers within a shard; Actions combines the shards' raw data before publishing the badge.
if [[ "$mode" != checks ]]; then
    poetry run pytest "$@" --cov --cov-report=term-missing --cov-report=xml:.cache/coverage/coverage.xml
fi
