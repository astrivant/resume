# resumeme

<!-- resumeme:branding:start -->
<p align="left">
  <img src="https://raw.githubusercontent.com/astrivant/resumeme/main/docs/assets/branding/resumeme-logo.png" alt="resumeme: a coffee-stained LinkedIn mark" width="220"><br>
  <a href="./resume.pdf"><img src="https://raw.githubusercontent.com/astrivant/resumeme/main/docs/assets/branding/brew-date.svg" alt="Brew date: 2026-10-08 (UTC)" width="220" height="28"></a>
</p>
<!-- resumeme:branding:end -->

**Your résumé deserves better than LinkedIn's PDF export.** Skip the clunky
formatting and the copy-paste routine of maintaining a second résumé. `resumeme` ☕ turns your profile into a polished, illustrated PDF you'll *actually want to send* to a hiring manager offline.

Build and release your résumé like software: fork the project, set your username,
capture your profile, and keep `main` current with monthly refreshes. Tag the
version you want to share to get a signed release.

**[View the résumé (PDF)](resume.pdf)** - [Preview a fork's README](FORK_EXAMPLE.md) - [Fork this project](https://github.com/astrivant/resume/fork)

## Why use this tool?

- **Review your résumé in Git.** Profile text, images, configuration, and templates
  live in your repository. Changes have diffs and history.
- **Keep the engineering detail.** Expanded descriptions, project links, company
  logos, and illustrations flow across plain US Letter pages in Garamond, with a
  two-column first page for your profile, contact information, and About section.
- **Keep it current and release deliberately.** Monthly CI refreshes LinkedIn and
  commits the PDF. Tag a revision to publish its signed PDF through the GitHub CLI.
- **Share verifiable output.** Cosign signatures, verification bundles, checksums,
  and a public-key fingerprint accompany each release.
- **Own the presentation.** Adjust paper size, colors, or text size in YAML, or
  select an [inline theme](docs/themes.md), including the autumn-colored `tiger`
  option. Custom LaTeX templates can change the layout without changing the collector.

## Contents

- [resumeme](#resumeme)
  - [Why use this tool?](#why-use-this-tool)
  - [Contents](#contents)
  - [Quick start](#quick-start)
    - [1. Install](#1-install)
      - [macOS prerequisites](#macos-prerequisites)
    - [2. Capture your profile](#2-capture-your-profile)
    - [3. Publish](#3-publish)
    - [Use with an AI agent](#use-with-an-ai-agent)
  - [How it works](#how-it-works)
  - [Update your résumé](#update-your-résumé)
    - [Refresh your profile](#refresh-your-profile)
    - [Refresh links and previews](#refresh-links-and-previews)
    - [Preview the PDF locally](#preview-the-pdf-locally)
  - [Customize your résumé](#customize-your-résumé)
    - [Sections and projects](#sections-and-projects)
    - [Job history](#job-history)
    - [Education](#education)
    - [Profile header and contact information](#profile-header-and-contact-information)
    - [GitHub activity](#github-activity)
    - [Skills](#skills)
    - [Codex summaries](#codex-summaries)
  - [Publishing](#publishing)
    - [GitHub Pages](#github-pages)
    - [Fork environment variables](#fork-environment-variables)
      - [Configure signing secrets](#configure-signing-secrets)
      - [LinkedIn authentication](#linkedin-authentication)
  - [Documentation](#documentation)

## Quick start

### 1. Install

In your fork's local checkout, install the package. Local capture requires
Python 3.13+, Poetry 2.5.1, and Firefox (default) or Chrome. GitHub Actions handles PDF compilation;
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

For a new fork, copy [resumeme.config.ref.yaml](resumeme.config.ref.yaml) over
[resumeme.config.yaml](resumeme.config.yaml), which contains the author's personal
settings. The reference uses package defaults, with optional integrations disabled
and no job, school, project, or date exclusions. Set your LinkedIn username:

```yaml
linkedin:
  username: your-linkedin-username
```

Capture your profile and check the saved snapshot:

```bash
poetry run resumeme capture
poetry run resumeme validate
```

Sign in to LinkedIn in the browser window and leave it open. Capture waits for you
to finish signing in, then saves your profile and images locally. **A username
change alone does not fetch a profile in CI:** Actions builds the snapshot you push.

To use Chrome, set `capture.browser: chrome` in the config; `firefox` is the default.
Install the selected browser first. See [browser setup](docs/README.md#local-capture).

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

After the pipeline succeeds, your fork contains **`resume.pdf` on `main`**.
Set `readme.output: README.md` to make its README a personal résumé page: your name,
a clickable first-page preview, and links to the full PDF, profiles, and releases.
This repository overrides the destination to [FORK_EXAMPLE.md](FORK_EXAMPLE.md)
so you can preview the result alongside these instructions. CI refreshes the
configured page and preview in the same commit as the PDF. Set `readme.mode: project`
to disable generation, or customize `readme.introduction`; see [README publication](docs/automation.md#personal-readme).
Configure LinkedIn secrets for automatic monthly refreshes. When ready to share,
tag the updated commit to create a release with signatures, hashes, and the key
fingerprint; see [monthly refresh and release](docs/automation.md).
The PDF link stays relative to your fork and follows `output.pdf`. Preview images
use absolute GitHub URLs so they also display on package indexes such as PyPI.

### Use with an AI agent

Open your checkout in an agent with terminal access and give it this prompt:

> Read `SKILL.md` in this checkout and generate my résumé for LinkedIn username
> `YOUR-USERNAME`. For first setup, start from `resumeme.config.ref.yaml` if the
> fork still has the author's config. Preserve my existing configuration choices.
> Handle setup, capture or reuse of my matching saved profile, validation, PDF
> generation, and visual checks.
> Let me complete browser login and MFA when needed, then return the finished PDF
> and what you verified.

The portable [agent skill](SKILL.md) also covers filters and themes, GitHub activity,
Codex summaries and employer-specific PDFs, signing, monthly refreshes, personal
READMEs, and Pages. Add the specific operation you want: for example, "publish to
my fork's main branch" or "create a signed résumé release from the accepted PDF
commit." Live LinkedIn About updates and skill additions are separate requests.
See the [CLI reference](docs/CLI.md) for commands and options.

## How it works

The Python package captures your profile through local Firefox or Chrome and uses `requests`
to cache images and project previews. Your browser login stays in the ignored local
profile. The portable inputs are `data/profile.json` and `data/assets/`.

Jinja translates those inputs and your YAML configuration into `tex/resume.tex`.
The digest-pinned `drpsychick/texlive-pdflatex` image compiles the PDF. CI installs
from the Poetry lockfile. Ordinary pushes rebuild committed inputs; monthly runs
capture LinkedIn first. After validation, main-branch publication commits the PDF
and any refreshed inputs together. User-created tags add a release link and key
fingerprint to the committed PDF's footer, sign it, and publish a release.
Pull requests validate without publishing or signing in.

For applications, add LinkedIn company usernames and job links to
`codex.companies`. CI tailors additional summaries to those employers and commits
the PDFs under `single-origin/`, alongside your generic resume. See
[single-origin resumes](docs/codex.md#single-origin-resumes) for configuration and
company/job context overrides.

See [configuration, architecture, and capture limits](docs/README.md) for the details.

## Update your résumé

### Refresh your profile

After editing your LinkedIn profile, run `poetry run resumeme capture` again, review
the changed snapshot and assets, and commit and push them. For layout changes,
edit `resumeme.config.yaml` and push; the saved profile can be reused.

Logs default to `ERROR`. Set `logging.level: DEBUG` or use `--log-level DEBUG`
before the command for request and browser diagnostics. Logs use OpenTelemetry
JSON on stdout; see [logging controls](docs/CLI.md#logging).

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
observed redirect destinations and titles; rendering reuses those saved references.
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

`project_filter` selects projects by source URL using a Python regex and defaults
to GitHub URLs. Set it to `null` to remove the URL restriction.
Use `projects.include` to choose names and optionally distinguish their companies:

```yaml
projects:
  include:
    - name: resumeme
    - name: Deployment platform
      affiliation: Example Company
  exclude:
    - name: resumeme
      affiliation: Former Company
```

Matching ignores case and extra spaces. `include: null` keeps all names;
`include: []` hides every project tile. `exclude` uses the same selectors and wins
when both lists match; `exclude: []` excludes nothing. The URL filter still applies. See
[project filtering](docs/README.md#project-consolidation-and-links) for examples.

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

### Education

Use `education.disable` to exclude entries by `school`, `degree`, `major`, or a
combination. All fields in a selector must match; any matching selector hides the
entry. The default is `[]`. For example:

```yaml
education:
  disable:
    - school: Example University
    - degree: Associate's Degree
      major: Mathematics
```

Comment out `education` in `section_order` to hide the entire section. See
[education filtering](docs/README.md#education-filtering) for matching rules.

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

### GitHub activity

Show clickable contribution circles beneath the GitHub link or in an appendix:

```yaml
github:
  username: your-github-account
  contributions:
    enabled: true
    months: 1
    placement: profile # or appendix
```

The graph uses GitHub's light-theme greens and each day's contribution link.
It follows the profile column's side and fills its width. No additional token or
secret is required. Set `enabled: false` to omit it; use `months: 1` through `12`
to choose the window. See [saved calendars and offline builds](docs/README.md#github-contribution-graph).

### Skills

The top 20 skills appear as a word cloud scored by **references + 2 * endorsements**.
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
See [model choices and API key setup](docs/codex.md#model-selection) and [local previews](docs/codex.md#local-generation-and-preview).

## Publishing

### GitHub Pages

Host the résumé at your Pages root or a custom domain. Enable `pages.enabled` in
[resumeme.config.yaml](resumeme.config.yaml) and select **GitHub Actions** as the
publishing source in your fork's **Settings > Pages**. CI updates `index.html` and
its linked PDF after successful publication to `main`.

`pages.path: /` serves the root; use a path such as `/cv/` for a subdirectory.
See [Pages setup](docs/pages.md) for custom domains, DNS, and local previews.

### Fork environment variables

Configure these **GitHub Actions repository secrets in your own fork** for the
features you use. GitHub supplies the publication token:

- **`LINKEDIN_USERNAME` - required for monthly refresh.** Your LinkedIn login email
  or account identifier; this is separate from `linkedin.username`, the profile slug.
- **`LINKEDIN_PASSWORD` - required for monthly refresh.** The login password. These
  two secrets reach capture on refresh runs and the optional
  [LinkedIn signing identity update](docs/ownership.md) after signed releases.
- **`OPENAI_API_KEY` - required when `codex.enabled` or `codex.skills.enabled` is `true`.** Create a project key on
  the [OpenAI API keys page](https://platform.openai.com/api-keys) and store it as an Actions repository secret. The Codex summary
  jobs receive it; pull-request checks do not. API usage is billed to that project.
  See [Codex setup](docs/codex.md) and [tag-only skill suggestions](docs/skills.md).
- **`COSIGN_PRIVATE_KEY` - required for signed releases.** Set this to the complete
  PEM contents of your own Cosign private key, including the header, footer, and
  newlines. The value is the key itself, not a filename.
- **`COSIGN_PASSWORD` - required for an encrypted signing key.** Set this to that
  key's password. Leave it unset for an unencrypted key; the signing script defaults
  to an empty password.
- **`GH_TOKEN` / `GITHUB_TOKEN` - supplied automatically; no secret to create.**
  Actions generates the repository token, and the deploy workflow passes it to the
  GitHub CLI as `GH_TOKEN`. It uses `contents: write` to commit `resume.pdf` and
  publish releases. No personal access token is needed; repository and branch rules
  must permit those writes. Tag publication also uses the built-in token with
  `packages: write` to push the tool's container image to GHCR.
- **`PYPI_API_TOKEN` - package maintainers only.** Grant the repository access to
  this organization secret, or define it as a repository/`pypi` environment secret.
  Version-tag releases expose it to Poetry as `POETRY_PYPI_TOKEN_PYPI` and upload
  `resumeme` to PyPI. Forks that only generate resumes do not need it. See
  [package releases](docs/development.md#publish-to-pypi).

#### Configure signing secrets

With OpenSSL, Cosign 3.x, and an authenticated GitHub CLI installed, run
`bash scripts/release/setup-signing.sh --repo YOUR-USERNAME/YOUR-FORK`.

The script creates an encrypted signing key, retains a local backup, and sets
`COSIGN_PRIVATE_KEY` and `COSIGN_PASSWORD` on your fork. To reuse a saved key,
add `--key-dir /path/to/backup`. See [signing setup and recovery](docs/README.md#signed-releases)
for prerequisites, key storage, and verification.

#### LinkedIn authentication

Set the public profile slug under `linkedin.username` in `resumeme.config.yaml`.
Local `resumeme capture` opens the configured browser and waits for you to finish signing in.
When both login environment variables are present, it submits them automatically;
interactive capture still waits for you to complete MFA. Scheduled runs use
`capture --headless` and fail without updating `main` if authentication requires
interaction. See [automation setup and recovery](docs/automation.md).

## Documentation

- [CLI reference](docs/CLI.md): complete command help, options, examples, and exit status.
- [Configuration and operation](docs/README.md): capture, job filters, rendering, and signed releases.
- [Monthly refresh and release](docs/automation.md): LinkedIn secrets, scheduling, and shareable signed PDFs.
- [Suggested LinkedIn skills](docs/skills.md): tag-only Codex proposals and optional additions that preserve existing skills and endorsements.
- [GitHub Pages](docs/pages.md): automatic website updates, publication paths, and custom domains.
- [Themes](docs/themes.md) and [templates](docs/templates.md): colors, typography, and custom layouts.
- [Container image](docs/containers.md): Docker usage, local builds, and tag publication to GHCR.
- [Development](docs/development.md): setup, parallel tests, tooling, and document checks.
