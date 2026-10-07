# Configuration and operation

## Contents

- [Configuration](#configuration)
- [Job filtering](#job-filtering)
- [Environment variables](#environment-variables)
- [Profile schema and skill clouds](profile-schema.md)
- [Local capture](#local-capture)
- [Rendering and PDF builds](#rendering-and-pdf-builds)
- [Container usage and tag publication](containers.md)
- [Signed releases](#signed-releases)
- [Pipeline and ownership](#pipeline-and-ownership)
- [Capture limits and recovery](#capture-limits-and-recovery)

## Configuration

`resumeme.config.yaml` is the single user-maintained configuration file. A new
owner only needs to change `linkedin.username`; they must also capture their own
profile while signed in. Configuration and snapshot ownership are validated before
rendering. All paths are relative to the configuration file, even when the command
runs from another directory. Unknown fields and paths escaping that directory fail.

| Setting | Default | Purpose |
| --- | --- | --- |
| `linkedin.username` | `emmeowzing` | Profile slug from `/in/<username>/` |
| `disable` | `[]` | Section keys to omit from the generated resume |
| `experience.disable` | `[]` | Job selectors with `title`, `company`, or both; matching jobs are omitted |
| `experience.last_years` | `null` | Include jobs overlapping the trailing N calendar years; null keeps all dates |
| `experience.as_of` | `null` | Quoted ISO date fixing the window endpoint; null uses today's UTC date |
| `capture.page_timeout_seconds` | `30` | Browser and media request timeout |
| `capture.max_scrolls` | `60` | Maximum expansion iterations per page |
| `capture.max_pages_per_section` | `30` | Bound on section pagination |
| `capture.retry_attempts` | `5` | Total attempts for transient browser and HTTP failures |
| `capture.retry_backoff_seconds` | `10` | Initial exponential retry delay |
| `capture.retry_max_backoff_seconds` | `300` | Maximum retry delay |
| `capture.fetch_link_previews` | `true` | Resolve external links, record page titles, and download previews or icons |
| `output.profile` | `data/profile.json` | Portable, validated profile snapshot |
| `output.assets` | `data/assets` | Content-addressed PNG images |
| `output.tex` | `tex/resume.tex` | Generated LaTeX source |
| `output.pdf` | `resume.pdf` | Compiled PDF and CI commit destination |
| `style.paper` | `letter` | `letter` (8.5 × 11 inches) or `a4` |
| `style.accent` | `3F6248` | Six-digit hexadecimal link color; muted forest green by default |
| `style.background` | `FFFFFF` | Six-digit hexadecimal page background; white by default |
| `style.font_size` | `10` | Body font size: `10`, `11`, or `12` points |
| `style.show_header_photo` | `true` | Display the cover/background photo; set to `false` in the reference config |
| `style.show_table_of_contents` | `true` | Link visible sections below the LinkedIn profile link in the first-page left column |
| `style.show_connection_count` | `false` | Show the captured connection count once below the LinkedIn profile link |
| `style.show_connection_link` | `false` | Link the count, or a concise Connections label, to the captured connections page |
| `style.display_birthday` | `false` | Show the birthday field when Contact info is enabled |
| `style.skills_word_cloud` | `true` | Render Skills as a cloud weighted by references and endorsements |
| `style.ink` | `363636` | Six-digit hexadecimal body text color; soft charcoal by default |
| `style.name_color` | `191919` | Six-digit hexadecimal profile name color |
| `style.heading_color` | `191919` | Six-digit hexadecimal section heading color |
| `style.entry_color` | `363636` | Six-digit hexadecimal entry heading color; matches body text by default |
| `style.skill_colors` | `[555555]` | Nonempty list of hexadecimal cloud colors; one neutral tone by default |
| `style.theme` | `null` | Optional name from `style.themes`; null uses the base style |
| `style.themes` | `{}` | Inline partial style overrides; the reference config includes `tiger` |
| `template` | `null` | Optional custom Jinja/LaTeX template |

The configuration and profile JSON Schemas are packaged under
`pkg/resumeme/resources/` and checked by pre-commit.

Select `style.theme: tiger` to use the autumn palette included in the reference
config, or add your own entries under `style.themes`. The selected entry overrides
matching base style fields, including paper size and visibility toggles. Omitted
fields keep their base values. See [inline themes and palette sources](themes.md).

To hide entire sections, add their keys to the top-level `disable` list:

```yaml
disable:
  - featured
  - interests
  - recommendations
```

Run `poetry run resumeme build` or push the configuration change to rebuild in CI.
The list applies to both the packaged template and custom templates. Disabled
sections' text, links, and images are omitted from the generated resume; capture
still collects them, and their data remains in the saved snapshot and repository.
Removing a key from the list restores that section without another capture.
The shipped `resumeme.config.yaml` hides Contact info, Featured, Recommendations,
Interests, Causes, Organizations, and Languages.

Use exact, lowercase `sections[].key` values from `data/profile.json`. Common keys
are `contact`, `about`, `featured`, `experience`, `education`, `projects`, `skills`,
`recommendations`, `languages`, `organizations`, `interests`, and `causes`. Custom
section keys are supported. Keys absent from the snapshot have no effect, and an
empty list includes every captured section. The profile header remains visible,
and existing capture-warning checks still apply.

The reference config hides the cover/background photo with
`style.show_header_photo: false`. Set it to `true` to restore the photo on the next
build. This applies to packaged and custom templates, keeps the portrait and section
images visible, and retains the captured photo so re-enabling it needs no recapture.

Captured pronouns appear directly beneath the name, above the portrait in the
first-page identity column, and are not repeated in the introductory text.
The header omits standalone captured URLs and repeated connection metadata, leaving
one concise LinkedIn profile link. Set `style.show_connection_count: true` for a
plain connection count or `style.show_connection_link: true` for a Connections link.
Enabling both makes the count clickable. These flags also work in inline themes;
missing counts and destinations are never guessed. Contact info is independently
controlled by the `contact` entry in `disable`.

The first-page identity column includes a **Contents** heading and indented links
directly beneath the LinkedIn profile link. Only rendered sections appear, in PDF
order, including consolidated Projects and a generated Skills cloud. Empty or
disabled sections have no link, and a header-only profile has no contents block.
Set `style.show_table_of_contents: false` to hide it, or override the setting in an
inline theme. Custom templates receive `section_navigation`, a list of
`(anchor, section)` pairs with unique TeX-safe destinations in display order.

Birthdays remain hidden even when Contact info is enabled. Set
`style.display_birthday: true` to include the captured birthday field, or override
it in an inline theme. The setting applies to packaged and custom templates and
preserves the birthday in the snapshot. Disabling `contact` still hides the whole
block, regardless of this setting.

Captured intro text remains available, and URLs embedded in that prose retain
their resolved destinations. Custom templates receive the same cleaned header
plus `connection_count` and `connection_url`, which are empty when disabled or
unavailable. The snapshot itself is unchanged.

The Skills cloud shows at most 20 labels, ranked by **references + 2 × endorsements**,
using only enabled sections. It displays at up to 75% of the body width, preserving
its aspect ratio. `disable: [skills]` hides it entirely. Set
`style.skills_word_cloud: false` to restore the captured Skills list. The PNG and
`tex/skills.weights.json` are regenerated with the TeX. See the
[profile schema and scoring rules](profile-schema.md) for supported sections,
minimal profiles, legacy snapshots, and count interpretation.

## Job filtering

Keep job presentation settings under `experience` in `resumeme.config.yaml`:

```yaml
experience:
  disable:
    - title: Intern
      company: Example Company
    - company: Another Employer
  last_years: 5
  as_of: null
```

- `disable` accepts selectors with a job `title`, a `company`, or both. All supplied
  fields must match; any matching selector excludes the role. Matches are exact
  after ignoring case and repeated whitespace. A company-only selector hides all
  its roles; a title-only selector hides that title at every employer. Copy titles
  and employer names from the Experience entries in `data/profile.json`, omitting
  the employer's `· Full-time` or similar employment-type suffix.
- `last_years` is a positive integer, or `null` to keep all dates. Jobs are included
  when any part of their employment overlaps the inclusive window from N calendar
  years before `as_of` through `as_of`. A job does not have to start inside it.
  Explicit exclusions still take precedence. Future jobs outside the window are
  omitted; current jobs that have already started are included.
- `as_of` is a quoted `YYYY-MM-DD` string, or `null` for the current UTC date when
  rendering. Pin it for repeatable historical builds; with `null`, the window
  advances over time even if the snapshot does not change. A February 29 anniversary
  becomes February 28 in a non-leap cutoff year.

For example, five years ending on `2026-10-07` includes a role held from `2018` to
`2022` and one ending exactly on `2021-10-07`. A role ending on `2021-10-06` is
outside the window. Recognized dates include English month names/abbreviations,
years, and ISO dates. Month-only dates cover the entire month, and year-only dates
cover the entire year: `Oct 2021` and `2021` end dates both overlap this cutoff.
Missing, invalid, or unsupported date text stays visible rather than being guessed.

Grouped company entries retain individual role boundaries on capture. Filtering
removes only the excluded roles, along with their descriptions, links, images, and
skill contributions. Retained roles keep their original text and dates; an employer
with no retained roles disappears. Earlier snapshots may contain only flattened
company groups: whole-group filtering works, but a partial selection asks you to
run `resumeme capture` once so media and skill ownership can be separated correctly.

Whole-section `disable: [experience]` takes precedence over job filters. These
settings apply before asset staging, skill scoring, and either packaged or custom
templates. Projects extracted from excluded jobs are omitted too. They do not filter
independently captured entries in other sections, such as Projects or the main Skills
list, where the same employer or skill might independently appear. Captured inputs
stay intact, so removing a filter restores the content without another capture.

## Environment variables

Start with the [fork environment variable list](../README.md#fork-environment-variables)
for the signing secrets and automatically supplied GitHub token. No additional
environment variables are required for ordinary capture, builds, or publication.

The following overrides are optional:

- **`RETRY_ATTEMPTS`** — total attempts for transient failures in CI network
  commands; defaults to `5`. Accepts an integer from `1` to `99`.
- **`RETRY_BACKOFF_SECONDS`** — initial delay between those attempts; defaults to
  `10` seconds. Accepts a nonnegative integer. The delay doubles after each retry,
  up to `RETRY_MAX_BACKOFF_SECONDS`.
- **`RETRY_MAX_BACKOFF_SECONDS`** — maximum delay for those retries; defaults to
  `300` seconds. Accepts a positive integer.
- **`SE_CACHE_PATH`** — local Selenium Manager cache directory; defaults to
  `.cache/selenium/` under the configuration directory. Export an absolute path
  before running `poetry run resumeme capture` to use another directory.
- **`SE_AVOID_STATS`** — Selenium Manager statistics opt-out; defaults to `true`.
  Export `false` before capture to allow statistics collection.
- **`RESUMEME_TEX_BACKEND`** — PDF compiler backend: `docker` by default on the host,
  or `local` to invoke `pdflatex` directly. The published container sets `local`
  automatically for its bundled toolchain. Ordinary users need no override.

Export retry overrides when running the shell scripts locally, or add them to
the `env` mapping of the relevant job in `.github/workflows/stage-*.yml`. Repository
Actions variables are not automatically exported: adding a repository variable
alone has no effect because these workflows do not read `vars.RETRY_*`.

Browser and image-download retries use the YAML `capture.retry_*` settings instead
of these shell overrides. Profile selection also uses YAML (`linkedin.username`);
`LINKEDIN_USERNAME` and `LINKEDIN_PASSWORD` are currently unsupported. Capture
requires a local Firefox login, and CI consumes the committed snapshot.

## Local capture

```bash
poetry run resumeme capture
poetry run resumeme validate
```

Firefox opens with a dedicated local profile under ignored `.cache/firefox/`. Sign in directly in that window,
complete any MFA, and leave the window open until the command finishes. Login has
no deadline: capture polls once per second until a LinkedIn tab has an authenticated
session cookie and has left the login or challenge page. No extra thread or subprocess
is needed; the same process owns the browser and cleans up on cancellation. Press
Ctrl-C or close the window to cancel. Network page loads retain bounded timeouts. The Python
browser client uses macOS's application launcher so Firefox can access its profile
and normal application services; Selenium connects to its loopback Marionette port.
Other platforms use Selenium's native Firefox launcher. Selenium Manager downloads
the driver on first use into `.cache/selenium/`.

Capture expands text and lazy lists, follows owner-scoped detail links, and traverses
pagination. It preserves grouped positions, full text, link targets, and referenced
images, and reads the owner's Contact info dialog. Contact fields shown there,
including email and birthday when present, are part of the snapshot. A separate
`requests` session downloads images and one level of external
project previews. Both HTML anchors and HTTP(S)/`www.` URLs found in intro text,
entry titles, descriptions, and grouped roles participate in link discovery.
Inspection records the final HTTP redirect destination and Open Graph, Twitter,
or HTML page title, then resolves preview images relative to that page or its HTML
base URL. LinkedIn short-link exit pages are followed through their explicit
external-site control, with a bounded hop count and the same public-address checks.
It does not crawl the page's outgoing links. Direct binary downloads
retain their destination without inventing an image preview.

Run `poetry run resumeme enrich` to apply this to an existing snapshot without
starting Firefox. Original text and source URLs remain intact. Shared URLs and
images are fetched once per run, and existing local images are reused. Contact
links and LinkedIn navigation are not inspected. `capture.fetch_link_previews: false`
disables remote inspection, while prose URL discovery remains available. Inspection
failures produce the same incomplete-capture diagnostics as media failures and
leave the accepted snapshot unchanged unless explicitly accepted.

The requests session never receives browser cookies or credentials. Browser cookies remain in that local profile for retries and are never exported to the
snapshot, build artifacts, or CI. Diagnostics stay ignored under `.cache/capture/`.
The collected text is saved there before media downloads start, so an interrupted
download retains a diagnostic snapshot marked incomplete.

Review the captured snapshot and assets before committing them. These files contain
the profile information and media that will appear in the public résumé. They do
not include the browser login, private messages, contacts, or profile-view analytics.

If attaching to a Firefox instance you deliberately opened with Marionette, use
`resumeme capture --connect-port PORT`. The command owns that automation session and
closes it on completion. Ordinary capture requires no port configuration.

## Rendering and PDF builds

```bash
poetry run resumeme render
poetry run resumeme build
```

Rendering does not contact LinkedIn. It consumes the committed snapshot, copies
only referenced PNGs into `tex/assets/`, escapes profile text, and renders the
packaged `resume.tex.j2` with strict undefined-variable handling. Templates use
`((( variable )))` for expressions and `((* statement *))` for control flow.
Prose URLs become inline hyperlinks, using saved resolved destinations when
available. Older snapshots gain clickable prose links locally; network metadata
requires capture or `enrich`. The `tex_links` filter accepts text and its associated
links for custom templates, for example `paragraph|tex_links(entry.links)`.

List presentation is normalized during rendering, leaving captured text intact.
Line-start dashes, ASCII bullets, Unicode bullets/arrows, checkboxes, emoji markers,
and numbered or lettered lists become regular LaTeX bullets with hanging indentation.
Nested indentation and explicitly indented continuations are preserved. Ambiguous
initials need adjacent list items, and dates, negative numbers, versions, inline
punctuation, and unrecognized prose stay unchanged. Custom templates can use
`paragraphs|text_blocks` to obtain text and optional bullet depth, then apply
`tex_links` to each block's text.

Job location metadata links to Google Maps while retaining its captured wording.
Individual roles and shared company locations in grouped jobs are supported;
work arrangements such as Remote, Hybrid, and On-site remain plain text. Links
use [Google's Maps URL format](https://developers.google.com/maps/documentation/urls/get-started)
with an encoded location query, so builds need no geocoding request or API key.
The snapshot stays unchanged. Custom templates can use `entry|job_locations`,
which maps each recognized metadata line to a `Link` with its place label and URL.

Before staging assets, `latex/projects.py` moves project links and attachments from
visible Experience and Featured entries into Projects. Existing project descriptions
take precedence, and repeated references add their role associations. Resolved URLs
identify duplicates, falling back to original destinations when inspection has not
run. Comparison ignores trailing slashes and fragments while preserving paths and
queries, so a repository and its documentation page remain distinct. A URL-less
project can match an unambiguous project name; LinkedIn's shared attachment viewer
URL never merges unrelated projects. No external destination is guessed.

Attachment descriptions move with their cards from Experience into Projects.
Observed standalone card titles identify the following description text; another
card, role title/date, or role-content heading ends that block. Ambiguous labels
and inline mentions do not establish ownership. Role narrative, employer logos,
and Featured post text remain in place. A Featured post's native preview accompanies its first external project reference.
Inline links retain their resolved destinations after their cards move. Capture
data remains unchanged. Disabling Projects hides all these cards; disabled source
sections and excluded jobs never contribute cards. Custom templates receive the
same consolidated profile view.

Project company logos appear inline immediately before the company name, sized to
1.1 em and linked to the captured company destination when available. Logos can be
reused from visible jobs; unlabeled project logos are matched only when the company
association is unambiguous. Project titles and previews carry their destinations,
so duplicate standalone URL/link rows are omitted. Dates and affiliations appear
above the media, with project descriptions below the image or logo. Projects
without images still display their descriptions. Other distinct references remain
visible. Custom templates can use `entry|project_layout` and its `metadata` and
`description` lists for this presentation view without changing the snapshot.

`build` runs two pdfLaTeX passes in the digest-pinned
[`drpsychick/texlive-pdflatex` image](https://hub.docker.com/r/drpsychick/texlive-pdflatex).
The image is an amd64 image; Docker Desktop uses emulation on Apple Silicon.
Compilation has networking and shell escape disabled. Inputs are mounted read-only,
and a failed build leaves the previous PDF intact. Logs are in `.cache/build/`.
Fixed PDF timestamps and metadata make identical inputs reproducible. When using
`experience.last_years`, pin `experience.as_of` to keep the date window fixed too.

The default layout uses white US Letter pages with 19 mm margins, EB Garamond
type, and unboxed section headings. On the first page, the profile header, linked
contents, and enabled contact information occupy the left column; About starts the right column,
followed by the remaining enabled sections. Later pages use the full text width.
Projects uses two top-aligned columns of entries; long entries continue across pages
without truncation. If it would begin in the first-page identity layout, it starts
on the next page instead. Sections after Projects resume full width.
Disabling About starts the right column with the next enabled section. A minimal
profile produces only its header, without empty section headings. Images and
hyperlinks remain available.

Child headings that repeat their parent section title are omitted, so a Languages
section does not contain another Languages heading. Comparison normalizes Unicode
presentation forms, case, and whitespace; distinct titles and ordinary body text
remain intact. Paragraphs, images, and link destinations survive even when a heading
is suppressed. This presentation rule leaves captured data unchanged. Custom
templates can apply `entry.title|distinct_heading(section.title)` before rendering
an entry heading; an empty result means omit the heading.

Image sizing follows the source's visual roles instead
of download resolution: the profile portrait is a 36.4 mm circle, company/school
logos fit within 8 mm, and site icons fit within 3.5 mm. Featured and Activity images
are larger illustrations; job and project attachments fit within 24 × 14 mm.
Experience logos sit to the left of the employer name, including company headings
for grouped roles, and are not repeated below the job description. Missing logos
leave the company text in place without an empty image placeholder.
The first-page identity column uses the same logo-and-name row for captured header
companies, displaying each matched company once. Labels or identical staged logos
from visible Experience entries establish ownership; unmatched logos stay in the
header gallery. Custom templates can use the `header_logos` filter to obtain the
header display copy and its inline badges without changing the profile snapshot.
The linked logo replaces the separate text reference to the same employer URL;
jobs without a linked logo keep that reference. Rendering also removes LinkedIn's
"helped me get this job" attribution and its repeated fragments from experience,
including the data supplied to custom templates. Captured snapshots remain intact.
Only portraits are cropped to a circle; other images retain their aspect ratio
and full content. These are print proportions, not pixel-for-pixel browser sizes.

Garamond is bundled for offline builds in both compiler backends and used for
the skills cloud too. Font credits and licenses are in
[`pkg/resumeme/latex/resources/fonts/`](../pkg/resumeme/latex/resources/fonts/README.md).
Set `style.paper: a4` for ISO A4; `style.font_size` controls the body text.
Emoji use the image-based `twemojis` package from the
compiler image. Twemoji graphics are copyright Twitter and contributors, licensed
under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); attribution is also
included in PDF metadata. pdfLaTeX supports the configured Latin font repertoire;
unsupported Unicode characters fail compilation rather than silently disappearing.

## Signed releases

Main-branch publication requires `COSIGN_PRIVATE_KEY` and, for an encrypted key,
`COSIGN_PASSWORD`. See the [fork environment variable list](../README.md#fork-environment-variables)
for their exact values and the automatically supplied publication token.

With Cosign installed, generate and configure your key outside the source tree.
Replace `OWNER/resumeme` with your fork's repository name:

```bash
cosign generate-key-pair
gh secret set COSIGN_PRIVATE_KEY --repo OWNER/resumeme < cosign.key
gh secret set COSIGN_PASSWORD --repo OWNER/resumeme
```

Keep the private key in your own secure storage. `*.key` is ignored as a precaution;
the signing workflow reads the secret using `env://COSIGN_PRIVATE_KEY` without
writing it to the workspace or passing its contents as a command argument.

The build signs `resume.pdf` with pinned Cosign 3.1.3, creates a SHA-256 manifest,
signs that manifest, and verifies both signatures before uploading any PDF artifact.
Cosign uses Sigstore's transparency services and includes verification material in
its bundles. Pull requests and non-main branches compile the PDF but do not receive
the signing secret in a step or upload an unsigned PDF.

After every verification stage succeeds, deploy verifies the downloaded artifacts,
commits the PDF to `main`, and uses the GitHub CLI to create a release named
`resume-<source commit SHA>`. Assets are uploaded to a draft before it becomes public:

- `resume.pdf`: signed document.
- `resume.pdf.sig`: detached base64 signature.
- `resume.pdf.sigstore.json`: complete PDF verification bundle.
- `cosign.pub`: public signing key.
- `key-fingerprint.txt`: SHA-256 fingerprint of the DER-encoded public key.
- `source.json`: source commit, compiler image digest, and public-key fingerprint.
- `SHA256SUMS`: SHA-256 hashes of the PDF and its verification metadata.
- `SHA256SUMS.sigstore.json`: signature bundle authenticating the manifest.

Release notes include the PDF hash, key fingerprint, source commit, and verification
commands. Compare the key fingerprint with a separately trusted copy of the signing
key, then verify downloaded assets:

```bash
cosign verify-blob --key cosign.pub --bundle SHA256SUMS.sigstore.json SHA256SUMS
cosign verify-blob --key cosign.pub --bundle resume.pdf.sigstore.json resume.pdf
shasum -a 256 --check SHA256SUMS
openssl pkey -pubin -in cosign.pub -outform DER | shasum -a 256
```

The PDF uses a detached Cosign signature, not an embedded PDF/Acrobat certificate.
The packaged public key lets recipients verify the signature; the independently
trusted fingerprint establishes whose key they are trusting.

## Pipeline and ownership

The workflow follows Polyad's stage architecture: resolve one immutable source
commit; run independent test and build stages; require both in `CI verification`;
then publish the PDF only from `main`. Pushed tags publish the tested runtime
container through a separate stage with `packages: write` and `contents: write`
for the tag release's pull instructions; see
[container publication](containers.md#publish-on-a-tag). Test and build jobs have read-only repository access.
Only the PDF and container publication jobs have `contents: write`. Every external action is pinned by SHA,
Poetry installs from the lockfile, and development tools stay out of runtime installs.

Fork owners must enable Actions and permit `GITHUB_TOKEN` writes. Branch protection
must permit the bot's PDF commit. Publication fetches `main` and requires it still
to match the built source. If another commit arrives, the stale run skips publication;
a concurrent push after that check rejects the ordinary fast-forward update. It
never force-pushes or rebases an obsolete PDF. The bot uses `GITHUB_TOKEN`, so its
generated commit does not start a recursive workflow run. If a run committed the
PDF but failed during release publication, rerunning it recognizes that exact
generated commit and resumes the release. Draft creation also reconciles an
existing draft before retrying after a lost network response.

The Python package separates capture from document generation:

| Path under `pkg/resumeme/` | Responsibility |
| --- | --- |
| `linkedin/browser.py` | Firefox lifecycle, login, and expanded profile capture |
| `linkedin/parsing.py` | LinkedIn HTML extraction into shared profile models |
| `linkedin/links.py` | Safe URL normalization and prose link discovery without network access |
| `linkedin/sections.py`, `linkedin/skills.py` | Section aliases, visible skill labels, and endorsement totals |
| `linkedin/dates.py`, `latex/experience.py` | Employment date interpretation and job visibility before rendering |
| `linkedin/media.py` | Link destination/title inspection, image previews, and portable PNG caching |
| `linkedin/retrying.py` | Bounded exponential retries for browser operations |
| `latex/escaping.py` | Literal text, emoji, and URL conversion for LaTeX |
| `latex/header.py` | Concise identity text and optional connection counts and links |
| `latex/headings.py` | Immediate parent/child heading comparison without changing captured content |
| `latex/lists.py` | List-marker recognition, indentation, and literal prose blocks for rendering |
| `latex/locations.py` | Job location metadata and Google Maps destinations |
| `latex/projects.py` | Consolidated project cards, resolved-link deduplication, and retained role associations |
| `latex/project_descriptions.py`, `latex/project_layout.py` | Attachment description ownership and project text/media ordering |
| `latex/rendering.py` | Visibility filtering, asset staging, and strict Jinja rendering |
| `latex/compilation.py` | Two-pass PDF compilation using the pinned TeX Live container |
| `latex/resources/` | Packaged Jinja template and compiler image manifest |
| `visualization/skills.py` | Skill scoring, deterministic word clouds, and score manifests |
| `config.py`, `models.py`, `resources/` | Shared configuration, profile records, persistence, and schemas |
| `cli.py` | Command orchestration across capture, validation, rendering, and compilation |
| `tests/` | Package-local unit tests and pipeline integration tests |

Capture produces a `Profile` snapshot and cached images. Rendering consumes those
inputs without contacting LinkedIn and passes escaped values to Jinja; Jinja owns
template parsing. Compilation consumes the generated TeX and staged images to
produce the PDF. Both domains use the shared configuration and profile models.

`scripts/` contains repository tooling, CI transport, and release orchestration.
`tex/` holds generated source; `data/` holds owner inputs; `.cache/` holds temporary
browser, test, build, and signing data. The reference projects are not dependencies.

### Document review

The test stage runs [TeXtidote Action](https://github.com/marketplace/actions/textidote-action)
in a read-only job alongside Python checks. It renders the saved profile with the
committed configuration, then checks `README.md` and the configured `output.tex`
using `--check en`. Relative LaTeX inputs resolve from the generated file's directory.

The workflow invokes the upstream action's published `gokhlayeh/textidote` image
by digest. Its default `action.yml` points at `latest`, so pinning only the action's
Git commit would still allow the executable image to change. The workflow records
the image digest explicitly for reproducible reviews.

Annotated HTML reports are retained for 14 days in the `textidote-reports` artifact,
including completed reports when another check fails. Counts appear in the job
summary and findings produce a workflow warning. Spelling, grammar, and style
findings are advisory: technical names, résumé fragments, and custom LaTeX commands
can produce false positives. Review the report before editing the README or the
source LinkedIn profile. TeXtidote never rewrites captured text.
Container execution, invalid inputs, and report-generation failures fail the test
stage and therefore block the shared publication gate. No LinkedIn credentials or
signing secrets are passed to this job.

## Capture limits and recovery

LinkedIn's ordinary sign-in API does not provide a complete profile from a username.
See [API access](https://learn.microsoft.com/en-us/linkedin/shared/authentication/getting-access)
and [LinkedIn's account export](https://www.linkedin.com/help/linkedin/answer/a1339364/downloading-your-account-data?lang=en).
This project reads what the authenticated browser displays and cannot guarantee
content hidden by LinkedIn or anticipate all future markup changes.

Missing headings, empty detail pages, looping pagination, and exhausted expansion
limits fail capture. Unvisited tabbed sections and failed media downloads are recorded as
warnings. A warning-bearing result is written to `.cache/capture/profile.json` for
review instead of replacing the accepted snapshot. `--allow-incomplete` is an
explicit override on capture, validation, render, and build; CI never uses it.

If Firefox reports that its profile cannot be loaded, close the error dialog and
retry `resumeme capture` using the current package. The macOS launcher creates an
absolute profile directory before opening Firefox and retains it across retries. The launcher closes only the process it started, releasing
the profile lock while preserving the local login. If the capture window is closed during login, retry and leave it open.
Authentication challenges remain interactive; the collector does not bypass them.

Refresh expired or unavailable image references with another local capture. Updating
your LinkedIn profile does not automatically update the snapshot: capture again,
review the changes, and commit the new inputs. CI then builds a new signed release.

Retries use exponential delays: 10, 20, 40, 80, 160, then at most 300 seconds,
reminiscent of Kubernetes image-pull backoff. The default five attempts use the
first four delays. HTTP 429 and transient 5xx responses honor Retry-After within
the same cap. Browser timeouts retry reads; schema, ownership, parsing, and signature
validation errors fail visibly. CI network commands use matching defaults through
`RETRY_ATTEMPTS`, `RETRY_BACKOFF_SECONDS`, and `RETRY_MAX_BACKOFF_SECONDS`.
