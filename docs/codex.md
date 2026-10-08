# Codex summaries

Codex can write the résumé's About paragraph and a short description beneath the
portrait from the visible profile and your additional context. The original
LinkedIn snapshot is retained. Summary text changes the PDF only. A separate
[tag-only skill proposal flow](skills.md) can optionally add missing profile skills
to LinkedIn while retaining every existing skill and endorsement.

## Enable in your fork

Add an **`OPENAI_API_KEY`** repository secret under **Settings -> Secrets and
variables -> Actions**, or use the GitHub CLI's interactive prompt:

```bash
gh secret set OPENAI_API_KEY
```

Configure [resumeme.config.yaml](../resumeme.config.yaml):

```yaml
codex:
  enabled: true
  model: null
  about_max_words: 100
  headline_max_words: 18
  context: |
    Target senior platform engineering roles.
    Emphasize developer experience, reliability, and infrastructure automation.
    Use direct, factual language for an engineering audience.
```

`context` accepts writing preferences and additional factual background. It is
committed with the configuration and sent with visible professional text to
OpenAI. Keep credentials out of this field. `model: null` uses the pinned Codex
CLI's default; set a model ID available to your API project to override it.
API usage is billed to that project.

Push to `main` or manually dispatch the pipeline on `main`. Generation is off by
default. Summary generation does not run on pull requests, other branches, or tags.
Tags can run the separately enabled skill proposal flow. Enabling either generator
without the API secret fails with a setup message.

## Inputs and output

- Section and job exclusions apply before preparing the prompt. Contact blocks,
  images, and remote link metadata are omitted.
- About is replaced only when enabled in the document. The short summary appears
  beneath the portrait, before company/location details and social links.
  It replaces the captured headline even when `style.show_headline` is true.
- `headline_max_words` accepts 1-40 words; `about_max_words` accepts 1-300 words.
  Responses exceeding those limits fail validation.
- Minimal profiles can return empty fields. Empty fields retain ordinary rendering.
- JSON includes an owner and input fingerprint. Changes to the evidence, context,
  model, or word limits require regeneration. Model output is escaped as plain text.

The `resumeme-summary` Actions artifact contains the generated JSON and any
company/job evidence snapshots. The test and build stages download that same
artifact and independently validate each selected response. TeXtidote checks the
generic document's generated copy. Summary jobs have repository
read permissions, a read-only Codex permission profile, and the action's
`drop-sudo` strategy. The API key is supplied only to the Codex action.
Signing and publication keep their existing jobs and credentials.

## Single-origin resumes

Add company/job targets under `codex.companies`. Each target generates an additional
About paragraph and portrait summary based on the same visible profile, with
emphasis on experience relevant to that employer's position.

```yaml
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

CI creates a summary matrix containing the generic request plus one item per
company/job pair, with up to four generation jobs running concurrently. Each
item uses the same pinned Codex Action and shared word limits. Adding a company
does not change the generic request. Employer requirements remain separate from
the applicant's facts: the prompt asks for relevant emphasis, not invented skills,
achievements, or employment at the target company. Section, job, education, and
project filters apply to every variant.

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

The generic PDF keeps its configured `output.pdf` path. Additional PDFs use:

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
    --output-schema .cache/codex/schema.json \
    --output-last-message .cache/codex/summary.json - < .cache/codex/prompt.txt
poetry run resumeme build --summary .cache/codex/summary.json
```

If you set `codex.model`, pass the same ID with `--model` to the local Codex
command. Review both summary fields before publishing. Requests and generated
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
`schema.json` and writing the result to its `summary.json`. Keep each `company.json`
beside its response. Then build the complete set, or replace `build` with `render`
to inspect the TeX without compiling PDFs:

```bash
poetry run resumeme build \
    --summary .cache/codex/summary.json \
    --company-summaries .cache/codex/companies
```

The compiler acquires an enabled GitHub calendar once and shares it across the
generic and tailored versions. `--github-calendar` can reuse an existing calendar
snapshot for a fully offline build. No additional secrets are required for company
variants beyond the existing `OPENAI_API_KEY` used by generation.
