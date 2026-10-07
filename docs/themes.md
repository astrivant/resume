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
  skill_colors: ['777777', '363636']
  themes:
    tiger:
      accent: '245135'
      ink: '363636'
      name_color: '6B2737'
      heading_color: 'A44813'
      entry_color: '363636'
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
| `ink`, `entry_color` | `363636` | Body text and entry titles |
| `accent` | `245135` | Clickable text in deep plant green |
| `skill_colors` | `[9A7663, 6B2737]` | Skill endorsement gradient: muted brown to burgundy |

The tiger palette references [Tiger Lily Plants](https://tiger-lily-plants.com/assets/main.css).
Colors are configured locally; builds do not fetch the stylesheet. Logos and
photographs retain their source colors.

## Skill endorsement gradient

`skill_colors` is an ordered list of hexadecimal color stops. The first represents
zero endorsements; the last represents the highest endorsement count among the
20 displayed skills. Intermediate counts interpolate between the stops.
The centered cloud includes a short caption and a compact vertical 0–100% color scale to its left;
single-color palettes omit the scale.

```text
color percentage = 100 × skill endorsements / highest displayed endorsement count
size weight       = visible references + 2 × observed endorsements
```

Equal endorsement counts receive equal colors regardless of skill name or reference
count. If every count is zero, every word uses the first color. A one-color palette
produces a monochrome cloud. Color changes do not alter word positions or sizes.

See the [configuration reference](README.md#configuration) and
[scoring contract](profile-schema.md#scoring-and-rendering).
