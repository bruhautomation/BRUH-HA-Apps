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
