# Configuration layout

`resumeme.config.yaml` uses a grouped layout so a setting's path explains which
part of the application consumes it. Copy [the reference config](../.config/resumeme.config.ref.yaml)
and change only the values needed for a fork.

```yaml
logging:
  level: ERROR

capture:
  browser: firefox

profile:
  linkedin:
    username: your-linkedin-username
  github:
    username: your-github-username
  sections:
    order: [contact, about, experience, projects, skills]
    projects:
      source_url_filter: '(?i)^https?://(?:www\.)?github\.com(?:[/?#]|$)'
      include: null
      exclude: []
    experience:
      since: null
      disable: []
    education:
      disable: []

document:
  output:
    pdf: resume.pdf
  style:
    theme: null
  template: null

publishing:
  linkedin:
    resume:
      publish: false
    ownership:
      update_about: false
  readme:
    mode: auto
    output: README.md
  pages:
    enabled: false

automation:
  codex:
    enabled: false
```

## Groups

| Path | Responsibility |
| --- | --- |
| `logging` | Cross-cutting application log severity and output format. |
| `capture` | Browser selection, navigation limits, retries, and link enrichment. |
| `profile.linkedin` | Public LinkedIn profile identity. Login credentials remain environment variables. |
| `profile.github` | Public GitHub identity and optional contribution graph. |
| `profile.sections` | Section order, visibility, filters, and date windows applied to the captured profile. |
| `document.output` | Snapshot, asset, generated TeX, and PDF destinations. |
| `document.style` | Paper, typography, colors, columns, wrapping, and visibility switches. |
| `document.template` | Optional repository-relative Jinja/LaTeX template. |
| `publishing.linkedin` | Signed resume upload and public ownership text updates. |
| `publishing.readme` | Generated README destination and mode. |
| `publishing.pages` | GitHub Pages enablement, path, and custom domain. |
| `automation.codex` | Optional generated summaries, skill proposals, and company-specific variants. |

## Schema design lesson

Configuration is an interface, not an implementation dump. Group fields by the
operation that owns them, and make the path tell a maintainer where the value is
used. Identity and section selection belong under `profile`; files and visual
choices belong under `document`; external writes belong under `publishing`; and
model-assisted work belongs under `automation`. A short key is useful only when
its parent gives it a precise meaning, so `document.output.pdf` is clearer than a
top-level `pdf` or an ambiguous `output` shared by unrelated operations.

Keep one canonical path for every setting. The loader may translate legacy paths
at the input boundary during a migration, but it must reject a file that supplies
both paths instead of choosing a winner. The typed runtime model may be flatter
for implementation convenience; that translation should be explicit and tested
so the public schema remains readable without coupling users to internal classes.

When a schema moves, update the reference config, active examples, partial
overrides, JSON Schema, migration table, CLI and operational documentation, and
round-trip tests in the same change. Validate defaults, unknown fields, nested
overrides, empty and minimal configurations, and the ambiguity rule. This keeps
the configuration language deterministic and lets a maintainer understand both
the human-facing contract and the compiler boundary at a glance.

The loader maps this public structure to the stable typed runtime model used by
the compiler and publishers. That keeps the processing pipeline deterministic
while allowing the configuration language to remain readable. Existing flat
paths remain accepted for migration, but new files should use the grouped form.

## Renamed paths

| Legacy path | Canonical path |
| --- | --- |
| `linkedin.username` | `profile.linkedin.username` |
| `github.*` | `profile.github.*` |
| `section_order` | `profile.sections.order` |
| `experience.*` | `profile.sections.experience.*` |
| `education.*` | `profile.sections.education.*` |
| `projects.include/exclude` | `profile.sections.projects.include/exclude` |
| `project_filter` | `profile.sections.projects.source_url_filter` |
| `output.*` | `document.output.*` |
| `style.*` | `document.style.*` |
| `template` | `document.template` |
| `linkedin.resume` | `publishing.linkedin.resume` |
| `linkedin.ownership` | `publishing.linkedin.ownership` |
| `readme.*` | `publishing.readme.*` |
| `pages.*` | `publishing.pages.*` |
| `codex.*` | `automation.codex.*` |

Do not set a canonical path and its legacy equivalent in the same file. The
loader rejects that ambiguity instead of choosing a winner. The schema accepts
both forms so an existing fork can migrate incrementally, then `config lint`
can verify the result:

```bash
poetry run resumeme config lint resumeme.config.yaml
```

Company-specific `automation.codex.companies[].overrides` use the same grouped
paths, but may change only profile selection, document presentation, or the
Codex writing inputs. Capture identity, publication destinations, and output
ownership remain global or matrix-owned. Lists replace inherited lists; mappings
merge recursively; `null`, `false`, and empty lists are intentional values.
