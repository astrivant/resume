#!/usr/bin/env bash
# Record package-manager boundaries without accessing registries or altering the developer's environment.
set -euo pipefail
printf '%s %s\n' "${0##*/}" "$*" >>"$SETUP_CALLS"

if [[ "${0##*/}" == poetry && "${1:-}" == check && "${SETUP_LOCK_VALID:-true}" != true ]]; then
    exit 1
fi
