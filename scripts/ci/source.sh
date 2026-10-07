#!/usr/bin/env bash
# Bind every reusable pipeline stage to the checked-out source commit.
set -euo pipefail
echo "sha=$(git rev-parse HEAD)" >>"$GITHUB_OUTPUT"
