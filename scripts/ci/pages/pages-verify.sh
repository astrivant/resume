#!/usr/bin/env bash
# Require the public PDF bytes to match the accepted artifact before reporting publication success.
set -euo pipefail
: "${PAGES_URL:?Set the deployed site URL including its configured path}"
: "${PDF_SHA256:?Set the accepted PDF SHA-256}"

if [[ ! "$PDF_SHA256" =~ ^[0-9a-f]{64}$ || "$PAGES_URL" != https://* ]]; then
    echo '::error::Live verification requires an HTTPS site and a SHA-256 digest.' >&2
    exit 1
fi

temporary=$(mktemp)
trap 'rm -f -- "$temporary"' EXIT
backoff=5

# Fresh query URLs and revalidation headers avoid a previously cached response while the Pages edge propagates.
for attempt in 1 2 3 4 5 6; do
    url="${PAGES_URL%/}/resume.pdf?sha256=$PDF_SHA256&attempt=$attempt"

    if curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
        --connect-timeout 10 --max-time 30 --header 'Cache-Control: no-cache' "$url" --output "$temporary"; then
        actual=$(shasum -a 256 "$temporary")
        actual=${actual%% *}

        if [[ "$actual" == "$PDF_SHA256" ]]; then
            printf 'Live resume verified: SHA256 %s\n' "$PDF_SHA256"

            if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
                printf 'Published [%sresume.pdf](%sresume.pdf). SHA256: <code>%s</code>\n' \
                    "${PAGES_URL%/}/" "${PAGES_URL%/}/" "$PDF_SHA256" >>"$GITHUB_STEP_SUMMARY"
            fi

            exit 0
        fi

        printf 'Public PDF is still different (SHA256 %s); propagation check %s/6.\n' "$actual" "$attempt"
    fi

    if ((attempt < 6)); then
        sleep "$backoff"
        backoff=$((backoff < 30 ? backoff * 2 : 60))
    fi
done

echo '::error::GitHub reported a deployment, but the public PDF does not match the accepted artifact. Rerun Pages; capture is not required.' >&2
exit 1
