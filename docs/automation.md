# Monthly refresh and signed releases

The pipeline refreshes LinkedIn on the first day of every month at **06:17 UTC**
(`17 6 1 * *`). It captures the configured profile, downloads images and project
previews, runs the existing validation and PDF build, and commits the complete
snapshot, referenced assets, and PDF to `main` together. Ordinary pushes rebuild
the saved inputs. Neither path creates a release.

Every generated résumé commit also gives the [project logo](assets/branding/resumeme-logo.png)
a fresh coffee stain. CI varies its orientation, proportions, placement, and
density using the verified source commit as a seed. Retries reproduce the same
logo; unchanged PDFs and profile inputs produce no extra commit. This uses the
bundled image layers and Pillow, with no image-generation API calls or secrets.
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
- `LINKEDIN_PASSWORD`: account password, passed only to the capture step.
- `OPENAI_API_KEY`: needed only if `codex.enabled` is true; monthly builds then
  regenerate the About and portrait summaries from that same fresh capture.
- `COSIGN_PRIVATE_KEY` and optional `COSIGN_PASSWORD`: needed when publishing a
  signed tag release, not for monthly refreshes.

The runner uses headless Firefox. Browser state and diagnostics stay in its
temporary workspace; only the profile and referenced downloaded media are
transferred to downstream jobs. No browser cookies or passwords enter commits
or uploaded capture artifacts.

## Run or adjust the schedule

Edit `on.schedule` in `.github/workflows/ci.yml` to change the cadence. To run the
same refresh now, select **Run workflow → main → refresh**, or run:

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

Complete any challenge in Firefox, then commit the accepted snapshot and assets
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

After verification, the tag workflow signs the **PDF already committed at that
revision**, preserving the selected content and generated summaries. It releases
the PDF, Cosign signature bundles, public key, SHA-256 manifest, key fingerprint,
and source revision. The container stage then appends its pull instructions to
the same release. See [signature verification](README.md#signed-releases).

Tag releases do not sign in to LinkedIn, update `main`, or choose a newer document.
Reruns reconcile the same tag; an existing public PDF is never replaced. Share
the release's PDF and verification files with the intended recipient.
