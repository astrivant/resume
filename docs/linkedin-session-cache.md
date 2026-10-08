# Encrypted LinkedIn sessions

The CI session wrapper carries an accepted browser login between captures using
authenticated encrypted archives. Ordinary local CLI capture still retains an
unencrypted browser profile. This encryption does not cover captured profile
JSON, prompts, PDFs, or other workflow artifacts. Read the
[data-handling inventory and risks](data-handling.md) before enabling reuse.

## Setup

Install OpenSSH, OpenSSL, and the GitHub CLI on macOS or Linux. Authenticate the
CLI with access to manage Actions secrets on your fork, then run:

```bash
bash scripts/ci/setup-session-cache.sh --repo YOUR-USERNAME/YOUR-FORK
```

The script generates RSA-3072 keys with `ssh-keygen -m PEM`, exports the public
PEM, encrypts the private PEM, and uploads these **Actions secrets**:

- `RESUMEME_CACHE_PRIVATE_KEY`: encrypted private PEM.
- `RESUMEME_CACHE_PUBLIC_KEY`: matching public PEM.
- `RESUMEME_CACHE_KEY_PASSWORD`: private-key password.

The local backup is under `${XDG_DATA_HOME:-$HOME/.local/share}/resumeme/session-cache-keys/`.
Its directory and files have private permissions. Keep the backup for recovery;
it includes the password needed to decrypt the private key. Anyone with the whole
backup can decrypt your session archives; protect its storage accordingly. Plain temporary key
files are removed. Add `--key-dir /path/to/backup` to reuse an identity or retry
an interrupted upload. These keys are separate from Cosign release signing.
Generating a new pair rotates the cache namespace and requires a fresh login.

With these secrets configured, CI creates the first encrypted session cache
automatically after a successful LinkedIn capture. A cache miss on the first run
is normal. Users do not create or upload a cache file. GitHub authentication
authorizes the setup script to store repository secrets when the account has
the required permissions; it does not authenticate that browser to LinkedIn.

After the workflow changes are on `main`, you can optionally warm its shared
cache before tagging by starting a refresh:

```bash
gh workflow run ci.yml --repo YOUR-USERNAME/YOUR-FORK --ref main -f refresh=true
```

Watch the capture job. App approvals and unknown checkpoints allow up to
`capture.app_approval_timeout_seconds` (900 seconds by default). Approve the pending
request in your LinkedIn app when one appears. Recognized code-entry MFA, CAPTCHA,
denial, and expiry fail immediately.

Without cache keys, jobs still capture using the login secrets and temporary
browser state but save no session cache. A partial key set fails before capture.
`LINKEDIN_USERNAME` and `LINKEDIN_PASSWORD` remain required for fresh or expired logins.

## Cache lifecycle

Each LinkedIn job restores one encrypted file, decrypts it into a private temporary
directory, and runs its browser command. The browser subprocess does not receive
the encryption-key environment variables. After success, the wrapper encrypts and
signs the updated profile, then removes temporary browser files and raw driver
diagnostics. Failed commands preserve the last accepted cache.

Cleanup also runs in an `always()` workflow step after failure or cancellation.
This cleanup covers the temporary browser directory, not accepted snapshots,
downloaded assets, CLI warning JSON, or publisher backups in the checkout. An
abrupt host shutdown or `SIGKILL` can prevent it, and deletion is not secure
erasure. Protect runner disks/backups and remove abandoned data separately.

Archives use a fresh AES-256-GCM key and nonce per write. RSA-OAEP wraps the data
key, and RSA-PSS authenticates the complete envelope before decryption. Verification
binds it to the repository, configured LinkedIn owner, browser, OS, and architecture.
Tampering, mismatched keys, and a different context fail before restoration.
Extraction rejects links, traversal paths, and oversized archives.

GitHub Actions caches only the encrypted envelope from `.cache/encrypted-session/`.
Unencrypted browser directories, screenshots, raw browser HTML, and PEM key files
are not session-cache upload paths. The encrypted archive contains regular browser
profile files, potentially including history/storage as well as cookies. Capture
and build artifacts retain their separate, unencrypted-by-resumeme upload paths.

[GitHub cache scope](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching)
allows tags to restore a cache from the default branch, but different tags cannot
restore one another's tag-scoped caches. Refresh `main` to renew the shared seed
after a session expires. Tag runs can reuse their own cache on retries. Cache
eviction or an expired LinkedIn session requires another sign-in; reuse does not
guarantee LinkedIn will omit challenges.

There is no application-level archive TTL or replay prevention. Old valid
archives can be restored, and key rotation does not delete them or revoke account
sessions. GitHub can evict unused caches before the next monthly refresh; the
optional persistent runner directory has no automatic expiry. See
[cache limits and recovery](data-handling.md#encrypted-browser-sessions-in-ci).

## Optional dedicated runner

GitHub-hosted Ubuntu remains the default. To keep browser execution on a stable
machine, register an existing Linux or macOS host following
[GitHub's runner setup](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/add-runners).
Install the configured browser, Git, and dependencies needed by the existing setup
action. Use a current Actions runner compatible with Node.js 24 actions and give
it a dedicated `resumeme-linkedin` label.

Set these repository **variables**, not secrets:

| Variable | Example | Purpose |
| --- | --- | --- |
| `RESUMEME_LINKEDIN_RUNNER` | `["self-hosted","resumeme-linkedin"]` | JSON runner labels for capture and optional LinkedIn publication jobs |
| `RESUMEME_SESSION_CACHE_DIR` | `/srv/resumeme/encrypted-sessions` | Optional absolute ciphertext directory outside every checkout |

The runner service account must own the cache directory. Only encrypted envelopes
persist there; each job gets its own temporary decrypted profile, so parallel jobs
never open the same browser directory. Successful writes replace encrypted files
atomically. The local ciphertext copy can be reused across tags independently of
GitHub's cache scope.

Use one dedicated runner registration for the account to serialize browser jobs.
Restrict runner access to trusted repository workflows. Pull-request and ordinary
branch checks in this pipeline remain hosted; capture runs only for tags, monthly
runs, or an explicit refresh on `main`. Do not grant untrusted pull-request workflows
access to this machine.

To bootstrap interactively, use the same service account, browser, and repository
context. Load the saved key backup and run from the existing checkout:

```bash
export GITHUB_REPOSITORY=YOUR-USERNAME/YOUR-FORK
export RESUMEME_SESSION_CACHE_DIR=/srv/resumeme/encrypted-sessions
export RESUMEME_CACHE_PRIVATE_KEY="$(cat /path/to/backup/session.key)"
export RESUMEME_CACHE_PUBLIC_KEY="$(cat /path/to/backup/session.pub)"
export RESUMEME_CACHE_KEY_PASSWORD="$(cat /path/to/backup/session.password)"
poetry run python scripts/ci/linkedin-session.py run --interactive
```

This closes the browser, encrypts the accepted session, and removes temporary
plaintext after capture succeeds. Never cache `RESUMEME_BROWSER_STATE_DIR` or
the runner's temporary directory.

## Diagnostics and recovery

Checkpoint notices and timeout errors report only classification, a fixed detector
name, readability, and input/frame counts. Unknown pages wait within the same
deadline; redraws do not reset it. No raw account details enter these diagnostics.

For key-loading errors, rerun setup with the existing backup directory. For rejected
cache authentication, restore the correct identity or remove the matching encrypted
cache entry through GitHub's cache UI and capture again. The wrapper does not
silently accept or overwrite an unauthenticated cache.
