---
name: resumeme
description: >-
  Generate a resume PDF from a user's LinkedIn profile with this repository's
  Python CLI. Use for first-time setup, interactive Firefox capture, rebuilding
  saved profile data, or applying resume configuration changes. Includes optional
  GitHub publication when requested.
---

# Generate a LinkedIn résumé PDF

Produce the user's PDF using this project's existing capture, validation, and
build commands. A successful local build is the default deliverable. This file
is plain Markdown with skill frontmatter: agents can read it directly without a
particular editor, plugin, or skill installer.

## Establish the inputs

Work in the existing `resumeme` checkout containing `pyproject.toml`, `poetry.lock`,
and `resumeme.config.yaml`. If this skill was copied elsewhere, locate the checkout
first; all paths below are relative to that checkout. Inspect `git status --short`
and preserve existing changes.

Use the LinkedIn username supplied or previously confirmed by the user. For a
profile URL, use the slug after `/in/`. A new fork can still contain the original
author's username, snapshot, and PDF; establish whose profile is wanted before
reusing those inputs. Ask for the username only when the conversation and existing
configuration do not establish it.

Set `linkedin.username` in `resumeme.config.yaml`, preserving comments and other
settings. Apply section exclusions, job filters, or styling changes only as
requested; see [configuration](docs/README.md#configuration) and
[themes](docs/themes.md). Paths in `output` are relative to the config directory.
For a custom config, put the global option before the subcommand:

```bash
poetry run resumeme --config path/to/config.yaml build
```

Choose the appropriate starting point:

- First run, a different owner, or requested LinkedIn updates: capture first.
- Layout-only changes or a requested rebuild: reuse the matching saved snapshot.
  Validation checks ownership; changing the username does not fetch new data.
- Link resolution or preview refresh on acquired text: run `poetry run resumeme enrich`
  against the saved snapshot, then validate and build. This makes bounded public
  HTTP requests and needs no Firefox session. Original text and URLs are retained;
  the snapshot gains resolved destinations, page titles, and cached previews.

## Prepare the local environment

Use Python 3.13+, Poetry 2.5.1, Firefox for capture, and a running Docker daemon
for the default local PDF build. On macOS, follow the
[Homebrew bootstrap](docs/README.md#install); `Brewfile` supplies host tools, and
the bootstrap installs the pinned Poetry version. On other hosts, use equivalent
tools and a graphical session for Firefox. Reuse an existing working environment.

Install runtime dependencies from the committed lockfile:

```bash
export POETRY_VIRTUALENVS_IN_PROJECT=true
export POETRY_KEYRING_ENABLED=false
export POETRY_INSTALLER_RE_RESOLVE=false
export MPLCONFIGDIR="$PWD/.cache/matplotlib"
poetry check --lock
poetry install --only main --no-interaction
poetry run resumeme --help
```

Use the project environment even if the agent inherited an unrelated activated
virtualenv. Follow the bootstrap's `poetry env use` step when selecting Python.
Keep the committed dependency resolution; normal PDF generation does not need
`poetry update`, a new lockfile, or development dependencies.

## Capture with the user present

Run capture in a persistent process whose lifetime allows the user to sign in:

```bash
poetry run resumeme capture
```

Once Firefox opens, tell the user to sign in there, complete any MFA, and leave
the window open. The command detects login completion automatically and has no
login deadline. Keep the process running while the user finds their password;
poll its status without imposing a short overall command timeout or starting
duplicate captures. Login credentials can be entered in Firefox or supplied using
`LINKEDIN_USERNAME` and `LINKEDIN_PASSWORD`; never request or print secret values
in chat. Interactive capture still waits for manual MFA. The explicit `--headless`
mode is for unattended CI and fails when an account challenge requires interaction.

Wait for capture to finish successfully before validating or building. It saves
the snapshot and downloaded media at the configured paths, normally
`data/profile.json` and `data/assets/`. The session persists under ignored
`.cache/firefox/`; preserve it for retries. Capture already applies capped
exponential backoff to transient failures. See
[local capture](docs/README.md#local-capture) for browser attachment and diagnostics.

If the window closes, rerun capture after addressing that failure. If capture
reports incomplete content, inspect `.cache/capture/` and the reported error;
correct the cause before retrying. Avoid repeated full captures without a changed
condition. Use `--allow-incomplete` only when the user explicitly accepts the
reported omissions; otherwise surface the blocker and retain the last good inputs.

## Validate, build, and inspect

Run these sequentially, proceeding only after each succeeds:

```bash
poetry run resumeme validate
docker info >/dev/null
poetry run resumeme build
```

Start Docker Desktop on macOS if needed. The build renders Jinja templates and
runs two pdfLaTeX passes in the pinned TeX image. A host LaTeX installation is
unnecessary. For a render-only diagnosis, run `poetry run resumeme render`; generated
TeX alone is not the finished deliverable. Compiler logs are in `.cache/build/`.

Confirm that this build succeeded and that the configured PDF exists and is
nonempty. An older `resume.pdf` may remain after a failed build, so its presence
alone is not success. Inspect the new PDF with the available viewer or PDF tools,
checking the owner's identity, enabled sections, text clipping, images, and links.
The skill cloud displays at most 20 skills ranked by references plus twice each
endorsement; the score manifest retains all scored skills.

Return a link to the actual output path (normally `resume.pdf`), note whether the
snapshot was refreshed or reused, and report validation/build results and any
remaining limitation. If browser or Docker access is unavailable, identify the
missing capability and the next runnable command instead of claiming completion.

## Publish when requested

For an authorized push or signed release, continue with the
[fork setup](docs/automation.md#configure-a-fork) and
[signed release workflow](docs/README.md#signed-releases). Reuse authorization
already given in the conversation; local PDF generation alone does not require
GitHub setup or publication.

Review the captured contact information and media that will be published. Stage
only the intended config, snapshot, and assets, using their configured paths;
preserve unrelated staged work. Keep browser sessions, diagnostics, and signing
keys outside commits. Configure the fork's `COSIGN_PRIVATE_KEY` and, for an
encrypted key, `COSIGN_PASSWORD` through GitHub secrets without printing their
contents. Actions supplies the publication token.

A push to `main` builds the committed snapshot and commits the PDF back. Monthly
or manually requested refreshes authenticate to LinkedIn with Actions secrets and
commit fresh inputs alongside the PDF after verification. User-created tags sign
the PDF already committed at that revision and publish its verification artifacts.
Follow [monthly refresh and release](docs/automation.md); report hosted success
only after the corresponding pipeline completes. Container publication follows
the signed release on the same tag.
