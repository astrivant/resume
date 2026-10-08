# Sensitive data handling

This document describes the checked-in CLI and workflows, reviewed on 2026-10-08.
Paths below are defaults relative to the configuration directory unless stated
otherwise. Fork changes, custom templates, alternate actions, and runner settings
can change these boundaries. See [SECURITY.md](../SECURITY.md) for reporting and
maintainer responsibilities.

## Contents

- [Before capturing or publishing](#before-capturing-or-publishing)
- [Credentials and who can use them](#credentials-and-who-can-use-them)
- [Local files and their lifetime](#local-files-and-their-lifetime)
- [Encrypted browser sessions in CI](#encrypted-browser-sessions-in-ci)
- [Key creation, backups, and rotation](#key-creation-backups-and-rotation)
- [CI artifacts, commits, and public output](#ci-artifacts-commits-and-public-output)
- [Optional AI processing](#optional-ai-processing)
- [Other network recipients and live writes](#other-network-recipients-and-live-writes)
- [Logs and debugging](#logs-and-debugging)
- [Disable, delete, or respond to exposure](#disable-delete-or-respond-to-exposure)
- [Implementation references](#implementation-references)

## Before capturing or publishing

**The captured profile can contain more personal information than the PDF shows.**
Capture runs as the signed-in LinkedIn user and reads the profile's Contact info
dialog, including email, birthday, and other fields when present. Logged-in
content is not necessarily public content. Recommendations and other profile
sections can also identify third parties.

**Visibility settings are presentation filters, not source-data redaction.**
Removing a section from `section_order`, excluding a job or school, or disabling
the birthday or profile photo does not remove it from `data/profile.json` or its
referenced assets. Refresh publication commits those captured inputs to `main`.
There is no separate configuration switch that strips sensitive fields before
capture-artifact upload or the refresh commit. Review the entire snapshot and
assets, not just the rendered PDF, before using a public repository. A later
automatic capture can restore manually removed source fields.

**Encrypted session reuse does not encrypt the project.** Only the browser-profile
cache described below receives application-level encryption. Source snapshots,
configuration, AI prompts/results, TeX, PDFs, README previews, ordinary workflow
artifacts, and Docker build caches do not use that encryption. GitHub's storage
and access controls are a separate layer.

## Credentials and who can use them

Put credentials in GitHub Actions **secrets**, not YAML configuration, public
repository variables, issue bodies, or command-line arguments. Locally, use a
secret manager or the process environment. The CLI does not load `.env` itself.
`.gitignore` prevents ordinary accidental staging of selected files; it is not
encryption, an access control, or protection against `git add -f`.

| Credential | Consumer and purpose | Exposure boundary |
| --- | --- | --- |
| `LINKEDIN_USERNAME`, `LINKEDIN_PASSWORD` | Browser capture and enabled LinkedIn publishers; submitted to LinkedIn's login form when needed | Present in the command's environment and process memory. Headless commands require both even when restoring a session. The public profile slug belongs in `linkedin.username`; an email/phone is needed for unattended login. |
| `RESUMEME_CACHE_PRIVATE_KEY`, `RESUMEME_CACHE_KEY_PASSWORD` | Session wrapper restores and creates encrypted browser archives | The same wrapper can access the encrypted private PEM and its password. It removes the three cache-key variables from the launched `resumeme` subprocess environment; this is not isolation from the wrapper, runner administrator, or other code running as that user. |
| `RESUMEME_CACHE_PUBLIC_KEY` | Cache encryption, signature verification, and cache-key fingerprint | Public key material, supplied as a secret for setup consistency. It cannot decrypt an archive or sign a valid replacement by itself. |
| `OPENAI_API_KEY` | Upstream Codex action for enabled summaries or skill proposals | Passed to that action, which owns API authentication. Browser, signing, and publication credentials are not supplied to the model jobs. |
| `COSIGN_PRIVATE_KEY`, `COSIGN_PASSWORD` | Tag release signing | Cosign reads `env://COSIGN_PRIVATE_KEY`; the release script does not write the private key to a file or put its contents in arguments. The signing process and trusted code in its step can use the key. |
| `GITHUB_TOKEN`, optional `RESUME_PUBLISH_TOKEN` | Repository commits, releases, Pages, and GHCR as permitted by each job | A publication token allowed to bypass reviews/checks can write protected `main`. Deploy checkout retains authentication for its Git push; most other checkouts set `persist-credentials: false`. |
| `PYPI_API_TOKEN`, `DOCKER_HUB_TOKEN_EMMEOWZING` | Package/registry publication, supplied only to their publication steps | PyPI receives the former through `POETRY_PYPI_TOKEN_PYPI`. Docker Hub publication is restricted to upstream tag runs. Resume-only forks do not need either secret. |

GitHub decrypts Actions secrets to inject them into workflow runtime; these are
not keys kept inaccessible to the executing job. Restrict who can modify
workflows, dependencies, source, and tags that receive credentials. A malicious
change on a trusted trigger can read secrets regardless of log masking or cache
encryption. Organization-secret access and protected-environment approvals are
controlled by the repository/organization owner.
[GitHub's secret model](https://docs.github.com/en/actions/concepts/security/secrets)
describes these controls and masking limits.

## Local files and their lifetime

| Location | Stored content and reason | Lifetime and protection |
| --- | --- | --- |
| `resumeme.config.yaml` and overrides | Profile identifiers, presentation choices, company/job targets, and optional writing context | Usually committed. Treat context and target lists as publishable; never put passwords or tokens here. |
| `.cache/firefox/`, `.cache/chrome/` | Dedicated browser profile for login reuse, potentially including session cookies, storage, history, preferences, and browser-managed databases | Ordinary CLI capture, including direct `--headless`, retains it across commands without resumeme encryption. Profile directory permissions are `0700`; the current OS user and privileged processes can read it. No automatic expiry or deletion. |
| `.cache/capture/` | Expanded profile/detail HTML, failure screenshots, driver logs, and recoverable profile JSON for diagnosis | Ordinary local capture retains plaintext until removed. These files can contain account details or page tokens beyond the parsed snapshot. On a warning-bearing capture/enrichment, the CLI also writes `.cache/capture/profile.json`. |
| `data/profile.json`, `data/assets/` | Accepted full profile, original/resolved links, and downloaded images for reproducible builds | Written after capture/enrichment; retained until replaced or deleted. No application encryption or automatic personal-data redaction. Downloads can leave additional local assets after failure. |
| `tex/`, `.cache/build/`, `resume.pdf`, `single-origin/` | Generated source/assets, compiler logs, PDF, and optional employer variants | Generated for rendering; retain personal text and images. Compiler scratch directories are removed on normal exit, but TeX, logs, and final outputs remain. Configured output paths can differ. |
| `.cache/codex/` | Prompt/schema files, generated JSON, and employer/job evidence | Retained locally for generation and validation until removed. Contains personal prose and user context even when no API key is stored there. |
| `.cache/ownership/about-before-*.txt`, `.cache/skills/before-*.json` | Original live About text or existing skill names, saved before a non-dry-run change for recovery | Plaintext backups with private temporary-file permissions, retained until removed. Also written in CI checkouts when those publishers make changes; not selected for artifact upload or removed by the session wrapper. |
| `.cache/linkedin-resumes/` | Temporary byte-for-byte PDF copy with a content-derived filename for browser upload | Nested temporary directory removed on normal command exit; the original PDF and LinkedIn's saved copy remain. Abrupt failure can leave staging files. |
| `tex/github-contributions.json` and generated graph assets | Public contribution dates/counts used for repeatable rendering | Retained as build inputs/output; dates, account identity, and links can disclose activity patterns. |
| `.cache/selenium/` | Downloaded browser-driver tooling | Separate from browser authentication state. Not part of the encrypted session archive. |

The parsed snapshot intentionally excludes browser credentials, private messages,
the connections address book, and profile-view analytics. That is a collector
boundary, not a guarantee that page HTML or browser databases contain only those
fields. Do not upload an entire `.cache/` directory when asking for support.

## Encrypted browser sessions in CI

The [session action](../.github/actions/linkedin-session/action.yml) wraps capture
and each enabled LinkedIn publisher. Direct CLI invocation does not implicitly
enable this wrapper. The [setup guide](linkedin-session-cache.md) provides the
key-generation command and optional dedicated-runner configuration.

1. The wrapper loads and verifies a matching RSA PEM pair of at least 3072 bits.
   No cache secrets means no saved session cache; an incomplete or invalid key
   configuration fails instead of saving plaintext.
2. Cache lookup includes the repository, configured LinkedIn username, selected
   browser, OS, architecture, and SHA-256 public-key fingerprint. The Actions key
   also includes the run ID, attempt, and job. It does not contain the password or
   cookie value.
3. Actions restores one `.cache/encrypted-session/*.bin` file. If
   `RESUMEME_SESSION_CACHE_DIR` is set, an existing matching file in that absolute
   directory outside the checkout takes precedence over the Actions copy.
4. The wrapper verifies the RSA-PSS signature, unwraps the AES key with RSA-OAEP,
   and verifies AES-GCM authentication before extracting the archive. Repository,
   owner, browser, OS, and architecture are authenticated context. Invalid
   signatures, mismatched context, and unsafe archive members fail restoration.
5. Decrypted files go into a newly created private `resumeme-browser-*` directory
   under `RUNNER_TEMP` (the OS temporary directory outside Actions).
   `RESUMEME_BROWSER_STATE_DIR` directs browser files and raw browser diagnostics
   there. Restored regular files use `0600`, directories `0700`.
6. The command operates on plaintext browser data in memory and on disk. It can
   also write accepted snapshots/assets and CLI warning JSON in the checkout;
   the wrapper is not cleanup for the entire job filesystem.
7. Only after exit status zero, regular files in the selected browser profile are
   archived in memory. Symlinks, runtime locks, and named disposable caches are
   skipped. This is a profile archive, not a cookie-only allowlist: other browser
   databases, history, or saved data can be included. File-content/archive limits
   are 256 MiB; extraction rejects traversal, links, devices, and duplicate paths.
8. Each write creates a fresh 256-bit AES-GCM key and 12-byte nonce. RSA-OAEP with
   SHA-256 wraps that key; RSA-PSS with SHA-256 signs the context and envelope.
   Ciphertext atomically replaces the local envelope and optional persistent copy.
   Actions saves only that envelope, never the decrypted profile directory.
9. Temporary browser storage is removed on normal success/failure and handled
   cancellation. An `always()` step attempts cleanup again. Failed commands do not
   replace the accepted encrypted session.

Encryption protects copied cache contents when the private key remains secret.
It does **not** protect an active runner from its administrator, same-user code,
malicious dependencies, or a compromised browser. Cookies can authorize an
account session without another password or MFA prompt. Anyone obtaining both
the key/password and an archive may recover that session.

There is no archive age limit, anti-replay counter, or forward secrecy. An older
valid envelope for the same context/key can be restored; LinkedIn decides whether
its session is still valid. A later private-key compromise can decrypt older
copied archives. Rotation selects a new cache namespace but does not delete old
archives or revoke LinkedIn sessions. Context binding prevents accidental
cross-context restores; it is not an authorization boundary for someone holding
the private key.

GitHub cache access can include pull requests against the base branch, including
fork pull requests. Treat cache ciphertext as obtainable by others. GitHub
currently evicts caches unused for over seven days and can evict for storage
pressure; this is not a session TTL or a guaranteed deletion schedule for copies.
Tags can restore a default-branch cache but not another tag's cache. A monthly
refresh alone does not ensure the Actions cache survives until next month.
Persistent runner ciphertext has no automatic expiry in this project.
[GitHub cache access and retention](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching)
are separate from the archive encryption.

`SIGKILL`, host shutdown, or runner failure can prevent cleanup. File deletion is
not secure erasure: process memory, swap, disk snapshots, backups, and copied files
are not wiped. Dedicated-runner owners must manage temporary directories,
checkout cleanup, disk encryption, backups, and access. Do not run untrusted
workflows on a machine that holds a LinkedIn session or these keys.

## Key creation, backups, and rotation

Both setup scripts require an explicit `--repo OWNER/REPO`, disable shell tracing,
use `umask 077`, and upload secret values through `gh secret set` stdin. They
replace secrets in the selected repository; a partially completed upload can be
retried with `--key-dir`. They do not rotate keys on a timer.

| Setup | Creation and retained files | Storage |
| --- | --- | --- |
| [Session cache](../scripts/ci/setup-session-cache.sh) | `ssh-keygen -t rsa -b 3072 -m PEM`; public PEM exported; private PEM encrypted by OpenSSL AES-256-CBC using a random password. Keeps `session.key`, `session.pub`, `session.password`. | `${XDG_DATA_HOME:-$HOME/.local/share}/resumeme/session-cache-keys/key.*/` |
| [Release signing](../scripts/release/setup-signing.sh) | OpenSSL P-256 key imported into Cosign's encrypted key format. Keeps `cosign.key`, `cosign.pub`, `cosign.password`. | `${XDG_DATA_HOME:-$HOME/.local/share}/resumeme/signing/key.*/` |

These are separate identities. The RSA key is used for cache cryptography, not
installed as an SSH login key. New backup directories/files are private to the
creating user under the script's umask; `--key-dir` does not harden an existing
directory's permissions. Temporary plaintext private keys are removed by the
scripts' cleanup, which cannot run after abrupt host failure or `SIGKILL`.

**Each backup directory contains both the encrypted private key and its password.**
Copying the whole directory gives the recipient everything needed to use that
identity. Encryption of the key file alone does not protect that complete backup.
Protect the directory with OS access controls and encrypted storage; keep it out
of Git, Actions caches/artifacts, shared folders, and support attachments. The
same consideration applies to a CI job receiving both key and password secrets.

## CI artifacts, commits, and public output

These are ordinary artifacts, not encrypted session archives. Artifact download
requires a signed-in GitHub account with repository read access, so public-repo
artifacts are not private to maintainers. The durations below are the workflow's
requested retention; repository/organization limits also apply. Logs have the
repository's own retention setting, not the artifact-specific values.
[GitHub artifact access and retention](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/download-workflow-artifacts).

| Artifact | When and why | Content | Requested days |
| --- | --- | --- | --- |
| `resumeme-profile` | Tag, monthly, or requested main refresh; share one capture with downstream jobs | Full accepted snapshot and every referenced downloaded image, including fields hidden in the PDF. No browser-profile directory. | 7 |
| `resumeme-summary-inputs` | Enabled summary generation on main or tags; feed the matrix | `.cache/codex/` prompts, schemas, and company/job evidence, including configured writing context. | 7 |
| `resumeme-summary-result-*` | Each successful matrix item | Validated generated JSON and employer evidence for that item. | 7 |
| `resumeme-summary` | Collect matrix results for test/build consumers | Combined validated summary JSON and employer snapshots, not the input prompts. | 14 |
| `resumeme-skills` | Enabled skill generation after a signed tag release | Proposed skill names, supporting profile quotes, owner/tag identifiers, and source digest. | 30 |
| `resume-pdf` | Successful build, including ordinary branch/PR builds using saved inputs | Generic PDF, generated employer PDFs/manifest, brew date, and enabled README/preview publication files. | 14 |
| `resumeme-source` | Successful PDF build | Entire `tex/` directory, including generated text, images, and contribution data when used. | 14 |
| `signed-resume` | Successful tag signing | Publication directory plus generic PDF signatures, public key, fingerprint, checksums, and provenance. | 14 |
| `github-pages` | Enabled Pages preparation after accepted main publication | Static `index.html` and generic PDF at the configured path. | 7 |
| `resumeme-python-distributions` | Successful package build; later used for version-tag PyPI publication | Wheel and source archive, including package metadata and README content. | 14 |
| `resumeme-container` | Tag container build; later registry publication | Tested production container archive. | 7 |
| `python-coverage`, `textidote-reports` | Tests/document checks | Source-path coverage and document reports; reports can include excerpts of checked prose. | 14 |

On main publication, the bot stages the PDF, generated employer PDFs, enabled
README/preview files, and branding changes. A refresh also stages the full
accepted profile and its referenced images. Neither disabled display sections
nor AI prompt filtering restrict that snapshot commit. Git history, existing
assets, earlier variants, forks, and downloaded artifacts can retain older data;
removing a reference is not a repository-wide purge. Ordinary branch builds and
PR checks can upload artifacts containing already-committed personal data without
receiving any login secret.

Manually committed documents and conversation transcripts are publications too.
Review them for personal details, internal URLs, and credentials before committing;
the pipeline does not automatically redact their contents.

Tag releases attach the generic PDF and its verification files; employer PDFs in
the build artifact are not individually signed by the current signing script.
The signed release footer and notes disclose the release URL, public-key
fingerprint, source commit, and hashes. Main publication can expose employer
targets through committed configuration and variant paths as well as PDF text.

Pages serves the generic PDF and a landing page containing identity/profile links.
This project adds no visitor authentication. A custom domain or unlinked path is
not an access control; confirm the site's actual visibility separately from the
repository's visibility. Deleting a workflow artifact does not remove its
published Git commit, release, Pages deployment, or recipients' copies.

PyPI and container publishing can disclose custom content placed in README,
package resources, or source files. The production image does not copy `data/`,
browser profiles, or PDFs from the checkout, but its installed wheel carries
package metadata/README text. Docker's `type=gha` cache is separate, unencrypted
by this project, and can retain intermediate build layers containing source and
README content. The development build context also admits configuration and
scripts. Review package archives and build inputs before registry publication.

## Optional AI processing

`codex.enabled` prepares summaries on main/tag runs; `codex.skills.enabled`
independently prepares skill proposals on tag runs. `codex.skills.publish: false`
only stops LinkedIn writes, not generation or API use. The reference config
disables both generators; the author's active config may differ.

The summary prompt includes the public username, name, configured context and
limits, and filtered section titles, paragraphs, skill names, and nested roles.
It omits the structured Contact section, image objects, and ordinary profile-link
metadata. Employer variants additionally include the selected company/job text,
URLs, target context, and configured target overrides. Skill prompts include the
username, tag, source revision, selection context, and text lines from the same
filtered professional sections. A phone number, email, confidential detail, or
URL written inside ordinary prose/context is still text and can be sent.

The pinned upstream action receives the prompt and OpenAI API key. Its jobs use
repository read permissions, `permission-profile: ':read-only'`, and
`safety-strategy: drop-sudo`. Prompts instruct the model not to use tools and to
treat source text as data. These measures do not establish a prompt-only read
boundary: the checkout and restored full profile are present in the job, and a
read-only permission profile does not hide files. Do not put unrelated secrets
or private documents in that workspace. This project relies on the upstream
action's controls and does not create an additional locked-down model account.

Prompt/result files and action stdout/stderr can contain personal content. The
summary-input artifact uploads prompts as listed above. `--ephemeral` prevents
Codex session rollout persistence; it does not remove these files, suppress
Actions logs, or select an API retention policy.
[Codex non-interactive behavior](https://learn.chatgpt.com/docs/non-interactive-mode)
documents that flag.

OpenAI receives generation inputs and processes outputs under the API account's
data controls. Its documented default includes abuse-monitoring retention of up
to 30 days, with stated exceptions; endpoint/application state and approved
retention settings can differ. This project does not configure Zero Data
Retention or guarantee immediate provider-side deletion. Review the current
[OpenAI API data controls](https://developers.openai.com/api/docs/guides/your-data)
for the account you use. Disabling generation stops future calls, not previously
stored data. Validate generated claims before enabling automatic publication.

## Other network recipients and live writes

| Recipient | Data or access | Control and limit |
| --- | --- | --- |
| LinkedIn | Browser identity, login/MFA interaction, profile requests; enabled publishers send About changes, skill additions, or a PDF/recruiter-sharing setting | The browser has a real account session, not a narrowly scoped profile-read API token. Default publishers are off. Session reuse does not bypass challenges or guarantee continued access. |
| Image, project, icon, and employer/job hosts | Requested URL/path/query, source IP, request headers; downloaded content is parsed locally | Dedicated requests sessions do not inherit LinkedIn cookies, `.netrc`, or environment proxies. Preview/media requests clear cookies, check public addresses for each redirect, allow only HTTP(S) ports 80/443, and bound redirects/bytes. HTTP is permitted and is not encrypted in transit. |
| GitHub public contribution endpoint | GitHub username and requested dates | Unauthenticated public activity fetch; no additional token. Disabling the graph avoids that request. |
| Sigstore services | Signing/verification metadata and public-key identity for the PDF and checksum manifest | Current `cosign sign-blob --yes` uses default public transparency services. Expect public, durable signature/digest records even if the release is later deleted. |
| GitHub, PyPI, GHCR, Docker Hub and tool registries | Artifacts/publications described above and ordinary dependency/image/driver download requests | Each service has its own access and retention rules; public publication is not covered by the cache key. |

`capture.fetch_link_previews: false` disables external project-preview inspection,
not required profile-image downloads or separately enabled icons/employer fetches.
URL validation reduces local-network exposure but is not a network sandbox: DNS
is checked before the HTTP client's connection, and browser network access is
separate. Use runner-level egress controls if that boundary is required. Original
and resolved source URLs can retain query strings in snapshots/PDF links even
though diagnostic logging redacts URL queries. Review token-bearing links before
capture or publication. Clicking PDF links also contacts their destination.

The [release signing script](../scripts/release/sign.sh) signs locally with the
private key; it does not publish that key. Cosign's blob transparency metadata
is signature/hash/public-key information rather than an encrypted PDF archive.
Signing establishes integrity relative to a trusted key, not confidentiality or
truth of résumé claims. Public log records can link multiple releases to one key.
See [Cosign signing defaults](https://github.com/sigstore/cosign/blob/v3.1.3/cmd/cosign/cli/options/sign.go)
and [Rekor's immutable log](https://docs.sigstore.dev/logging/overview/).

The independent write switches are `linkedin.ownership.update_about`,
`codex.skills.publish`, and `linkedin.resume.publish`.
`linkedin.resume.share_with_recruiters` is an optional account-setting override
during resume publication. Review these before tagging: CI executes enabled
writes without a separate interactive review of each change. Disabling them
does not undo About edits, uploaded resumes, added skills, or sharing settings.

## Logs and debugging

Application logs default to `ERROR` and use OpenTelemetry JSON on stdout. This
package configures a console exporter, not a remote OpenTelemetry collector.
`DEBUG` adds request method, sanitized URL, timing, status/size, and browser/file
details. Redaction replaces configured environment secret values and sensitive
attribute names; URL userinfo is removed and query/fragment text is redacted.
Paths, names in ordinary text, profile slugs, and non-secret attributes may remain.
Redaction is not a general personal-information detector or a guarantee against
encoded/partial secret leakage.

Checkpoint notices expose classification, fixed detector names, readability, and
visible input/frame counts, not raw page text or cookies. Separate raw driver
logs, HTML, screenshots, compiler logs, plain CLI prints, Codex output, and shell
output are not all passed through that redaction filter. For example,
`publish-ownership --dry-run` prints the proposed About text and skill publication
prints names. GitHub's own secret masking also has limits. Review logs before
sharing; never enable shell tracing or attach the entire browser profile for a
bug report. Local logs remain until removed; hosted logs follow Actions settings.

## Disable, delete, or respond to exposure

1. Stop relevant workflows and active runs before changing credentials or
   cleaning storage. Otherwise a scheduled capture, tag, or retry can recreate
   data. Changes on `main` do not alter the code/configuration of an existing tag.
2. To stop session caching, remove all three `RESUMEME_CACHE_*` secrets and unset
   `RESUMEME_SESSION_CACHE_DIR`. Delete matching Actions caches and local persistent
   envelopes separately. Direct local CLI profiles still persist until removed.
3. Close the capture browser, then remove its dedicated `.cache/firefox/` or
   `.cache/chrome/`, raw `.cache/capture/` diagnostics, and abandoned
   `resumeme-browser-*` temporary directories as applicable. Clean profile/media,
   prompts, build output, and backups separately when no longer needed.
4. If session data or its decrypting identity was exposed, revoke the affected
   sessions in LinkedIn and replace exposed login credentials as appropriate.
   Cache deletion or encryption-key rotation alone does not invalidate cookies.
   Generate a fresh cache identity, delete old caches, and seed a new login only
   after the runner/repository is trusted again.
5. Rotate exposed API, GitHub, registry, or signing credentials at their issuing
   service. For a compromised signing key, publish the replacement fingerprint
   through a trusted channel and identify affected releases; generating a new
   key does not make old signatures trustworthy or erase transparency records.
6. Remove affected Actions artifacts/logs/caches, releases, Pages deployments,
   registry versions, and repository files/history as needed. Turning off Pages
   generation does not unpublish an existing site. Contact hosting support where
   necessary. Copies in forks, clones, search indexes, recipient downloads,
   backups, or transparency logs may remain beyond your control.

For upstream defects, use the private reporting route in [SECURITY.md](../SECURITY.md).
For fork credentials, infrastructure, or published personal data, contact the
fork owner. Send synthetic examples or sanitized excerpts, never working secrets.

## Implementation references

- [Browser capture](../pkg/resumeme/linkedin/browser.py), [CLI persistence](../pkg/resumeme/cli.py), and [public downloads](../pkg/resumeme/linkedin/media.py).
- [Session wrapper](../scripts/ci/linkedin-session.py), [archive cryptography](../pkg/resumeme/linkedin/session_cache.py), and [session action](../.github/actions/linkedin-session/action.yml).
- [Capture artifact allowlist](../scripts/ci/profile-artifact.py), [build uploads](../.github/workflows/stage-build.yml), and [main publication](../scripts/ci/publish.sh).
- [Summary evidence](../pkg/resumeme/compiler/passes/summary.py), [summary workflow](../.github/workflows/stage-summary.yml), and [skill workflow](../.github/workflows/stage-skills.yml).
- [Logging redaction](../pkg/resumeme/telemetry.py), [release attachments](../scripts/release/publish.sh), and [Pages workflow](../.github/workflows/stage-pages.yml).

Update this inventory when upload paths, credentials, cleanup, retention, or
external integrations change. Workflow settings describe requested behavior;
verify the actual fork and hosting settings before relying on them.
