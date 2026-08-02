# Home Assistant brand assets

These are the four PNGs per domain that Home Assistant's brand system wants,
rendered from `../branding/` by `../branding/render.mjs`. Regenerate rather
than hand-edit.

| File | Size |
| --- | --- |
| `icon.png` | 256×256 |
| `icon@2x.png` | 512×512 |
| `logo.png` | 341×256 |
| `logo@2x.png` | 682×512 |

The lockups are 341×256 and not the 512×384 the add-on store gets, because
brands caps the **shortest** side of a logo at 256 (512 for hDPI) — a 384px-tall
plate fails `scripts/validate.sh` in that repo on height alone. Same 4:3
drawing, two sizes; `render.mjs` writes both.

## home-assistant/brands no longer accepts these

This directory exists for a submission that can no longer be made. Since
Home Assistant 2026.3.0 the `custom_integrations/` folder in
[home-assistant/brands](https://github.com/home-assistant/brands) is legacy,
and a PR that adds a **new** folder under it is closed automatically by
`.github/workflows/close-new-custom-integrations.yml` — the bot comments and
sets the PR to `closed` in the same run, so there is nothing to appeal. The
PR template says the same thing in its opening comment. See the
[Brands Proxy API announcement](https://developers.home-assistant.io/blog/2026/02/24/brands-proxy-api).

Assets here are kept in spec anyway: they are the same files the integration
ships, and a validator that passes is worth more than one that has never been
run.

## What replaces it, and where it lives now

A custom integration serves its own artwork from a `brand/` folder beside its
manifest; Home Assistant prefers those over the CDN and needs no manifest
change to find them. **Both integrations ship one** — this is the live route,
and the one to edit:

```
brain/custom_components/brain/brand/                     # brAIn
bruh-minecraft-server/custom_components/bruh_minecraft/brand/   # BRUH Minecraft
├── icon.png        256×256
├── icon@2x.png     512×512
├── logo.png        341×256
└── logo@2x.png     682×512
```

`render.mjs` writes those folders and this directory from the same SVGs, so the
two sets are byte-identical by construction. That is deliberate: which route
resolves first is not something we control, and a user's logo should not depend
on it.

Note the `brand/` **folder** is what HA reads. A bare
`custom_components/<domain>/icon.png` — which this repo used to ship — is not
read by anything, and was removed rather than left to look load-bearing.

Nothing extra is needed to ship them: both add-ons deploy their integration with
a recursive copy, so the folder travels with the files beside it.

There is no `custom_integrations/bruh_claude/` here any more. That domain was
renamed to `brain` in 1.0.0 and never submitted, so publishing artwork for it
now would brand an integration nobody can install.

## Which string comes from where

The displayed strings come from three different places, so it is worth being
precise about which is which:

| What you see | Where it comes from |
| --- | --- |
| The integration's name | `manifest.json` → `"name": "brAIn"` |
| The config-entry title under it | whatever you typed at setup; defaults to `DEFAULT_NAME` in `const.py` |
| The icon and wide logo | the `brand/` folder above, falling back to the brands CDN |

A fresh install that reads "brain brAIn" rather than showing a logo is HA
falling back to the raw domain because it found no artwork on either route.
