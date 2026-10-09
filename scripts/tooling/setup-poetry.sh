#!/usr/bin/env bash
# Restore a dedicated Poetry runtime without mixing build tooling into resumeme's dependencies.
set -euo pipefail

if [[ "${POETRY_CACHE_HIT:-false}" != true || ! -x "$POETRY_ENVIRONMENT/bin/poetry" ]]; then
    python -m venv "$POETRY_ENVIRONMENT"
    "$POETRY_ENVIRONMENT/bin/python" -m pip install --disable-pip-version-check "poetry==$POETRY_VERSION"
fi

# Verify the restored executable before sharing it with later steps in this job.
"$POETRY_ENVIRONMENT/bin/poetry" --version
printf '%s\n' "$POETRY_ENVIRONMENT/bin" >>"$GITHUB_PATH"
printf '%s\n' \
    'POETRY_VIRTUALENVS_IN_PROJECT=true' \
    'POETRY_KEYRING_ENABLED=false' \
    'POETRY_INSTALLER_RE_RESOLVE=false' >>"$GITHUB_ENV"
