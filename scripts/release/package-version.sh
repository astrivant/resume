#!/usr/bin/env bash
# Apply version tags to the disposable build checkout and report the distribution version.
set -euo pipefail

# Require an explicit Python release version so tag input cannot invoke Poetry's relative bump commands.
if [[ -n "${RELEASE_TAG:-}" ]]; then
    if [[ ! "$RELEASE_TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+((a|b|rc)[0-9]+)?(\.post[0-9]+)?(\.dev[0-9]+)?$ ]]; then
        echo '::error::Use vMAJOR.MINOR.PATCH with an optional Python suffix, such as v0.2.0rc1.' >&2
        exit 1
    fi

    # Keep stdout machine-readable for publication; only the checkout's package metadata changes, never the lockfile.
    poetry version "${RELEASE_TAG#v}" >&2
fi

poetry version --short
