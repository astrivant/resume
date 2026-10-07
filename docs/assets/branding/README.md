# Project logo

`resumeme-logo.png` is the transparent README logo. Its two immutable source
layers are `linkedin-base.png` and `coffee-ring.png`. The composition is inspired
by [LaTeX Coffee Stains](https://www.overleaf.com/latex/examples/latex-coffee-stains/qsjjwwsrmwnc)
by Hanno Rein and collaborators. The source layers were generated with the built-in
image-generation tool; no Overleaf package files or artwork were copied.

CI renders a new composition only when it has a changed résumé or profile to
commit. The verified source SHA controls the stain's rotation, reflection,
proportions, position, saturation, brightness, and opacity. The ring sits off
center toward a corner, with room for its entire outline and droplets. The blue
mark stays fixed at 80% opacity and 80% saturation beneath the coffee layer.
A retry uses the same seed and locked Pillow dependency, and reproduces the same
PNG bytes. No API key, network request, clock, or run counter is involved.

Preview a revision locally from the repository root:

```bash
poetry run python scripts/ci/refresh-logo.py --seed "$(git rev-parse HEAD)"
```

Use `--output .cache/branding-preview.png` to preview without replacing the README
asset. Changing the bundled layers or renderer changes the composition; keep
them with the source revision when reproducing an older logo.

## Generation prompts

Both source layers were edited from the initial generated coffee-stained mark.
These prompts describe asset creation; CI only composites the saved layers.

### Initial concept

Use case: logo-brand.
Asset type: final standalone square project logo for the open-source Python project resumeme, used at the top of its GitHub README.
Primary request: a coffee-stained LinkedIn logo.
Subject: the immediately recognizable LinkedIn icon: a flat LinkedIn-blue #0A66C2 square with subtly rounded corners, containing the correct bold white lowercase letters "in" and the dot over the i.
Stain treatment: inspired by the Overleaf "LaTeX Coffee Stains" example by Hanno Rein and collaborators: an organic, imperfect approximately 270-degree coffee-cup ring, uneven ink-like edges, translucent espresso-brown and warm burnt-orange staining, and two or three tiny natural splashes. Overlay the coffee ring on the blue mark and its white lettering; allow parts of the ring to extend modestly outside the blue square. Preserve the readability of the in mark at README icon size.
Style: polished, minimal flat graphic logo with authentic paper-absorbed coffee texture confined to the stain. Strong clean geometry for the underlying brand mark; the stain provides the handmade character.
Composition: one centered logo, square 1024 by 1024 canvas, icon and stain together fill approximately 82% of the canvas with clear margins and no clipped droplets.
Text verbatim: "in". Do not add resumeme or any other words.
Background: true transparent alpha outside the icon and stain; no paper rectangle or scene.
Avoid: coffee cups, mugs, beans, desk scenes, 3D rendering, bevels, drop shadows, extra symbols, watermark, multiple concepts, heavy grunge, background checkerboard drawn into the image.

### Clean mark

Use case: precise-object-edit. Edit target: the supplied coffee-stained LinkedIn project logo. Create the pristine base layer for a programmatically composited logo. Remove ALL coffee rings, droplets, brown coloration, shadows, and mottling. Retain only a crisp, perfectly flat LinkedIn-blue #0A66C2 subtly rounded square with the original bold white lowercase "in" and white dot, preserving recognizable LinkedIn lettering and its proportions. Center the blue square with approximately 12% transparent margin on all sides. Square canvas, true transparent alpha outside the blue square. No other graphics or words. This must be a clean blue-and-white logo with NO stain; a separate image will supply the coffee layer.

### Coffee overlay

Use case: precise-object-edit. Edit target: the supplied coffee-stained LinkedIn project logo. Isolate just its irregular broken coffee-cup ring and a few small droplets as a reusable transparent overlay. Delete the blue square and ALL white lettering completely; the interior of the ring must be fully transparent, as must the background outside the ring. Replace portions of the ring previously contaminated by blue with natural warm espresso-brown coffee hues. Keep the asymmetric approximately 270-degree organic ring, absorbent ragged edges, subtle translucent brown washes, and two or three small natural splashes. Keep the ring delicately stained and uneven, like the Overleaf LaTeX Coffee Stains example. Center the whole stain inside a square canvas with at least 15% transparent margins so it can be rotated without clipping. No letters, blue areas, mugs, paper, shadows, checkerboard pattern, or any other objects. True transparent alpha background and ring interior.
