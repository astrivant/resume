#!/usr/bin/env bash
# Sign the PDF and checksum manifest using a private key held only in the environment.
set -euo pipefail

if [[ -z "${COSIGN_PRIVATE_KEY:-}" ]]; then
    echo 'Set the COSIGN_PRIVATE_KEY Actions secret to the PEM-encoded Cosign private key.' >&2
    exit 1
fi

export COSIGN_PASSWORD="${COSIGN_PASSWORD:-}"
artifact_dir="${1:-.cache/publication}"
test -s "$artifact_dir/resume.pdf"

# Derive the public identity without writing the private key to a file or expanding it into process arguments.
cosign public-key --key env://COSIGN_PRIVATE_KEY >"$artifact_dir/cosign.pub"

# Embed the release URL and derived public fingerprint before signing; subsequent publication must preserve these bytes.
python scripts/release/metadata.py "$artifact_dir"
bash scripts/tooling/retry.sh cosign sign-blob --yes --key env://COSIGN_PRIVATE_KEY \
    --bundle "$artifact_dir/resume.pdf.sigstore.json" "$artifact_dir/resume.pdf"

# The signed manifest binds the PDF's verification bundle and provenance files into the same release payload.
python scripts/release/checksums.py "$artifact_dir"
bash scripts/tooling/retry.sh cosign sign-blob --yes --key env://COSIGN_PRIVATE_KEY \
    --bundle "$artifact_dir/SHA256SUMS.sigstore.json" "$artifact_dir/SHA256SUMS"

# Treat local verification as a build gate; upload steps must only see artifacts that passed the same verifier consumers use.
bash scripts/release/verify.sh "$artifact_dir"
