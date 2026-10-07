#!/usr/bin/env bash
# Resolve Python from this checkout, ignoring unrelated active environments.
set -euo pipefail
cd "$(dirname "$0")/../.."

# Prefer the checkout's interpreter even if a caller has activated an unrelated Python environment.
if [[ -x .venv/bin/python ]]; then
    exec .venv/bin/python "$@"
fi

unset VIRTUAL_ENV PYENV_VERSION PYENV_VIRTUAL_ENV
exec poetry run python "$@"
