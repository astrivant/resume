# Profile schema and skill clouds

## Contents

- [Minimal profile](#minimal-profile)
- [Section coverage](#section-coverage)
- [Skills and endorsements](#skills-and-endorsements)
- [Scoring and rendering](#scoring-and-rendering)
- [Verification](#verification)

## Minimal profile

Only the profile slug and display name are required in a snapshot:

```json
{"username": "example-person", "name": "Alex Example"}
```

Missing `sections`, `intro`, `links`, `images`, and `warnings` default to empty
lists. `schema_version` defaults to `1`; `captured_at` defaults to an empty string.
A profile with no optional content renders its name and LinkedIn URL. Empty
sections are omitted from the document. Login pages and pages without an identity
still fail capture.

The [JSON Schema](../pkg/resumeme/compiler/asts/resources/profile.schema.json) validates snapshots;
[typed models](../pkg/resumeme/compiler/asts/profile.py) supply optional defaults. Existing version-1
snapshots remain valid.

## Section coverage

Sections contain a `key`, a `title`, and optional `entries`. Each entry may contain
`title`, full `paragraphs`, labeled `links`, referenced `images`, and structured
`skills`. Text preserves dates, locations, issuers, credential identifiers,
proficiency, collaborators, descriptions, and other displayed fields. Grouped
positions stay together. Media retains its source URL, accessible label, cached
PNG path, and click destination.

Each link retains its original `label` and `url`. Optional `resolved_url` and
`title` fields record the final redirect destination and observed page title;
both default to an empty string in older snapshots. Introspection never replaces
profile prose with remote page content. HTTP(S) and `www.` references in text are
also stored as links, and the PDF uses resolved destinations for inline links,
reference labels, and associated images. Capture and `resumeme enrich` obtain this
metadata; offline builds do not fetch pages.

Grouped employment entries also carry optional `positions`, a list of entries
with each role's own title, paragraphs, links, images, and skills. The parent keeps
its flattened content for compatibility. Capture and media caching retain both;
rendering uses the boundaries for job filtering and nested role progression. Existing snapshots without this metadata
remain valid. See [job filtering](README.md#job-filtering) for configuration and
when an earlier grouped snapshot needs recapture.

The catalog covers LinkedIn's [documented profile sections](https://www.linkedin.com/help/linkedin/answer/a564064/your-linkedin-profile?lang=en)
and [Add profile section choices](https://www.linkedin.com/help/learning/answer/a540837/add-sections-to-your-profile?lang=en):

| Section | Canonical `disable` key |
| --- | --- |
| Contact information | `contact` |
| About | `about` |
| Featured | `featured` |
| Activity visible on the profile | `activity` |
| Experience, including grouped positions | `experience` |
| Education | `education` |
| Services | `services` |
| Career breaks, when displayed separately | `career-breaks` |
| Licenses and certifications | `certifications` |
| Volunteer experience | `volunteering-experiences` |
| Projects | `projects` |
| Publications | `publications` |
| Patents | `patents` |
| Courses | `courses` |
| Honors and awards | `honors` |
| Test scores | `test-scores` |
| Skills and endorsements | `skills` |
| Recommendations | `recommendations` |
| Languages | `languages` |
| Organizations | `organizations` |
| Interests | `interests` |
| Causes | `causes` |

Heading and route aliases are normalized. For example,
`licenses-and-certifications` and `licenses-certifications` both resolve to
`certifications`. Unknown sections retain their normalized heading or route key
and the same content structure, so new section categories need no schema redesign.
Use `sections[].key` from your snapshot for custom exclusions.

Capture retains data from disabled sections. Rendering removes those sections
before asset staging and skill scoring, so hidden content cannot affect the cloud.
Account analytics, editing suggestions, and navigation controls are excluded from
profile content.

## Skills and endorsements

Entries can carry structured skill metadata:

```json
{
  "title": "Python",
  "paragraphs": ["4 endorsements"],
  "skills": [{"name": "Python", "endorsements": 4}]
}
```

`name` is required for a skill; `endorsements` defaults to zero and must be a
nonnegative integer. The parser records visible counts, including accessible
labels on endorsement buttons. Duplicate displays use the largest total, rather
than adding the same endorsements twice. A displayed `99+` contributes the known
lower bound of 99. Missing or undisplayed counts contribute zero.

Job skill associations are stored in `entry.skills` while their summary rows stay
out of job descriptions. A collapsed "+3 skills" does not invent three labels.
Existing snapshots without structured skills still supply names and counts from
their Skills entries. Previously stripped job tags require recapture to recover;
the renderer does not infer them.

## Scoring and rendering

For each named skill or hashtag:

```text
weight = visible references + 2 * observed endorsements
```

One skill declaration contributes one reference. Matching elsewhere is
case-insensitive and uses complete phrases, with longer names matched first.
Multiword skills and names such as C++, C#, .NET, and JavaScript remain intact.
A job tag contributes one reference when it is not already mentioned in that
entry's text. Mirrored link labels do not count again. Unknown aliases are not
inferred, and ordinary prose is not promoted into a skill vocabulary.

The cloud displays the top 20 skills by combined weight, with case-insensitive
alphabetical tie-breaking. Size uses square-root scaling and a minimum size for
legibility. The layout is deterministic for fixed inputs and dependency versions.

Color represents endorsement count independently of references:

```text
endorsement percentage = 100 * endorsements / highest displayed endorsement count
```

`style.skill_colors` defines ordered stops from 0% to 100%. Equal counts share a
color. Profiles with no endorsements use the first stop; a single-stop palette is
monochrome. Raw counts for all skills remain in `tex/skills.weights.json`, including
skills outside the top 20. See [theme configuration](themes.md).

`style.skills_word_cloud: true` replaces the Skills list with the cloud. Explicit
tags can produce a Skills card even when there is no separate captured Skills
section. Omitting `skills` from `section_order` hides the cloud and the list; disabled sections cannot
contribute labels, endorsements, or references. Set `style.skills_word_cloud: false`
to render the captured list. No available skills means no cloud or empty Skills card.

The source snapshot is retained. Custom templates receive the filtered `profile`
and `skill_cloud`, which is a relative PNG path or `None`.

## Verification

The [minimal fixture](../pkg/resumeme/tests/fixtures/profile-minimal.html) and
[maximal fixture](../pkg/resumeme/tests/fixtures/profile-maximal.html) exercise empty
and populated profiles, all catalogued sections, nested jobs, media, endorsements,
and an unfamiliar section. Tests cover schema round trips, exclusions, scoring,
and deterministic PNG generation without a LinkedIn account.

These fixtures validate supported markup and the portable schema. LinkedIn changes
its browser layouts independently; live variants may require additional selectors.
Explicit empty detail states are supported, while an unparsed heading-only detail
page still fails rather than discarding a previously captured preview.
