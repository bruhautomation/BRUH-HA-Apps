# Home Assistant brand assets

Device and integration pages load branding from Home Assistant's central
[brands repository](https://github.com/home-assistant/brands) — files
shipped inside a custom integration are never used there, which is why a
fresh install shows "icon not available" until the brand is submitted.

One-time submission (assets here are already to spec):

1. Fork `home-assistant/brands`
2. Copy `custom_integrations/bruh_claude/` from this directory into the
   fork at the same path
3. Open a PR titled "Add bruh_claude custom integration"

After it merges, icons appear once the CDN cache refreshes (up to a day).
