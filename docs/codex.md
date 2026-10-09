# Codex summaries

Codex can write the résumé's About paragraph and a short description beneath the
portrait from the visible profile and your additional context. The original
LinkedIn snapshot is retained. Summary text changes the PDF only. A separate
[tag-only skill proposal flow](skills.md) can optionally add missing profile skills
to LinkedIn while retaining every existing skill and endorsement.

## Enable in your fork

Create a project key on the [OpenAI API keys page](https://platform.openai.com/api-keys).
Add it as an **`OPENAI_API_KEY`** repository secret under **Settings -> Secrets and
variables -> Actions**, or use the GitHub CLI's interactive prompt:

```bash
gh secret set OPENAI_API_KEY
```

Configure [resumeme.config.yaml](../resumeme.config.yaml):

```yaml
automation:
  codex:
    enabled: true
    model: gpt-6-astra
    reasoning_effort: low
    about_max_words: 100
    headline_max_words: 18
    context: |
      Target senior platform engineering roles.
      Emphasize developer experience, reliability, and infrastructure automation.
      Use direct, factual language for an engineering audience.
```

`context` accepts writing preferences and additional factual background. It is
committed with the configuration and sent with visible professional text to
OpenAI. Keep credentials out of this field. `model: null` and
`reasoning_effort: null` use the pinned Codex CLI's defaults.
API usage is billed to that project.

Push to `main`, manually dispatch the pipeline on `main`, or push a release tag.
Generation is off by default and does not run on pull requests or other branches.
Tags capture LinkedIn first and generate enabled summaries from that fresh profile.
They can also run the separately enabled skill proposal flow. Enabling either
generator without the API secret fails with a setup message.

## Model selection

This repository selects `gpt-6-astra` with `reasoning_effort: low` for light
reasoning. The model ID and reasoning level are separate settings. Both settings
apply to generic summaries, company/job variants, and tag-only skill proposals.
The upstream [Codex Action](https://learn.chatgpt.com/docs/github-action) receives
them through its `model` and `effort` inputs.

| `automation.codex.model` | Use case |
| --- | --- |
| [`gpt-6-astra`](https://developers.openai.com/api/docs/models/gpt-6-astra) | Detailed writing and demanding reasoning; selected here with low effort. |
| [`gpt-6.1-sol`](https://developers.openai.com/api/docs/models/gpt-6.1-sol) | Complex work with a lower cost than Astra. |
| [`gpt-6-luna`](https://developers.openai.com/api/docs/models/gpt-6-luna) | Focused, frequent generation with low cost and latency. |
| [`gpt-6-sol`](https://developers.openai.com/api/docs/models/gpt-6-sol) | An alternative for existing Sol-based workflows. |

Select a model available to your API project. These choices use the same
`OPENAI_API_KEY` secret; there is no separate key per model. See the
[API setup guide](https://developers.openai.com/api/docs/quickstart) and
[model catalog](https://developers.openai.com/api/docs/models) for current access
and pricing details.

`reasoning_effort` accepts `none`, `minimal`, `low`, `medium`, `high`, `xhigh`,
`max`, or `null`; the selected model must support the value. For Astra, use
`low`, `medium`, `high`, `xhigh`, or `max`. Lower effort favors speed and fewer
reasoning tokens. See [reasoning controls](https://developers.openai.com/api/docs/guides/reasoning).

## Inputs and output

- Section and job exclusions apply before preparing the prompt. Contact blocks,
  images, and remote link metadata are omitted.
- About is replaced only when enabled in the document. Set
  `document.style.show_headline: true` to display the short summary beneath the portrait,
  before company/location details and social links. It replaces the captured
  headline. The default, `false`, hides both headlines without hiding About.
- `headline_max_words` accepts 1-40 words; `about_max_words` accepts 1-300 words.
  Responses exceeding those limits fail validation.
- Minimal profiles can return empty fields. Empty fields retain ordinary rendering.
- JSON includes an owner and input fingerprint. Changes to the evidence, context,
  model, explicit reasoning effort, or word limits require regeneration. Model output is escaped as plain text.

The `resumeme-summary` Actions artifact contains the generated JSON and any
company/job evidence snapshots. The document review and PDF build stages download that same
artifact and independently validate each selected response. TeXtidote checks the
generic document's generated copy. Summary jobs have repository
read permissions, a read-only Codex permission profile, and the action's
`drop-sudo` strategy. The API key is supplied only to the Codex action.
Signing and publication keep their existing jobs and credentials.

The summary-input artifact also uploads the prepared prompts and context for
seven days. Contact fields embedded in ordinary prose are not automatically
redacted. The read-only action can read the job's checkout, including the restored
full profile; the prompt filter is not an exclusive file-access boundary.
`--ephemeral` does not change API retention or remove workflow artifacts/logs.
Review [AI processing and storage](data-handling.md#optional-ai-processing) before
enabling either generator.

## Single-origin resumes

Add company/job targets under `automation.codex.companies`. Each target generates an additional
About paragraph and portrait summary based on the same visible profile, with
emphasis on experience relevant to that employer's position.

```yaml
automation:
  codex:
    enabled: true
    context: Use direct, factual language for senior engineering roles.
    companies:
      - username: example-company
        job_url: https://www.linkedin.com/jobs/view/1234567890/
        context: Emphasize platform reliability and developer tooling.
      - username: example-company
        job_url: https://careers.example.com/jobs/developer-platform
        context: Emphasize cross-team technical leadership.
```

| Field | Required | Meaning |
| --- | --- | --- |
| `username` | Yes | Company slug from `linkedin.com/company/<username>/` |
| `job_url` | Yes | HTTPS link to a specific LinkedIn or external job posting |
| `context` | No | Additional writing preferences for this target |
| `company_context` | No | Company description to use instead of fetching its LinkedIn About page |
| `job_context` | No | Job description to use instead of fetching the job URL |
| `overrides` | No | Partial root configuration inherited only by this company/job variant |

CI creates a summary matrix containing the generic request plus one item per
company/job pair, with up to four generation jobs running concurrently. Each
item uses the same pinned Codex Action with its resolved model, reasoning effort,
and word limits. Adding a company
does not change the generic request. Employer requirements remain separate from
the applicant's facts: the prompt asks for relevant emphasis, not invented skills,
achievements, or employment at the target company. Section, job, education, and
project filters apply to every variant after its overrides are merged.

### Per-posting configuration

`overrides` uses the same field names and validation as `resumeme.config.yaml`.
Omitted fields inherit the base config. Mappings merge recursively; lists replace
the inherited list. Scalars, `false`, and `null` replace the inherited value.
For example, `profile.sections.experience.disable: []` clears inherited job exclusions, while an
omitted `disable` preserves them. An empty mapping changes nothing.

```yaml
automation:
  codex:
    enabled: true
    companies:
      - username: example-company
        job_url: https://www.linkedin.com/jobs/view/1234567890/
        context: Emphasize platform reliability.
        overrides: &platform_resume
          profile:
            sections:
              order: [contact, about, experience, projects, skills]
              experience:
                since: '2020-06-01'
                disable: []
              projects:
                include:
                  - affiliation: Example Company
          document:
            style:
              theme: null
              font_size: 10
              display_current_position: false
          automation:
            codex:
              about_max_words: 70
              headline_max_words: 12
      - username: another-company
        job_url: https://careers.example.com/jobs/platform-engineer
        context: Emphasize developer experience.
        overrides: *platform_resume
```

YAML anchors reuse partials without extra files or a separate preset language.
YAML's `<<` merge also works, but merges at one mapping level; nested values in
each final partial then merge recursively with the base config.

Supported grouped sections are `profile.sections`, `document`, `capture`, and
`automation.codex`. Under `profile.sections`, use `order`, `experience`, `education`,
and `profile.sections.projects.source_url_filter`; under `document`, use `document.style` and `document.template`.
Under `automation.codex`, override `context`, `model`, `reasoning_effort`,
`about_max_words`, or `headline_max_words`. `automation.codex.context` replaces the shared writing context;
the target's sibling `context` remains additional guidance. Theme precedence
still applies: set `document.style.theme: null` to use direct style values, or override
the selected entry under `document.style.themes`.

The LinkedIn capture, account publication settings, Pages/README settings,
logging, summary enablement, skill publication, and target matrix remain global.
Output paths stay matrix-owned under `single-origin/`; those fields are rejected
inside `overrides`. Per-target `capture` settings apply to public company/job and
icon/calendar requests, not a separate browser capture. Relative template and
icon paths remain relative to the main config directory.

Merged settings drive both the prompt's filtered evidence and the resulting PDF.
Changed target overrides invalidate its saved summary bundle. The generic resume
and sibling targets retain their own settings.

Public company/job text is fetched before generation using the configured
timeouts and exponential retries. Supported pages expose LinkedIn description
blocks or Organization/JobPosting JSON-LD. If a page requires login, has expired,
or exposes no usable description, preparation fails with an override instruction.
Paste its text into `company_context` or `job_context` to proceed; supplying both
makes request preparation offline. These fields are committed with your config.

```yaml
    - username: example-company
      job_url: https://www.linkedin.com/jobs/view/1234567890/
      company_context: |
        Example Company builds developer infrastructure for engineering teams.
      job_context: |
        Senior Platform Engineer. Own Kubernetes infrastructure, improve service
        reliability, and collaborate with application teams on developer tooling.
```

The generic PDF keeps its configured `document.output.pdf` path. Additional PDFs use:

```text
resume.pdf
single-origin/
  example-company/
    job-1234567890/resume.pdf
    job-<URL-digest>/resume.pdf
```

LinkedIn jobs use their numeric job ID; external postings use the first 16
hexadecimal characters of the job URL's SHA-256. Multiple jobs at one company
remain independent. Duplicate destinations are rejected. Generated TeX and assets
stay under `.cache/single-origin/`.

Main-branch publication commits the selected PDFs together after validation. The
`resume-pdf` CI artifact also contains them under `single-origin/`. Removed targets
are no longer regenerated; their previously committed PDFs remain until you
remove them. The existing tagged release signs the generic PDF; company PDFs are
additional working artifacts in the repository and CI bundle.

Each response is bound to its owner, visible profile, word limits, model, target,
preferences, and exact fetched descriptions. Builds reuse the saved evidence
without refetching pages. A missing response or changed input fails validation
instead of falling back to generic text for a company.

The action and CLI are pinned in
[stage-summary.yml](../.github/workflows/stage-summary.yml). The integration uses
the official [Codex GitHub Action](https://learn.chatgpt.com/docs/github-action)
and its [structured output contract](https://learn.chatgpt.com/docs/non-interactive-mode).

## Local generation and preview

Install the same Codex CLI version as CI, enable `codex` in the configuration, and
prepare the request:

```bash
npm install -g @openai/codex@0.161.0
poetry run resumeme summary-prompt
```

Set `OPENAI_API_KEY` through your local secret manager or shell, then run:

```bash
CODEX_API_KEY="$OPENAI_API_KEY" codex exec --ephemeral --sandbox read-only \
    --model gpt-6-astra -c 'model_reasoning_effort="low"' \
    --output-schema .cache/codex/schema.json \
    --output-last-message .cache/codex/summary.json - < .cache/codex/prompt.txt
poetry run resumeme build --summary .cache/codex/summary.json
```

Match `--model` to `automation.codex.model` and `-c 'model_reasoning_effort="low"'` to
`automation.codex.reasoning_effort`; omit the corresponding flag when its value is `null`.
See the [Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference).
Review both summary fields before publishing. Requests and generated
JSON stay under ignored `.cache/codex/`; no credentials are written into them.

An ordinary `resumeme build` remains offline and uses captured text. The compiler
never invokes a model or automatically discovers cached summaries. To preview a
CI result locally, download the `resumeme-summary` artifact from the matching
commit and pass its JSON file explicitly with `--summary`.

To prepare the generic and all company requests locally:

```bash
poetry run resumeme summary-prompt --companies
```

Run the same Codex command for each emitted directory, using its `prompt.txt` and
`schema.json` and writing the result to its `summary.json`. Use the model and
reasoning effort recorded in that prompt when a target overrides them. Keep each `company.json`
beside its response. Then build the complete set, or replace `build` with `render`
to inspect the TeX without compiling PDFs:

```bash
poetry run resumeme build \
    --summary .cache/codex/summary.json \
    --company-summaries .cache/codex/companies
```

Enabled GitHub calendars are shared when account and date window match. A target
can hide the graph or move it to the appendix independently; a different account
or window fetches its own calendar once. `--github-calendar` reuses matching
observations from an existing snapshot. For offline builds, all enabled target
graphs must match that snapshot, and configured icons must use local paths.
No additional secrets are required beyond `OPENAI_API_KEY` used by generation.
