# BRUH Apps branding

Source SVGs for the add-ons in this repo. **The SVGs are the source of truth;
every PNG is derived from them by `render.mjs` and should be regenerated, not
hand-edited.**

    npm install playwright        # once
    node branding/render.mjs

That writes the add-on store entries (`brain/icon.png`, `brain/logo.png`,
`bruh-minecraft-server/…`), the integration icon shipped inside the add-on, and
the whole `brands/custom_integrations/` tree for the home-assistant/brands
submission. The two panel favicons (`*/panel/favicon.svg`) and the Minecraft
panel's inline header mark are copies of the tiles — refresh them by hand if a
tile changes.

## BRain & BRUH Minecraft

Two app marks, both direct descendants of the BRUH Automation logo rather than
lookalikes.

## The system

The **BR ligature** and the **gable** are constant across the family, lifted
unmodified from `bruh-logo-dark.svg`:

| Element | Source |
| --- | --- |
| `BR` ligature | the parent's own single path — B stacked on R, one continuous stem, the bottom of the B is the top of the R |
| Gable | the parent's own roof path — notched asymmetric apex, 45° slopes, 2×2 window as a knockout |

What identifies each app is the **treatment of the small caps**, set on the parent's
own metrics — cap height `135–144`, baseline `333`, and the parent's `14.5u` gap
between the eave and the cap line:

- **BRain** — smooth monoline caps, `AI` in azure. Carries the parent's three
  signal rules and bubbles in the wedge between the R and the roof.
- **BRUH Minecraft** — the same lockup with `MC` drawn on a 16u block grid, and the
  signal motif dropped so the blocks and the roof carry it alone.

Newly drawn in both: the small caps only. The source has no A/I/N/M/C outlines to
lift, so they are built on the parent's stroke-to-cap ratio (`0.111`, measured from
its own `H`: `16/142`).

## Colour

| Token | Hex | Use |
| --- | --- | --- |
| Azure | `#1E9FE0` | roof, highlight caps, signal |
| Sky | `#5AC4F2` | highlight caps + signal on dark grounds |
| Ink | `#0B1016` | plain caps on light grounds |
| Paper | `#F4F8FB` | plain caps on dark grounds |

The roof's window is a **knockout**, never a filled shape — it always shows the
background through. That is what lets the mono files work as true single-colour art.

## Files

Each app folder — `branding/brain/` and `branding/minecraft/` — carries the same twelve files.

**Horizontal lockup** — the primary mark. Minimum width **132px**.

| File | Use |
| --- | --- |
| `*-logo-onlight.svg` | white / light grounds |
| `*-logo-ondark.svg` | dark UI |
| `*-logo-onazure.svg` | reversed on brand azure |
| `*-logo-mono-black.svg` | one colour — print, stamps, embroidery |
| `*-logo-mono-white.svg` | one colour reversed — photography, dark print |

**Square lockup** — the full logo on a 1:1 transparent canvas with the standard 68u
clear space on all four sides. Use for app icons at **64px and up**; it keeps the
letters, so the two apps stay distinguishable where a bare gable would not.

| File | Use |
| --- | --- |
| `*-square-onlight.svg` | dark art, for light grounds |
| `*-square-ondark.svg` | light art, for dark grounds |
| `*-square-mono-black.svg` | one colour |
| `*-square-mono-white.svg` | one colour reversed |

**Tiles** — 512×512 with the platform corner radius baked in.

| File | Use |
| --- | --- |
| `*-tile-dark.svg` | PWA, desktop, Home Assistant sidebar |
| `*-tile-azure.svg` | azure ground |
| `*-tile-light.svg` | light ground |

All SVGs are self-contained: no fonts, no external references, no filters, no clip
paths. Every shape is a path, rect or circle, so they rasterise cleanly at any size
and open in Figma, Illustrator and Inkscape with nothing to substitute.

## Usage rules

**Size floors.** Horizontal lockup 132px. Square lockup 64px — the 15u caps fall
below one device pixel under that.

**Never ship the gable on its own.** It is the family mark: it says BRUH, and it
says nothing about which app you are looking at. Two add-ons putting the same
roof in the same Home Assistant sidebar are two add-ons nobody can tell apart —
which is what the square lockups exist to prevent. Below 64px the square lockup
is still the answer; it goes soft, but it is never the wrong app. This is why
`brain-icon.svg`, `brain-app-tile-*.svg` and `bruh-mark.svg` are gone.

- Never recolour the roof away from azure.
- Never separate `AI` from BRain, or `MC` from Minecraft, and never set them in a
  different weight from the rest of the word.
- BRain keeps its signal rules and bubbles; Minecraft does not. Don't swap them.
- BRain's caps are smooth, Minecraft's are blocky. That contrast is the system —
  don't blur it by making one look like the other.
- No shadows, gradients, outlines, rotation or skew.
- The apex notch is inherited and deliberate. Do not straighten it.
- Clear space: **68u** at master scale (half the small-cap height) on all four sides.
  The square lockup and the tiles have it built in; add it yourself around the
  horizontal lockup.

## Rasters

Not included — every consumer here takes SVG. If you need PNGs for an app store,
render `*-tile-dark.svg` at 512, 192 and 180; for legacy favicons render
`bruh-glyph-azure.svg` at 32 and 16.

## Supporting type

Poppins (ExtraLight → SemiBold) for UI and marketing copy; JetBrains Mono for
version strings, entity IDs and terminal output. Neither is used inside the logo
files — the letters are outlines.
