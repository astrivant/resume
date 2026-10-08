# Themes

Set `style.theme` to a key in `style.themes`, or `null` to use base style values.
The shipped config selects `tiger`; the package default is `null`.

## Configuration

```yaml
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
  skill_colors: ['777777', '363636']
  themes:
    tiger:
      accent: '245135'
      ink: '363636'
      name_color: '6B2737'
      heading_color: 'A44813'
      entry_color: '363636'
      company_color: '6B2737'
      skill_colors: ['9A7663', '6B2737']
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
| `name_color` | `6B2737` | Profile name |
| `heading_color` | `A44813` | Section headings |
| `company_color` | `6B2737` | Employer names and project affiliations, including linked names |
| `ink`, `entry_color` | `363636` | Body text and entry titles |
| `accent` | `245135` | Other clickable text in deep plant green |
| `skill_colors` | `[9A7663, 6B2737]` | Skill endorsement gradient: muted brown to burgundy |

The tiger palette references [Tiger Lily Plants](https://tiger-lily-plants.com/assets/main.css).
Colors are configured locally; builds do not fetch the stylesheet. Logos and
photographs retain their source colors.

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

Set `skills_allow_vertical: true` to mix vertical and horizontal labels while
favoring horizontal text. The package default is `false`; this repository enables
it. Inline themes can override the setting. Orientation changes keep the same
top 20 skills, scores, colors, and legend.

`skill_colors` is an ordered list of hexadecimal color stops. The first represents
zero endorsements; the last represents the highest endorsement count among the
20 displayed skills. Intermediate counts interpolate between the stops.
The centered cloud includes a compact, unnumbered vertical color scale to its left.
Below the scale, three progressively larger `a` samples illustrate 0, 1+, and 5+
endorsements. These are size references, not exact font-size thresholds: profile
mentions also contribute to size. Single-color palettes omit the scale and its legend.

```text
color percentage = 100 * skill endorsements / highest displayed endorsement count
size weight       = visible references + 2 * observed endorsements
```

Equal endorsement counts receive equal colors regardless of skill name or reference
count. If every count is zero, every word uses the first color. A one-color palette
produces a monochrome cloud. Color changes do not alter word positions or sizes.

See the [configuration reference](README.md#configuration) and
[scoring contract](profile-schema.md#scoring-and-rendering).
