#!/usr/bin/env bash
# Retry idempotent network commands only when their output describes a transient failure.
set -euo pipefail
attempts="${RETRY_ATTEMPTS:-5}"
backoff="${RETRY_BACKOFF_SECONDS:-10}"
max_backoff="${RETRY_MAX_BACKOFF_SECONDS:-300}"
# Validate environment overrides before shell arithmetic or sleeping so malformed values fail immediately.
if [[ ! "$attempts" =~ ^[1-9][0-9]?$ || ! "$backoff" =~ ^[0-9]+$ || ! "$max_backoff" =~ ^[1-9][0-9]*$ || $# == 0 ]]; then
    echo 'Usage: RETRY_ATTEMPTS=5 RETRY_BACKOFF_SECONDS=10 RETRY_MAX_BACKOFF_SECONDS=300 retry.sh COMMAND [ARGS...]' >&2
    exit 2
fi
# Retain each command's combined diagnostics for classification, and replay them so failures remain visible in CI logs.
log=$(mktemp)
trap 'rm -f "$log"' EXIT
for ((attempt = 1; attempt <= attempts; attempt++)); do
    if "$@" >"$log" 2>&1; then
        cat "$log"
        exit 0
    else
        status=$?
    fi
    cat "$log" >&2
    message=$(tr '[:upper:]' '[:lower:]' <"$log")
    # Retry only recognized transport failures; invalid arguments, authorization errors, and failed verification need intervention.
    if [[ ! "$message" =~ (timeout|timed\ out|connection\ reset|connection\ refused|temporary\ failure|could\ not\ resolve|unexpected\ eof|http[^0-9]*(429|500|502|503|504)|tls\ handshake) ]]; then
        exit "$status"
    fi
    if ((attempt == attempts)); then
        exit "$status"
    fi
    # Cap before every sleep so increasing the initial delay cannot bypass the configured maximum.
    if ((backoff > max_backoff)); then backoff=$max_backoff; fi
    echo "Transient failure; retrying attempt $((attempt + 1))/$attempts in ${backoff}s." >&2
    sleep "$backoff"
    backoff=$((backoff * 2))
done
