# BRUH add-on design system

One visual language for every BRUH Automation add-on. Each icon shares:

- **The tile** — a rounded square with a dark navy gradient
  (`#182432 → #0b111a`) and a hairline dodger-blue inner ring.
- **The BRUH chip** — a brand-blue (`#1e90ff`) rounded badge with a
  bold white **B** broadcasting signal waves, the bruhautomation.com
  lettermark. Badged top-left on every icon at the same size and
  position — the unmistakable "this is a BRUH app" signal.
- **A per-add-on glyph + accent colour** centered in the tile:

| Add-on | Glyph | Accent |
|---|---|---|
| Claude Terminal | Prompt chevron `>` + underscore, coral AI spark as the cursor | Coral `#d97757` |
| Insights | Rising bars + sparkle | Blue `#1e90ff` → violet `#8f7ae8` → pink `#d55181` |
| Minecraft Server | Pixel grass block | Green `#6fbf43` |

The landscape `logo.png` banners share one layout: mini icon tile on the
left, `BRUH` in brand blue, the add-on name in Liberation Sans Bold, and
a `HOME ASSISTANT ADD-ON` byline, with faint beacon rings bleeding off
the right edge.

## Regenerating

The `*.svg` files in this directory are generated masters — edit
`build-logos.py` (geometry, palette, layout) and re-run it; don't edit
the SVGs by hand.

```bash
pip install cairosvg
python3 brands/design/build-logos.py
```

This rewrites the SVG masters here and renders every consumer:

- `<addon>/icon.png` (512×512) and `<addon>/logo.png` (1024×320)
- `bruh-insights/panel/favicon.svg`, `bruh-minecraft-server/panel/favicon.svg`
- `brands/custom_integrations/bruh_claude/icon.png` (256) + `icon@2x.png` (512)
- `bruh-claude-terminal/custom_components/bruh_claude/icon.png`

Remember to bump each add-on's `config.yaml` version (and changelog)
when shipping regenerated assets — CI enforces it.
