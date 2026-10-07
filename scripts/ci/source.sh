#!/usr/bin/env bash
# Bind every reusable pipeline stage to the checked-out source commit.
set -euo pipefail
refresh="${REFRESH_PROFILE:-false}"

# LinkedIn credentials are used only for scheduled or explicitly requested refreshes of main.
if [[ "$refresh" == true && ("$GITHUB_REF" != refs/heads/main || ! "$GITHUB_EVENT_NAME" =~ ^(schedule|workflow_dispatch)$) ]]; then
    echo 'Profile refresh requires main and either the monthly schedule or a manual refresh request.' >&2
    exit 1
fi

echo "sha=$(git rev-parse HEAD)" >>"$GITHUB_OUTPUT"
echo "refresh=$refresh" >>"$GITHUB_OUTPUT"
