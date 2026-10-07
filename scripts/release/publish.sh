#!/usr/bin/env bash
# Upload verified, signed artifacts to a draft release before making it public.
set -euo pipefail
artifact_dir="${1:-.cache/publication}"

# Verify again at the publication boundary, after artifacts have crossed job storage and download boundaries.
bash scripts/release/verify.sh "$artifact_dir"

# The caller selects an existing Git tag; releases never invent an automatic tag during monthly publication.
tag="${RELEASE_TAG:?Set RELEASE_TAG to the user-created Git tag}"
test "$(git rev-parse HEAD)" = "$SOURCE_SHA"
test "$(git rev-parse "refs/tags/$tag^{commit}")" = "$SOURCE_SHA"
notes="$RUNNER_TEMP/resume-release-notes.md"

{
    printf 'Resume selected from tag %s at commit %s.\n\n' "$tag" "$SOURCE_SHA"
    printf 'Signing key fingerprint (SHA-256 of DER public key): %s.\n\n' "$(cat "$artifact_dir/key-fingerprint.txt")"
    printf 'PDF SHA-256: %s.\n\n' "$(shasum -a 256 "$artifact_dir/resume.pdf" | cut -d ' ' -f 1)"
    printf 'Verify the fingerprint against a trusted copy of the signing key, then run:\n\n'
    printf '```bash\n'
    printf 'cosign verify-blob --key cosign.pub --bundle SHA256SUMS.sigstore.json SHA256SUMS\n'
    printf 'cosign verify-blob --key cosign.pub --bundle resume.pdf.sigstore.json resume.pdf\n'
    printf 'shasum -a 256 --check SHA256SUMS\n'
    printf '```\n'
} >"$notes"

if draft=$(bash scripts/tooling/retry.sh gh release view "$tag" --json isDraft --jq .isDraft 2>/dev/null); then
    if [[ "$draft" == false ]]; then
        # Public releases are immutable here; a retry succeeds only if the existing PDF, key, and provenance match exactly.
        previous=$(mktemp -d "$RUNNER_TEMP/resume-release.XXXXXX")
        bash scripts/tooling/retry.sh gh release download "$tag" --dir "$previous" --pattern resume.pdf --pattern key-fingerprint.txt --pattern source.json
        cmp "$artifact_dir/resume.pdf" "$previous/resume.pdf"
        cmp "$artifact_dir/key-fingerprint.txt" "$previous/key-fingerprint.txt"
        cmp "$artifact_dir/source.json" "$previous/source.json"
        echo 'An identical PDF and signing identity are already released for this source.'
        exit 0
    fi
else
    bash scripts/tooling/retry.sh bash scripts/release/create-draft.sh "$tag" "$notes"
fi

# Assemble the complete attachment set before publication so consumers never see a public release with missing verification material.
artifacts=(resume.pdf resume.pdf.sig resume.pdf.sigstore.json cosign.pub key-fingerprint.txt source.json SHA256SUMS SHA256SUMS.sigstore.json)
paths=()

for artifact in "${artifacts[@]}"; do
    paths+=("$artifact_dir/$artifact")
done

# Replacing draft assets makes interrupted uploads recoverable; the final visibility change is the publication boundary.
bash scripts/tooling/retry.sh gh release upload "$tag" "${paths[@]}" --clobber
bash scripts/tooling/retry.sh gh release edit "$tag" --draft=false --notes-file "$notes"
