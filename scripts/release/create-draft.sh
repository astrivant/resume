#!/usr/bin/env bash
# Reconcile a draft after uncertain network outcomes so creation can safely be retried.
set -euo pipefail
tag="$1"
notes="$2"

# A previous create request may have succeeded despite a lost response; reconcile server state before attempting another write.
if result=$(gh release view "$tag" --json isDraft --jq .isDraft 2>&1); then
    if [[ "$result" != true ]]; then
        echo 'The release is already public; refusing to replace its assets.' >&2
        exit 1
    fi

    exit 0
fi

# Only a confirmed missing release permits creation; propagate auth or transport failures to the retry policy.
if [[ "$result" != *'release not found'* && "$result" != *'HTTP 404'* ]]; then
    printf '%s\n' "$result" >&2
    exit 1
fi

gh release create "$tag" --draft --verify-tag \
    --title "Resume $tag" --notes-file "$notes"
