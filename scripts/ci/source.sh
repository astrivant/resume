#!/usr/bin/env bash
# Bind every reusable pipeline stage to the checked-out source commit.
set -euo pipefail
refresh="${REFRESH_PROFILE:-false}"

# Every tag captures live profile changes before building, even when no manual refresh flag was supplied.
if [[ "$GITHUB_EVENT_NAME" == push && "$GITHUB_REF" == refs/tags/* ]]; then
    refresh=true

# Branch captures remain restricted to scheduled or explicitly requested refreshes of main.
elif [[ "$refresh" == true && ("$GITHUB_REF" != refs/heads/main || ! "$GITHUB_EVENT_NAME" =~ ^(schedule|workflow_dispatch)$) ]]; then
    echo 'Profile refresh requires a tag push, or main with a scheduled or requested manual refresh.' >&2
    exit 1
fi

echo "sha=$(git rev-parse HEAD)" >>"$GITHUB_OUTPUT"
echo "refresh=$refresh" >>"$GITHUB_OUTPUT"
