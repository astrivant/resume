# Formatting your LinkedIn profile

Use simple paragraphs, clear labels, and consistent lists in LinkedIn's editor.
Resumeme rebuilds the layout from the captured text and links, so your profile
does not need to imitate the PDF's columns, spacing, or typography.

## Contents

- [Paragraphs and spacing](#paragraphs-and-spacing)
- [Lists and small headings](#lists-and-small-headings)
- [Links, projects, and skills](#links-projects-and-skills)
- [Preview your changes](#preview-your-changes)

## Paragraphs and spacing

- Write each paragraph as continuous text and let the editor wrap it. Avoid
  pressing Enter just to make a line fit your screen.
- Leave a blank line between distinct paragraphs. A single line break inside a
  captured paragraph can be joined back into a sentence during rendering.
- Use normal characters. Avoid decorative Unicode alphabets, repeated spaces,
  tabs used as columns, ASCII tables, or rows of punctuation as separators.
- Keep titles, employers, dates, locations, and schools in their LinkedIn fields.
  Use the description for the work itself rather than repeating that metadata.

Font size, line spacing, paragraph gaps, colors, and columns belong in
`resumeme.config.yaml`. Pasted bold text or website typography is not a substitute
for a recognized subsection label.

## Lists and small headings

Put one item on each line, starting with a hyphen and a space. Keep a bullet's
sentence on that line; normal wrapping happens automatically in the PDF.
Resumeme also recognizes common Unicode bullets, checkboxes, and numbered lists,
but renders them as ordinary bullets. If a step number carries meaning, include
it in the sentence instead of relying on the list marker.

Standalone labels such as `Responsibilities`, `Achievements`, `Projects`, and
`Technologies` become small headings in job descriptions. A trailing colon is
optional. Use a separate line for the label, followed by the relevant bullets:

```text
Built deployment tools for engineering teams and supported their daily operation.

Responsibilities:
- Automated application deployments and rollback checks.
- Improved service diagnostics and incident runbooks.

Achievements:
- Reduced the steps needed to launch a new service.
- Helped teams recover safely from failed deployments.
```

Blank lines make these boundaries clear. A label must match the entire standalone
block: `Projects improved reliability` stays a sentence. For nested lists, use
consistent indentation before the child marker where the editor preserves it;
flat lists are the simplest option.

Custom labels such as `Impact` can be added to `experience.subheadings`. That
array replaces the defaults, so retain the labels you still use.
`style.highlight_job_subheadings` controls their emphasis, and
`experience.reflow_soft_breaks` controls joining captured soft breaks in jobs.
See [job text settings](README.md#job-text-and-subheadings) for the full example.

## Links, projects, and skills

- Supply complete links, such as `https://github.com/your-name/project`, or use
  LinkedIn's native link and attachment fields. Prefer a direct destination over
  a short link and give attachments a meaningful title and description.
- Put project descriptions with the project or attachment. Captured previews from
  roles and Featured can move into the consolidated Projects section with their
  captions. Repeated resolved destinations can merge into one project tile.
- Check project filters if an item is missing. The default URL filter includes
  GitHub projects; other sites require a broader `project_filter` or `null`.
- Keep skill entries in LinkedIn's Skills section. Mention technologies naturally
  when explaining your work; repeated tag-only rows make descriptions harder to
  read. Project skill/tag rows are omitted from tiles.
- Put contact details in Contact info rather than embedding them in About or a
  job description. Display and privacy settings then control the appropriate fields.

## Preview your changes

After saving your edits on LinkedIn, capture them again and rebuild:

```bash
poetry run resumeme capture
poetry run resumeme build
```

Review `resume.pdf` for paragraph boundaries, bullet grouping, recognized labels,
links, and page breaks. Rebuilding from the existing saved profile alone will not
include new edits made on LinkedIn. If a boundary is wrong, first simplify the
source text, then adjust the documented parsing settings if needed.
