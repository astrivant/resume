# Publish your signing identity on LinkedIn

Resumeme can maintain two lines in your live LinkedIn About section:

```text
resume signature: SHA256:<public-key fingerprint>
releases: https://github.com/OWNER/REPO/releases
```

The fingerprint is SHA-256 of the public key's canonical DER encoding, identical
to `key-fingerprint.txt` in each signed release. It identifies the signing key,
not the PDF hash. Readers can compare it with the released key and verify the
PDF's signature. Your existing About text stays intact; subsequent updates replace
only this pair of lines, including when you rotate keys.

## Configure your fork

```yaml
linkedin:
  username: your-linkedin-slug
  ownership:
    update_about: true
    repository: null
    releases_url: null
```

- `update_about`: opt in to the live update after a signed tag release. Defaults
  to `false`; capture, rendering, and monthly refreshes do not edit your profile.
- `repository`: `OWNER/REPO`, or `null` to use `GITHUB_REPOSITORY` in Actions and
  the GitHub `origin` remote locally. It is independent of `github.username`.
- `releases_url`: optional HTTPS short link that **you configure to redirect to
  your releases page**. Resumeme publishes it verbatim; it does not create or
  verify the redirect. `null` uses the repository's full GitHub releases URL.

Existing repository secrets are sufficient:

- `COSIGN_PRIVATE_KEY`: PEM private key used by the signing stage.
- `COSIGN_PASSWORD`: password when that key is encrypted.
- `LINKEDIN_USERNAME`: LinkedIn login email or phone for headless authentication.
- `LINKEDIN_PASSWORD`: LinkedIn login password.

The ownership job runs separately after release publication, verifies the signed
PDF and manifest, and derives the fingerprint from the verified `cosign.pub`.
Only the browser step receives LinkedIn credentials. The private signing key is
not passed to this job. Updates are serialized per repository, and a rerun of a
tag that is no longer GitHub's latest release is skipped. Container publication
proceeds independently if the browser update fails.

## Preview or update locally

Download the public key from the release you want to associate with your profile:

```bash
mkdir -p .cache/ownership-release
gh release download --repo OWNER/REPO --pattern cosign.pub --dir .cache/ownership-release
resumeme publish-ownership --public-key .cache/ownership-release/cosign.pub --dry-run
resumeme publish-ownership --public-key .cache/ownership-release/cosign.pub
```

The first command opens the browser selected by `capture.browser` (Firefox by
default, or Chrome) and previews the complete About text without
saving. The second explicitly updates the live profile, regardless of the CI
`update_about` setting. It requires no captured snapshot. Use `--headless` with
the LinkedIn environment variables for unattended operation, or `--connect-port`
to attach to an existing Firefox Marionette session with `capture.browser: firefox`. Interactive login waits
until you finish; unattended challenges fail after the configured page timeout.

Use LinkedIn's English interface. The updater checks the configured profile's
owner edit controls, reads its About editor, and preserves its existing text.
Before submitting, it saves a private local backup under `.cache/ownership/`.
After Save, it reopens the editor to verify persistence. Backups and browser state
are ignored by Git and excluded from CI artifacts; retain a local backup if you
need recovery after an ephemeral Actions run.

Retries use `capture.retry_*` and re-read current About text before another write.
If a previous Save succeeded, no second Save occurs. Concurrent edits, ambiguous
or duplicated ownership lines, and text exceeding the editor's limit fail without
truncating your About. A browser failure after Save can leave the update applied;
inspect your profile or rerun the command to reconcile it. Authentication failures
do not undo the already published release.

The local command uses the public key you supply; use the release verification
procedure before relying on a key from an untrusted download. It never asks for
or publishes a private key.

## Verify the association

Download `cosign.pub` and the verification artifacts from the linked release.
Compute the public fingerprint:

```bash
openssl pkey -pubin -in cosign.pub -outform DER | openssl dgst -sha256
```

Compare the hexadecimal digest with the `SHA256:` value in About and
`key-fingerprint.txt`, then follow the [PDF signature verification steps](README.md#signed-releases).
Matching About text associates that LinkedIn account with the signing key;
verification establishes that the corresponding key signed the downloaded PDF.
Older releases retain their original keys and fingerprints after rotation.
