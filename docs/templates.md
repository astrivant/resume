# Template interface

Set `template` in `resumeme.config.yaml` to a project-relative Jinja file.
Rendering uses strict undefined-variable checks and these delimiters:

- Expressions: `((( value )))`
- Statements: `((* statement *))`
- Comments: `((# comment #))`

## Context

| Variable | Contract |
| --- | --- |
| `profile` | Filtered profile with consolidated projects, staged image paths, and sections in configured display order |
| `style` | Effective style after theme overrides |
| `skill_cloud` | Relative PNG path, or `None` |
| `summary_headline` | Validated generated text beneath the portrait, or an empty string when absent or `style.show_headline` is false |
| `connection_count`, `connection_url` | Enabled captured values, otherwise empty strings |
| `github_username` | Configured public account, or `None` |
| `contributions` | Validated `ContributionCalendar` with `username`, `start`, `end`, `days`, `weeks`, and `total`, or `None` |
| `contribution_colors` | GitHub light-theme hex colors indexed by intensity level 0 through 4 |
| `contribution_placement` | `profile` or `appendix` |
| `contact_enabled` | Whether `contact` is included in `section_order`; controls the identity column's contact and social block |
| `website_icon` | Staged PNG path for the optional website icon, or `None` when unused; use this instead of the configured path or public URL |
| `current_position` | Selected sidebar employment (`title`, `company`, optional staged `logo`), or `None`; independent of body Experience visibility |
| `section_navigation` | `(anchor, section)` pairs in display order with unique TeX-safe anchors |

Filters return presentation values without changing the captured snapshot.
For each calendar day, `contributions.cell(day)` returns its zero-based week,
Sunday-first weekday, and exact GitHub activity URL. Escape that URL with `url`.
Disabled sections and jobs are excluded before templates run.
`section_order` applies after generated and empty sections have settled, so both
`profile.sections` and `section_navigation` have the same sequence. The packaged
template shares its tiled row renderer between Projects and Featured.

## Filters

| Expression | Result |
| --- | --- |
| `text\|tex` | Escaped literal LaTeX text |
| `destination\|url` | Escaped URL for a LaTeX link destination |
| `text\|tex_links(links)` | Escaped text with resolved inline hyperlinks |
| `text\|tex_contact(links)` | Escaped contact captions linked to their captured destinations, including labels without a URL scheme |
| `value\|contact_email_url` | Encoded mailto destination for a single captured email address, or an empty string |
| `paragraphs\|text_blocks` | Blocks with `text` and optional bullet `depth` |
| `entry.title\|distinct_heading(parent_title)` | Original title, or empty when it repeats its parent |
| `entry\|job_locations` | Metadata lines mapped to Google Maps `Link` values |
| `entry\|employer_badge` | `(paragraph_index, logo)` or `None`; index `-1` identifies the company heading |
| `entry\|experience_layout` | Company-only metadata and nested `positions`; standalone entries are unchanged |
| `company\|job_destination(roles=none)` | Anchor for the first matching visible company/role, or an empty string |
| `line\|job_association` | `(prefix, label, anchor)` for a matched affiliation, or `None` |
| `entry\|project_layout(show_title=true)` | Project presentation with `entry`, `title_url`, `affiliations`, `companies`, `metadata`, and `description` |
| `profile\|header_logos` | Header display copy and inline logo mapping keyed by company text |
| `image\|image_role(header=false)` | `cover`, `portrait`, `logo`, `icon`, or `preview` |

Escape user text and URL destinations explicitly. Render paragraphs through
`text_blocks` and `tex_links` to preserve list structure and inline links.

`experience_layout` exposes each role's dates, location, description, and owned
references. Render the company's metadata once, then its positions in order.
Legacy flattened groups split at recognizable title/date boundaries; their media
and links remain at company scope.

The packaged template anchors employment headings with the section anchor plus
`-job-<entry index>`, appending `-<position index>` for each nested role. Indices
start at zero. Custom templates using the job navigation filters must emit these
same destinations for their rendered employment hierarchy.

`project_layout` separates dates and affiliations from descriptive text. Render
`metadata` above project media and `description` below it. Pass `show_title=false`
when omitting a project heading so its destination remains available elsewhere.
`companies` groups recognized affiliations into rows with `company`, `roles`, and
`logo`. When rendering those rows, omit their original keys in `affiliations` from
`metadata`; retain unmatched associations as text.

The [packaged template](../pkg/resumeme/compiler/backends/latex/resources/resume.tex.j2) defines the
default layout and compilation requirements.
