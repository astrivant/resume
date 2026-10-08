# Suggested LinkedIn skills

On a tag push, Codex can propose profile skills from the tagged LinkedIn snapshot.
An optional `resumeme publish-skills` command adds missing suggestions to the live
profile after release publication. Existing skills and their endorsements are
always retained. The publisher does not remove, rename, reorder, replace, or
endorse skills.

These are self-declared profile skills. LinkedIn endorsements are validation from
connections, not a count the profile owner can assign.
[LinkedIn's skills and endorsements documentation](https://www.linkedin.com/help/linkedin/answer/a565106/skill-endorsements-overview)
describes that distinction and the 100-skill profile limit.

## Configure generation and publication

```yaml
codex:
  # Independent of codex.enabled, which controls the résumé summaries on main.
  skills:
    enabled: true
    publish: false
    max_skills: 20
    context: Prioritize platform engineering, infrastructure, and developer tooling.
```

- `enabled`: generate a proposal after a signed tag release. The package default
  is `false`. Set it to `false` to skip generation and its API usage.
- `publish`: opt in to live LinkedIn additions after generation and validation.
  Defaults to `false`; this stops LinkedIn writes but does not stop generation.
- `max_skills`: maximum proposed names per tag, from 1 to 100; defaults to 20.
- `context`: selection preferences. Captured text remains the evidence source.

Generation uses `codex.model`, `codex.reasoning_effort`, and the existing `OPENAI_API_KEY`
repository secret. See [model choices and API key setup](codex.md#model-selection).
Publication also needs `LINKEDIN_USERNAME` and `LINKEDIN_PASSWORD`, using the
configured Firefox or Chrome browser. Neither feature runs on branch pushes,
pull requests, monthly refreshes, or manual branch workflows. Ordinary résumé
summary generation keeps its existing main-branch behavior.

To stop all Codex API usage, set `codex.enabled`, `codex.skills.enabled`, and
`codex.skills.publish` to `false`. PDF builds, signed releases, and Pages publication
remain available using the captured profile. No API key is required in this mode.
Commit the config before pushing the next tag: rerunning an existing tag uses
the config at that tag, not the updated config on `main`.

## Proposal contract

The `resumeme-skills` Actions artifact contains `skills.json`, retained for 30 days:

```json
{
  "username": "your-linkedin-slug",
  "source_tag": "resume-2026-10",
  "source_digest": "<SHA-256 of the generation input>",
  "skills": [
    {"name": "Python", "evidence": "Built services with Python and Rust."},
    {"name": "Rust", "evidence": "Built services with Python and Rust."}
  ]
}
```

The digest is generated automatically. Section, job, school, and project filters
apply before preparing evidence. Contact fields and employer/job targeting
requirements are excluded. Each name needs a literal supporting quote from the
retained profile text; unsupported synonyms, duplicate names, invented quotes,
endorsement counts, and oversized responses fail validation. Empty profiles can
produce an empty list. Review the proposed skills and their quotes for relevance.

The artifact is bound to its owner, Git tag, checked-out commit, model, preferences,
and filtered evidence. Changing those inputs requires regeneration. Suggestions
are kept separate from the captured profile and PDF; they do not become observed
skills or endorsements merely because Codex proposed them.

## Review or publish a tagged proposal

In a checkout of the proposal's tag, download its Actions artifact and preview the
missing skills against the live profile:

```bash
git switch --detach resume-2026-10
gh run download RUN_ID --name resumeme-skills --dir .cache/codex/skills
poetry run resumeme publish-skills --tag resume-2026-10 \
    --suggestions .cache/codex/skills/skills.json --dry-run
```

After opting in with `codex.skills.publish: true`, omit `--dry-run` to add the
missing skills. Use `--headless` with the LinkedIn login secrets for unattended
execution. Interactive login waits for you to finish signing in. The command
requires the supplied tag to point to the checked-out commit; in Actions it also
requires a matching tag-push event.

For local Codex generation on a tagged checkout:

```bash
poetry run resumeme skills-prompt --tag resume-2026-10
CODEX_API_KEY="$OPENAI_API_KEY" codex exec --ephemeral --sandbox read-only \
    --output-schema .cache/codex/skills/schema.json \
    --output-last-message .cache/codex/skills/skills.json - < .cache/codex/skills/prompt.txt
```

Use the [same pinned Codex CLI](codex.md#local-generation-and-preview) as CI and
pass `--model` if `codex.model` is set and `-c 'model_reasoning_effort="low"'` for
`codex.reasoning_effort: low` (adjust the value to match your config). The command prepares inputs; CI uses the
upstream Codex action to generate the structured response.

## Preservation and retry behavior

The browser checks owner edit controls and reads the complete live skill list
before writing. It skips existing names, including every endorsed skill. If the
proposal would exceed LinkedIn's 100-skill limit, it fails before adding anything;
it never makes room by deleting a skill. Only exact autocomplete matches are
selected. Use LinkedIn's English interface.

Before each Save, the updater rereads current state. After Save, it verifies the
new skill is present and all previously observed skills remain. A lost response
uses the configured exponential backoff and a fresh read, avoiding duplicate
additions. A failure can leave a partially applied batch; rerunning adds only the
remaining names. Unexpected loss of existing names stops further additions.
Ignored local backups of the prior names are stored under `.cache/skills/`.

CI serializes this job with the signing-identity About updater and skips tags that
are no longer the latest published release. The model receives no LinkedIn
credentials; the browser job receives no OpenAI key or private signing key.
Generation or browser failures do not undo the signed release. Capture again,
or let the monthly refresh run, to include newly added skills in the next PDF.
