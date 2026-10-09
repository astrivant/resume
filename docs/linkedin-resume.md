# Saved application resumes

[Project README](../README.md) | [CLI reference](CLI.md#resumeme-publish-resume)

Upload each signed release PDF to LinkedIn's **Jobs > Preferences > Resumes and
application data**. This makes the file available for future LinkedIn job
applications. It does not submit an application or add a Featured post.

## Enable tag uploads

Set the opt-in in `resumeme.config.yaml`, commit it, and tag that revision:

```yaml
linkedin:
  username: your-linkedin-username
  resume:
    publish: true
    replace_existing: false
    share_with_recruiters: null
```

The package, reference config, and checked-in personal config default to `false`.
Use the existing Actions secrets `LINKEDIN_USERNAME` (login email or phone) and
`LINKEDIN_PASSWORD`. Public usernames and profile URLs identify an account but
require interactive sign-in, so they cannot authenticate this headless job.
Signed releases also require the [signing secrets](../README.md#configure-signing-secrets).

The separate `linkedin-resume-stage` runs after a successful signed release on a
tag push. It downloads this run's `signed-resume` artifact, verifies the Cosign
signatures and checksum manifest, and uploads that exact PDF. It never uses the
PDF committed in the tag or rebuilds the signed document. The browser step
receives only the LinkedIn credentials; no signing key or OpenAI key is needed.
Branch pushes, monthly refreshes, and pull requests do not upload resumes.

Uploads are serialized per repository. Inside that job, the tag must match
GitHub's current latest release; older tags and prereleases that are not latest
are skipped. A failure in this optional job leaves the signed release available.

## LinkedIn behavior

LinkedIn stores the [four most recently uploaded resumes](https://www.linkedin.com/help/linkedin/answer/a510363)
for reuse. Each new document gets a filename such as
`emma-doyle-resume-0123456789abcdef.pdf`: the captured profile name is normalized
to an ASCII slug, followed by the first 16 hexadecimal characters of the PDF's
SHA-256 digest. This distinguishes revisions and lets retries skip a file
already present. With `linkedin.resume.replace_existing: false` (the package and
reference-config default), older saved resumes remain available. Set it to
`true` to remove every other saved resume after the new PDF is confirmed. The
publisher uses the resume's own options menu and verifies each deletion after a
fresh settings load. It preserves the new release PDF, does not change other
application settings, and fails closed if it cannot bind a delete control to a
specific filename. A failed removal leaves the new PDF saved and reports that
older files may remain. LinkedIn's menu path is documented as the ellipsis next
to a resume, then **Delete** in its [resume management guide](https://www.linkedin.com/help/linkedin/answer/a510363/upload-your-resume-to-linkedin).
Review the selected resume when applying: uploading does not guarantee that
LinkedIn will select it for every application or transfer it to external
employers' application sites.

Replacement is a destructive account change. When enabled, the publisher removes
previous saved resumes from LinkedIn after a successful upload; previously
submitted job applications are unaffected. Dry runs never delete files. This
repository enables replacement in its personal config, while the copyable
reference config leaves it disabled.

`linkedin.resume.share_with_recruiters` controls the account's **Share resume data
with recruiters** setting after the PDF is confirmed saved:

- `null` (default): retain the current LinkedIn setting.
- `true`: enable recruiter sharing.
- `false`: disable recruiter sharing.

The override applies during `publish-resume` and its tag job, including when the
same PDF is already saved. Live changes require `linkedin.resume.publish: true`.
It is an account-wide setting for saved resume data, not a per-file permission.
**Save resumes and application data** remains unchanged. When sharing is enabled,
LinkedIn can use saved resume data for recruiter
searches; recruiters do not receive the full PDF through that setting alone.
See [LinkedIn's sharing guide](https://www.linkedin.com/help/linkedin/answer/a1327213).

LinkedIn recommends files smaller than 2 MB. Larger PDFs produce a warning and
remain unchanged; the site decides whether to accept them. Resumeme never
recompresses signed bytes. Reduce document content before creating a new release
if LinkedIn rejects its size.

## Preview and recovery

Download the release assets and [verify their signatures](README.md#signed-releases)
before selecting a local PDF. Paths below are relative to the config directory:

```bash
resumeme publish-resume --pdf .cache/publication/resume.pdf --dry-run
resumeme publish-resume --pdf .cache/publication/resume.pdf
```

`--dry-run` validates the PDF, signs in, confirms ownership of `linkedin.username`,
and checks the upload form and any requested recruiter-sharing override without
changing LinkedIn. It works with publication disabled and prints the requested
sharing state when an override is set. The live command requires
`linkedin.resume.publish: true`. Local use
does not independently verify Cosign signatures or require a Git tag; the CI job
performs those checks before invoking it.

Both commands use `capture.browser` (`firefox` by default, or `chrome`). Without
`--headless`, complete login and MFA in the browser with no login deadline.
Headless authentication challenges fail the job and require an interactive retry.

The publisher sends the file at most once per invocation, then reloads settings
to confirm the saved filename. Transient reads use the configured exponential
backoff. If confirmation fails, inspect the settings page for that filename or
an upload error before retrying the same PDF. An uncertain upload may already
have succeeded. Retries skip an existing copy; they do not delete or reorder it.
An explicit sharing override reads the current switch before clicking and verifies
the result after reloading settings. An uncertain click is not repeated within
the command; read retries use the same backoff. If sharing fails, the PDF remains
saved and the job fails. Inspect the setting and retry the same PDF to reconcile.
This recovery command does not update About, skills, or previous applications.
