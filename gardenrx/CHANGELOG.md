# Changelog

## 0.2.5

### Changed

- Grey text (subtitles, counts, tab labels, hints) and the green money and "% left" figures are readable in every theme, at least 4.5:1 against what they sit on (1354, 1357).
- The bottom bar's seven labels fit whole on a phone, and each is the screen's own title: Today, Crops, Garden, Harvest, Spray, Products, Weather (1355).
- Out of season, Today shows what matters while the garden rests (a frost warning, when each crop usually wakes and what to do then, the last spray and the last pick) and drops the watering tip while nothing is growing (1356).
- Product badges say what they are ("REI 24h", "Re-spray 10d", or "n/a") (1358).
- The spray window says why an hour or a day is on hold ("below 40°", "wind", "rain"), and at night the rating reads "Dark" rather than a good spraying score (1359).

## 0.2.4

### Fixed

- The watering advice reads the forecast: with a quarter inch or more of rain due in the next three days it says to wait for the rain, and the Today chip and the Weather card give the same advice. In real heat a "water now" stays when the rain coming is less than the soil is short (1271).
- The dashboard cards each have a heading (Last spray, Harvest, Stock), which a card's `title:` can change or remove. The calm stock card says "Nothing at 20% or less" and names the lowest, and Log harvest says what it still needs before it can log (1272).
- The 3-day spray window greys hours that are over and hours in the dark, and the banner's next opening is the grid's first green hour. Nothing says it is good to spray in the dark (1273).
- Annual crops at the end of the season read "Finished for the year" instead of "Dormant"; garlic and shallots, planted in the fall and in the ground over winter, read "Dormant". A crop with no varieties (roses, shrubs) follows its group's season, and the resting note names the crops still growing (1274).

This is 0.2.2 made again from a clean start after its revert in 0.2.3.

## 0.2.3

### Removed

