# Changelog

## 0.1.4

### Changed

- **An update asks for a restart only when it needs one.** The add-on log says "restart Home Assistant" only when the integration's code changed, and the cards' address now follows the file, so a card change needs only a page reload. The first update with this change still asks once.

## 0.1.3

### Added

- **Everything the panel logs can be logged from Home Assistant, voice or brAIn.** New services: `gardenrx.log_spray` (a spray that was not queued; it clears queued sprays for the same crops and takes what was used out of stock, warning when a product is not labelled for a crop), `gardenrx.queue_spray`, `gardenrx.adjust_inventory` (add to, take from, or set what is on hand; a product not stocked yet is added), `gardenrx.add_crop`, `gardenrx.add_variety`, `gardenrx.log_note` (a dated note on a bed or tree on the Garden Map, which now shows its notes) and `gardenrx.get_harvests` (harvests by crop and dates, with totals). Each answers with the record it made and refuses with a sentence naming what is wrong. (#393)

### Security

- **Six vulnerable dependencies updated** (shadcn, @shadcn/registry, zod, undici, fast-uri, body-parser), within their existing ranges.

## 0.1.2

### Security

- Updated `proxy-addr` to 2.0.8 (CVE-2026-90711: an IPv4 address could be
  trusted through a mapped IPv6 subnet with a short prefix) and
  `@modelcontextprotocol/sdk` to 1.32.1 (bounded request bodies, same-origin
  redirects only).
- Updated Next.js to 16.4.2, which closes an unauthenticated remote code
  execution in its image optimizer when SVG files are served, and a denial
  of service in Server Actions.
- Updated the test tools (Vitest 4.1.12, Vite 8.3.5) and `ip-address`
  10.7.4. None of them ships in the add-on's image.

## 0.1.1

### Fixed

- The Today link (the logo and Today in the menu) opened a 404. It went to
  the panel's address with no slash at the end, which Home Assistant does
  not answer. Every page link now ends in a slash, and CI follows every link
  on every page through an ingress stand-in that answers only what Home
  Assistant answers.

## 0.1.0

### Added

- GardenRX as a Home Assistant add-on: the whole app — Today, Crops, Garden
  Map, Harvest, Spray, Treatments, Inventory and Weather — in the sidebar
  through ingress, behind Home Assistant's own login.
- The data lives in a SQLite file in the add-on's own `/data`
  (`gardenrx.db`), so it is in every Home Assistant backup and needs no
  database server. The product and label catalog (256 products, their active
  ingredients, crop uses and pre-harvest intervals, crop groups, phenology
  and tank-mix rules) is loaded on first start; your crops, varieties,
  sprays, harvests and stock start empty.
- Forecasts and rainfall for Home Assistant's own location and time zone.
- A `gardenrx` integration with sensors for this year's harvest (weight and
  value), the last spray, queued sprays, crops in a pre-harvest interval and
  treatments running low.
- Services: `gardenrx.log_harvest`, `gardenrx.delete_harvest`,
  `gardenrx.complete_queued_spray`, `gardenrx.delete_queued_spray` and
  `gardenrx.refresh`. Each does what the panel's own button does and answers
  with what happened; a refusal is an error with the reason.
- Three cards, each for Lovelace and for Morph: harvest (this year by crop,
  recent picks, a form to log one), sprays (the last spray, crops not to
  harvest yet, queued sprays to mark done) and stock (lowest first).

### Fixed

- The theme picker saved nothing: it built the settings update and never ran
  it, so the theme reverted on the next page load.
