# BRUH Apps branding

Source SVGs for the add-ons in this repo. The SVGs are the source of truth;
every PNG is derived from them by `render.mjs` and should be regenerated, not
hand-edited.

## brAIn

The brAIn mark is a **descendant of the BRUH Automation logo, not a lookalike**.
The `BR` ligature, the gable and the signal motif are lifted unmodified from
`bruh-logo-dark.svg`; only the `A`, `I` and `N` are newly drawn, as monoline
geometric caps built on the parent's own ratios (cap height 135, stem 15, so
stroke-to-cap `0.111` against the parent `H`'s `0.113`).

The gable **is** the `A`. That is the whole idea, and it is why the wordmark
can't be set in a font or letterspaced by hand.

Master coordinate system: `viewBox="0 0 496 342"`.

### Colour

| Token | Hex | Use |
| --- | --- | --- |
| Azure | `#1E9FE0` | roof, `AI`, signal motif |
| Sky | `#5AC4F2` | `AI` + signal on dark grounds |
| Ink | `#0B1016` | `B`, `R`, `N` on light grounds |
| Paper | `#F4F8FB` | `B`, `R`, `N` on dark grounds |

The window in the roof is a **knockout**, not a filled shape — it always shows
the ground through. That is what lets the mono files work as single-colour art,
and what lets the panel's inline copy follow `currentColor`.

### Files

| File | Use |
| --- | --- |
| `brain-logo-onlight.svg` | primary mark, white / light grounds |
| `brain-logo-ondark.svg` | primary mark, dark UI |
| `brain-logo-onazure.svg` | reversed on brand azure |
| `brain-logo-mono-black.svg` | one colour — print, stamps, embroidery |
| `brain-logo-mono-white.svg` | one colour reversed — photography, dark print |
| `brain-icon.svg` | gable icon, azure, transparent ground |
| `brain-icon-mono-white.svg` | gable icon reversed |
| `brain-icon-mono-black.svg` | gable icon, one colour |
| `brain-app-tile-dark.svg` | 512×512 tile — PWA, desktop, HA sidebar, favicon |
| `brain-app-tile-azure.svg` | 512×512 tile, azure ground |

All are self-contained: no fonts, no external references, no filters. Every
shape is a path, rect or circle, so they rasterise cleanly at any size and open
in Figma, Illustrator and Inkscape without substitution.

### Usage rules

- Minimum wordmark width **132px**. Below that, use the gable icon alone. The
  panel's top bar is exactly this case — it has room for about 52px of
  wordmark, so it carries `brain-icon`'s path plus the word as live text.
- The signal rules and the bubbles are always the same colour as each other.
  Never white on a light ground — that was the original file's own CSS, and it
  disappears.
- Never recolour the roof away from azure. Never separate `AI` from the word or
  set it in a different weight.
- No shadows, gradients, outlines, rotation or skew.
- The apex is asymmetric on purpose, inherited from the parent. Do not
  straighten it.
- Clear space: **68u** at master scale (half the small-cap height) on all four
  sides.

### Supporting type

Poppins (ExtraLight → SemiBold) for UI and marketing copy; JetBrains Mono for
version strings, entity IDs and terminal output. Neither is used *inside* the
logo files — the wordmark is outlines.

## BRUH Minecraft

`bruh-minecraft.svg` is unchanged: the earlier "Solid Blocks" tile system
(azure gradient tile, navy negative-space glyph, roof-slope corner tell). It
was not part of this brand pass.

`bruh-mark.svg` is the parent BRUH house mark, used for compact lockups.

## Regenerating the PNGs

```bash
npm install playwright        # once
node branding/render.mjs
```

Writes, all from `branding/icons/`:

| Output | From | Size |
| --- | --- | --- |
| `brain/icon.png` | `brain-app-tile-dark.svg` | 256×256 |
| `brain/logo.png` | `brain-logo-ondark.svg` on an ink plate | 512×384 |
| `brands/custom_integrations/brain/icon.png` | tile | 256×256 |
| `brands/custom_integrations/brain/icon@2x.png` | tile | 512×512 |
| `brands/custom_integrations/brain/logo.png` | lockup | 512×384 |
| `brands/custom_integrations/brain/logo@2x.png` | lockup | 1024×768 |

The lockups sit on an ink plate rather than shipping transparent: the `B`, `R`
and `N` are ink on light grounds and paper on dark, and a PNG can't switch with
the theme — so it carries its own ground and reads the same in both.

The plate is 4:3, not the old family's 640×200. This mark is 496×342, near
enough square that a 3.2:1 banner would either sit it in a puddle of empty
plate or crop it. The old lockups were wide because the old wordmark was.
