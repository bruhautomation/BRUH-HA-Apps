# Changelog

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
