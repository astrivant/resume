#!/usr/bin/env bash
# Generate or reuse a dedicated RSA PEM key pair and upload the encrypted-cache identity to an explicit GitHub repository.
set -euo pipefail
set +x
umask 077

# Describe setup without generating keys or changing remote secrets.
# -> ret::exit_code
usage() {
    cat <<'USAGE'
Usage: bash scripts/ci/setup-session-cache.sh --repo OWNER/REPO [--key-dir DIRECTORY]

Requires ssh-keygen, OpenSSL, and an authenticated gh CLI on macOS or Linux.
Creates a dedicated RSA-3072 PEM key pair and an encrypted local backup.
Sets RESUMEME_CACHE_PRIVATE_KEY, RESUMEME_CACHE_PUBLIC_KEY, and
RESUMEME_CACHE_KEY_PASSWORD as Actions secrets on the selected repository.
Use --key-dir to reuse the saved identity. A new identity rotates the cache key.
USAGE
}

cache_repo=''
cache_key_dir=''
while (($#)); do
    case "$1" in
        --repo | --key-dir)
            if (($# < 2)) || [[ -z "$2" ]]; then
                usage >&2
                exit 2
            fi
            if [[ "$1" == --repo ]]; then
                cache_repo="$2"
            else
                cache_key_dir="$2"
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

if [[ ! "$cache_repo" =~ ^[[:alnum:]][[:alnum:]-]*/[[:alnum:]_.-]+$ ]]; then
    echo 'Pass --repo OWNER/REPO for the fork whose cache secrets should be configured.' >&2
    exit 2
fi

for dependency in ssh-keygen openssl gh; do
    if ! command -v "$dependency" >/dev/null 2>&1; then
        printf 'Required command is unavailable: %s\n' "$dependency" >&2
        exit 1
    fi
done

# Confirm the explicit remote exists before creating local key material.
gh repo view "$cache_repo" --json nameWithOwner --jq .nameWithOwner

if [[ -z "$cache_key_dir" ]]; then
    cache_key_root="${XDG_DATA_HOME:-$HOME/.local/share}/resumeme/session-cache-keys"
    mkdir -p "$cache_key_root"
    cache_key_dir="$(mktemp -d "$cache_key_root/key.XXXXXX")"
    trap 'rm -f "$cache_key_dir/plain.key" "$cache_key_dir/plain.key.pub"' EXIT

    # Generate with ssh-keygen, export the public PEM, and encrypt the private PEM before retaining its backup.
    ssh-keygen -q -t rsa -b 3072 -m PEM -N '' -C resumeme-session-cache -f "$cache_key_dir/plain.key"
    ssh-keygen -e -m PKCS8 -f "$cache_key_dir/plain.key.pub" >"$cache_key_dir/session.pub"
    RESUMEME_CACHE_KEY_PASSWORD="$(openssl rand -hex 32)"
    export RESUMEME_CACHE_KEY_PASSWORD
    printf '%s' "$RESUMEME_CACHE_KEY_PASSWORD" >"$cache_key_dir/session.password"
    openssl pkey -in "$cache_key_dir/plain.key" -aes-256-cbc -passout env:RESUMEME_CACHE_KEY_PASSWORD -out "$cache_key_dir/session.key"
    rm -f "$cache_key_dir/plain.key" "$cache_key_dir/plain.key.pub"
fi

for filename in session.key session.pub session.password; do
    if [[ ! -s "$cache_key_dir/$filename" || ! -r "$cache_key_dir/$filename" ]]; then
        printf 'Missing or unreadable cache-key backup: %s/%s\n' "$cache_key_dir" "$filename" >&2
        exit 1
    fi
done

# Compare derived public keys before replacing secrets, without printing either private material or passwords.
private_fingerprint="$(openssl pkey -in "$cache_key_dir/session.key" -passin "file:$cache_key_dir/session.password" -pubout -outform DER | openssl dgst -sha256)"
public_fingerprint="$(openssl pkey -pubin -in "$cache_key_dir/session.pub" -outform DER | openssl dgst -sha256)"
if [[ "$private_fingerprint" != "$public_fingerprint" ]]; then
    echo 'The saved cache key pair does not match.' >&2
    exit 1
fi

gh secret set RESUMEME_CACHE_PRIVATE_KEY --repo "$cache_repo" <"$cache_key_dir/session.key"
gh secret set RESUMEME_CACHE_PUBLIC_KEY --repo "$cache_repo" <"$cache_key_dir/session.pub"
gh secret set RESUMEME_CACHE_KEY_PASSWORD --repo "$cache_repo" <"$cache_key_dir/session.password"
printf 'Cache key backup: %s\nPublic key fingerprint: %s\n' "$cache_key_dir" "$public_fingerprint"
printf 'Seed the shared cache after pushing the workflow: gh workflow run ci.yml --repo %s --ref main -f refresh=true\n' "$cache_repo"
