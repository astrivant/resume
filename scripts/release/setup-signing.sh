#!/usr/bin/env bash
# Generate or reuse a Cosign key and install its secrets on an explicitly selected GitHub repository.
set -euo pipefail
set +x
umask 077

# Describe required inputs without generating a key or contacting GitHub.
# -> ret::exit_code
usage() {
    cat <<'USAGE'
Usage: bash scripts/release/setup-signing.sh --repo OWNER/REPO [--key-dir DIRECTORY]

Requires OpenSSL, Cosign 3.x, and an authenticated GitHub CLI on macOS or Linux.
Without --key-dir, generate a new signing identity and save its encrypted key,
public key, and password under ${XDG_DATA_HOME:-$HOME/.local/share}/resumeme/signing/.
With --key-dir, upload the existing cosign.key and cosign.password from that directory.
Both modes replace COSIGN_PRIVATE_KEY and COSIGN_PASSWORD in the selected repository.
USAGE
}

signing_repo=''
signing_dir=''

# Require an explicit destination so a fork cannot inherit gh's upstream repository default.
while (($#)); do
    case "$1" in
        --repo | --key-dir)
            if (($# < 2)) || [[ -z "$2" ]]; then
                usage >&2
                exit 2
            fi

            if [[ "$1" == --repo ]]; then
                signing_repo="$2"
            else
                signing_dir="$2"
            fi
            shift 2
            ;;
        -h | --help)
            usage
            exit 0
            ;;
        *)
            usage >&2
            exit 2
            ;;
    esac
done

if [[ ! "$signing_repo" =~ ^[[:alnum:]][[:alnum:]-]*/[[:alnum:]_.-]+$ ]]; then
    echo 'Pass --repo OWNER/REPO for the fork whose signing secrets should be updated.' >&2
    exit 2
fi

# Check prerequisites and repository access before creating local key material.
for dependency in openssl cosign gh; do
    if ! command -v "$dependency" >/dev/null 2>&1; then
        printf 'Required command is unavailable: %s\n' "$dependency" >&2
        exit 1
    fi
done

gh repo view "$signing_repo" --json nameWithOwner --jq .nameWithOwner

if [[ -n "$signing_dir" ]]; then

    # A retry reuses all three saved files and preserves password bytes exactly through stdin.
    for filename in cosign.key cosign.pub cosign.password; do
        if [[ ! -s "$signing_dir/$filename" || ! -r "$signing_dir/$filename" ]]; then
            printf 'Missing or unreadable signing backup: %s/%s\n' "$signing_dir" "$filename" >&2
            exit 1
        fi
    done
else
    signing_root="${XDG_DATA_HOME:-$HOME/.local/share}/resumeme/signing"
    mkdir -p "$signing_root"
    signing_dir="$(mktemp -d "$signing_root/key.XXXXXX")"
    printf 'Local signing-key backup: %s\n' "$signing_dir"
    trap 'rm -f "$signing_dir/openssl.key"' EXIT

    # Keep plaintext key material temporary and preserve the exact generated password for CI.
    COSIGN_PASSWORD="$(openssl rand -hex 32)"
    export COSIGN_PASSWORD
    printf '%s' "$COSIGN_PASSWORD" >"$signing_dir/cosign.password"
    openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out "$signing_dir/openssl.key"
    cosign import-key-pair --key "$signing_dir/openssl.key" --output-key-prefix "$signing_dir/cosign"
fi

# Upload secrets through stdin; an interrupted upload can be retried with --key-dir and this same identity.
printf 'Using signing-key backup: %s\n' "$signing_dir"
gh secret set COSIGN_PRIVATE_KEY --repo "$signing_repo" <"$signing_dir/cosign.key"
gh secret set COSIGN_PASSWORD --repo "$signing_repo" <"$signing_dir/cosign.password"
openssl pkey -pubin -in "$signing_dir/cosign.pub" -outform DER | openssl dgst -sha256
gh secret list --repo "$signing_repo"
