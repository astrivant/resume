#!/usr/bin/env bash
# Install from the committed lockfile; CI must never resolve new versions.
set -euo pipefail

# Keep development tools out of runtime-only jobs and reject unsupported cache partitions before installing anything.
case "${DEPENDENCY_GROUPS:-main,dev}" in
    main | main,dev) ;;
    *)
        printf '%s\n' 'DEPENDENCY_GROUPS must be main or main,dev.' >&2
        exit 2
        ;;
esac

# Pin installation behavior as well as dependency versions; CI must consume the committed resolution without prompting for a keyring.
export POETRY_VIRTUALENVS_IN_PROJECT=true
export POETRY_KEYRING_ENABLED=false
export POETRY_INSTALLER_RE_RESOLVE=false
poetry check --lock

# Exact cache hits already contain the selected locked dependencies. The composite action binds the current source afterward.
if [[ "${PROJECT_CACHE_HIT:-false}" != true || ! -x .venv/bin/python ]]; then
    poetry sync --only "${DEPENDENCY_GROUPS:-main,dev}" --no-root --no-interaction --no-ansi
else
    printf '%s\n' 'Reusing cached project dependencies; lockfile validation passed.'
fi
