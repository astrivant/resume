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

## Deterministic contracts

The compiler targets the supported profile schema, not the repository owner's
biography. Rules describe source syntax and ownership: section keys, complete UI
labels, nested roles, captured links, and explicit configuration. Names, employers,
fingerprints, and release hosts are data. Unrecognized prose remains prose;
ambiguous role boundaries produce a `ProfileError` when a requested filter cannot
be applied safely.

The functional core consumes typed, validated values and returns display copies.
It neither mutates caller-owned collections nor acquires external state. Date
windows need a pinned `as_of` or an explicit reference date. Orchestration resolves
UTC once through `passes/context.py` before filtering, evidence hashing, and
calendar validation. `render_profile(..., today=date(...))` supports deterministic
replay in Python; CLI callers can pin `profile.sections.experience.as_of` and
`profile.github.contributions.as_of` in YAML. Unbound date windows called directly through
the pure helpers raise a domain-specific error instead of reading the clock.
Identity-only exclusions do not imply a date window.

For repeatable rendering, retain the same profile, effective configuration,
reference date, template, local assets, optional summary, and contribution calendar.
Fetching a website icon, a new capture, or a model response belongs to orchestration
and changes the inputs. TeX and skill graphics use stable ordering and a fixed
word-cloud seed. Byte-identical PDFs additionally depend on the pinned toolchain,
fonts, release-footer inputs, and PDF postprocessor; source determinism alone does
not establish binary reproducibility across toolchain versions.

The property tests in
[`test_contracts.py`](../pkg/resumeme/tests/compiler/test_contracts.py) generate
minimal and nested schema-valid profiles with independent identities and Unicode
text. They check source preservation, output-schema closure, stable ordering,
normalizer idempotence, explicit date resolution, and repeatable HTML-to-TeX
translation. Targeted cases check repeated accessibility badges, split ownership
records, redirects, and malformed URLs. These are executable contracts over the
tested domain, not a formal proof of totality over arbitrary HTML or all Python
objects. Missing assets, invalid configuration, malformed external observations,
and unsupported filters remain explicit failures.

Only passes documented as normalizers promise idempotence. The whole pipeline is
ordered: visibility must precede scoring, and escaping must happen at the target
boundary. Reordering passes or escaping text twice is not an equivalent operation.

## Compilation order

1. Load and validate configuration and snapshot ownership.
2. Bind explicit date context, discover text links locally, resolve themes, and filter sections and jobs.
3. Apply header/contact visibility, optional validated summary copy, and consolidate visible project attachments.
4. Expand collapsed skill summaries, score skills, and stage local image/font assets.
5. Build section and employment destinations from the retained hierarchy.
6. Apply layout passes and escape text while Jinja emits LaTeX.
7. Compile twice with the pinned toolchain and atomically publish the PDF.

Passes return display copies; they do not modify the snapshot or fetch remote
data. Exclusions precede scoring, media staging, and destination generation.
Hidden jobs therefore cannot contribute assets or dangling internal PDF links.

`passes/ownership.py` treats `resume signature:` and `releases:` as the publisher's
reserved About fields. It first classifies the complete section, then removes
their text, links, and previews even when capture placed them in separate or nested
entries. Original/resolved URL pairs supply redirect equivalence without network
requests; a destination referenced by retained personal prose stays visible.
Identical media in other sections remains owned by those sections.
`passes/experience.py` recognizes repeated full or shortened LinkedIn job badges
as a complete-line grammar, so arbitrary duplication does not require another
literal string exception. Sentences containing those words remain authored prose.

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
