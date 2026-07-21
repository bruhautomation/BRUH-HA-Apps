# Home Assistant brand assets

Device and integration pages load branding from Home Assistant's central
[brands repository](https://github.com/home-assistant/brands) — files
shipped inside a custom integration are never used there, which is why a
fresh install shows "icon not available" until the brand is submitted.

One-time submission (assets here are already to spec — `icon.png` 256×256,
`icon@2x.png` 512×512, rasterized from `../branding/icons/`):

1. Fork `home-assistant/brands`
2. Copy `custom_integrations/bruh_claude/` and
   `custom_integrations/bruh_minecraft/` from this directory into the
   fork at the same paths
3. Open a PR titled "Add bruh_claude and bruh_minecraft custom integrations"

(BRUH Insights has no companion custom integration, so it needs no brands
entry — its icon lives in the add-on itself.)

After it merges, icons appear once the CDN cache refreshes (up to a day).
