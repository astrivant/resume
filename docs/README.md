# Configuration and operation

## Contents

- [Install](#install)
- [Configuration](#configuration)
- [Job filtering](#job-filtering)
- [Education filtering](#education-filtering)
- [GitHub contribution graph](#github-contribution-graph)
- [Job text and subheadings](#job-text-and-subheadings)
- [Environment variables](#environment-variables)
- [Sensitive data handling](data-handling.md)
- [Profile schema and skill clouds](profile-schema.md)
- [Local capture](#local-capture)
- [Rendering and PDF builds](#rendering-and-pdf-builds)
- [Container usage and tag publication](containers.md)
- [Signed releases](#signed-releases)
- [LinkedIn signing identity](ownership.md)
- [LinkedIn application resume uploads](linkedin-resume.md)
- [Pipeline and ownership](#pipeline-and-ownership)
- [Development](development.md)
- [Capture limits and recovery](#capture-limits-and-recovery)

## Install

In your fork's checkout, use Python 3.13+, Poetry 2.5.1, and Firefox or Chrome for capture.
Docker is required for local PDF builds; Actions supplies its own toolchain.

```bash
poetry install --only main
poetry run resumeme --help
```

On macOS, install the host tools from [Brewfile](../Brewfile) and select Python:

```bash
brew bundle install
pipx install --python "$(brew --prefix python@3.13)/bin/python3.13" "poetry==2.5.1"
export PATH="${PIPX_BIN_DIR:-$HOME/.local/bin}:$PATH"
poetry env use "$(brew --prefix python@3.13)/bin/python3.13"
```

Copy [resumeme.config.ref.yaml](../resumeme.config.ref.yaml) to `resumeme.config.yaml`
for a new owner, then set `linkedin.username`,
[capture your profile](#local-capture), then follow [fork publication setup](automation.md#configure-a-fork).

## Configuration

`resumeme.config.yaml` is the active user configuration. The checked-in copy contains
the author's personal settings. Start a new fork by copying
[resumeme.config.ref.yaml](../resumeme.config.ref.yaml) over it, then change
`linkedin.username`. The reference lists package defaults and commented examples;
it is not loaded automatically or merged with the active config. Users must capture their own
profile while signed in. Configuration and snapshot ownership are validated before
rendering. All paths are relative to the configuration file, even when the command
runs from another directory. Unknown fields and paths escaping that directory fail.

`logging.level` defaults to `ERROR`. Logs use the OpenTelemetry SDK's JSON console
format on stdout. `INFO` reports progress; `DEBUG` adds sanitized request and browser
details. Override with `RESUMEME_LOG_LEVEL` or `resumeme --log-level DEBUG capture`.
See [logging controls and record fields](CLI.md#logging).

| Setting | Default | Purpose |
| --- | --- | --- |
| `linkedin.username` | Required | Public username or LinkedIn `/in/<username>/` URL, normalized to a slug; replace the reference placeholder |
| `linkedin.resume.publish` | `false` | Upload the verified signed PDF to LinkedIn's saved application resumes after a tag release; [setup and recovery](linkedin-resume.md) |
| `linkedin.resume.replace_existing` | `false` | After a confirmed upload, delete every other saved LinkedIn resume; the repository's personal config enables this |
| `linkedin.resume.share_with_recruiters` | `null` | After upload, `true` enables recruiter resume-data sharing and `false` disables it; `null` preserves LinkedIn's current setting |
| `readme.mode` | `auto` | [Personal README](automation.md#personal-readme) on forks; `project` preserves a custom README, `resume` generates everywhere |
| `readme.introduction` | `null` | Optional plain-text introduction replacing the personal README boilerplate |
| `codex.skills.enabled` | `false` | Generate evidence-backed skill proposals after tag capture; live publication waits for the signed release; `false` skips generation and its API usage |
| `codex.skills.publish` | `false` | Opt in to adding missing skills to LinkedIn; existing skills and endorsements are always retained |
| `codex.skills.max_skills` | `20` | Maximum suggested skill names per tagged release |
| `codex.skills.context` | Empty | Skill selection preferences; [generation and publishing instructions](skills.md) |
| `linkedin.ownership.update_about` | `false` | Update live About with the public signing fingerprint after a signed release |
| `linkedin.ownership.repository` | `null` | Release repository (`OWNER/REPO`); defaults to Actions context or local origin |
| `linkedin.ownership.releases_url` | `null` | Optional HTTPS short link; otherwise use the repository releases page |
| `logging.level` | `ERROR` | Minimum severity for OpenTelemetry JSON logs on stdout; override with `RESUMEME_LOG_LEVEL` or `--log-level` |
| `section_order` | All known section keys | Enabled sections in PDF and contents order; comment out a key to hide it |
| `project_filter` | GitHub source URLs | Python regex selecting Projects by resolved source URL; `null` includes all projects |
| `projects.include` | `null` | Project filters with `name`, `affiliation`, or both; `null` keeps all projects, `[]` selects none |
| `projects.exclude` | `[]` | Omit matching name/affiliation selectors; exclusions override `include` |
| `experience.disable` | `[]` | Job selectors with `title`, `company`, or both; matching jobs are omitted |
| `experience.last_years` | `null` | Trailing N calendar years when `since` is unset; null keeps all dates |
| `experience.since` | `null` | Inclusive fixed start date; overrides `last_years` when set |
| `experience.as_of` | `null` | Quoted ISO date fixing the window endpoint; null uses today's UTC date |
| `experience.reflow_soft_breaks` | `true` | Join wrapped job prose and bullet continuations; false retains captured line boundaries |
| `experience.subheadings` | Built-in job labels | Complete standalone subsection labels; a supplied list replaces the defaults and `[]` disables recognition |
| `education.disable` | `[]` | Selectors with `school`, `degree`, `major`, or a combination; matching education entries are omitted |
| `github.username` | `null` | Public account used by the profile link and optional contribution graph |
| `github.contributions.enabled` | `false` | Acquire public GitHub activity during `render` or `build` |
| `github.contributions.months` | `1` | Trailing calendar months, from 1 through 12, including both boundary dates |
| `github.contributions.placement` | `profile` | Below the GitHub link in the profile column, or `appendix` for a separate final page |
| `github.contributions.as_of` | `null` | Quoted ISO end date; null uses today's UTC date |
| `capture.browser` | `firefox` | `firefox` or `chrome` for capture, live profile updates, and saved resume uploads |
| `capture.page_timeout_seconds` | `30` | Browser and media request timeout |
| `capture.app_approval_timeout_seconds` | `900` | Headless wait for LinkedIn app approval, capped at 15 minutes; `0` disables waiting. Code-entry MFA and CAPTCHA fail immediately |
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
| `codex.enabled` | `false` | Enable optional generated About and portrait summaries; requires the `OPENAI_API_KEY` Actions secret |
| `codex.context` | `''` | Additional background, target roles, audience, and tone supplied to Codex |
| `codex.model` | `null` | Codex model override, or the pinned CLI's default |
| `codex.reasoning_effort` | `null` | Reasoning level override; this repository selects `low` with `gpt-6-astra`. See [model selection](codex.md#model-selection) |
| `codex.about_max_words` | `100` | Maximum generated About length, from 1 to 300 words |
| `codex.headline_max_words` | `18` | Maximum portrait summary length, from 1 to 40 words |
| `codex.companies` | `[]` | Company usernames and job URLs for additional tailored PDFs under `single-origin/`; see [company summaries](codex.md#single-origin-resumes) |
| `style.profile_column_side` | `left` | `right` places the profile at the upper right and lets body content use the full width beneath it |
| `style.paper` | `letter` | `letter` (8.5 x 11 inches) or `a4` |
| `style.accent` | `245135` | Six-digit hexadecimal link color; deep plant green by default |
| `style.background` | `FFFFFF` | Six-digit hexadecimal page background; white by default |
| `style.font_size` | `10` | Body font size: `10`, `11`, or `12` points |
| `style.show_header_photo` | `true` | Display the cover/background photo; disabled in the author's personal config |
| `style.display_profile_photo` | `true` | Display the round profile portrait in either first-page column; independent of the cover photo |
| `style.display_location` | `true` | Display the profile location and labeled personal address fields; false also removes them from the committed snapshot. Both checked-in configs opt out |
| `style.show_table_of_contents` | `true` | Link visible sections below the LinkedIn profile link in the first-page profile column |
| `style.highlight_job_subheadings` | `true` | Bold recognized job subsection labels with a small preceding gap; false leaves their text plain |
| `style.show_connection_count` | `false` | Show the captured connection count once below the LinkedIn profile link |
| `style.show_connection_link` | `false` | Link the count, or a concise Connections label, to the captured connections page |
| `style.display_birthday` | `false` | Show the birthday field when Contact is enabled |
| `style.display_websites` | `false` | Show captured Website fields in Contact; independent of LinkedIn, Email, and GitHub |
| `style.website_icon` | `null` | Local image path relative to the config directory, or direct public image/favicon URL, beside enabled Website fields |
| `style.display_current_position` | `null` | Sidebar company/logo/title: latest visible role; `true` uses the latest captured role regardless of filters, `false` hides it |
| `style.skills_word_cloud` | `true` | Render Skills as a cloud weighted by references and endorsements |
| `style.skills_allow_vertical` | `false` | Allow mixed vertical and horizontal cloud labels; enabled in this repository |
| `style.skills_size_legend` | `false` | Show character-size examples for 0, 1+, and 5+ endorsements beneath the cloud's color scale |
| `style.ink` | `363636` | Six-digit hexadecimal body text color; soft charcoal by default |
| `style.name_color` | `191919` | Six-digit hexadecimal profile name color |
| `style.heading_color` | `191919` | Six-digit hexadecimal section heading color |
| `style.entry_color` | `363636` | Six-digit hexadecimal entry heading color; matches body text by default |
| `style.skill_colors` | `[777777, 363636]` | Ordered color stops from zero to maximum displayed endorsements |
| `style.theme` | `null` | Optional name from `style.themes`; null uses the base style |
| `style.themes` | `{}` | Inline partial style overrides; the reference config includes `tiger` |
| `template` | `null` | Optional custom Jinja/LaTeX template |

The configuration and profile JSON Schemas are packaged under
`pkg/resumeme/compiler/asts/resources/` and checked by pre-commit.

Select `style.theme: tiger` to use the autumn palette included in the reference
config, or add your own entries under `style.themes`. The selected entry overrides
matching base style fields, including paper size and visibility toggles. Omitted
fields keep their base values. See [inline themes and palette sources](themes.md).

### First-page profile placement

Set `style.profile_column_side: right` for an upper-right profile block. Its height
is measured from the enabled portrait, header text, social links, contents, and
leading Contact section. Body text starts to its left and continues at full width
below it, adjusting at paragraph boundaries. Later pages use the full width.
The default, `left`, retains the original full-height column layout. This setting
also supports inline theme overrides.
An oversized profile block falls back to ordinary flowing columns so long contact
information remains visible.

### Section visibility, order, and tiles

The top-level `section_order` array controls both visibility and order. Move an
entry to reorder it, comment it out to hide it, and uncomment it to restore it:

```yaml
section_order:
  - about
  - experience
  - projects
  # - featured
  - education
  - skills
```

Only listed sections appear, in that order. Missing and empty sections are skipped;
`section_order: []` renders only the profile header. Omitting the setting uses the
package's full default list. Use lowercase `sections[].key` values from
`data/profile.json`; add unfamiliar keys explicitly to include them. Known aliases
are accepted, with their first occurrence setting the position.

[resumeme.config.ref.yaml](../resumeme.config.ref.yaml) lists every known section, with
`contact`, `featured`, `recommendations`, `interests`, `causes`, `organizations`, and
`languages` commented out. The same visibility rules apply before project
consolidation, skill scoring, and Codex summary generation. The captured snapshot
remains complete. The table of contents follows the chosen order, including
generated Projects and Skills sections.

The former top-level `disable` key is no longer accepted. To migrate an older
config, remove it and comment out those keys in `section_order` instead.
`experience.disable` and `education.disable` control individual jobs and education entries.

Contact occupies the first-page identity column above Contents whenever `contact`
is enabled, with both headings at the same size. It groups the LinkedIn and GitHub
links, the profile contribution graph, and captured contact fields. Commenting out
`contact` hides this block; an explicitly configured contribution appendix remains independent.
The compiler removes repeated LinkedIn profile URLs and edit controls, and links
website captions inline. Birthday visibility still follows `style.display_birthday`.
Email addresses display as an envelope icon and a clickable `Email` label.
GitHub and its contribution graph follow the other contact links, immediately above Contents.
Captured Website fields, such as linktr.ee, are hidden by default. Set
`style.display_websites: true` to show them. Optionally set `style.website_icon`
to an image path relative to the configuration directory, such as
`docs/assets/website.png`, or a direct public URL such as
`https://example.org/favicon.ico`. PNG, JPEG, WebP, and ICO favicons are decoded
with [Pillow](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html#ico)
and staged as PNG at the same inline scale as the social icons. URLs must point
to image bytes; HTML pages and SVG are unsupported. Public URLs are downloaded
during rendering using `capture` timeouts and exponential retries, without login
credentials. Use a local path for offline builds. Invalid or unavailable enabled
icons fail the build with a configuration-specific error.
`null` keeps the text-only website row; hidden or absent websites require no icon
file or download. Both settings support inline theme overrides.
About has no forced position beyond its place in the default array.

Projects and Featured use the same two-column tiles with a subtle gray background
and inset padding. Tiles use the full page width and can continue across pages
without truncating long posts. Uncomment `featured` in `section_order` to display posts;
their project previews still consolidate into Projects.

### Header and skills

- `show_headline` controls the captured headline beneath the portrait; it defaults
  to false. Location and the selected employment block are independent. Older snapshots use a
  conservative role-at-company match when an explicit headline field is absent.
- `display_current_position` controls the company, logo, and role title in either
  profile-column layout. `null` selects the first retained Experience role after
  job exclusions, date windows, and section visibility; `true` selects from the
  original capture instead. `false` hides the block. Selection follows LinkedIn's
  listed order, including the first retained role within a company group. With
  no eligible experience, no employment block is shown. This setting also supports
  theme overrides and never restores excluded job descriptions or project assets.
- `github.username` adds a public GitHub link below LinkedIn; `null` hides it.
  Both links have platform icons. This setting is top-level identity configuration.
- `show_header_photo` controls the cover image; `display_profile_photo` independently
  controls the round portrait. Both default to `true`; hiding the portrait removes its layout space.
- `show_table_of_contents` adds links to visible sections in document order.
- `show_connection_count` and `show_connection_link` control connection metadata
  independently. Enabling both links the count.
- `display_birthday` applies only when `contact` is included in `section_order`.
- `skills_word_cloud` replaces the Skills list with the top 20 weighted skills.
  Size represents references plus twice the endorsement count. Color represents
  endorsements relative to the highest count among those 20 skills.
- `skills_allow_vertical` allows vertical labels alongside horizontal ones in the cloud.
  The package default is `false`; this repository enables it.
- `skills_size_legend` shows small, medium, and large `a` examples beneath the
  endorsement color scale. It defaults to `false`; the color scale remains visible.

Set `skills_word_cloud: false` for the text list or comment out `skills` in `section_order` to
hide the section. See [skill scoring](profile-schema.md#scoring-and-rendering) and
[theme configuration](themes.md). All style fields support inline theme overrides.

## Job filtering

Keep job presentation settings under `experience` in `resumeme.config.yaml`:

```yaml
experience:
  disable:
    - title: Intern
      company: Example Company
    - company: Another Employer
  last_years: 5
  since: null
  as_of: null
```

- `disable` accepts selectors with a job `title`, a `company`, or both. All supplied
  fields must match; any matching selector excludes the role. Matches are exact
  after ignoring case and repeated whitespace. A company-only selector hides all
  its roles; a title-only selector hides that title at every employer. Copy titles
  and employer names from the Experience entries in `data/profile.json`, omitting
  the employer's middle-dot separator and `Full-time` or similar employment-type suffix.
- `last_years` is a positive integer, or `null` to keep all dates when `since` is unset. Jobs are included
  when any part of their employment overlaps the inclusive window from N calendar
  years before `as_of` through `as_of`. A job does not have to start inside it.
  Explicit exclusions still take precedence. Future jobs outside the window are
  omitted; current jobs that have already started are included.
- `since` is a quoted `YYYY-MM-DD` string defining a fixed inclusive start, or
  `null` to use `last_years`. When set, it overrides `last_years` and must be on or
  before the effective `as_of` date. For example, `since: '2020-06-01'` with
  `as_of: null` keeps jobs overlapping June 1, 2020 through today, including jobs
  that started earlier and ended on or after that date. The start never advances.
- `as_of` is a quoted `YYYY-MM-DD` string, or `null` for the current UTC date when
  rendering. Pin it for repeatable historical builds; with `null`, the endpoint
  advances over time even if the snapshot does not change. When using `last_years`,
  a February 29 anniversary becomes February 28 in a non-leap cutoff year.

For example, five years ending on `2026-10-07` includes a role held from `2018` to
`2022` and one ending exactly on `2021-10-07`. A role ending on `2021-10-06` is
outside the window. Recognized dates include English month names/abbreviations,
years, and ISO dates. Month-only dates cover the entire month, and year-only dates
cover the entire year: `Oct 2021` and `2021` end dates both overlap this cutoff.
Missing, invalid, or unsupported date text stays visible rather than being guessed.

Grouped employment renders under a single company heading, with nested role titles
and a muted vertical rule. Structured `positions` retain role-specific descriptions,
dates, locations, and references. Filtering removes excluded roles before rendering
and scoring; companies with no retained roles are omitted.

Legacy flattened groups support the same layout when title/date boundaries are
recognizable. Partial job filtering still requires structured positions; run
`resumeme capture` if the filter reports missing role boundaries.

Omitting `experience` from `section_order` hides all jobs. Excluded roles cannot contribute
project attachments or skill references. Independently captured Projects and Skills
entries remain subject to their own section settings.

## Education filtering

Exclude individual schools or qualifications under `education`:

```yaml
education:
  disable:
    - school: Example University
    - degree: Associate's Degree
      major: Mathematics
```

All fields within a selector must match; any matching selector removes the entire
entry. School-only selectors exclude every entry for that school. Degree-only or
major-only selectors apply across schools. Matches are exact, ignoring case,
repeated whitespace, and straight versus curly apostrophes.

Copy the school from the Education entry's `title` in `data/profile.json`. The first
qualification row usually contains `Degree, Major`: `degree` matches the portion
before the first comma or the complete row; `major` matches the remainder. If only
one qualification value is present, either field can match that complete value.
Dates and later descriptive paragraphs are not searched for qualification matches.

The default `disable: []` keeps every entry. Comment out `education` in
`section_order` to hide the entire section. Exclusions run before rendering, asset
staging, skill scoring, and summary generation; the captured snapshot is unchanged.
An empty education list produces no section heading or contents link.

## GitHub contribution graph

```yaml
github:
  username: your-github-account
  contributions:
    enabled: true
    months: 1
    placement: profile
    as_of: null
```

`profile` fills the profile column beneath its GitHub link, following
`style.profile_column_side`. `appendix` adds a separate final page and a contents
link. Longer windows are easier to read in the appendix. The graph uses
Sunday-first weeks, one clickable circle per day, and GitHub's default light-theme
greens independently of your resume theme. Partial weeks stay blank outside the
requested interval. Zero-activity days use the lightest shade.

Each circle opens that account's GitHub overview with the same `from` and `to`
date filters used by GitHub's calendar. Counts and intensity levels come from the
public profile, including private activity only when its count is publicly shown.
No API token, additional Actions secret, or LinkedIn login is needed.
See [GitHub's contribution calendar behavior](https://docs.github.com/en/account-and-profile/how-tos/contribution-settings/viewing-contributions-on-your-profile).

When enabled, `render` and `build` fetch the calendar before compiling. HTTP reads
use the existing `capture` timeout and exponential retry settings. An unavailable,
incomplete, or changed calendar response fails the build instead of drawing
invented zero-activity cells. Disabled graphs make no GitHub requests. The exact
observations are saved beside generated TeX as `github-contributions.json` and
included in CI's `resumeme-source` artifact.

For an offline rebuild, set `as_of` to the saved JSON's `end` date, retain its
username and month window, then supply that file explicitly:

```bash
resumeme build --github-calendar tex/github-contributions.json
```

Tag builds refresh enabled contribution graphs under the configured date window.
The release signs that run's compiled PDF without fetching or rerendering the graph again.

## Job text and subheadings

Job descriptions retain their internal hierarchy. Standalone labels such as
"Responsibilities," "Projects," and "Technologies" use bold body-sized text with a
small preceding gap. Disable that emphasis without hiding the labels:

```yaml
style:
  highlight_job_subheadings: false
```

The default is `true`, and inline themes can override it. Customize recognition
and line reflow under `experience`:

```yaml
experience:
  reflow_soft_breaks: true
  subheadings:
    - Responsibilities
    - Projects
    - Technologies
    - Impact
    - Deliverables
```

This list replaces the defaults shown in `resumeme.config.yaml`. Matching uses the
entire standalone text block, with Unicode normalization, case folding, collapsed
whitespace, and an optional trailing colon. Labels are literal text. "Projects
improved reliability" remains ordinary prose. Adding a label also preserves its
boundary during reflow, including when highlighting is disabled. Use `[]` to turn
off label recognition, or remove individual labels to avoid unwanted emphasis.
These settings apply to standalone jobs and nested roles; they preserve the saved
profile, employer metadata, job titles, and bullet content.

Capture joins text inside inline HTML spans, emphasis, and links. HTML block
elements remain separate paragraphs. Within a captured paragraph, a single `<br>`
or newline can reflow into a space; blank lines, list markers, dates, and recognized
subheadings preserve boundaries. `reflow_soft_breaks: false` keeps those captured
line boundaries for jobs. Normal page-width wrapping still happens in LaTeX.

Older snapshots flattened HTML breaks into independent rows. They retain a
conservative continuation rule for indented bullet fragments and lowercase continuations
after a comma or semicolon.
A fresh capture records the paragraph ownership needed to reflow other soft breaks
reliably. No profile text is discarded by these presentation settings.

## Environment variables

Start with the [fork environment variable list](automation.md#configure-a-fork)
for the signing secrets and automatically supplied GitHub token. No additional
environment variables are required for ordinary capture, builds, or publication.

The following overrides are optional:

- **`RETRY_ATTEMPTS`** - total attempts for transient failures in CI network
  commands; defaults to `5`. Accepts an integer from `1` to `99`.
- **`RETRY_BACKOFF_SECONDS`** - initial delay between those attempts; defaults to
  `10` seconds. Accepts a nonnegative integer. The delay doubles after each retry,
  up to `RETRY_MAX_BACKOFF_SECONDS`.
- **`RETRY_MAX_BACKOFF_SECONDS`** - maximum delay for those retries; defaults to
  `300` seconds. Accepts a positive integer.
- **`SE_CACHE_PATH`** - local Selenium Manager cache directory; defaults to
  `.cache/selenium/` under the configuration directory. Export an absolute path
  before running `poetry run resumeme capture` to use another directory.
- **`SE_AVOID_STATS`** - Selenium Manager statistics opt-out; defaults to `true`.
  Export `false` before capture to allow statistics collection.
- **`RESUMEME_BROWSER_STATE_DIR`** - absolute browser-profile and diagnostic directory.
  CI sets this to a private temporary directory through the encrypted-session wrapper.
  This plaintext working directory must never be cached.
- **`RESUMEME_SESSION_CACHE_DIR`** - optional absolute directory for encrypted session
  envelopes outside the checkout on a dedicated runner. See [session caching](linkedin-session-cache.md).
- **`RESUMEME_LINKEDIN_RUNNER`** - repository Actions variable containing JSON runner
  labels; defaults to `["ubuntu-24.04"]`. It selects only LinkedIn browser jobs.
- **`RESUMEME_TEX_BACKEND`** - PDF compiler backend: `docker` by default on the host,
  or `local` to invoke `pdflatex` directly. The published container sets `local`
  automatically for its bundled toolchain. Ordinary users need no override.

Export retry overrides when running the shell scripts locally, or add them to
the `env` mapping of the relevant job in `.github/workflows/stage-*.yml`. Repository
Actions variables are not automatically exported: adding a repository variable
alone has no effect because these workflows do not read `vars.RETRY_*`.

Browser and image-download retries use the YAML `capture.retry_*` settings instead
of these shell overrides. Profile selection also uses YAML (`linkedin.username`);
`LINKEDIN_USERNAME` (login email/phone) and `LINKEDIN_PASSWORD` supply credentials for
automated login. The same username variable detects public usernames and profile
URLs, which require interactive sign-in and must match the configured owner.
Tag pushes, scheduled runs, and requested manual
refreshes use `capture --headless`; ordinary branch builds consume committed snapshots. See
[monthly authentication setup](automation.md#configure-a-fork).

## Local capture

```bash
poetry run resumeme capture
poetry run resumeme validate
```

Select the browser in `resumeme.config.yaml`; Firefox remains the default:

```yaml
capture:
  browser: chrome  # firefox or chrome
```

Install the selected browser locally. On macOS, the Brewfile installs Firefox;
install the optional Chrome alternative with `brew install --cask google-chrome`.
Both browsers use Selenium, including its
[Chrome options](https://www.selenium.dev/documentation/webdriver/browsers/chrome/)
and [automatic driver management](https://www.selenium.dev/documentation/selenium_manager/).

Each browser opens a dedicated profile under ignored `.cache/firefox/` or
`.cache/chrome/`. Switching browsers requires a separate first login; subsequent
captures reuse that browser's login. The setting also applies to `capture --headless`
and `publish-ownership`. The GitHub Actions Ubuntu runner
[includes both browsers and their drivers](https://github.com/actions/runner-images/blob/main/images/ubuntu/Ubuntu2404-Readme.md#browsers-and-drivers).
The published container bundles Firefox; use local Chrome capture and build the
saved snapshot in the container when choosing Chrome.

Sign in directly in the selected browser window,
complete any MFA, and leave the window open until the command finishes. Login has
no deadline: capture polls once per second until a LinkedIn tab has an authenticated
session cookie and has left the login or challenge page. No extra thread or subprocess
is needed; the same process owns the browser and cleans up on cancellation. Press
Ctrl-C or close the window to cancel. Network page loads retain bounded timeouts. The Python
browser client uses macOS's application launcher for interactive Firefox so it can
access its profile and normal application services; Selenium connects to its loopback
Marionette port. Chrome, headless Firefox, and Firefox on other platforms use Selenium's
native launcher. Selenium Manager resolves the selected browser's driver and caches
downloads under `.cache/selenium/`.

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
starting a browser. Original text and source URLs remain intact. Shared URLs and
images are fetched once per run, and existing local images are reused. Contact
links and LinkedIn navigation are not inspected. `capture.fetch_link_previews: false`
disables remote inspection, while prose URL discovery remains available. Inspection
failures produce the same incomplete-capture diagnostics as media failures and
leave the accepted snapshot unchanged unless explicitly accepted.

The requests session does not receive the browser's LinkedIn cookies or login
credentials. Ordinary local capture retains its unencrypted browser profile for
retries and plaintext diagnostics under ignored `.cache/capture/`. The collected
text is saved before media downloads start so an interrupted download retains an
incomplete diagnostic snapshot. CI uses the [session wrapper](linkedin-session-cache.md)
to place browser state in temporary storage and optionally reuse an encrypted
profile archive; browser files are not part of the capture artifact.

Review the entire snapshot and referenced assets before committing them. They
include captured fields hidden from the PDF by section, job, school, photo, and
contact display settings. They exclude browser credentials, private messages,
the connections address book, and profile-view analytics, but can include the
owner's email, birthday, and other Contact info fields. Refresh publication
commits the full accepted snapshot. See [storage, disclosure, and cleanup](data-handling.md).

If attaching to a Firefox instance you deliberately opened with Marionette, use
`resumeme capture --connect-port PORT`. The command owns that automation session and
closes it on completion. This attachment option requires `capture.browser: firefox`;
Chrome launches its own dedicated session. Ordinary capture requires no port configuration.

## Rendering and PDF builds

```bash
poetry run resumeme render
poetry run resumeme build
```

`render` reads the configured snapshot and cached assets, applies visibility rules,
and writes LaTeX. It runs offline unless the optional GitHub graph is enabled
without `--github-calendar`. `build` then compiles twice using the pinned
[`drpsychick/texlive-pdflatex` image](https://hub.docker.com/r/drpsychick/texlive-pdflatex).
Docker Desktop runs its amd64 toolchain under emulation on Apple Silicon.

Compilation disables networking and shell escape. Failed builds preserve the
previous PDF; compiler logs are in `.cache/build/`. Identical inputs and dependency
versions produce reproducible output. Pin `experience.as_of` when using a date
window in a reproducible build.

### Document layout

The default is US Letter with 19 mm margins and bundled EB Garamond. Set
`style.paper: a4` for ISO A4 and `style.font_size` for 10, 11, or 12 point body text.
The first page has an identity column and a content column starting with About by
default; `section_order` controls the content sequence. Subsequent pages use the
full text width. Projects and Featured use two-column tiles.

With `style.profile_column_side: right`, each body paragraph adjusts its line widths
to the measured profile height. Portraits, headline, social links, contribution
graph, contents, and leading Contact information all participate in that measurement.
Text can widen within a paragraph or bullet as it clears the profile; disabling
items does not reserve their former space. Full-width tiles and the skills plot
can use the remaining first-page area. A profile too tall to leave usable space
below it retains the breakable two-column layout.

| Content | Presentation |
| --- | --- |
| Profile | Round portrait, pronouns beneath the name, company logo beside its name |
| Grouped experience | Company heading followed by nested roles with muted dots beside their titles and a connecting line clear of each dot; long groups continue across pages |
| Projects | Light-gray tiles with linked titles, dates, and a logo beside each company name; associated roles beneath the company, descriptions beneath media |
| Featured | The same two-column tiles, retaining complete post text and links; project previews consolidate into Projects |
| Skills | Up to 20 words; size by combined score, color by relative endorsement count |
| Headings | Child headings identical to their parent are omitted, ignoring case and Unicode/whitespace formatting |
| Lists | Recognized ASCII, Unicode, checkbox, and ordered markers render as bullets with nested indentation |
| Locations | Captured job locations link to Google Maps; work arrangements remain plain text |
| Images | Portrait: 36.4 mm; organization logos: up to 8 mm; icons: up to 3.5 mm; attachments: up to 24 x 14 mm |

Photos and logos retain their proportions; only portraits are cropped. Section and
entry text remains complete across page breaks. LinkedIn UI attribution, repeated
header company names, and redundant standalone references are omitted.

Within a bullet, unindented lowercase text after a comma or semicolon rejoins the
preceding sentence. Explicitly indented continuations also stay in the same item.
Blank lines, new markers, and ordinary paragraph boundaries remain separate; the
saved snapshot is unchanged.

### Project consolidation and links

Projects includes attachments from visible Experience and Featured entries.
Descriptions associated with an attachment move with it; role narrative and
Featured post text remain in their source sections. Disabling Projects also hides
these consolidated attachments.

Project tiles omit standalone skills, tags, and skill-association links. Those
skills still contribute to the central Skills section; there is no tile-visibility
toggle. Project descriptions retain ordinary references to technologies.

Deduplication uses resolved URLs, falling back to captured URLs. Fragments and
trailing slashes are ignored; paths and query strings are significant. Unlinked
attachments can match an unambiguous title within their captured affiliation.
Same-named projects at different companies remain distinct unless they share a
resolved destination. Unknown affiliations do not bridge ambiguous names.
Shared LinkedIn viewer URLs do not identify a unique project.

`project_filter` applies after consolidation and deduplication. By default, only
projects linking to `github.com` appear. The filter uses Python `re.search` on each
resolved destination, falling back to its captured URL when unresolved. Image click
targets count as source URLs; image download URLs, titles, and descriptions do not.
Any matching source URL retains the combined entry. Unlinked projects are omitted
unless the filter is `null`.

```yaml
# Default: github.com and www.github.com, case-insensitive.
project_filter: '(?i)^https?://(?:www\.)?github\.com(?:[/?#]|$)'

# To limit projects to one GitHub account:
# project_filter: '(?i)^https?://github\.com/emmeowzing/'

# To include every project, including entries without a source URL:
# project_filter: null
```

Use single-quoted YAML strings to preserve regex backslashes. Custom expressions
are case-sensitive unless they include `(?i)`; invalid regexes fail configuration
validation. Filtering leaves the snapshot and inline links in role/post narrative
intact. Excluded project entries contribute no media, skill weights, or Codex
summary evidence. It does not change the visibility of other sections.

Use `projects.include` to select individual projects and `projects.exclude` to omit matches:

```yaml
projects:
  include:
    - name: resumeme
    - affiliation: Another Company
    - name: Deployment platform
      affiliation: Example Company
  exclude:
    - affiliation: Archived Company
    - name: resumeme
      affiliation: Former Company
```

Each selector accepts `name`, `affiliation`, or both. A name-only filter matches
the exact **displayed project name** across affiliations. An affiliation-only
filter matches every project associated with that company or organization.
Supply both fields to select a particular company's project by name.
Names and affiliations ignore case and repeated whitespace; affiliation matching
also ignores a trailing period, consistent with company-logo matching. These are
literal matches, not substring searches or regexes. For example, `Deployment
platform` does not match `Deployment platform v2`.

Every supplied field in a selector must match. Any matching inclusion selector includes the project;
the existing project order is preserved. `include: null` (the default) adds no
selector restriction. `include: []` selects no project tiles. `project_filter` still
applies: set it to `null` when selecting projects without GitHub or source links.
Projects must also remain enabled in `section_order`.

`exclude` uses the same selectors and removes a tile if any selector matches,
even if `include` also matches. Its default, `[]`, excludes nothing. To keep
everything except specific projects, use `include: null` with an `exclude` list.

The same field rules apply to `experience.disable` (`title`, `company`) and
`education.disable` (`school`, `degree`, `major`). Each filter requires at least
one supported field. Empty mappings, blank or null field values, and unknown keys
fail configuration validation.

Selection runs after consolidation, so it covers native Projects, attachments
from visible jobs, and previews from enabled Featured posts. Affiliations come
from captured `Associated with COMPANY` metadata or the company associated with
an extracted role. Mentions in descriptions do not establish an affiliation.
When several companies reference the same resolved URL, they share one project
tile; an inclusion matching any affiliation retains that tile and its complete context,
while an exclusion matching any affiliation removes the entire tile.
If the affiliation was not captured, a selector requiring it does not match.
Excluded tiles contribute no media, skill weights, or summary evidence; captured
inputs and ordinary job/post narrative remain intact.

Company names in Projects link to their associated role in Experience. When a
project names multiple roles, the company name targets the first matching role
in document order; each role label also links to its own position. Company-only
associations target the first visible company entry. Excluded or unmatched jobs
remain plain text. Company logos retain their captured external links.

Text, titles, and media use captured link destinations. `capture` and `enrich`
resolve redirects and fetch preview metadata; rendering does not refetch those
links. Optional GitHub calendar acquisition is a separate input stage.
Distinct references remain available even when a duplicate heading or
standalone URL is omitted.

### Templates and assets

Set `template` to a project-relative Jinja file to replace the packaged layout.
See the [template interface](templates.md) for context variables, filters, and
escaping requirements.

Bundled font licenses and credits are in
[`compiler/backends/latex/resources/fonts/`](../pkg/resumeme/compiler/backends/latex/resources/fonts/README.md).
Emoji use Twemoji graphics under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/),
with attribution in PDF metadata. Unsupported Unicode characters fail compilation.

## Signed releases

User-created tag releases require `COSIGN_PRIVATE_KEY` and, for an encrypted key,
`COSIGN_PASSWORD`. See the [fork environment variable list](automation.md#configure-a-fork)
for their exact values and the automatically supplied publication token.

Run the [signing setup script](../scripts/release/setup-signing.sh) from the checkout
on macOS or Linux. It requires Bash, OpenSSL, Cosign 3.x, and an authenticated GitHub
CLI account that can manage your fork's Actions secrets. On macOS,
`brew install openssl@3 cosign gh` installs the tools. On Linux, install
[Cosign](https://docs.sigstore.dev/cosign/system_config/installation/),
[gh](https://github.com/cli/cli#installation), and your distribution's OpenSSL package.
Run `gh auth login` once before setup.

```bash
bash scripts/release/setup-signing.sh --repo YOUR-USERNAME/YOUR-FORK
```

The script generates an OpenSSL P-256 key, imports it into Cosign's encrypted
format, uploads both secrets through `gh`, and prints the public-key fingerprint.
The explicit `--repo` prevents an upstream repository default from selecting the
wrong destination. Key contents and passwords are passed through stdin.

Keep the printed backup directory secure. It contains `cosign.key`, `cosign.pub`,
and `cosign.password` beneath `${XDG_DATA_HOME:-$HOME/.local/share}/resumeme/signing/`.
The temporary unencrypted OpenSSL key is removed when the script exits.
Running setup again without `--key-dir` creates a new identity and replaces the
repository secrets. If an upload fails, retry with the same files:

```bash
bash scripts/release/setup-signing.sh --repo YOUR-USERNAME/YOUR-FORK \
    --key-dir /path/printed/by/setup
```

For an existing key without a saved password file, `gh secret set COSIGN_PASSWORD
--repo OWNER/REPOSITORY` prompts without echoing the password. The private-key secret
must contain the imported `cosign.key`, not the original OpenSSL PEM. Keep the
private key and password in your own secure storage. `*.key` is ignored as a precaution;
the signing workflow reads the secret using `env://COSIGN_PRIVATE_KEY` without
writing it to the workspace or passing its contents as a command argument.
See [Cosign key import](https://docs.sigstore.dev/cosign/key_management/import-keypair/)
and [`gh secret set`](https://cli.github.com/manual/gh_secret_set) for the upstream contracts.

The tag pipeline captures LinkedIn headlessly and builds a new PDF. Its release
stage downloads that run's `resume-pdf` artifact and adds provenance,
then signs it with pinned Cosign 3.1.3, creates a SHA-256 manifest, signs that manifest, and verifies both signatures
before uploading the signed artifacts. Monthly and ordinary builds upload unsigned
working PDFs for verification and publication to `main`.
Cosign uses Sigstore's transparency services and includes verification material in
its bundles. Pull requests and branch builds do not receive the signing secret.

The last page has a light-gray footer to the right of its centered page number,
linking to the release and displaying the full public-key fingerprint (`SHA256:`
followed by the DER digest, wrapped across two lines). The fingerprint
matches `key-fingerprint.txt` and identifies the release's `cosign.pub`; the detached
signature verifies the PDF, including its footer. The release step preserves the
freshly compiled document's body and layout without rerendering it.

Local and monthly builds show a releases link and **Unsigned working copy** instead
of a signing identity. They use `linkedin.ownership.releases_url` or `.repository`,
then the Actions repository or local GitHub origin. Outside a checkout, the link
is omitted if no repository is configured. Signed releases always link to the
actual publishing repository and tag, independent of the About short link.

After verification succeeds, the tag workflow uses the GitHub CLI to publish on
the user-selected tag. Assets are uploaded to a draft before it becomes public.
See [monthly refresh and choosing a release](automation.md). Release assets are:

- `resume.pdf`: signed document.
- `resume.pdf.sig`: detached base64 signature.
- `resume.pdf.sigstore.json`: complete PDF verification bundle.
- `cosign.pub`: public signing key.
- `key-fingerprint.txt`: SHA-256 fingerprint of the DER-encoded public key.
- `source.json`: source commit, compiler image digest, public-key fingerprint, and release URL.
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

CI resolves one immutable source commit. Tag pushes, monthly runs, and requested manual refreshes
capture LinkedIn first; each consumer restores the same complete capture artifact.
Test and build stages run in parallel and are required by `CI verification`.
PDF publication commits the PDF, any refreshed inputs, and the fork's personal
README and first-page preview together only on `main`.
Pushed tags publish the tested runtime
container through a separate stage with `packages: write` and `contents: write`
for the tag release's pull instructions; see
[container publication](containers.md#publish-on-a-tag). Test and build jobs have read-only repository access.
Only the PDF commit, signed release, and container publication jobs have `contents: write`. Every external action is pinned by SHA,
Poetry installs from the lockfile, and development tools stay out of runtime installs.

Version tags set the package version in CI and also publish `resumeme` to
PyPI through `stage-pypi.yml`, using `PYPI_API_TOKEN` from the organization,
repository, or `pypi` environment. This stage uploads the verified distributions
with read-only repository access. See [package releases](development.md#publish-to-pypi).

Fork owners must enable Actions and permit `GITHUB_TOKEN` writes. Branch protection
must permit the bot's PDF commit. Publication fetches `main` and requires it still
to match the built source. If another commit arrives, the stale run skips publication;
a concurrent push after that check rejects the ordinary fast-forward update. It
never force-pushes or rebases an obsolete PDF. The bot uses `GITHUB_TOKEN`, so its
generated commit does not start a recursive workflow run. A publication retry
recognizes an identical generated commit instead of writing it again. User-created
tags separately sign and release the fresh PDF artifact from the same run. Draft creation reconciles
an existing draft after a lost network response.

| Component | Responsibility | Interface |
| --- | --- | --- |
| `linkedin/` | Browser authentication, capture, HTTP enrichment, asset caching | HTML and cached PNGs |
| `compiler/asts/` | HTML parsing, schemas, attrs source and presentation records | HTML/JSON -> typed profile and intermediate records |
| `compiler/passes/` | Visibility, content organization, layout, and navigation | Typed profile -> display structures |
| `compiler/backends/latex/` | Escaping, Jinja resources, fonts, PDF toolchain | Display structures -> TeX -> PDF |
| `compiler/pipeline.py`, `compiler/constants/` | Pass ordering, template bindings, shared vocabularies and target settings | Configured offline compilation |
| `github/contributions.py`, `compiler/asts/contributions.py` | Public calendar acquisition and validated day observations | Optional GitHub graph input |
| `visualization/` | Skill scoring and endorsement colors | Visible profile -> cloud + score manifest |
| `config.py` | Validated runtime and presentation settings | YAML -> typed configuration |
| `cli.py` | Pipeline commands | `capture`, `enrich`, `validate`, `render`, `build` |
| `scripts/` | Tooling, CI, and release automation | Workflow steps and package entry points |

`data/` contains committed inputs, `tex/` contains generated source, and `.cache/`
contains local browser state and build intermediates. Capture and optional GitHub
calendar acquisition own network access; compiler stages consume local inputs. See the
[template interface](templates.md) for rendering extensions.
See [compiler boundaries and pass order](compiler.md) for the internal interfaces.

### Document review

CI runs [TeXtidote Action](https://github.com/marketplace/actions/textidote-action)
against `README.md` and generated LaTeX with `--check en`. The action container is
pinned by digest in `stage-documents.yml`.

Findings are advisory; execution and report-generation failures block publication.
Annotated HTML reports are retained for 14 days in `textidote-reports`, and counts
appear in the job summary. Review technical names and LaTeX-specific findings
before editing source text.

## Capture limits and recovery

LinkedIn's ordinary sign-in API does not provide a complete profile from a username.
See [API access](https://learn.microsoft.com/en-us/linkedin/shared/authentication/getting-access)
and [LinkedIn's account export](https://www.linkedin.com/help/linkedin/answer/a1339364/downloading-your-account-data?lang=en).
This project reads what the authenticated browser displays and cannot guarantee
content hidden by LinkedIn or anticipate all future markup changes.

Recommendations and Interests are collected across every visible tab, including
tabs on the profile itself when there is no initial Show all link. A detail link
revealed by another tab is followed for full pagination. Tab labels are retained
with each entry. Capture collects these sections even when the PDF configuration
hides them.

Missing headings, unreadable tabs, empty detail pages without an explicit empty
state, looping pagination, and exhausted expansion limits fail capture. Failed
media downloads are recorded as warnings. A warning-bearing result is written to `.cache/capture/profile.json` for
review instead of replacing the accepted snapshot. `--allow-incomplete` is an
explicit override on capture, validation, render, and build; CI never uses it.

If Firefox reports that its profile cannot be loaded, close the error dialog and
retry `resumeme capture` using the current package. The macOS launcher creates an
absolute profile directory before opening Firefox and retains it across retries. The launcher closes only the process it started, releasing
the profile lock while preserving the local login. If the capture window is closed during login, retry and leave it open.
Authentication challenges remain interactive; the collector does not bypass them.

Refresh expired or unavailable image references with another local capture or a
manual CI refresh. With LinkedIn secrets configured, the monthly schedule captures
profile changes and updates `main`. Create a tag when ready to publish a signed
version. See [automation and authentication recovery](automation.md).

Retries use exponential delays: 10, 20, 40, 80, 160, then at most 300 seconds,
with the default five attempts using the first four delays. HTTP 429 and transient 5xx responses honor Retry-After within
the same cap. Browser timeouts retry reads; schema, ownership, parsing, and signature
validation errors fail visibly. CI network commands use matching defaults through
`RETRY_ATTEMPTS`, `RETRY_BACKOFF_SECONDS`, and `RETRY_MAX_BACKOFF_SECONDS`.
