#!/usr/bin/env bash
# Print the committed distribution version and reject version tags that disagree with it.
set -euo pipefail
version=$(poetry version --short)

# Ordinary branch builds need no release tag; tagged publication must identify this exact package version.
if [[ -n "${RELEASE_TAG:-}" && "$RELEASE_TAG" != "v$version" ]]; then
    echo "::error::Release tag must be v$version to match pyproject.toml. Update and commit the package version before tagging." >&2
    exit 1
fi

printf '%s\n' "$version"