- The 0.2.2 changes (forecast-aware watering advice, the spray grid's past and dark hours, card headings, crop season states) are taken back out while they are redone: the development loop's own monitor found that a reviewer of that change wrote scratch test files while checking it, and its rule is to revert and redo such a change from a clean start. They return in the next release (1271, 1272, 1273, 1274).

## 0.2.2

### Fixed

- The watering advice reads the forecast: with a quarter inch or more of rain due in the next three days it says to wait for the rain, and the Today chip and the Weather card give the same advice. In real heat a "water now" stays when the rain coming is less than the soil is short (1271).
- The dashboard cards each have a heading (Last spray, Harvest, Stock), which a card's `title:` can change or remove. The calm stock card says "Nothing at 20% or less" and names the lowest, and Log harvest says what it still needs before it can log (1272).
- The 3-day spray window greys hours that are over and hours in the dark, and the banner's next opening is the grid's first green hour. Nothing says it is good to spray in the dark (1273).
- Annual crops at the end of the season read "Finished for the year" instead of "Dormant". A crop with no varieties (roses, shrubs) follows its group's season, and the resting note names the crops still growing (1274).

## 0.2.1

### Security

- Next.js is updated from 16.4.2 to 16.4.5, a security release.

### Fixed

- The dashboard cards' Mark sprayed button and their status text are readable on Home Assistant's default theme, light and dark.

## 0.2.0

### Changed

- Every screen now sits on one page grid: the title and everything under it share the same left edge and width, and the header's search and weather line up with the page instead of drifting to the window edge on wide screens. Phones use a 16 px margin.
- One heading style for sections (and one size for page titles) replaces the five different ones, including the tiny uppercase labels on Weather, Spray and Harvest. Crop detail now shows every section as a card.
- Spacing, corner radius, text sizes and button and field heights follow the shared design standard: one set of corner radii (the crop search box now matches the product searches), nothing smaller than 12 px, 40 px buttons and fields (44 px on touch screens).
- Tablets (640-900 px wide) keep two or more columns instead of a stretched phone layout, the bottom bar now switches to the sidebar at 900 px, and Today uses the full width when only one column has content.
- Harvest picks switch to the stacked card layout below 900 px so the Value column is no longer cut off.
- The Lovelace cards (harvest, spray, stock) follow the shared card style: 16 px padding, 44 px buttons with 8 px corners, the theme's primary colour for main buttons, and an optional `title` option.

## 0.1.13

### Changed

- The Lovelace stock card says "Nothing running low · 14 in stock" when nothing is low, then lists the three lowest under "Lowest stock"; amounts stay on one line (#1164).
- Harvest: when nothing is ready, held or developing, the three zero cards become one line, e.g. "Nothing to pick or hold right now · 21 crops off season", so the season total shows without scrolling (#1163).
- Crops: on a phone the title stays on one line and the search field has its own full-width row with a readable placeholder (#1162).

### Fixed

- The rainfall card no longer shows a red DROUGHT badge for a resting garden: it uses the same resting rule as the watering advice beside it, so a dormant garden short of rain is at most "Dry", and DROUGHT appears only in the growing season (#1165).

## 0.1.12

### Changed

- Harvest, Crops, Weather and Today now share one season rule: crops that are dormant or past harvest are left out of "Still developing" and counted in one line as off season, the same way Crops shows them (#1090).
- The 7-day forecast's chip uses the same rule as the banner and says when: "Spray 3–7 pm", "Short 4–5 pm" for a window under three hours, or nothing when no spray is due (#1092).
- Each crop card on Crops is one compact row; spray lines say when the next spray is due ("Fungicide: next due Dec 3") and are left off for resting crops, with one line at the top saying what resting means (#1095).
- Log Harvest sits in the picks log's header instead of floating over the last row (#1093).

### Fixed

- A resting garden is never told "Water now": in cool weather it gets a quiet "No watering needed while the garden rests", or "Check the soil before winter" after a dry spell, and each watering card gives one instruction. Today shows a one-line rain summary that links to Weather instead of the whole card twice (#1091).
- The stock search box is 44px tall with 16px text and the sort chips 40px on a phone; the stock card colours red exactly what it counts as running low, and says where that line is (20% or less) (#1094).

## 0.1.11

### Changed

- Inventory stock cards on a phone show the whole product name (on up to two lines), the level bar and the amount left. Size, count and cost sit behind a pencil button, with fields wide enough for their full values; the area labels moved inside it too, and filtering by area stays in the chips at the top (#1017).

## 0.1.10

### Fixed

- Crop stages follow the date and the garden's own season, so a past-season crop reads Dormant in November instead of Bud Break or Green Fruit, and a stage set by hand gives way to the calendar once its season is over. "Fungicide due" and "Ready to pick" count only crops in season, a crop picked in the last two weeks still counts as ready, and the pre-harvest warning is never hidden (#1014).
- Chips, tabs, toggles and text links on a phone are at least 40px tall and wide, and "Select all" is readable (#1015).
- The hold-off card names the next good spray window with its day and time, never the hour already under way, and the Weather page gives the same answer; a crop's attention row opens a Tank mix with that crop chosen (#1016).
- The picks log on a phone is one compact row per pick that opens for editing on a tap, and its last row clears the Log Harvest button (#1018).

## 0.1.9

### Removed

- Everything in 0.1.8 is taken back out, and GardenRX is again as it was in 0.1.7. The development loop's transcript monitor flagged the batch that made 0.1.8: its fixer edited a test file while working, a scratch file that was never merged. The monitor's rule is to revert any batch it flags and redo it on a stronger model, so the same fixes (#1014, #1015, #1016, #1017, #1018) come back in a later release.

## 0.1.8

### Fixed

- Crop stages follow the date and the garden's own season, so a past-season annual or a resting perennial reads Dormant in November instead of Bud Break or Green Fruit. A southern-hemisphere garden reads its own season, and a stage set by hand gives way to the calendar once its season is over. "Fungicide due" and "Ready to pick" count only crops in season (#1014).
- Chips, tabs, toggles, menus and text links on a phone are at least 40px tall, and "Select all" and the green links are readable (#1015).
- The hold-off card names the next good spray window with its day and time, the Weather page gives the same answer, and a crop's attention row opens a Tank mix with that crop chosen (#1016).
- Inventory cards on a phone show the whole product name, the level bar and the amount left. Size, count and cost sit behind an edit button, with their full values (#1017).
- The picks log on a phone is one compact row per pick that opens for editing on a tap, and its last row clears the Log Harvest button (#1018).

## 0.1.7

### Fixed

- Crops resting for the season (dormant or after harvest) no longer show a red "lapsed" or count as due, and the Crops counts and Today's Needs attention agree, because both ask one rule what is due. "Fung" and "Ins" are written out as Fungicide and Insecticide (#931).
- The picks log on Harvest shows each pick as a small card on a phone instead of a table running off the right edge, and the last row clears the Log Harvest button (#930).
- The rainfall card no longer says to water now when most of the garden is resting and highs are under about 60°F, and the best spray window only ever names a time still to come (#929).
- The amber FAIR pill, "Hold off", Inventory percentages, FRAC codes and section tabs are readable in light mode (#928).
- The header's theme, search and settings buttons are 40px on a phone, and fields use 16px text so the phone no longer zooms in when one is tapped (#927).

## 0.1.6

### Security

- Updated a bundled web library (hono, used by the MCP SDK) to 4.13.18, which closes several advisories in its request validation, body limit, mounting and static-file handling.

## 0.1.5

### Fixed

- Today no longer says coverage is due, or suggests a spray, for crops that are dormant or past harvest (#654).

### Security

- Updated the bundled HTTP server library used by the MCP SDK to 2.1.6, which closes a static-path bypass advisory.

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
