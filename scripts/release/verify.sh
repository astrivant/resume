#!/usr/bin/env bash
# Verify the signed manifest and PDF, then check every attached file's SHA-256 digest.
set -euo pipefail
artifact_dir="${1:-.cache/publication}"
# Authenticate the checksum list before using it to judge the attached files, then independently authenticate the PDF.
bash scripts/tooling/retry.sh cosign verify-blob --key "$artifact_dir/cosign.pub" \
    --bundle "$artifact_dir/SHA256SUMS.sigstore.json" "$artifact_dir/SHA256SUMS"
bash scripts/tooling/retry.sh cosign verify-blob --key "$artifact_dir/cosign.pub" \
    --bundle "$artifact_dir/resume.pdf.sigstore.json" "$artifact_dir/resume.pdf"
# Manifest paths are relative to the artifact directory, allowing the same verifier to run after download elsewhere.
cd "$artifact_dir"
shasum -a 256 --check SHA256SUMS
