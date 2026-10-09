#!/usr/bin/env bash
# Simulate Pages boundaries without requesting credentials, deploying, or sleeping in regression tests.
set -euo pipefail
printf '%s %s\n' "${0##*/}" "$*" >>"$PAGES_TEST_ROOT/calls"

case "${0##*/}" in
    git)
        [[ "$*" == 'rev-parse HEAD' ]]
        printf '%s\n' "$PAGES_TEST_HEAD"
        ;;
    curl)
        output=''

        while (($#)); do
            if [[ "$1" == --output ]]; then
                output=$2
                shift
            fi

            shift
        done

        if [[ "$PAGES_TEST_MODE" == deploy ]]; then
            printf '{"value":"synthetic-oidc-token"}\n' >"$output"
            printf '%s\n' "$output" >"$PAGES_TEST_ROOT/temporary"
        elif [[ "$PAGES_TEST_MODE" == stale ]]; then
            printf 'old PDF' >"$output"
        elif [[ "$PAGES_TEST_MODE" == propagation && ! -e "$PAGES_TEST_ROOT/downloaded" ]]; then
            touch "$PAGES_TEST_ROOT/downloaded"
            printf 'old PDF' >"$output"
        else
            cp "$PAGES_TEST_ROOT/resume.pdf" "$output"
        fi
        ;;
    gh)
        [[ "${1:-}" == api ]]

        if [[ "$*" == *'/cancel' ]]; then
            touch "$PAGES_TEST_ROOT/cancelled"
        elif [[ "$*" == *'--input '* ]]; then
            cp "${@: -1}" "$PAGES_TEST_ROOT/submitted.json"
            printf '{"id":"pages-deployment"}\n'
        elif [[ "$PAGES_TEST_STATUS" == transport ]]; then
            echo 'HTTP 503' >&2
            exit 1
        else
            printf '%s\n' "$PAGES_TEST_STATUS"
        fi
        ;;
    sleep) ;;
    *) exit 2 ;;
esac
