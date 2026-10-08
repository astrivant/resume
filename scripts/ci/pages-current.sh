#!/usr/bin/env bash
# Skip superseded site artifacts after waiting for the shared Pages deployment slot.
set -euo pipefail

if [[ "$GITHUB_REF" != refs/heads/main || "$GITHUB_EVENT_NAME" == pull_request ]]; then
    echo 'Pages publication requires a main-branch run.' >&2
    exit 1
fi

# The built-in token needs only contents:read here; transient API failures use the shared bounded backoff.
current_sha="$(bash scripts/tooling/retry.sh gh api "repos/$GITHUB_REPOSITORY/git/ref/heads/main" --jq '.object.sha')"

if [[ "$current_sha" != "$PUBLISHED_SHA" ]]; then
    echo 'Main advanced after PDF publication; skipping the older site.'
    echo 'current=false' >>"$GITHUB_OUTPUT"
else
    echo 'current=true' >>"$GITHUB_OUTPUT"
fi
