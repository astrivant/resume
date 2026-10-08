# Monthly refresh and signed releases

The pipeline refreshes LinkedIn on the first day of every month at **06:17 UTC**
(`17 6 1 * *`). It captures the configured profile, downloads images and project
previews, runs the existing validation and PDF build, and commits the complete
snapshot, referenced assets, and PDF to `main` together. Ordinary pushes rebuild
the saved inputs. Neither path creates a release.

Forks publish a [personal README and PDF preview](#personal-readme) in that same
commit. Repositories retaining the project README also give the [project logo](assets/branding/resumeme-logo.png)
a fresh coffee stain. CI varies its orientation, proportions, placement, and
density using the verified source commit as a seed. Retries reproduce the same
logo; unchanged PDFs and profile inputs produce no extra commit. This uses the
bundled image layers and Pillow, with no image-generation API calls or secrets.
The linked **Brew date** badge below the logo shows the published PDF build's UTC
date and opens the configured résumé PDF. Build artifacts carry the date so
deployment retries preserve it. Only the marked branding block is updated in
project READMEs; surrounding documentation is retained.
The logo is README branding; it does not add stains to the résumé PDF.

## Configure a fork

Enable Actions, keep `main` as the default branch, and permit the workflow bot to
push generated updates through your branch rules. Set the login secrets using
the GitHub CLI's interactive prompts:

```bash
gh secret set LINKEDIN_USERNAME
gh secret set LINKEDIN_PASSWORD
```

- `LINKEDIN_USERNAME`: login email/account identifier, separate from the public
  profile slug in `resumeme.config.yaml`.
- `LINKEDIN_PASSWORD`: account password, passed only to capture or an explicitly enabled
  ownership update.
- `OPENAI_API_KEY`: needed only if `codex.enabled` is true; monthly builds then
  regenerate the About and portrait summaries from that same fresh capture.
- `COSIGN_PRIVATE_KEY` and optional `COSIGN_PASSWORD`: needed when publishing a
  signed tag release, not for monthly refreshes. The private-key secret contains
  the entire Cosign PEM, including its header, footer, and newlines; the password
  is required only for encrypted keys.
- `GH_TOKEN` / `GITHUB_TOKEN`: supplied by Actions; no personal access token is
  needed. The workflow uses `contents: write` for generated commits and releases,
  and `packages: write` for the container. Repository rules must permit those writes.
- `PYPI_API_TOKEN`: package maintainers only. Version-tag releases map the organization,
  repository, or `pypi` environment secret to `POETRY_PYPI_TOKEN_PYPI`. Resume-only
  forks do not need it; see [package publication](development.md#publish-to-pypi).

The runner uses headless Firefox or Chrome, selected by `capture.browser` with
Firefox as the default. Browser state and diagnostics stay in its
temporary workspace; only the profile and referenced downloaded media are
transferred to downstream jobs. No browser cookies or passwords enter commits
or uploaded capture artifacts.

## Personal README

On a fork's first successful publication to `main`, CI replaces the inherited logo
and project instructions with the owner's name, a short introduction, a first-page
image linked to the complete PDF, and LinkedIn, optional GitHub, and release links.
The preview is committed at `docs/assets/resume-preview.png`. The PDF link follows
`output.pdf`; release links always target the publishing repository. The page count
comes from the actual PDF, and the name comes from the matching captured profile.
Hidden headline and contact fields are not copied into the introduction.

```yaml
readme:
  mode: auto
  introduction: null
```

| Setting | Behavior |
| --- | --- |
| `mode: auto` | Default: generate on repositories GitHub identifies as forks; preserve the upstream project README |
| `mode: resume` | Generate a personal page even in a standalone repository |
| `mode: project` | Preserve the existing README, including manual customizations |
| `introduction: null` | Use the shared résumé introduction |
| `introduction: "Platform engineer building reliable developer infrastructure."` | Replace the introduction with plain text; Markdown and HTML are escaped |

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

Generated README edits are overwritten on the next publication. Set `mode: project`
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

Manual runs without `refresh=true` use committed inputs. Refreshing another branch
is rejected. Capture, validation, or compilation failures leave `main` unchanged;
there is no fallback to an older capture reported as a successful refresh. If
`main` advances during verification, publication skips the stale update. Retry
the refresh on the new head when needed.

GitHub schedules run only from the default branch, can be delayed, and may be
disabled after 60 days without repository activity in public repositories.
Check the Actions tab if an expected refresh is missing. See
[GitHub's schedule behavior](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

## Authentication recovery

LinkedIn can require MFA, a CAPTCHA, or another account challenge, particularly
from a hosted runner. Unattended login waits for the existing page timeout and
then fails with an actionable error. It does not repeatedly submit passwords or
attempt to bypass challenges. Local capture keeps its unlimited interactive wait:

```bash
poetry run resumeme capture
poetry run resumeme validate
```

Complete any challenge in the selected browser, then commit the accepted snapshot and assets
and push them to `main`. Update incorrect secrets and rerun the refresh. Accounts
that consistently require interaction can use this local capture path; scheduled
authentication cannot guarantee unattended access.

## Choose a version to share

Wait for the PDF update on `main`, then tag that exact commit. Use a résumé tag
such as `resume-2026-10` to avoid triggering the separate `v<version>` PyPI release:

```bash
git switch main
git pull --ff-only
git tag resume-2026-10
git push origin resume-2026-10
```

After verification, the tag workflow takes the **PDF already committed at that
revision** and adds a light-gray footer on its last page with the exact release
link and signing key fingerprint. It preserves the selected content, layout, and
generated summaries, then signs the PDF including that footer. It releases
the PDF, Cosign signature bundles, public key, SHA-256 manifest, key fingerprint,
and source revision. The container stage then appends its pull instructions to
the same release. See [signature verification](README.md#signed-releases).

Tag releases do not update `main` or choose a newer document. If
`linkedin.ownership.update_about` is enabled, a separate job signs in after
publication to maintain the public signing fingerprint and releases link in
About. See [configuration, previews, and recovery](ownership.md).
Reruns reconcile the same tag; an existing public PDF is never replaced. Share
the release's PDF and verification files with the intended recipient.
