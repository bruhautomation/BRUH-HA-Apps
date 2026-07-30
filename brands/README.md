# Home Assistant brand assets

Device and integration pages load branding from Home Assistant's central
[brands repository](https://github.com/home-assistant/brands) — files
shipped inside a custom integration are never used there, which is why a
fresh install shows "icon not available" until the brand is submitted.

One-time submission (assets here are already to spec — `icon.png` 256×256,
`icon@2x.png` 512×512, `logo.png` 512×384, `logo@2x.png` 1024×768, rendered
from `../branding/icons/` by `../branding/render.mjs`):

1. Fork `home-assistant/brands`
2. Copy `custom_integrations/brain/` and `custom_integrations/bruh_minecraft/`
   from this directory into the fork at the same paths
3. Open a PR titled "Add brain and bruh_minecraft custom integrations"

**Until that PR merges**, Home Assistant has no artwork for the `brain`
domain and falls back to showing the raw domain next to the integration
name — which is why a fresh install reads "brain brAIn" rather than a
logo. Nothing in this repo can fix that; the artwork has to live in
home-assistant/brands. The `logo.png` lockup is what renders on the
integration page once it does.

There is no `custom_integrations/bruh_claude/` here any more. That domain was
renamed to `brain` in 1.0.0 and never submitted, so submitting it now would
publish artwork for an integration nobody can install.

The displayed strings come from three different places, so it is worth
being precise about which is which:

| What you see | Where it comes from |
| --- | --- |
| The integration's name | `manifest.json` → `"name": "brAIn"` |
| The config-entry title under it | whatever you typed at setup; defaults to `DEFAULT_NAME` in `const.py` |
| The icon and wide logo | home-assistant/brands (the PR above) |

After it merges, icons appear once the CDN cache refreshes (up to a day).
