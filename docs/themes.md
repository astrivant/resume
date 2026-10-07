# Inline themes

`style.theme` defaults to `null`: the renderer uses the base `style` fields.
The checked-in config selects the editable `tiger` theme for this résumé. Use
`style.theme: null` for the neutral base, then run `resumeme build` to regenerate the PDF offline.

Themes are maps of ordinary style fields. Values in the selected theme **override
the base style**, including explicitly configured values. Fields absent from the
theme keep their base values; color lists are replaced in full. For example:

```yaml
style:
  theme: tiger  # null disables theme overrides
  paper: letter
  font_size: 10
  background: 'FFFFFF'
  accent: '3F6248'
  ink: '363636'
  entry_color: '363636'
  skill_colors: ['555555']
  themes:
    tiger:
      accent: '3F6248'
      ink: '363636'
      name_color: '6B2737'
      heading_color: 'A44813'
      entry_color: '363636'
      skill_colors: ['86543B']
    compact:
      paper: a4
      font_size: 10
      show_header_photo: false
      skills_word_cloud: false
```

Here, `tiger` adds warm heading colors while retaining green links. Selecting `compact`
keeps the base colors and changes page and visibility settings. Theme definitions
cannot override `theme` or `themes`, select another theme, or change fields outside
`style`. An unknown selected name, misspelled field, invalid color, or empty cloud
palette fails validation. Custom templates receive the same resolved `style` as
the packaged template. Applying a theme leaves captured profile data unchanged.

All supported presentation fields are listed in the
[configuration reference](README.md#configuration). Overrides are validated using
the same JSON Schema definitions as their corresponding base style fields.

## The tiger palette

The autumn palette draws from [Tiger Lily Plants' CSS](https://tiger-lily-plants.com/assets/main.css),
inspected on October 7, 2026. Burnt copper and bark brown come from the stylesheet;
burgundy, forest green, and soft charcoal complete the print palette. Values live in `resumeme.config.yaml`,
so builds do not fetch the website or change when its CSS changes.

| Color | Hex | PDF role | Reference |
| --- | --- | --- | --- |
| Burgundy | `6B2737` | Profile name: the primary identity anchor | Complementary addition |
| Burnt copper | `A44813` | Section headings: the main scanning landmarks | Site link/navigation color |
| Soft charcoal | `363636` | Bold entry titles and regular body text | Neutral off-black for print |
| Forest green | `3F6248` | All clickable text, including linked titles and locations | Complementary addition |
| Bark brown | `86543B` | Skill cloud: one tone, with size indicating strength | `.tag-icon` |

Color follows purpose: the name anchors the page, warm section headings divide it,
and job titles sit beneath them in bold body ink. Green always identifies a link,
even inside a heading; logos and photographs retain their original colors. The
neutral base style uses dark headings, soft charcoal body text and entry titles,
green links, and a gray cloud.

The theme inherits white paper, Garamond, the two-column opening page, and image
proportions from the base design. The single cloud color avoids implying unrelated
skill categories; word size conveys the reference and endorsement weighting. Custom
multicolor palettes remain supported, with colors assigned by a stable hash of
each label. Changing colors preserves the word positions, weights, and endorsement
counts. Set `background` in either the base style or the selected theme to change
both the page and cloud canvas together.
