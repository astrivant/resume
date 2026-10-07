#!/usr/bin/env bash
# Reconcile a draft after uncertain network outcomes so creation can safely be retried.
set -euo pipefail
tag="$1"
notes="$2"
if result=$(gh release view "$tag" --json isDraft --jq .isDraft 2>&1); then
    if [[ "$result" != true ]]; then
        echo 'The release is already public; refusing to replace its assets.' >&2
        exit 1
    fi
    exit 0
fi
if [[ "$result" != *'release not found'* && "$result" != *'HTTP 404'* ]]; then
    printf '%s\n' "$result" >&2
    exit 1
fi
gh release create "$tag" --draft --target "$PUBLISHED_SHA" \
    --title "Resume ${SOURCE_SHA:0:12}" --notes-file "$notes"
