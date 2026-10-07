# Codex summaries

Codex can write the résumé's About paragraph and a short description beneath the
portrait from the visible profile and your additional context. The original
LinkedIn snapshot is retained. Generated text changes the PDF only; it does not
edit your LinkedIn account.

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
default. Pull requests, other branches, and tag builds use captured copy without
calling Codex. Enabling generation without the secret fails with a setup message.

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

The `resumeme-summary` Actions artifact contains the generated JSON. The test and
build stages download that same artifact and independently validate it; TeXtidote
therefore checks the copy used for the signed PDF. The summary job has repository
read permissions, a read-only Codex permission profile, and the action's
`drop-sudo` strategy. The API key is supplied only to the Codex action.
Signing and publication keep their existing jobs and credentials.

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
