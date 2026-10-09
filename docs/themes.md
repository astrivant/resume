# Themes

Set `document.style.theme` to a key in `document.style.themes`, or `null` to use base style values.
The shipped config selects `tiger`; the package default is `null`.

## Configuration

```yaml
document:
  style:
    theme: tiger
    paper: letter
    font_size: 10
    background: 'FFFFFF'
    accent: '245135'
    ink: '363636'
    entry_color: '363636'
    company_font_size: 13
    company_color: '191919'
    skill_colors: ['363636', '777777']
    themes:
      tiger:
        accent: '245135'
        ink: '363636'
        name_color: '6B2737'
        heading_color: 'A44813'
        entry_color: '363636'
        company_color: '6B2737'
        skill_colors: ['3B1F16', 'D77A2A']
      compact:
        paper: a4
        font_size: 10
        show_header_photo: false
        skills_word_cloud: false
```

Selected theme values override matching base fields. Omitted fields inherit base
values; lists replace their base list in full. Themes support all presentation
fields except `theme` and `themes`. Unknown names, fields, and invalid values fail
configuration validation. Rebuild with `poetry run resumeme build`.

## Color roles

| Setting | Tiger value | Role |
| --- | --- | --- |
| `document.style.name_color` | `6B2737` | Profile name |
| `document.style.heading_color` | `A44813` | Section headings |
| `document.style.company_color` | `6B2737` | Employer names and project affiliations, including linked names |
| `document.style.ink`, `document.style.entry_color` | `363636` | Body text and entry titles |
| `document.style.accent` | `245135` | Other clickable text in deep plant green |
| `document.style.skill_colors` | `[3B1F16, D77A2A]` | Skill endorsement gradient: dark brown for low counts to tangie orange for high counts |

The tiger palette references [Tiger Lily Plants](https://tiger-lily-plants.com/assets/main.css).
Colors are configured locally; builds do not fetch the stylesheet. Logos and
photographs retain their source colors.

## Body spacing and About background

Body typography and About panels also accept theme overrides: `line_height`
is a baseline multiplier (`1` to `2`), `paragraph_spacing` is measured in points
(`0` to `24`), and `about_background` is a six-digit hex color or `null` for
unshaded text. For example, `about_background: 'F0F4F7'` uses a pale gray-blue
panel with the shared project tile corners. The panel follows `later_page_body_width`
with 3 mm padding around the body text; the About heading stays outside it.
See [document layout](README.md#document-layout).

## Company names

`company_font_size` defaults to **13 pt**, with bold weight, above the normal
body subheadings. Set an integer from 10 through 20 to adjust it. `company_color`
defaults to `191919`; the `tiger` theme uses burgundy (`6B2737`). Both fields can
be overridden by any inline theme.

These settings apply to employer names in Experience, company labels beside
profile logos, and project affiliation rows. Recognized employers without logos
receive the same styling. Role titles, employment types, dates, and body
subheadings retain their own sizes and colors. Company links remain clickable
and keep the company color; other links continue to use `accent`.

## Skill endorsement gradient

Set `document.style.skills_allow_vertical: true` to mix vertical and horizontal labels while
favoring horizontal text. The package default is `false`; this repository enables
it. Inline themes can override the setting. Orientation changes keep the same
top 20 skills, scores, colors, and legend.

`document.style.skill_colors` is an ordered list of hexadecimal color stops. The first represents
zero endorsements; the last represents the highest endorsement count among the
20 displayed skills. Intermediate counts interpolate between the stops.
The centered cloud includes a compact, unnumbered vertical color scale to its left.
The `tiger` palette starts with dark brown for unendorsed skills and moves
directly to tangie orange as endorsement counts increase. The two-stop range keeps
the legend and cloud readable without a muddy intermediate gray.
Set `document.style.skills_size_legend: true` to show three progressively larger `a` samples
below the scale, illustrating 0, 1+, and 5+
endorsements. These are size references, not exact font-size thresholds: profile
mentions also contribute to size. Single-color palettes omit the scale and its legend.
The size legend defaults to `false` and supports inline theme overrides.

```text
color percentage = 100 * skill endorsements / highest displayed endorsement count
size weight       = visible references + 2 * observed endorsements
```

Equal endorsement counts receive equal colors regardless of skill name or reference
count. If every count is zero, every word uses the first color. A one-color palette
produces a monochrome cloud. Color changes do not alter word positions or sizes.

See the [configuration reference](README.md#configuration) and
[scoring contract](profile-schema.md#scoring-and-rendering).
