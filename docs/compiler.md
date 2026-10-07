# Compiler architecture

`compiler/` owns the offline translation from captured HTML or snapshot JSON to
typed profile records, presentation structures, LaTeX, and PDF. Browser sessions,
authentication, HTTP requests, retries, and image downloads remain in `linkedin/`.

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
3. Apply header/contact visibility and consolidate visible project attachments.
4. Score skills and stage local image/font assets.
5. Build section and employment destinations from the retained hierarchy.
6. Apply layout passes and escape text while Jinja emits LaTeX.
7. Compile twice with the pinned toolchain and atomically publish the PDF.

Passes return display copies; they do not modify the snapshot or fetch remote
data. Exclusions precede scoring, media staging, and destination generation.
Hidden jobs therefore cannot contribute assets or dangling internal PDF links.

The CLI remains `resumeme`. Configuration and snapshot locations are unchanged;
internal imports now use `resumeme.compiler`. Custom templates consume the
[documented context and filters](templates.md). Package-local tests remain under
`pkg/resumeme/tests/`, and wheels include schemas, templates, fonts, and notices.
