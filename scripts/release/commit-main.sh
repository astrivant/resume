#!/usr/bin/env bash
# Publish this run's signed release payload on top of the latest main commit.
set -euo pipefail

: "${SOURCE_SHA:?Set SOURCE_SHA to the tagged source commit}"
: "${RELEASE_TAG:?Set RELEASE_TAG to the published release tag}"
: "${GH_TOKEN:?Set GH_TOKEN so the latest published release can be checked}"
artifact_dir="${1:-.cache/publication}"
release_dir=output/release
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

# Keep the signed manifest and its inputs together without changing their signed bytes or relative filenames.
mkdir -p "$release_dir"
release_paths=()

for artifact in "${artifacts[@]}"; do
    test -s "$artifact_dir/$artifact"
    cp -- "$artifact_dir/$artifact" "$release_dir/$artifact"
    release_paths+=("$release_dir/$artifact")
done

# The root PDF remains the public entry point; migrate legacy sidecars out of the root on the next tag publication.
cp -- "$artifact_dir/resume.pdf" resume.pdf
git rm --ignore-unmatch -- "${artifacts[@]:1}"
git add -- resume.pdf "${release_paths[@]}"

# Preserve exactly the generated files staged by this verified tag, including its fresh profile and media.
staged_tree="$(git write-tree)"
mapfile -d '' -t generated_paths < <(git diff --cached --name-only -z)

# Include unchanged bundle members: a newer unsigned main may have removed a key that matches the tagged source.
generated_paths+=(resume.pdf "${release_paths[@]}" "${artifacts[@]:1}")

# The tag source must remain part of main history; unrelated rewrites require review instead of an automatic overlay.
git fetch --no-tags origin main

for attempt in 1 2 3; do
    main_sha="$(git rev-parse FETCH_HEAD)"

    if ! git merge-base --is-ancestor "$SOURCE_SHA" "$main_sha"; then
        echo 'The tagged source is no longer an ancestor of main; refusing to publish across divergent history.' >&2
        exit 1
    fi

    # Keep a newer project README intact; otherwise update its preview with this tag's fresh PDF.
    overlay_paths=()

    for path in "${generated_paths[@]}"; do
        if [[ "${README_MODE:-project}" == project && "$path" == README.md ]] &&
            ! git diff --quiet "$SOURCE_SHA" "$main_sha" -- README.md; then
            continue
        fi

        overlay_paths+=("$path")
    done

    if ((${#overlay_paths[@]} == 0)); then
        echo 'No generated release files remain eligible for publication.' >&2
        exit 1
    fi

    # A retry after a successful push sees the same release files and returns the accepted main commit.
    if git diff --quiet "$main_sha" "$staged_tree" -- "${overlay_paths[@]}"; then
        echo 'The verified release payload is already present on main.'
        echo "published-sha=$main_sha" >>"$GITHUB_OUTPUT"
        exit 0
    fi

    # Start from the latest main tree, then overlay only the files produced by this verified release.
    git reset --hard "$main_sha"

    for path in "${overlay_paths[@]}"; do
        if git cat-file -e "$staged_tree:$path" 2>/dev/null; then
            git checkout "$staged_tree" -- "$path"
        else
            git rm --ignore-unmatch -- "$path"
        fi
    done

    if git diff --cached --quiet; then
        echo 'The verified release payload is already present on main.'
        echo "published-sha=$main_sha" >>"$GITHUB_OUTPUT"
        exit 0
    fi

    # The signed commit marker prevents a token-triggered branch run from publishing these files again.
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

    if bash scripts/tooling/retry.sh git push origin HEAD:refs/heads/main; then
        echo "published-sha=$(git rev-parse HEAD)" >>"$GITHUB_OUTPUT"
        exit 0
    fi

    # Re-fetch after a rejected push and rebuild the same generated-file overlay on the new branch head.
    if ((attempt < 3)); then
        echo "Main changed during publication; retrying the signed payload on its new head (attempt $((attempt + 1))/3)."
        git fetch --no-tags origin main
    fi
done

echo 'Could not publish the verified release after three attempts against main.' >&2
exit 1
