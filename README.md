# resumeme

**Your résumé deserves better than LinkedIn's PDF export.** Skip the clunky
formatting and the copy-paste routine of maintaining a second résumé. `resumeme`
turns your profile into a polished, illustrated PDF you'll actually want to send.

Build and release your résumé like software: fork the project, set your username,
capture your profile, and let a push to `main` build, sign, and publish it.

**[View the résumé (PDF)](resume.pdf)** · [Fork this project](https://github.com/astrivant/resume/fork)

## Contents

- [resumeme](#resumeme)
  - [Contents](#contents)
  - [Quick start](#quick-start)
    - [1. Install](#1-install)
      - [macOS prerequisites](#macos-prerequisites)
    - [2. Capture your profile](#2-capture-your-profile)
    - [3. Publish](#3-publish)
    - [Use with an AI agent](#use-with-an-ai-agent)
  - [How it works](#how-it-works)
    - [Why use resumeme?](#why-use-resumeme)
  - [Update your résumé](#update-your-résumé)
    - [Refresh your profile](#refresh-your-profile)
    - [Refresh links and previews](#refresh-links-and-previews)
    - [Preview the PDF locally](#preview-the-pdf-locally)
  - [Customize your résumé](#customize-your-résumé)
    - [Sections and projects](#sections-and-projects)
    - [Job history](#job-history)
    - [Profile header and contact information](#profile-header-and-contact-information)
    - [Skills](#skills)
    - [Codex summaries](#codex-summaries)
  - [Publishing](#publishing)
    - [Fork environment variables](#fork-environment-variables)
      - [Configure signing secrets](#configure-signing-secrets)
      - [LinkedIn authentication](#linkedin-authentication)
  - [Documentation](#documentation)

## Quick start

### 1. Install

In your fork's local checkout, install the package. Local capture requires
Python 3.13+, Poetry 2.5.1, and Firefox. GitHub Actions handles PDF compilation;
Docker is needed only for a local PDF preview.

```bash
poetry install --only main
poetry run resumeme --help
```

#### macOS prerequisites

On macOS with [Homebrew](https://brew.sh) installed, bootstrap host tools from the
[Brewfile](Brewfile) and install the project's pinned Poetry version:

```bash
brew bundle install
pipx install --python "$(brew --prefix python@3.13)/bin/python3.13" "poetry==2.5.1"
export PATH="${PIPX_BIN_DIR:-$HOME/.local/bin}:$PATH"
poetry env use "$(brew --prefix python@3.13)/bin/python3.13"
```

Run `brew bundle check` to verify host dependencies. Start Docker Desktop before
building a PDF locally. Homebrew supplies current host tools; CI keeps its existing
version pins, and Python dependencies and linters install from `poetry.lock`.

### 2. Capture your profile

Change **one profile setting** in [resumeme.config.yaml](resumeme.config.yaml):

```yaml
linkedin:
  username: your-linkedin-username
```

Capture your profile and check the saved snapshot:

```bash
poetry run resumeme capture
poetry run resumeme validate
```

Sign in to LinkedIn in the Firefox window and leave it open. Capture waits for you
to finish signing in, then saves your profile and images locally. **A username
change alone does not fetch a profile in CI:** Actions builds the snapshot you push.

### 3. Publish

Before your first push, enable Actions in your fork, allow it to write repository
contents, and configure the [fork environment variables](#fork-environment-variables).
Branch rules must allow the bot's PDF commit. This setup is required once per fork.

Review `data/profile.json` and `data/assets/`, including the contact fields that will
appear in the PDF, then publish:

```bash
git add resumeme.config.yaml data/profile.json data/assets/
git commit -m "Update resume profile"
git push origin main
```

After the pipeline succeeds, your fork contains **`resume.pdf` on `main`** and a
GitHub release with the PDF, signatures, SHA-256 hashes, and signing-key fingerprint.
The [PDF link at the top of this README](resume.pdf) stays relative to the repository,
so it points to your résumé in your fork.

### Use with an AI agent

Open your checkout in an agent with terminal access and give it this prompt:

> Read `SKILL.md` and generate my résumé PDF from LinkedIn username `YOUR-USERNAME`.
> Handle setup, capture, validation, and the build. Let me sign in to Firefox,
> then give me the finished PDF.

The portable [agent skill](SKILL.md) covers first-run setup, the browser login
handoff, retries, saved-profile rebuilds, and optional GitHub publication. For
layout changes, tell the agent to reuse the saved profile. Add “publish through
my fork's GitHub Actions workflow” when you also want a signed release.

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

### Why use resumeme?

- **Review your résumé in Git.** Profile text, images, configuration, and templates
  live in your repository. Changes have diffs and history.
- **Keep the engineering detail.** Expanded descriptions, project links, company
  logos, and illustrations flow across plain US Letter pages in Garamond, with a
  two-column first page for your profile, contact information, and About section.
- **Make publishing a build step.** Push reviewed inputs; CI validates, renders,
  signs, commits the PDF, and publishes a release through the GitHub CLI.
- **Share verifiable output.** Cosign signatures, verification bundles, checksums,
  and a public-key fingerprint accompany each release.
- **Own the presentation.** Adjust paper size, colors, or text size in YAML, or
  select an [inline theme](docs/themes.md), including the autumn-colored `tiger`
  option. Custom LaTeX templates can change the layout without changing the collector.

## Update your résumé

### Refresh your profile

After editing your LinkedIn profile, run `poetry run resumeme capture` again, review
the changed snapshot and assets, and commit and push them. For layout changes,
edit `resumeme.config.yaml` and push; the saved profile can be reused.

### Refresh links and previews

To discover URLs in already captured text and refresh their destinations, page
titles, and preview images without another LinkedIn login:

```bash
poetry run resumeme enrich
poetry run resumeme validate
poetry run resumeme build
```

Capture also performs this enrichment. HTTP(S) and `www.` URLs become clickable
within the PDF's prose. Original text and URLs stay in the snapshot alongside
observed redirect destinations and titles; rendering remains offline.
`capture.fetch_link_previews: false` disables remote link inspection while keeping
local URL discovery. Contact links remain clickable without fetching their pages.

### Preview the PDF locally

To preview the PDF locally with Docker running:

```bash
poetry run resumeme build
```

## Customize your résumé

Edit [resumeme.config.yaml](resumeme.config.yaml) to choose what appears in the PDF.
For colors and typography, see [inline themes](docs/themes.md).

### Sections and projects

Use the `section_order` array for both visibility and order. Comment out an entry
to hide it; uncomment or move it to include or reorder it:

```yaml
section_order:
  - about
  - experience
  - projects
  # - featured
  - education
  - skills
```

This changes the generated resume while retaining the captured data. See
[configuration](docs/README.md#configuration) for section keys and other options.
The shipped config lists every known section, with Contact info, Featured,
Recommendations, Interests, Causes, Organizations, and Languages commented out.
Only uncommented entries appear in the PDF and its table of contents. Projects
and enabled Featured posts use matching light-gray, two-column tiles.

Projects and project attachments from visible jobs and Featured posts appear in
one two-column Projects section. Matching resolved links merge into a single entry
with their role associations. Attachment descriptions move out of Experience and
appear below the project's image or logo; role narrative stays with the job.
Post text and inline links stay in Featured. Commenting out `projects` also hides
the relocated project cards.

### Job history

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

### Profile header and contact information

The headline beneath the portrait is hidden by default; set
`style.show_headline: true` to restore it. The company and location remain visible.
Set `github.username` to your GitHub account for an icon and profile link directly
below LinkedIn, or `null` to omit it. Both links use their platform icons.

The cover/background photo is hidden by default in `resumeme.config.yaml`. Set
`style.show_header_photo` to `true` to display it again; the portrait stays visible.

Below the LinkedIn profile link, a compact contents list links to each visible
section in PDF order. Set `style.show_table_of_contents: false` to hide it;
it defaults to `true` and supports inline theme overrides.

Connection details are optional: set `style.show_connection_count: true` to show the captured count,
`style.show_connection_link: true` for a Connections link, or both to link the count.
Both default to `false` and can also be overridden in inline themes. Re-enable the
separate contact block by removing `contact` from `disable`.
The birthday stays hidden unless you also set `style.display_birthday: true`;
this setting defaults to `false` and supports inline theme overrides.

### Skills

The top 20 skills appear as a word cloud scored by **references + 2 × endorsements**.
Size reflects this score; color reflects endorsements relative to the most-endorsed
displayed skill. `style.skill_colors` defines the gradient from 0% to 100%.
Disabled sections contribute no references. Set `style.skills_word_cloud: false`
for the text list, or add `skills` to `disable` to hide it. Profiles with no optional
sections also work. See the [profile schema and scoring rules](docs/profile-schema.md).

### Codex summaries

Optionally let Codex write About and a short description beneath your portrait.
Add the `OPENAI_API_KEY` Actions secret, set `codex.enabled: true`, and provide
target roles, tone, or extra background under `codex.context` in
[resumeme.config.yaml](resumeme.config.yaml). Main-branch CI generates the copy
once for both document checks and the PDF build. The captured profile stays intact.
See [Codex setup and local previews](docs/codex.md).

## Publishing

### Fork environment variables

For signed main-branch releases, configure the Cosign values below as **GitHub
Actions repository secrets in your own fork**. The workflow passes them to the
signing step as environment variables; GitHub supplies the publication token:

- **`OPENAI_API_KEY` — required only when `codex.enabled: true`.** An API key from
  your OpenAI project, stored as an Actions repository secret. The Codex summary
  job receives it; ordinary builds and pull-request checks do not. API usage is
  billed to that project. See [Codex setup](docs/codex.md).
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
  must permit those writes. Tag publication also uses the built-in token with
  `packages: write` to push the tool's container image to GHCR.

#### Configure signing secrets

From your fork's checkout, with the GitHub CLI authenticated:

```bash
gh secret set COSIGN_PRIVATE_KEY < /secure/path/cosign.key
gh secret set COSIGN_PASSWORD
```

Run the password command only for an encrypted key. See [signing setup](docs/README.md#signed-releases)
to generate a key and [optional environment overrides](docs/README.md#environment-variables)
to adjust retry or local browser settings.

#### LinkedIn authentication

LinkedIn login currently has no environment-variable configuration:
`LINKEDIN_USERNAME` and `LINKEDIN_PASSWORD` are not read by the package or workflows.
Set the profile slug in `resumeme.config.yaml` under `linkedin.username`, sign in
locally with `resumeme capture`, and push the resulting snapshot and assets. Actions
builds those committed inputs without signing in to LinkedIn.

## Documentation

- [Configuration and operation](docs/README.md): capture, job filters, rendering, and signed releases.
- [Themes](docs/themes.md) and [templates](docs/templates.md): colors, typography, and custom layouts.
- [Container image](docs/containers.md): Docker usage, local builds, and tag publication to GHCR.
- [Development](docs/development.md): setup, parallel tests, tooling, and document checks.
