# Monthly refresh and signed releases

The pipeline refreshes LinkedIn on the first day of every month at **06:17 UTC**
(`17 6 1 * *`). It captures the configured profile, downloads images and project
previews, runs the existing validation and PDF build, and commits the complete
snapshot, referenced assets, and PDF to `main` together. Ordinary branch pushes rebuild
the saved inputs. Neither path creates a release.

Every tag push also performs a headless LinkedIn capture before validation and
compilation. The release signs the fresh PDF built in that same workflow run,
not the PDF committed at the tag. Tags require the LinkedIn login secrets and
do not commit their capture or PDF to `main` or deploy Pages.

Enable `pages.enabled` to also update a [GitHub Pages website](pages.md) after
that commit is accepted. The optional stage serves `index.html` and the same PDF
at the configured site path, including custom domains.

Forks publish a [personal README and PDF preview](#personal-readme) in that same
commit. Repositories retaining the project README also give the [project logo](https://raw.githubusercontent.com/astrivant/resumeme/main/docs/assets/branding/resumeme-logo.png)
a fresh coffee stain. CI varies its orientation, proportions, placement, and
density using the verified source commit as a seed. Retries reproduce the same
logo; unchanged PDFs and profile inputs produce no extra commit. This uses the
bundled image layers and Pillow, with no image-generation API calls or secrets.
The linked **Brew date** badge beside the project badges shows the published PDF build's UTC
date and opens the configured résumé PDF. Build artifacts carry the date so
deployment retries preserve it. Only the marked logo and date-badge regions are updated in
project READMEs; surrounding documentation is retained.
The logo is README branding; it does not add stains to the résumé PDF.

## Configure a fork

Copy [resumeme.config.ref.yaml](../resumeme.config.ref.yaml) to `resumeme.config.yaml`,
set `linkedin.username`, and capture your own profile before publishing. The
reference keeps optional integrations disabled and uses `readme.mode: auto` with
`readme.output: README.md`; it contains no personal exclusions or date window.

Enable Actions, keep `main` as the default branch, and permit the workflow bot to
push generated updates through your branch rules. Set the login secrets using
the GitHub CLI's interactive prompts:

```bash
gh secret set LINKEDIN_USERNAME
gh secret set LINKEDIN_PASSWORD
```

- `LINKEDIN_USERNAME`: accepts a login email/phone, public username, or LinkedIn
  `/in/` profile URL. URLs are normalized to usernames and public identifiers must
  match the configured owner. Use an email/phone for headless CI; public usernames
  and URLs use manual sign-in during interactive capture. No additional login
  variable is needed. Headless use of a public identifier fails before opening a browser.
- `LINKEDIN_PASSWORD`: account password, passed only to capture or explicitly enabled
  ownership/skill updates or saved resume uploads. A login identifier and password are required for tag, monthly, and
  requested manual captures.
- `OPENAI_API_KEY`: needed if `codex.enabled` or `codex.skills.enabled` is true.
  Create it on the [OpenAI API keys page](https://platform.openai.com/api-keys) and save it as an Actions secret.
  The first enables main-branch and tag summaries; the second enables tag-only skill proposals.
- `COSIGN_PRIVATE_KEY` and optional `COSIGN_PASSWORD`: needed when publishing a
  signed tag release, not for monthly refreshes. The private-key secret contains
  the entire Cosign PEM, including its header, footer, and newlines; the password
  is required only for encrypted keys.
- `GH_TOKEN` / `GITHUB_TOKEN`: supplied by Actions; no personal access token is
  needed for unprotected branches. The workflow uses `contents: write` for generated
  commits and releases,
  and `packages: write` for the container. The optional Pages deployment uses
  `pages: write`, `id-token: write`, `actions: read`, and `contents: read`.
  Repository rules must permit those writes.
- `RESUME_PUBLISH_TOKEN`: required for direct PDF commits when branch protection
  requires reviews or status checks. Use a repository-scoped contents-write token
  owned by an administrator or another actor permitted to bypass both rules.
  It is used only by the verified main publication job; unprotected forks can omit
  it. See [repository settings](development.md#repository-settings-and-reviews)
  before enabling the protection declared in `.github/settings.yml`.
- `PYPI_API_TOKEN`: package maintainers only. Version-tag releases map the organization,
  repository, or `pypi` environment secret to `POETRY_PYPI_TOKEN_PYPI`. Resume-only
  forks do not need it; see [package publication](development.md#publish-to-pypi).
- `DOCKER_HUB_TOKEN_EMMEOWZING`: upstream maintainers only. Grant `astrivant/resumeme`
  access to this organization Actions secret for tag-only pushes to
  `emmeowzing/resumeme`. Forks skip this job; see [container publication](containers.md#publish-on-a-tag).

`linkedin.username` accepts a public username or a profile URL such as
`https://www.linkedin.com/in/your-name/`. URLs are normalized to the username,
discarding tracking parameters and fragments. Configuration remains authoritative
for profile selection; login secrets do not silently switch the captured owner.
Public profile identifiers cannot reveal the account's private login email.

The runner uses headless Firefox or Chrome, selected by `capture.browser` with
Firefox as the default. Browser state and diagnostics stay in its
temporary workspace; only the profile and referenced downloaded media are
transferred to downstream jobs. No browser cookies or passwords enter commits
or uploaded capture artifacts.

## Personal README

See [the fork example](../FORK_EXAMPLE.md) for the generated landing page using this project's current profile and PDF.

With the default destination, a fork's first successful publication to `main` replaces
the inherited logo and project instructions with the owner's name, a short introduction, a first-page
image linked to the complete PDF, and LinkedIn, optional GitHub, and release links.
The preview is committed at `docs/assets/resume-preview.png`. The PDF link follows
`output.pdf`; release links always target the publishing repository. The page count
comes from the actual PDF, and the name comes from the matching captured profile.
Hidden headline and contact fields are not copied into the introduction.

```yaml
readme:
  mode: auto
  output: README.md
  introduction: null
```

| Setting | Behavior |
| --- | --- |
| `mode: auto` | Default: generate on repositories GitHub identifies as forks; preserve the upstream project README |
| `mode: resume` | Generate a personal page even in a standalone repository |
| `mode: project` | Preserve the existing README, including manual customizations |
| `output: README.md` | Default destination; replace the repository landing page |
| `output: FORK_EXAMPLE.md` | Publish the same page separately and retain the project README and its coffee branding |
| `introduction: null` | Use the shared résumé introduction |
| `introduction: "Platform engineer building reliable developer infrastructure."` | Replace the introduction with plain text; Markdown and HTML are escaped |

This repository sets `mode: resume` and `output: FORK_EXAMPLE.md` to exercise the
publication flow and keep a current example for adopters. Copying the reference
configuration selects `output: README.md` for your landing page. Forks retaining
the author's config can set that field directly. `mode: auto` restricts generation
to forks; `mode: resume` also generates in
standalone repositories. Nested paths such as `docs/examples/resume.md` are
supported, with PDF, configuration, and documentation links relative to
the destination. Images use absolute `raw.githubusercontent.com` URLs targeting
the publishing repository's `main` branch, so they also render outside GitHub.
Paths must stay inside the repository and must not overwrite
configured inputs or other outputs.

Names, profile links, and PDF paths are parameterized automatically. After changing
owners, capture the new owner's profile before pushing; a username mismatch fails
the build. A profile with only a name is sufficient. Set `github.username` to your
own account or `null` to omit that link.

Every PDF publication refreshes the README and preview together, including monthly
captures and ordinary pushes. CI renders page one with Ghostscript from the pinned
TeX image, then passes it with the PDF to deploy. No extra credentials or host
packages are needed. The preview retains the PDF's paper proportions and colors.
Retries produce identical output, and unchanged artifacts do not create extra commits.
Preview failures block publication; stale runs cannot overwrite newer `main` commits.

Edits to the configured output are overwritten on the next publication. Set `mode: project`
before maintaining your own page; the current README and preview remain in place.
Tag releases, pull requests, and non-main branches never replace the tracked README.
Configuration and operation instructions remain available in [the documentation](README.md),
including [installation](README.md#install) and the [agent workflow](../SKILL.md).

## Run or adjust the schedule

Edit `on.schedule` in `.github/workflows/ci.yml` to change the cadence. To run the
same refresh now, select **Run workflow -> main -> refresh**, or run:

```bash
gh workflow run ci.yml --ref main -f refresh=true
```

Manual runs without `refresh=true` use committed inputs. Manual refreshes on another
branch or tag are rejected; tag pushes refresh automatically. Capture, validation,
or compilation failures leave `main` unchanged and block new release publication;
there is no fallback to an older capture reported as a successful refresh. If
`main` advances during verification, publication skips the stale update. Retry
the refresh on the new head when needed.

GitHub schedules run only from the default branch, can be delayed, and may be
disabled after 60 days without repository activity in public repositories.
Check the Actions tab if an expected refresh is missing. See
[GitHub's schedule behavior](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

## Authentication recovery

LinkedIn can require MFA, a CAPTCHA, or another account challenge, particularly
from a hosted runner. Waiting for a usable login form uses
`capture.page_timeout_seconds` and the configured exponential retry policy.
Capture supports both LinkedIn's fixed-ID login form and generated-ID layouts
using autocomplete attributes and a regular Sign in button. It selects visible
controls and waits for the submit button to enable after filling the fields.
Autocomplete matching accepts token lists such as `username webauthn`, including
when LinkedIn enables passkey support while the form is being filled.
Credentials are submitted once. If that click times out during navigation, the
client checks the existing session for login completion without submitting again.
Unattended authentication then waits for the page timeout and reports the failed
stage and a sanitized page category, such as `login` or `checkpoint`. Challenges
require interactive completion. Local capture keeps its unlimited interactive wait:

```bash
poetry run resumeme capture
poetry run resumeme validate
```

Complete any challenge in the selected browser, then commit the accepted snapshot and assets
and push them to `main`. Update incorrect secrets and rerun the refresh. Accounts
that consistently require interaction can use this local capture path for ordinary
branch builds. Tag releases now require a successful headless capture; committing
a local snapshot does not bypass that requirement. Unattended authentication is
not guaranteed from a hosted runner.

For a failed About, skills, or saved resume publication, run the corresponding
`publish-ownership`, `publish-skills`, or `publish-resume` command locally without
`--headless`; committing a captured snapshot does not apply those account updates.
For a resume upload, use the verified signed release PDF. See [CLI commands](CLI.md).

## Choose a version to share

Commit and push the configuration you want to use, then tag that revision. Its
pipeline captures your current LinkedIn profile and builds a new PDF. Use a résumé tag
such as `resume-2026-10` to avoid triggering the separate `v<version>` PyPI release:

```bash
git switch main
git pull --ff-only
git tag resume-2026-10
git push origin resume-2026-10
```

The source stage exports one complete `resumeme-profile` capture for this run.
Validation, enabled summaries, compilation, and optional skill proposals use that
same capture. After verification, the release job downloads **this run's
`resume-pdf` artifact** and adds a light-gray footer on its last page with the exact
release link and signing key fingerprint. It preserves the freshly compiled body
and generated summaries, then signs the PDF including that footer. It releases
the PDF, Cosign signature bundles, public key, SHA-256 manifest, key fingerprint,
and source revision. The container stage then appends its pull instructions to
the same release. See [signature verification](README.md#signed-releases).

When `codex.skills.enabled` is true, a separate stage generates an evidence-backed
`resumeme-skills` artifact. Set `codex.skills.publish: true` to add missing skills
to LinkedIn after publication. All existing skills and endorsements are retained;
see [skill proposals and publication](skills.md).

Missing credentials, an authentication challenge, an incomplete capture, or a
missing build artifact fails the pipeline instead of publishing an older PDF.
The capture artifact is retained for seven days and the PDF build artifact for
fourteen days. `source.json` identifies the tagged code revision; the live capture
is an input artifact from the run, not a change to that Git commit.

Tag releases do not update `main` or the Pages website. If
`linkedin.ownership.update_about` is enabled, a separate job signs in after
publication to maintain the public signing fingerprint and releases link in
About. See [configuration, previews, and recovery](ownership.md).

Set `linkedin.resume.publish: true` to upload the same verified `signed-resume`
artifact to LinkedIn's saved application resumes in another job. This opt-in
defaults to false and uses the existing LinkedIn secrets. An optional
`linkedin.resume.share_with_recruiters` override enables (`true`) or disables
(`false`) recruiter sharing after upload; `null` preserves the account setting.
The job checks that its tag is GitHub's latest release before
uploading; an older tag's retry is skipped. See [application resume uploads](linkedin-resume.md).

Public release PDFs are never replaced on retries. Rerunning failed downstream
jobs can reuse the completed capture and build from that run; rerunning all jobs
captures again and can produce a different PDF that cannot replace an already
public release. Use a new tag for updated content or pipeline fixes. Rerunning an
old tag does not pick up workflow changes committed later on `main`. Share the
release's PDF and verification files with the intended recipient.
