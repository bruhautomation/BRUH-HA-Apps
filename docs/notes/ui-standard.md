# UI standard

The spacing, width, type, radius and control-height rules every add-on's screens are built from, the one token block that carries them, and the ratchet that stops a stylesheet drifting from them.

Part of the project notes (see `CLAUDE.md` › *Where the notes are*). Read this file before changing any stylesheet's spacing, widths, type sizes, radii, control heights or breakpoints; add a note here, not in `CLAUDE.md`.

An audit found every add-on stylesheet using its own numbers. The standard is brAIn's own token set (`brain/panel/style.css` `:root`), adopted by every app. **Colour tokens are out of scope**: each app keeps its own names and palette.

## The tokens

The source is `branding/ui/tokens.css`; this table is its reading.

| Token | Value | Rule |
|---|---|---|
| `--sp-1 … --sp-12` | 4 8 12 16 20 24 32 48 (`--sp-1,2,3,4,5,6,8,12`) | Every padding, margin and gap is one of these or 0. 1-2px only for a border or an optical nudge. |
| `--gutter` | 24px; 16px under 640 | Set once on the page shell. The header's inner wrapper uses the same. |
| `--page-read` / `--page` / `--page-wide` | 760 / 1120 / 1400px | Centred. The title and the body share one wrapper. |
| `--section-gap` | 24px | Between sections, as `gap` on the parent, never a per-element margin. |
| `--card-gap` | 12px | Between cards. |
| `--card-pad` | 16px; 12px under 640 | On every bordered surface; rows inside a card take the same left inset. |
| `--fs-title` | 20/28, 600 | One per screen. Companions `--lh-*`, `--fw-*`. |
| `--fs-card` | 16/24, 600 | A card or section heading. |
| `--fs-body` | 14/20 | |
| `--fs-meta` | 12/16 | |
| `--fs-control` | 14px; 16px on touch | The 16px floor for text inputs on touch. |
| `--card-radius` / `--control-radius` | 12 / 8px | Pills are 999px. |
| `--btn-h` | 40px; 44px on `pointer: coarse` | Buttons, inputs and selects share it. |
| `--btn-h-sm` | 32px | The one small size. |

Breakpoints are 640 / 900 / 1200 only, written `@media (max-width: 639.98px)` and `(min-width: 640px)` so the two halves never both match.

## Page and section

- **Widths.** Reading screens (settings, a form, a list) use `--page-read`; ordinary screens `--page`; dense ones `--page-wide`. Never a width of the app's own.
- **Named exceptions: canvas screens run full width** (Bambu Studio and Design, the BRight show editor, brAIn's terminal). A canvas screen still takes the gutter and the spacing scale.
- **Morph** keeps its own fonts and display sizes but takes the shared gutter, page widths, spacing scale and control heights.
- **One section pattern.** A heading (16/600, `--fs-card`), an optional count, then the content, separated from the next section by `--section-gap`. Boxed content is a card; a list inside a card divides its rows with hairlines; a fold gets one rule, not two. Every app sets explicit `h2`/`h3` rules: no browser-default headings.

## How the token block is synced

`branding/ui/tokens.css` is the single source. Nothing is served from `branding/`: a stylesheet that has adopted the standard carries a copy between two marker comments, verbatim:

```
/* ui-tokens:start (synced from branding/ui/tokens.css; do not edit here) */
…the block…
/* ui-tokens:end */
```

Edit the source, then run `python3 .github/scripts/ui_tokens.py --write`, which rewrites the block in every listed stylesheet that already has the markers (it never adds them: adopting is a deliberate edit that puts the markers in). Without `--write` it is the check, and exits non-zero when a marked block differs. The list of stylesheets is `STYLESHEETS` in `.github/scripts/ui_tokens.py`; a new app's stylesheet is added there and in no other place.

## The ratchet

`python3 .github/scripts/check.py` runs a `ui` step (`.github/scripts/ui_ratchet.py`) that first runs the token-block check and then counts, per stylesheet, with comments and the marked block stripped:

- **space**: distinct px values in `padding`, `margin` and `gap` declarations not in {0, 1, 2, 4, 8, 12, 16, 20, 24, 32, 48} (sign ignored);
- **radius**: distinct `border-radius` values not in {0, 8, 12, 999px} (a percentage is ignored);
- **font**: distinct `font-size` values not in {12, 14, 16, 20px};
- **media**: distinct `min-width` / `max-width` values in `@media` rules not in {640, 900, 1200px} (639.98, 899.98 and 1199.98 count as their partner).

Only off-standard values are counted, so adopting a standard value can never fail the check. Morph's stylesheet keeps its own display sizes by design, so its `font` baseline stays high.

It fails when any count is higher than `.github/scripts/ui_baseline.json` records, naming the file, the metric and the new values; the fix is a token, not a new baseline. Values inside `var()` fallbacks and `calc()` are counted as written. A count that goes **down** passes and prints one line suggesting the update.

- `python3 .github/scripts/ui_ratchet.py --report` prints the table of counts against the baseline.
- **Lowering a baseline**: after a cleanup, run `python3 .github/scripts/ui_ratchet.py --update` and commit `ui_baseline.json` with the change. It rewrites every count from the tree as it is, so run it only when the tree is what you mean to ship; a baseline is never raised by hand to let a change through.
- The target for an adopted stylesheet is 0 on every metric (Morph's `font` excepted).

## Looking at it

`tests/manual/shoot-all.mjs` screenshots every app at 390 / 768 / 1280 / 1920 for before-and-after comparison (see `tests/manual/README.md`). It is a hand tool, not a gate.
