#!/usr/bin/env bash
# Upload the verified Python distributions using the PyPI token supplied only to this job.
set -euo pipefail

# Report a missing organization-secret grant before contacting PyPI; never echo credentials.
if [[ -z "${POETRY_PYPI_TOKEN_PYPI:-}" ]]; then
    echo '::error::PYPI_API_TOKEN is unavailable. Grant this repository access to the organization secret, or set a repository/pypi environment secret.' >&2
    exit 1
fi

# Validate the tag and both expected artifacts before uploading either half of the release.
: "${RELEASE_TAG:?A version tag is required for PyPI publication}"
version=$(bash scripts/release/package-version.sh)

for artifact in "dist/resumeme-$version-py3-none-any.whl" "dist/resumeme-$version.tar.gz"; do
    if [[ ! -s "$artifact" ]]; then
        echo "::error::Missing verified distribution: $artifact" >&2
        exit 1
    fi
done

# Skip already uploaded files on reruns; retry only transport failures using the shared exponential backoff.
bash scripts/tooling/retry.sh poetry publish --no-interaction --skip-existing
