#!/usr/bin/env bash
# Install from the committed lockfile; CI must never resolve new versions.
set -euo pipefail
python -m pip install --disable-pip-version-check poetry==2.1.3
export POETRY_VIRTUALENVS_IN_PROJECT=true
export POETRY_KEYRING_ENABLED=false
export POETRY_INSTALLER_RE_RESOLVE=false
poetry check --lock
if [[ "${DEPENDENCY_GROUPS:-main,dev}" == main ]]; then
    poetry install --only main --no-interaction --no-ansi
else
    poetry install --with dev --no-interaction --no-ansi
fi
