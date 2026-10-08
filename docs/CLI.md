# CLI reference

[Project README](../README.md) | [Configuration reference](README.md#configuration)

Run `resumeme` after installation, or `poetry run resumeme` from the project
environment. This reference includes the current CLI's complete `--help` output
in collapsible blocks, plus command behavior and examples.

## Contents

- [Invocation and paths](#invocation-and-paths)
- [Logging](#logging)
- [Commands](#commands)
  - [resumeme capture](#resumeme-capture)
  - [resumeme enrich](#resumeme-enrich)
  - [resumeme validate](#resumeme-validate)
  - [resumeme summary-prompt](#resumeme-summary-prompt)
  - [resumeme render](#resumeme-render)
  - [resumeme build](#resumeme-build)
  - [resumeme site](#resumeme-site)
  - [resumeme publish-ownership](#resumeme-publish-ownership)
  - [resumeme skills-prompt](#resumeme-skills-prompt)
  - [resumeme publish-skills](#resumeme-publish-skills)
- [Exit status](#exit-status)

## Invocation and paths

```bash
resumeme --help
resumeme --config ./resumeme.config.yaml capture
resumeme --config ./resumeme.config.yaml build
resumeme build --help
```

Place the global `--config` option **before** the command. It defaults to
`resumeme.config.yaml` in the current working directory. Configuration output
paths and the `--summary`, `--company-summaries`, `--github-calendar`, and
`--suggestions` paths resolve relative to the configuration directory.
These paths must stay within that directory; absolute paths are rejected.
`--public-key` resolves relative to the current working directory.

Profile identity, browser choice, retries, filters, themes, and output paths are
configured in YAML. See the [configuration reference](README.md#configuration)
and [environment variables](../README.md#fork-environment-variables).

<details>
<summary>resumeme</summary>

~~~text
usage: - [-h] [--config CONFIG]
         [--log-level {DEBUG,INFO,WARNING,ERROR,CRITICAL}]
         {capture,enrich,validate,summary-prompt,render,build,site,publish-ownership,skills-prompt,publish-skills} ...

Capture your LinkedIn profile and build an illustrated PDF résumé.

positional arguments:
  {capture,enrich,validate,summary-prompt,render,build,site,publish-ownership,skills-prompt,publish-skills}
    capture             Open the configured browser, wait for login, and save
                        your expanded profile and images
    enrich              Discover text links, resolve destinations, and cache
                        previews from the saved profile
    validate            Validate configuration and snapshot ownership
    summary-prompt      Prepare a Codex summary prompt and output schema from
                        visible profile text
    render              Generate tex/resume.tex from the saved profile
    build               Render LaTeX and compile resume.pdf with Docker or the
                        bundled container toolchain
    site                Prepare a GitHub Pages site in .cache/pages from the
                        existing PDF
    publish-ownership   Update live LinkedIn About with a signed release's
                        public key identity
    skills-prompt       Prepare an evidence-backed Codex skill proposal for
                        the checked-out tag
    publish-skills      Add missing proposed skills to LinkedIn without
                        changing existing skills

options:
  -h, --help            show this help message and exit
  --config CONFIG       Configuration file (default: resumeme.config.yaml)
  --log-level {DEBUG,INFO,WARNING,ERROR,CRITICAL}
                        Override RESUMEME_LOG_LEVEL and logging.level
                        (default: ERROR)
~~~

</details>

## Logging

Application logs use the [OpenTelemetry SDK console exporter](https://opentelemetry-python.readthedocs.io/en/latest/sdk/_logs.export.html)
and are written to stdout as one JSON object per line. Records include UTC event
and observation timestamps, severity name and number, `service.name: resumeme`,
package version, logger name, structured attributes, and any active OpenTelemetry
trace/span IDs. No collector or network telemetry export is configured.

The default level is `ERROR`. Set `logging.level` to `DEBUG`, `INFO`, `WARNING`,
`ERROR`, or `CRITICAL` in `resumeme.config.yaml`:

```yaml
logging:
  level: ERROR
```

Precedence is **`--log-level` > `RESUMEME_LOG_LEVEL` > `logging.level`**. Place the
global CLI option before the command; CLI and environment values are case-insensitive.

```bash
resumeme --log-level DEBUG capture
RESUMEME_LOG_LEVEL=INFO resumeme build
```

`INFO` reports pipeline progress. `WARNING` includes retries and recoverable
capture failures. `DEBUG` adds request method, sanitized URL, response status,
duration, downloaded byte count, browser navigation, compiler passes, and error
details. Request/response bodies, headers, cookies, and Selenium wire payloads
are not logged. URL credentials, query strings, fragments, and configured secret
values are redacted before export.

Command results remain on stdout alongside enabled logs: output paths, validation
status, and explicit dry-run text are not log records. Argument parser usage errors
remain on stderr. Application failures are structured `ERROR` records on stdout.
Local browser-driver and compiler diagnostic files remain separate from this log stream.

Library callers can opt into the same exporter with
`resumeme.telemetry.logging_context(level="DEBUG")`; importing the package does
not configure the host application's root logger. The context restores handlers
when it exits, so repeated calls do not duplicate records.

## Commands

### resumeme capture

Open Firefox or Chrome, wait for authentication, and save the expanded profile
and downloaded assets to `output.profile` and `output.assets`. Interactive login
waits until you finish. `--headless` requires `LINKEDIN_USERNAME` (email/phone) and
`LINKEDIN_PASSWORD`. The same username variable accepts public usernames and
profile URLs, which are normalized and use manual login without `--headless`.
See [credential setup](automation.md#configure-a-fork).
`--connect-port` attaches to an existing Firefox Marionette
session and requires `capture.browser: firefox`.

```bash
resumeme capture
resumeme capture --headless
```

If capture records warnings, the diagnostic snapshot goes to
`.cache/capture/profile.json` and the accepted snapshot stays intact. Use
`--allow-incomplete` to explicitly accept that diagnostic result. See
[capture configuration](README.md#configuration).

<details>
<summary>resumeme capture</summary>

~~~text
usage: resumeme capture [-h] [--allow-incomplete] [--connect-port CONNECT_PORT]
                        [--headless]

options:
  -h, --help            show this help message and exit
  --allow-incomplete    Explicitly accept recorded capture warnings or missing images
  --connect-port CONNECT_PORT
                        Attach to an explicitly opened local Firefox Marionette port
  --headless            Capture unattended using LinkedIn login environment variables
~~~

</details>

### resumeme enrich

Read the saved profile, discover links in its text, resolve remote destinations,
and cache previews and images. Saves the enriched snapshot to `output.profile`.
This command uses network requests and does not launch a login browser. Warnings
follow the same diagnostic/acceptance behavior as `capture`.

```bash
resumeme enrich
```

<details>
<summary>resumeme enrich</summary>

~~~text
usage: resumeme enrich [-h] [--allow-incomplete]

options:
  -h, --help          show this help message and exit
  --allow-incomplete  Explicitly accept recorded capture warnings or missing images
~~~

</details>

### resumeme validate

Validate the configuration and saved profile schema, require the snapshot owner
to match `linkedin.username`, and reject capture warnings unless
`--allow-incomplete` is set. Prints the profile name and section count on success.
This command does not compile a PDF or check remote links.

```bash
resumeme validate
```

<details>
<summary>resumeme validate</summary>

~~~text
usage: resumeme validate [-h] [--allow-incomplete]

options:
  -h, --help          show this help message and exit
  --allow-incomplete  Explicitly accept recorded capture warnings or missing images
~~~

</details>

### resumeme summary-prompt

Prepare `.cache/codex/prompt.txt` and `schema.json` from visible profile evidence.
Requires `codex.enabled: true` and a complete snapshot. This command prepares
inputs; the Codex CLI or CI action performs generation separately.

`--companies` also acquires configured company/job context and writes a prompt,
schema, and evidence under `.cache/codex/companies/<company>/<job>/`. Supplying
both `company_context` and `job_context` avoids those remote fetches.

```bash
resumeme summary-prompt
resumeme summary-prompt --companies
```

See [Codex generation and company variants](codex.md) for the model invocation,
API key, response format, and CI behavior.

<details>
<summary>resumeme summary-prompt</summary>

~~~text
usage: resumeme summary-prompt [-h] [--allow-incomplete] [--companies]

options:
  -h, --help          show this help message and exit
  --allow-incomplete  Explicitly accept recorded capture warnings or missing images
  --companies         Also acquire configured employer/job context and prepare each
                      prompt
~~~

</details>

### resumeme render

Generate `output.tex` (default `tex/resume.tex`), stage its image assets, and
write skill scores from the saved snapshot. Does not invoke the LaTeX compiler.

Pass `--summary` to apply a generated summary explicitly. Pass
`--company-summaries` to additionally render configured company/job variants
under `.cache/single-origin/`; this does not replace the generic document.
Each selected response must match its owner and source evidence.

When GitHub contributions are enabled, rendering fetches their calendar unless
`--github-calendar` supplies captured JSON. The saved calendar must match
`github.username`, `github.contributions.months`, and
`github.contributions.as_of`; set `as_of` to its end date for an offline replay.

```bash
resumeme render
resumeme render --summary .cache/codex/summary.json
resumeme render --github-calendar tex/github-contributions.json
```

See [templates](templates.md) and [GitHub activity](README.md#github-contribution-graph).

<details>
<summary>resumeme render</summary>

~~~text
usage: resumeme render [-h] [--allow-incomplete] [--summary SUMMARY]
                       [--company-summaries COMPANY_SUMMARIES]
                       [--github-calendar GITHUB_CALENDAR]

options:
  -h, --help            show this help message and exit
  --allow-incomplete    Explicitly accept recorded capture warnings or missing images
  --summary SUMMARY     Generated summary JSON relative to the configuration directory
  --company-summaries COMPANY_SUMMARIES
                        Explicit directory of company/job summary artifacts to render
                        additionally
  --github-calendar GITHUB_CALENDAR
                        Reuse captured calendar JSON instead of fetching GitHub; match
                        github.contributions.as_of
~~~

</details>

### resumeme build

Render the same inputs and options as `render`, then compile `output.pdf`
(default `resume.pdf`). Local source/package installs use Docker; the published
runtime container uses its bundled TeX toolchain. The generic PDF is replaced
only after successful compilation.

```bash
resumeme build
resumeme build --summary .cache/codex/summary.json \
    --company-summaries .cache/codex/companies
```

Company PDFs go to `single-origin/<company>/<job>/resume.pdf` in addition to the
generic PDF. This command produces working PDFs; tag CI handles signing and
release publication. See [container usage](containers.md) and
[signed releases](README.md#signed-releases).

<details>
<summary>resumeme build</summary>

~~~text
usage: resumeme build [-h] [--allow-incomplete] [--summary SUMMARY]
                      [--company-summaries COMPANY_SUMMARIES]
                      [--github-calendar GITHUB_CALENDAR]

options:
  -h, --help            show this help message and exit
  --allow-incomplete    Explicitly accept recorded capture warnings or missing images
  --summary SUMMARY     Generated summary JSON relative to the configuration directory
  --company-summaries COMPANY_SUMMARIES
                        Explicit directory of company/job summary artifacts to render
                        additionally
  --github-calendar GITHUB_CALENDAR
                        Reuse captured calendar JSON instead of fetching GitHub; match
                        github.contributions.as_of
~~~

</details>

### resumeme site

Build `.cache/pages/` from the existing PDF and matching profile snapshot.
`pages.path` selects the site's publication path. The command prepares files
without rebuilding the PDF or deploying to GitHub Pages.

`--repository OWNER/REPO` selects the publishing repository. Otherwise the
command uses `GITHUB_REPOSITORY`, then the local Git `origin`.

```bash
resumeme site --repository YOUR-USERNAME/YOUR-FORK
```

See [Pages configuration and local preview](pages.md#local-preview).

<details>
<summary>resumeme site</summary>

~~~text
usage: resumeme site [-h] [--repository REPOSITORY]

options:
  -h, --help            show this help message and exit
  --repository REPOSITORY
                        Publishing OWNER/REPO; defaults to GITHUB_REPOSITORY or the
                        local Git origin
~~~

</details>

### resumeme publish-ownership

Update the live LinkedIn About section with the supplied public key's fingerprint
and configured release link, preserving the surrounding About text. Requires no
captured snapshot. `--dry-run` opens the browser and prints the proposed About
text without saving it.

```bash
resumeme publish-ownership --public-key cosign.pub --dry-run
resumeme publish-ownership --public-key cosign.pub
```

The local command explicitly authorizes the update regardless of the CI setting
`linkedin.ownership.update_about`. `--public-key` is relative to the current
working directory. `--headless` requires both LinkedIn login environment variables;
`--connect-port` is for an existing Firefox session. See
[ownership publication and verification](ownership.md).

<details>
<summary>resumeme publish-ownership</summary>

~~~text
usage: resumeme publish-ownership [-h] --public-key PUBLIC_KEY [--dry-run]
                                  [--headless] [--connect-port CONNECT_PORT]

options:
  -h, --help            show this help message and exit
  --public-key PUBLIC_KEY
                        Release cosign.pub path relative to the current directory
  --dry-run             Read and preview About without submitting any changes
  --headless            Use LinkedIn login environment variables without a desktop
  --connect-port CONNECT_PORT
                        Attach to an explicitly opened local Firefox Marionette port
~~~

</details>

### resumeme skills-prompt

Prepare `.cache/codex/skills/prompt.txt` and `schema.json` for a skill proposal.
Requires `codex.skills.enabled: true`, a complete matching snapshot, and an
existing `--tag` pointing to the checked-out commit. It is independent of the
`codex.enabled` summary switch and does not invoke Codex itself.

```bash
resumeme skills-prompt --tag resume-2026-10
```

In Actions, a matching tag-push event is also required. See
[skill generation](skills.md) for the structured response and generation command.

<details>
<summary>resumeme skills-prompt</summary>

~~~text
usage: resumeme skills-prompt [-h] --tag TAG

options:
  -h, --help  show this help message and exit
  --tag TAG   Existing Git tag pointing to the checked-out commit
~~~

</details>

### resumeme publish-skills

Validate a generated skill proposal against the configured owner, tag, and
source evidence, then add only missing names to the live LinkedIn profile.
Existing skills and endorsements are retained. A full list stops publication;
the command never removes skills to make room.

```bash
resumeme publish-skills --tag resume-2026-10 \
    --suggestions .cache/codex/skills/skills.json --dry-run
```

`--dry-run` compares against the live profile and prints proposed additions
without saving. For live additions, set `codex.skills.publish: true` and omit
`--dry-run`. Both modes require `codex.skills.enabled: true` and the matching
tagged checkout; Actions additionally requires that tag's push event.
`--headless` requires both LinkedIn login environment variables. A validated
empty proposal completes without opening a browser.

A failure can leave some additions applied. Retries reread the live list and skip
names already present. See [skill publication](skills.md#review-or-publish-a-tagged-proposal)
for artifact download, opt-in settings, and retry behavior.

<details>
<summary>resumeme publish-skills</summary>

~~~text
usage: resumeme publish-skills [-h] --suggestions SUGGESTIONS --tag TAG [--dry-run]
                               [--headless] [--connect-port CONNECT_PORT]

options:
  -h, --help            show this help message and exit
  --suggestions SUGGESTIONS
                        Generated skills JSON relative to the configuration directory
  --tag TAG             Existing Git tag matching the proposal and checked-out commit
  --dry-run             Compare with live skills and print additions without saving
  --headless            Use LinkedIn login environment variables without a desktop
  --connect-port CONNECT_PORT
                        Attach to an existing local Firefox Marionette port
~~~

</details>

## Exit status

| Code | Meaning |
| --- | --- |
| `0` | Command completed successfully, including `--help` and successful dry runs |
| `2` | Invalid arguments, configuration, snapshot, or a reported pipeline/browser failure |
| `130` | Operation interrupted with Ctrl-C |

Application failures are logged as OpenTelemetry JSON on stdout; argument usage
errors remain on stderr. Commands print result paths or status on stdout;
`publish-ownership --dry-run` prints the proposed About text. After a browser
interruption during Save, inspect the live profile or rerun the command to
reconcile persisted changes.
