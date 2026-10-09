---
name: resumeme
description: >-
  Build and maintain LinkedIn résumé PDFs with the resumeme repository and CLI.
  Use for setup, browser capture, saved-profile rebuilds, configuration and layout
  changes, Codex summaries and employer variants, or requested signing, GitHub
  publication, and LinkedIn profile updates.
---

# Build and publish a LinkedIn résumé

Use the existing CLI and configuration to deliver the requested PDF or publication.
This is a portable Markdown skill: agents can read it from the checkout without
an editor plugin or skill installer. Read the [CLI reference](docs/CLI.md) for
complete command help and only the guides relevant to the requested operation.

## Establish owner, inputs, and scope

Work in the existing checkout containing `pyproject.toml`, `poetry.lock`, and
`resumeme.config.yaml`. If its location is unknown, ask for it rather than creating
another project. Paths in this skill are relative to that checkout. Inspect
`git status --short` and preserve existing edits and staged work.

Use the user's confirmed LinkedIn slug, or extract it after `/in/` in their profile
URL. A fork may retain the author's configuration, snapshot, and PDF; changing
`linkedin.username` does not fetch new data. Reuse a snapshot only when it belongs
to the intended owner. Ask for missing identity information only when it cannot
be established from the conversation and configuration.

Review inherited `github.username`, job and school exclusions, date windows,
README destination, Pages domain, and optional Codex/live-update settings when
setting up a new owner. Apply the user's choices while preserving YAML comments.
For a first setup still using the author's configuration, copy
[.config/resumeme.config.ref.yaml](.config/resumeme.config.ref.yaml) to `resumeme.config.yaml` and
set the confirmed username. The reference uses package defaults and disables
optional integrations; preserve an existing owner's customized config.
The checked-in configuration contains personal overrides; do not assume it is the
package's default configuration. Minimal profiles and missing sections are valid;
do not invent content to fill them. See [profile coverage](docs/profile-schema.md).

