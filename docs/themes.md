# Inline themes

`style.theme` defaults to `null`: the renderer uses the base `style` fields.
The reference config includes an editable `tiger` theme. Select it with
`style.theme: tiger`, then run `resume build` to regenerate the PDF offline.

Themes are maps of ordinary style fields. Values in the selected theme **override
the base style**, including explicitly configured values. Fields absent from the
theme keep their base values; color lists are replaced in full. For example:

```yaml
style:
  theme: tiger  # null disables theme overrides
  paper: letter
  font_size: 10
  background: 'FFFFFF'
  accent: '0A66C2'
  themes:
    tiger:
      accent: 'A44813'
      ink: '241A15'
      name_color: '6B2737'
      heading_color: 'C44A11'
      entry_color: '8F2E08'
      skill_colors: ['6B2737', '8F2E08', 'A44813', 'C44A11', '86543B']
    compact:
      paper: a4
      font_size: 10
      show_header_photo: false
      skills_word_cloud: false
```

Here, `tiger` replaces the blue base accent with copper. Selecting `compact`
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
inspected on October 7, 2026. The burgundy is a complementary addition; the other
colors come directly from the stylesheet. Values live in `resume.config.yaml`,
so builds do not fetch the website or change when its CSS changes.

| Color | Hex | PDF role | Reference |
| --- | --- | --- | --- |
| Burgundy | `6B2737` | Profile name and cloud | Complementary addition |
| Burnt orange | `C44A11` | Section headings and cloud | `--color-primary` |
| Deep rust | `8F2E08` | Entry headings and cloud | `--color-primary-dark` |
| Copper | `A44813` | Links and cloud | Site link/navigation color |
| Bark brown | `86543B` | Cloud | `.tag-icon` |
| Warm dark brown | `241A15` | Body text | `--color-surface`, adapted for text on white |

The theme inherits white paper, Garamond, the two-column opening page, and image
proportions from the base design. Skill colors are assigned by a stable hash of
each label. Changing colors preserves the word positions, weights, and endorsement
counts. Set `background` in either the base style or the selected theme to change
both the page and cloud canvas together.
