#!/usr/bin/env bash
# Resolve the visitor URL from GitHub's actual Pages configuration and the validated site-relative directory.
set -euo pipefail

if [[ -n "$EXPECTED_DOMAIN" && "${EXPECTED_DOMAIN,,}" != "${PAGES_HOST,,}" ]]; then
    echo '::error::pages.custom_domain does not match GitHub Pages. Configure the domain in Settings > Pages before deploying.' >&2
    exit 1
fi

# configure-pages already includes the repository prefix, or the custom domain without that prefix.
printf 'url=%s%s\n' "${PAGES_BASE_URL%/}" "$PUBLICATION_PATH" >>"$GITHUB_OUTPUT"