Place a custom `--config` before the subcommand. Configured outputs and artifact
arguments such as `--summary` resolve beneath the configuration directory;
`--public-key` resolves from the working directory. See [path rules](docs/CLI.md#invocation-and-paths).
Carry existing authorization forward. A local PDF request does not authorize
GitHub writes, key rotation, model usage, or live LinkedIn edits; use those modes
when requested or already authorized.

## Choose the operation

| Request | Command or route | Result and relevant constraint |
| --- | --- | --- |
| First run, new owner, or fresh LinkedIn data | `resumeme capture` | Browser capture plus downloaded media; complete login before continuing |
| Resolve links or refresh previews | `resumeme enrich` | Public HTTP requests update the saved snapshot and assets without a browser |
| Check inputs | `resumeme validate` | Validate config, snapshot schema, owner, and recorded warnings |
| Inspect generated LaTeX | `resumeme render` | Generate TeX and staged assets without PDF compilation |
| Rebuild or change layout | `resumeme build` | Reuse the matching snapshot and produce `output.pdf` |
| Generate About/portrait copy or employer variants | `resumeme summary-prompt` with optional `--companies` | Prepare model inputs; use the [Codex workflow](docs/codex.md) for generation and response selection |
| Prepare a website | `resumeme site --repository OWNER/REPO` | Build `.cache/pages/` from the existing PDF; [deployment is separate](docs/pages.md) |
| Publish a signing identity to About | `resumeme publish-ownership` | Preview or update the live profile using a verified release public key |
| Save a resume for LinkedIn applications | `resumeme publish-resume` | Preview or upload a verified release PDF; live uploads require `linkedin.resume.publish: true` |
| Propose or add LinkedIn skills | `resumeme skills-prompt` / `resumeme publish-skills` | Requires a matching tagged checkout; generation and live additions have separate opt-ins |
| Commit PDFs, refresh monthly, release, or publish packages | [GitHub workflows](docs/automation.md) | Select the correct event and destination; see publication below |

## Prepare the environment

For a source checkout, use Python 3.13+, Poetry 2.5.1, and the committed lockfile.
Reuse the project environment, not an unrelated inherited virtualenv. Follow the
[installation guide](docs/README.md#install) and `.config/Brewfile` on macOS when tools are
missing. Install Firefox (default) or Chrome for capture according to
`capture.browser`. A normal local PDF build needs a running Docker daemon.

Install runtime dependencies with `poetry install --only main --no-interaction`
and verify `poetry run resumeme --help`. Keep dependency resolution fixed;
ordinary PDF generation does not require `poetry update` or development packages.
Set `MPLCONFIGDIR` to the checkout's `.cache/matplotlib` when the agent cannot write
to the host's default cache. Prefix the command examples with `poetry run` when
using the source environment.

The [runtime container](docs/containers.md) includes the CLI, Firefox, Tini, and
TeX for `linux/amd64`; it compiles without a nested Docker daemon. Chrome capture
requires a host installation. Use the published image path from the selected
release, mount the existing inputs, and retain its documented user and path rules.

## Capture and recover

Run `resumeme capture` in a persistent process. Once its browser opens, let the
user sign in, complete MFA, and leave the window open. Login completion is detected
automatically without a login deadline. Keep polling the same process while the
user signs in; do not start duplicate captures or impose a short overall timeout.

`LINKEDIN_USERNAME` (email/phone) and `LINKEDIN_PASSWORD` can supply credentials;
neither belongs in chat, config, or commits. The same username variable also
accepts a public username or `/in/` URL matching the configured owner; those use
interactive sign-in because LinkedIn cannot authenticate a public slug.
`linkedin.username` in YAML accepts either a public username or profile URL.
Never infer a private login email from the public slug. Interactive capture still permits manual challenges.
`--headless` is for unattended execution and fails if a challenge needs interaction.
`--connect-port` attaches only to an explicitly opened local Firefox Marionette
session. Read [capture and attachment instructions](docs/README.md#local-capture)
when that mode is needed.

Successful capture writes `output.profile` and `output.assets`, normally
`data/profile.json` and `data/assets/`. Preserve ignored `.cache/firefox/` or
`.cache/chrome/` sessions for retries; the browsers have separate logins. The CLI
already uses capped exponential backoff through `capture.retry_*`.

Before manually pushing a locally authenticated refresh, run `resumeme validate`
and `resumeme render`. The render command writes cleaned, section-marked TeX from
the saved capture; the main-branch workflow runs the same renderer when building
the PDF.

Incomplete capture or enrichment saves diagnostics under `.cache/capture/` without
replacing accepted inputs. Inspect the reported cause before retrying. Use
`--allow-incomplete` only when the user accepts those omissions. After a closed
window or failed headless login, use interactive capture to resolve the challenge;
do not bypass it or repeatedly submit credentials. Preserve the last good snapshot.

## Apply configuration and presentation choices

Use the config rather than deleting captured records or patching generated TeX.
Follow these settings and their linked contracts:

| Capability | Configuration and behavior |
| --- | --- |
| Section visibility and order | Reorder `section_order`; remove or comment out keys to hide them. There is no separate top-level `disable` list. Empty sections are skipped. [Section rules](docs/README.md#section-visibility-order-and-tiles). |
| Project selection | `project_filter` matches resolved source URLs and defaults to GitHub. `projects.include` and `projects.exclude` accept `name`, `affiliation`, or both. Supplied fields use AND, list entries use OR, and exclusions win. `include: null` allows all projects, `include: []` selects none, and `exclude: []` excludes nothing. [Project consolidation](docs/README.md#project-consolidation-and-links). |
| Job history | `experience.disable` matches title/company. `since` supplies a fixed inclusive start and overrides `last_years`; `as_of` fixes the endpoint. Include jobs overlapping the window, not just jobs starting within it. [Job filters](docs/README.md#job-filtering). |
| Education | `education.disable` matches school, degree, major, or their combination. Omit `education` from `section_order` to hide the whole section. [Education filters](docs/README.md#education-filtering). |
| Job text | Tune `experience.reflow_soft_breaks`, literal `experience.subheadings`, and `style.highlight_job_subheadings` to preserve paragraphs while recognizing small headers. [Text parsing](docs/README.md#job-text-and-subheadings). |
| Header and page style | `style.profile_column_side` selects left or right placement with separate columns by default. `style.profile_column_wrap: true` allows body text beneath the right-side profile. Configure paper, headline, cover photo, contact/birthday/connection visibility, and contents links through the [header options](docs/README.md#header-and-skills). |
| Themes and company hierarchy | `style.theme` selects an entry in `style.themes`, whose values override base fields. Use `tiger`, inline palettes, company font size/color, and link/skill colors as requested. [Themes](docs/themes.md). |
| Body spacing and About panel | `style.line_height` scales body baseline spacing; `style.paragraph_spacing` sets paragraph gaps in points. `style.about_background` accepts a six-digit hex color or `null`; enabled panels share project tile corners. These fields support inline themes. [Document layout](docs/README.md#document-layout). |
| Skills | The cloud shows at most 20 skills, sized by references plus twice observed endorsements and colored by relative endorsements. `style.skills_allow_vertical` allows rotated labels; `skills_word_cloud: false` uses the list. Raw scores remain in `tex/skills.weights.json`. [Scoring](docs/profile-schema.md#scoring-and-rendering). |
| GitHub activity | `github.username` supplies the profile link. `github.contributions` selects enabled state, months, profile/appendix placement, and `as_of`. [Calendar behavior](docs/README.md#github-contribution-graph). |
| Custom layouts | `template` selects a Jinja/LaTeX template. Read its [interface](docs/templates.md) and the [compiler architecture](docs/compiler.md) before changing rendering code. |

Project selection runs after deduplication across native Projects, visible roles,
and enabled Featured posts. Exclusions also apply to project media, skill scores,
and Codex evidence. Projects and Featured use shared rounded tiles; skills/tags
stay centralized in Skills and cannot be re-enabled inside project tiles. Preserve
role progression, linked company/school logos, inline links, and project-to-role
anchors when changing templates. These are display transformations, not edits to
LinkedIn or the source snapshot.

## Generate optional Codex outputs

For requested summaries, set `codex.enabled` and relevant context/model/effort/word limits.
Use separate `codex.model` and `codex.reasoning_effort` values; this repository selects
`gpt-6-astra` and `low`. See [models and API key setup](docs/codex.md#model-selection).
`summary-prompt` writes the filtered prompt and schema; it does not call a model.
Use the existing upstream action in CI or the pinned CLI and invocation in
[local generation](docs/codex.md#local-generation-and-preview). `OPENAI_API_KEY`
is required for generation. Summary text changes the PDF's About and portrait
copy, not the live LinkedIn About section.

`codex.companies` pairs a company username with a job URL and optional context.
Use `summary-prompt --companies`, generate each response, and pass both
`--summary .cache/codex/summary.json` and
`--company-summaries .cache/codex/companies` to `build` or `render`.
The generic PDF remains; variants go under `single-origin/<company>/<job>/`.
Preserve each `company.json` with its response. Supplied company/job context can
replace remote fetches. Employer requirements guide emphasis, not invented
qualifications. Responses are bound to owner and evidence; regenerate stale
responses rather than bypassing validation. Builds never auto-apply cached copy.

## Build and inspect the result

Run `resumeme validate`, then `resumeme build`. A host build renders Jinja and runs
two pdfLaTeX passes in the pinned Docker image; it needs no host TeX installation.
`render` is useful for diagnosis but generated TeX is not a completed PDF.
Compilation logs are in `.cache/build/`.

An enabled contribution graph makes a public GitHub request during render/build.
For offline replay, pass `--github-calendar tex/github-contributions.json` with
matching username, month window, and `github.contributions.as_of` set to the saved
calendar's end date. Do not silently replace the requested date window or disable
the graph to make a build pass. Other saved-profile rendering needs no capture.

Check the successful process result as well as the output: a failed compilation
can leave an older PDF intact. Inspect the new PDF for the intended owner, section
order, clipping, wrapping, logos, tiles, cloud/legend, and clickable links. Verify
company variants separately when requested. For code changes, run relevant
[development checks](docs/development.md); pytest runs in parallel by default.
A styling-only task does not require recapture or a full test matrix.

Return the actual output link, whether capture was refreshed or reused, what was
verified, and any concrete blocker. Distinguish a local build from a hosted CI
success. If browser or compiler access is unavailable, retain valid inputs and
report the failing stage instead of presenting an old PDF as newly built.

## Publish through the fork when requested

Use the explicit intended repository and existing authorization. Check inherited
live-update and model-generation settings before triggering a tag. Configure only
the secrets needed for selected features; see the [fork environment list](docs/automation.md#configure-a-fork).
Stage intended inputs/config/assets while preserving unrelated staged work.
Browser state, diagnostics, API credentials, and signing keys stay out of commits.

| Event or output | Behavior and setup |
| --- | --- |
| Push or manual build on `main` | Verify committed inputs, optionally generate enabled generic/company summaries, and commit accepted PDFs back to `main`. |
| Monthly schedule or manual `refresh=true` on `main` | Authenticate once with LinkedIn login secrets, capture six section shards in parallel on the configured browser, aggregate and verify the complete profile, then commit fresh inputs and PDFs. Interactive challenges leave `main` unchanged. |
| Personal README | Set `readme.output: README.md` for a fork landing page with its name, clickable first-page preview, and links. This repository uses `docs/FORK_EXAMPLE.md`; forks inherit that override. `mode: project` preserves handwritten content. [README publication](docs/automation.md#personal-readme). |
| Coffee branding | Project READMEs keep the generated coffee-stained logo and linked Brew date badge. Accepted updates retain a fading recent stain trail; retries do not add stains. [Branding renderer](docs/assets/branding/README.md). |
| Pages | `resumeme site` prepares files only. Enable `pages.enabled` and GitHub Actions as the Pages source to deploy the accepted PDF. `pages.path` selects the site directory; `custom_domain` checks an existing setup and does not configure DNS. [Pages setup](docs/pages.md). |
| User-created tag | Authenticate once with LinkedIn login secrets, capture six section shards in parallel on the configured browser, aggregate and validate the complete profile, then build and sign this run's generic PDF with its release/key footer. Enabled summaries and skill proposals use the same capture. Release the PDF, signature bundles, public key, fingerprint, hashes, and provenance. The tag also publishes the verified GHCR image and adds pull commands to release notes. Only `astrivant/resumeme` additionally publishes `emmeowzing/resumeme` to Docker Hub using `DOCKER_HUB_TOKEN_EMMEOWZING`; forks skip that job. |
| Package version tag | Tags such as `v0.2.0` set the package version in CI for the wheel, source archive, and container, then publish `resumeme` to PyPI using `PYPI_API_TOKEN`. No metadata commit is required. This is for package maintainers; use a résumé tag such as `resume-2026-10` for personal releases. [Package publishing](docs/development.md#publish-to-pypi). |

For requested key setup, use [setup-signing.sh](scripts/release/setup-signing.sh)
with `--repo OWNER/REPO`. It generates an OpenSSL P-256 key, imports it for Cosign,
saves a local backup, and uploads `COSIGN_PRIVATE_KEY` and `COSIGN_PASSWORD`.
Use `--key-dir` with the printed backup directory after a failed upload; running
without it creates a new identity. Do not rotate an existing key merely to retry.
Follow [signing and verification](docs/README.md#signed-releases).

Tag the intended configuration/code revision. Tag pushes capture LinkedIn and
rebuild before signing, commit the verified bundle to `output/release/` on `main`,
update the root `resume.pdf`, and deploy Pages when enabled. Missing credentials or
interactive challenges fail the tag run without falling back to a committed PDF.
Check the actual Actions run and outputs before reporting publication success.
Stale runs cannot overwrite newer `main`; rerun against the new revision rather
than force-pushing. Public release PDFs are not replaced on retries. Use a new
tag containing fixes instead of rerunning an old tag's workflow. See
[automation and recovery](docs/automation.md).

## Update LinkedIn only within the requested scope

The publishers use the configured browser/login and retry by rereading live
state. An interrupted Save may already have succeeded; inspect or rerun the
command to reconcile rather than blindly submitting again. Stop on ambiguous
ownership, missing required controls, or validation failure. Detailed recovery
and private backup locations are in the linked guides.

- **Signing identity:** `publish-ownership --public-key output/release/cosign.pub --dry-run`
  previews the About text. Omit `--dry-run` only for an authorized live update.
  Use the verified release public key; the CLI preserves surrounding About text.
  The local command writes regardless of the CI `update_about` setting.
  Tag CI uses `linkedin.ownership.update_about` after a verified signed release.
  See [ownership publication](docs/ownership.md).
- **Skill proposals:** `codex.skills.enabled` is independent of résumé summaries.
  `skills-prompt --tag TAG` prepares evidence-backed suggestions; the model call
  is separate. In Actions generation follows tag capture; live publication waits
  for a successful signed release and explicit opt-in. Proposals
  are self-declared skills, not connection endorsements. See [skill generation](docs/skills.md).
- **Application resumes:** `publish-resume --pdf PATH --dry-run` checks the PDF,
  account owner, and upload form without uploading. Live upload requires
  `linkedin.resume.publish: true` and omission of `--dry-run`. Use the verified
  signed release PDF. Tag CI verifies and uploads the same-run signed artifact
  in a separate job only for the latest release. Inspect saved resumes after an
  uncertain outcome and retry the same bytes; their hash-based filename avoids
  duplicates. `linkedin.resume.share_with_recruiters` defaults to `null` to
  preserve the account setting; explicit `true` or `false` overrides recruiter
  resume-data sharing after upload. Dry runs inspect and preview that override
  without clicking. `linkedin.resume.replace_existing` defaults to `false`; when
  true, the publisher removes other saved resumes only after confirming the new
  PDF. Dry runs never delete files. This repository's personal config enables
  replacement; its reference config does not. Do not submit job applications.
  See [upload setup and recovery](docs/linkedin-resume.md).
- **Skill additions:** `publish-skills --tag TAG --suggestions PATH --dry-run`
  compares the validated proposal with the live profile. Live additions require
  `codex.skills.publish: true` and omission of `--dry-run`. Both commands require
  the tag to match the checkout; Actions also requires its tag-push event.
  Add only missing skills. Never remove, rename, replace, reorder, or alter
  existing skills or endorsements; a full list stops publication. Capture again
  to bring additions into the snapshot/PDF. See [publication and retries](docs/skills.md#preservation-and-retry-behavior).
