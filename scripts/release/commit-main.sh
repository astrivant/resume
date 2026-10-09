#!/usr/bin/env bash
# Publish this run's signed release payload to main without replacing newer source.
set -euo pipefail

: "${SOURCE_SHA:?Set SOURCE_SHA to the tagged source commit}"
: "${RELEASE_TAG:?Set RELEASE_TAG to the published release tag}"
: "${GH_TOKEN:?Set GH_TOKEN so the latest published release can be checked}"
artifact_dir="${1:-.cache/publication}"
artifacts=(resume.pdf resume.pdf.sig resume.pdf.sigstore.json cosign.pub key-fingerprint.txt source.json SHA256SUMS SHA256SUMS.sigstore.json)

# Bind every downloaded file to the selected source and tag before changing the checkout.
test "$(git rev-parse HEAD)" = "$SOURCE_SHA"
test "$(git rev-parse "refs/tags/$RELEASE_TAG^{commit}")" = "$SOURCE_SHA"
jq -e --arg source "$SOURCE_SHA" '.source_commit == $source' "$artifact_dir/source.json" >/dev/null

# Ignore reruns of a release once a newer release is published.
latest_tag="$(bash scripts/tooling/retry.sh gh release view --repo "$GITHUB_REPOSITORY" --json tagName --jq .tagName)"
if [[ "$latest_tag" != "$RELEASE_TAG" ]]; then
    echo "Skipping main publication: $RELEASE_TAG is no longer the latest release."
    exit 0
fi

# Copy the complete verified release set so the committed PDF remains independently verifiable.
for artifact in "${artifacts[@]}"; do
    test -s "$artifact_dir/$artifact"
    cp -- "$artifact_dir/$artifact" "$artifact"
done

git add -- "${artifacts[@]}"

# A retry after a successful push recognizes the exact tree and provenance instead of making a duplicate commit.
git fetch --no-tags origin main
main_sha="$(git rev-parse FETCH_HEAD)"
if [[ "$main_sha" != "$SOURCE_SHA" ]]; then
    message="$(git log -1 --format=%B "$main_sha")"
    parent="$(git rev-parse "$main_sha^")"
    if [[ "$parent" == "$SOURCE_SHA" && "$message" == *"Resumeme-Signed-Release: $RELEASE_TAG"* ]] &&
        [[ "$(git rev-parse "$main_sha^{tree}")" == "$(git write-tree)" ]]; then
        echo 'The identical signed resume and captured profile were already committed.'
        echo "published-sha=$main_sha" >>"$GITHUB_OUTPUT"
        exit 0
    fi

    echo 'Main advanced while the signed payload was being prepared; skipping publication.'
    exit 0
fi

# The signed commit uses the same marker as routine PDF publication to avoid a redundant follow-up deploy.
git config user.name 'github-actions[bot]'
git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
commit_message="docs: publish signed resume from $RELEASE_TAG"
commit_message+=$'\n\nResumeme-Signed-Release: '
commit_message+="$RELEASE_TAG"
commit_message+=$'\nResumeme-Source-SHA: '
commit_message+="$SOURCE_SHA"

if [[ "${RESUME_PUBLISH_USES_TOKEN:-false}" == true ]]; then
    commit_message+=$'\nResumeme-Publication: true'
fi

git commit -m "$commit_message"
bash scripts/tooling/retry.sh git push origin HEAD:refs/heads/main
echo "published-sha=$(git rev-parse HEAD)" >>"$GITHUB_OUTPUT"
