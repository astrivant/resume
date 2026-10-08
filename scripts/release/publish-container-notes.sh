#!/usr/bin/env bash
# Reconcile container instructions after registry publication; retry this script to recover uncertain GitHub responses.
set -euo pipefail
: "${RELEASE_TAG:?Set RELEASE_TAG to the published Git tag}"
: "${IMAGE_TAGS:?Set IMAGE_TAGS to the successfully published registry references}"
notes=$(mktemp)
trap 'rm -f "$notes"' EXIT

# Re-read release state on every retry so a successful create or edit with a lost response cannot duplicate the section.
exists=true

if body=$(gh release view "$RELEASE_TAG" --json body --jq .body 2>"$notes"); then
    :
else
    error=$(cat "$notes")

    if [[ "$error" != *'release not found'* && "$error" != *'HTTP 404'* ]]; then
        printf '%s\n' "$error" >&2
        exit 1
    fi

    exists=false
    body=''
fi

# Use Docker metadata's exact references, including any normalized tag characters and the full source-commit alias.
begin='<!-- resume:container:start -->'
end='<!-- resume:container:end -->'
section=$(
    printf '%s\n\n## Container image\n\n' "$begin"
    printf 'Pull the tested image using any published reference (linux/amd64):\n\n```bash\n'

    while IFS= read -r reference; do
        [[ -n "$reference" ]] || continue
        printf 'docker pull --platform linux/amd64 %s\n' "$reference"
    done <<<"$IMAGE_TAGS"

    printf '```\n\n%s\n' "$end"
)

# Replace only our managed section, retaining manually written notes and signing instructions on either side.
if [[ "$body" == *"$begin"*"$end"* ]]; then
    updated="${body%%"$begin"*}${section}${body#*"$end"}"
elif [[ "$body" == *"$begin"* || "$body" == *"$end"* ]]; then
    echo 'Container release-note markers are incomplete; repair them before retrying.' >&2
    exit 1
elif [[ -n "$body" ]]; then
    updated=$(printf '%s\n\n%s' "$body" "$section")
else
    updated="$section"
fi

if [[ "$exists" == true && "$body" == "$updated" ]]; then
    exit 0
fi

printf '%s\n' "$updated" >"$notes"

# Editing notes preserves assets and draft status; new container releases do not displace the latest signed PDF release.
if [[ "$exists" == true ]]; then
    gh release edit "$RELEASE_TAG" --notes-file "$notes"
else
    gh release create "$RELEASE_TAG" --verify-tag --latest=false --title "$RELEASE_TAG" --notes-file "$notes"
fi
