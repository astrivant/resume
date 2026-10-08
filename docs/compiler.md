# Compiler architecture

`compiler/` owns the translation from captured HTML or snapshot JSON to
typed profile records, presentation structures, LaTeX, and PDF. Browser sessions,
authentication, and profile capture remain in `linkedin/`. Compilation uses saved
assets; an explicitly configured public website icon is downloaded during TeX
rendering through the shared credential-free media client. Local icon paths keep
rendering offline, and the PDF compiler runs without network access.

| Package | Responsibility |
| --- | --- |
| `asts/profile.py` | Lossless attrs records and schema-validated snapshot loading |
| `asts/parsing.py` | HTML extraction into the profile structure |
| `asts/dates.py`, `links.py`, `sections.py`, `skills.py` | Lexical interpretation and normalized source values |
| `asts/presentation.py` | Intermediate text blocks, company affiliations, project layout, and job destinations |
| `asts/resources/` | Versioned profile and configuration JSON Schemas |
| `passes/` | Visibility, project consolidation, heading/list normalization, branding, and internal navigation |
| `constants/` | Domain vocabularies, compiled patterns, resource locations, template delimiters, and compiler settings |
| `backends/latex/` | Target escaping, Jinja template, font assets, pinned toolchain, and PDF compilation |
| `pipeline.py` | Pass ordering, resource staging, template bindings, and TeX emission |

The source representation is the existing `Profile`/`Section`/`Entry` tree; it
retains captured text, links, images, skills, and nested positions. Presentation
records describe output layout without replacing the saved source schema.

## Compilation order

1. Load and validate configuration and snapshot ownership.
2. Discover text links locally, resolve themes, and filter sections and jobs.
3. Apply header/contact visibility, optional validated summary copy, and consolidate visible project attachments.
4. Expand collapsed skill summaries, score skills, and stage local image/font assets.
5. Build section and employment destinations from the retained hierarchy.
6. Apply layout passes and escape text while Jinja emits LaTeX.
7. Compile twice with the pinned toolchain and atomically publish the PDF.

Passes return display copies; they do not modify the snapshot or fetch remote
data. Exclusions precede scoring, media staging, and destination generation.
Hidden jobs therefore cannot contribute assets or dangling internal PDF links.

`passes/contact.py` splits flattened contact dialogs into field/value entries,
removes LinkedIn profile navigation and edit controls, and applies birthday
and website visibility before asset staging. Captured labels retain their observed link
destinations; the LaTeX backend renders them inline without a duplicate URL list.
Contact stays in the identity column above Contents, independently of body order.
`backends/latex/assets.py` normalizes a configured local or remote website icon to
a content-addressed PNG only when a Website field survives filtering.

`passes/header.py` selects sidebar employment independently from headline copy.
The default uses filtered Experience; an explicit `true` selects from the original
capture, and `false` omits it. The `HeaderPosition` record carries only company,
title, and logo. Stale captured employer rows are removed before staging, so the
sidebar and custom templates use the same selected identity without restoring
excluded descriptions or project attachments.

Optional [Codex summaries](codex.md) are generated outside the compiler. An explicit
`--summary` artifact must match the profile owner, filtered evidence, and generation
settings before its About and portrait text can be rendered. Ordinary builds
never invoke a model or load cached summary files implicitly.

`passes/skills.py` replaces summaries such as `Python, Bash and +2 skills` with
names recorded in the entry's structured tags or explicit Skills-section
associations. Reverse associations require an exact, unique entry title after
Unicode, whitespace, and case normalization. Repeated labels and endorsement
totals are deduplicated. Employment tags remain hidden from job descriptions.
If the capture lacks enough associated names, the compiler retains the summary
and logs a diagnostic; refreshing the capture supplies the missing evidence.

The CLI remains `resumeme`. Configuration and snapshot locations are unchanged;
internal imports now use `resumeme.compiler`. Custom templates consume the
[documented context and filters](templates.md). Package-local tests remain under
`pkg/resumeme/tests/`, and wheels include schemas, templates, fonts, and notices.
