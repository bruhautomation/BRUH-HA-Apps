# BRUH Apps branding

Source SVGs for the unified BRUH Automation "Solid Blocks" icon system used by all
add-ons in this repo. One 512×512 SVG per app (azure gradient tile, navy negative-space
glyph, roof-slope corner "tell"), plus the BRUH house mark for compact lockups.

Design tokens:

- azure `#1E9FE0` (primary), sky `#5AC4F2` (gradient top / accent)
- navy `#0A1622` (glyph, dark backgrounds), navy-2 `#0E1E30` (dark card surface)
- slate `#7E96AA` (muted text), ink `#04263c` (label text on azure)
- tile corner radius: 22.5% of size

Each add-on's `icon.png` (256×256, rounded, transparent corners) and `logo.png`
(640×200 lockup) are rasterized from these SVGs; the SVGs are the source of truth.
The ingress panels reference the SVGs directly as favicons.

## BRain

`brain.svg` is the mark for **BRain**, the merged add-on that supersedes BRUH
Terminal and BRUH Insights. Two glyph directions are checked in while the
choice is open:

| File | Glyph | Notes |
| --- | --- | --- |
| `brain.svg` | neural mesh | Node network with one clear hub. Holds up at 32 px. |
| `brain-alt-solid.svg` | solid brain | Literal brain profile, folds knocked out in the tile gradient. Reads warmer at large sizes, blobs at 32 px. |

Lockups (`brain-logo.svg`, `brain-logo-alt-solid.svg`) follow the family's
640×200 navy-plate layout, with the wordmark split **BR** (white) + **ain**
(sky) so the BRUH tie-in is explicit rather than a private joke.

The wordmark is Montserrat ExtraBold (`wght` 800). It is referenced by family
name, so rasterizing on a machine without it falls back and shifts the metrics
— install Montserrat before regenerating the PNGs.

Rendered output lives in `../branding/render/` and is copied into the add-on
directory (`icon.png`, `logo.png`) when BRain is scaffolded. The
`brands/custom_integrations/brain/` assets are the home-assistant/brands
submission for the `brain` integration domain.
