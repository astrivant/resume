#!/usr/bin/env bash
# Deploy one uploaded site using its accepted publication commit as the Pages build version.
set -euo pipefail
umask 077

: "${PUBLISHED_SHA:?Set the accepted publication commit}"
: "${PAGES_ARTIFACT_ID:?Set the uploaded Pages artifact ID for this run}"
: "${GH_TOKEN:?Set the built-in GitHub token for this job}"
: "${ACTIONS_ID_TOKEN_REQUEST_URL:?Pages deployment requires Actions OIDC}"
: "${ACTIONS_ID_TOKEN_REQUEST_TOKEN:?Pages deployment requires id-token write permission}"

if [[ "${GITHUB_EVENT_NAME:-}" == pull_request || ! "$PUBLISHED_SHA" =~ ^[0-9a-f]{40}$ || ! "$PAGES_ARTIFACT_ID" =~ ^[1-9][0-9]*$ ]]; then
    echo '::error::Pages requires a trusted publication commit and an uploaded artifact ID.' >&2
    exit 1
fi

test "$(git rev-parse HEAD)" = "$PUBLISHED_SHA"

# Keep credentials in private temporary files, never in verbose HTTP diagnostics or deployment summaries.
unset GH_DEBUG
temporary=$(mktemp -d)
deployment_id=''
pending=false

# Cancel only this pending deployment on timeout/failure; always remove its short-lived OIDC material.
# void -> ret::exit_code
# ShellCheck does not follow this function's EXIT trap invocation.
# shellcheck disable=SC2329
cleanup() {
    if [[ "$pending" == true ]]; then
        gh api --method POST "repos/$GITHUB_REPOSITORY/pages/deployments/$deployment_id/cancel" >/dev/null 2>&1 || true
    fi

    rm -rf -- "$temporary"
}
trap 'cleanup' EXIT

printf 'Authorization: bearer %s\n' "$ACTIONS_ID_TOKEN_REQUEST_TOKEN" >"$temporary/headers"
curl --fail --silent --show-error --proto '=https' --connect-timeout 10 --max-time 30 \
    --retry 3 --retry-max-time 90 --header "@$temporary/headers" \
    "$ACTIONS_ID_TOKEN_REQUEST_URL" --output "$temporary/oidc.json"
jq -e '.value | type == "string" and length > 0' "$temporary/oidc.json" >/dev/null
printf '::add-mask::%s\n' "$(jq -r '.value' "$temporary/oidc.json")"
jq -n --arg version "$PUBLISHED_SHA" --argjson artifact "$PAGES_ARTIFACT_ID" --slurpfile oidc "$temporary/oidc.json" \
    '{artifact_id: $artifact, pages_build_version: $version, oidc_token: $oidc[0].value}' >"$temporary/payload.json"

# The same accepted commit always names the same site input; bounded retries may safely repeat this request.
RETRY_ATTEMPTS=3 RETRY_MAX_BACKOFF_SECONDS=30 bash scripts/tooling/retry.sh \
    gh api --method POST "repos/$GITHUB_REPOSITORY/pages/deployments" --input "$temporary/payload.json" >"$temporary/deployment.json"
deployment_id=$(jq -er '.id | strings | select(test("^[A-Za-z0-9_-]+$"))' "$temporary/deployment.json")
pending=true
printf 'Pages artifact %s, publication commit %s, deployment %s\n' "$PAGES_ARTIFACT_ID" "$PUBLISHED_SHA" "$deployment_id"
deadline=$((SECONDS + 600))

# Terminal failures stop immediately; temporary status errors and queued deployments stay within one deadline.
while ((SECONDS < deadline)); do
    status=$(RETRY_ATTEMPTS=3 RETRY_MAX_BACKOFF_SECONDS=30 bash scripts/tooling/retry.sh \
        gh api "repos/$GITHUB_REPOSITORY/pages/deployments/$deployment_id" --jq .status)

    case "$status" in
        succeed)
            pending=false
            echo 'GitHub accepted the site deployment; checking the public PDF next.'
            exit 0
            ;;
        deployment_failed | deployment_content_failed | deployment_cancelled | deployment_lost)
            pending=false
            printf '::error::Pages deployment ended with %s.\n' "$status" >&2
            exit 1
            ;;
    esac

    printf 'Pages deployment status: %s\n' "$status"
    sleep 5
done

echo '::error::Pages deployment exceeded ten minutes.' >&2
exit 1
