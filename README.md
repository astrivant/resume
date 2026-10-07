# resume

**Build and release your résumé like software.** Turn your LinkedIn profile into an
illustrated PDF with versioned content, reproducible builds, and signed GitHub
releases. Fork the project, set your username, capture your profile, and let a push
to `main` handle the publishing.

**[View the résumé (PDF)](resume.pdf)** · [Fork this project](https://github.com/astrivant/resume/fork)

## Contents

- [Quick start](#quick-start)
- [Fork environment variables](#fork-environment-variables)
- [Why use resume?](#why-use-resume)
- [How it works](#how-it-works)
- [Update your résumé](#update-your-résumé)
- [Development](#development)

## Quick start

In your fork's local checkout, install the package. Local capture requires
Python 3.13+, Poetry 2.1.3, and Firefox. GitHub Actions handles PDF compilation;
Docker is needed only for a local PDF preview.

```bash
poetry install --only main
poetry run resume --help
```

Change **one profile setting** in [resume.reference.yaml](resume.reference.yaml):

```yaml
linkedin:
  username: your-linkedin-username
```

Capture your profile and check the saved snapshot:

```bash
poetry run resume capture
poetry run resume validate
```

Sign in to LinkedIn in the Firefox window and leave it open. Capture waits for you
to finish signing in, then saves your profile and images locally. **A username
change alone does not fetch a profile in CI:** Actions builds the snapshot you push.

Before your first push, enable Actions in your fork, allow it to write repository
contents, and configure the [fork environment variables](#fork-environment-variables).
Branch rules must allow the bot's PDF commit. This setup is required once per fork.

Review `data/profile.json` and `data/assets/`, including the contact fields that will
appear in the PDF, then publish:

```bash
git add resume.reference.yaml data/profile.json data/assets/
git commit -m "Update resume profile"
git push origin main
```

After the pipeline succeeds, your fork contains **`resume.pdf` on `main`** and a
GitHub release with the PDF, signatures, SHA-256 hashes, and signing-key fingerprint.
The [PDF link at the top of this README](resume.pdf) stays relative to the repository,
so it points to your résumé in your fork.

## Fork environment variables

For signed main-branch releases, configure the Cosign values below as **GitHub
Actions repository secrets in your own fork**. The workflow passes them to the
signing step as environment variables; GitHub supplies the publication token:

- **`COSIGN_PRIVATE_KEY` — required for signed releases.** Set this to the complete
  PEM contents of your own Cosign private key, including the header, footer, and
  newlines. The value is the key itself, not a filename.
- **`COSIGN_PASSWORD` — required for an encrypted signing key.** Set this to that
  key's password. Leave it unset for an unencrypted key; the signing script defaults
  to an empty password.
- **`GH_TOKEN` / `GITHUB_TOKEN` — supplied automatically; no secret to create.**
  Actions generates the repository token, and the deploy workflow passes it to the
  GitHub CLI as `GH_TOKEN`. It uses `contents: write` to commit `resume.pdf` and
  publish releases. No personal access token is needed; repository and branch rules
  must permit those writes.

From your fork's checkout, with the GitHub CLI authenticated:

```bash
gh secret set COSIGN_PRIVATE_KEY < /secure/path/cosign.key
gh secret set COSIGN_PASSWORD
```

Run the password command only for an encrypted key. See [signing setup](docs/README.md#signed-releases)
to generate a key and [optional environment overrides](docs/README.md#environment-variables)
to adjust retry or local browser settings.

**LinkedIn login currently has no environment-variable configuration:**
`LINKEDIN_USERNAME` and `LINKEDIN_PASSWORD` are not read by the package or workflows.
Set the profile slug in `resume.reference.yaml` under `linkedin.username`, sign in
locally with `resume capture`, and push the resulting snapshot and assets. Actions
builds those committed inputs without signing in to LinkedIn.

## Why use resume?

- **Review your résumé in Git.** Profile text, images, configuration, and templates
  live in your repository. Changes have diffs and history.
- **Keep the engineering detail.** Expanded descriptions, project links, company
  logos, and illustrations flow across pages in a LinkedIn-inspired layout.
- **Make publishing a build step.** Push reviewed inputs; CI validates, renders,
  signs, commits the PDF, and publishes a release through the GitHub CLI.
- **Share verifiable output.** Cosign signatures, verification bundles, checksums,
  and a public-key fingerprint accompany each release.
- **Own the presentation.** Adjust paper size, colors, or text size in YAML, or
  provide a custom LaTeX template without changing the collector.

## How it works

The Python package captures your profile through local Firefox and uses `requests`
to cache images and project previews. Your browser login stays in the ignored local
profile. The portable inputs are `data/profile.json` and `data/assets/`.

Jinja translates those inputs and your YAML configuration into `tex/resume.tex`.
The digest-pinned `drpsychick/texlive-pdflatex` image compiles the PDF. CI installs
from the Poetry lockfile and rebuilds committed inputs without contacting LinkedIn.
Main-branch builds are signed and verified before upload; publication waits for
both test and build checks. Pull requests run those checks without publishing.

See [configuration, architecture, and capture limits](docs/README.md) for the details.

## Update your résumé

After editing your LinkedIn profile, run `poetry run resume capture` again, review
the changed snapshot and assets, and commit and push them. For layout changes,
edit `resume.reference.yaml` and push; the saved profile can be reused.

Hide whole sections with the top-level `disable` list, for example:

```yaml
disable: [featured, interests, recommendations]
```

This changes the generated resume while retaining the captured data. See
[configuration](docs/README.md#configuration) for section keys and other options.

Filter individual jobs in the same file:

```yaml
experience:
  disable:
    - title: Intern
      company: Example Company
  last_years: 5
  as_of: null
```

Exclusions match the exact job title, company, or both, ignoring case and extra
whitespace. `last_years: 5` includes any job overlapping the last five years,
including jobs that began earlier and ongoing roles. The boundary is inclusive;
the full description and original dates stay intact. Jobs with unreadable or
missing dates remain visible. Defaults keep all jobs (`disable: []`,
`last_years: null`). `as_of: null` uses today's UTC date; set a quoted date such as
`as_of: '2026-10-07'` to keep builds anchored to the same window. See
[job filtering](docs/README.md#job-filtering) for grouped roles and date precision.

The cover/background photo is hidden by default in `resume.reference.yaml`. Set
`style.show_header_photo` to `true` to display it again; the portrait stays visible.

Skills appear as a word cloud scored by **references + 2 × endorsements**.
Disabled sections contribute no references. Set `style.skills_word_cloud: false`
for the text list, or add `skills` to `disable` to hide it. Profiles with no optional
sections also work. See the [profile schema and scoring rules](docs/profile-schema.md).

To preview the PDF locally with Docker running:

```bash
poetry run resume build
```

## Development

```bash
poetry install --with dev
poetry run pre-commit install
poetry run pre-commit run --all-files
poetry run pytest --cov --cov-report=term-missing
poetry build
```

Implementation and tests live in `pkg/resume/`: `linkedin/` handles capture and
media, and `latex/` handles escaping, Jinja rendering, and PDF compilation.
Configuration and profile models are shared at the package root. See
[package responsibilities](docs/README.md#pipeline-and-ownership) for the module map.
Repository tooling lives in `scripts/`. Local hooks and CI share Ruff, strict mypy,
Google-style docstring checks, schema validation, ShellCheck, and shfmt.
