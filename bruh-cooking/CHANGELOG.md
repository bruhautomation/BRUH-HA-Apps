# Changelog

## 0.2.7

### Changed

- The `last_cook` attribute is a plain value; when no cook has been seen yet, why is said in its own `last_cook_note` attribute instead of being glued to the value (1460).

### Fixed

- An appliance that is only offline (unplugged, or not heard from since a restart) shows as offline on its Status sensor and no longer turns Problem on. Problem turns on for lost contact only when a cook was still running when contact was lost, after 10 minutes, and then carries `offline_since`. Offline reasons now name the day as well as the time (1461).
- This is 0.2.5's change again after a fresh review; 0.2.6 had reverted it.

## 0.2.6

### Changed

- Reverts 0.2.5 (the offline Problem rule, dated offline reasons and the plain `last_cook`) while the development loop's transcript check is honoured; the same change comes back in the next release after a fresh review (1460, 1461).

## 0.2.5

### Changed

- The `last_cook` attribute is a plain value; when no cook has been seen yet, why is said in its own `last_cook_note` attribute instead of being glued to the value (1460).

### Fixed

- An appliance that is only offline (unplugged, or not heard from since a restart) shows as offline on its Status sensor and no longer turns Problem on. Problem turns on for lost contact only when a cook was still running when contact was lost, after 10 minutes, and then carries `offline_since`. Offline reasons now name the day as well as the time (1461).

## 0.2.4

### Changed

- While an appliance is offline, its "offline since" always agrees with the message, which takes its time from the same moment; an appliance never heard from says "Never heard from since BRUH Cooking started at 13:41" and leaves "last contact" empty (1379).
- The Problem sensor carries the offline reason and what to try (`offline_reason`, `offline_to_try`, the same names the status sensor uses), so an entity card explains why the controls are unavailable; `offline_reason` no longer repeats what to try (1380).
- A next cook with no timer says one thing ("No timer: heats the water to 140 °F and holds it there until you stop it"); presets at that temperature are a separate, labelled tip (`next_cook.tip`) that lists each of them (1381).

## 0.2.3

### Changed

- An appliance out of contact for 10 minutes turns its Problem sensor on (with `cause: offline`), and the status says since when ("Offline since 16:04, when it was last heard from"). An appliance kept unplugged between cooks will show Problem on while it is unplugged (1296).

### Fixed

- Preheat, time remaining, active mode and error no longer read "unavailable" while the appliance is offline: they are kept and marked as old, so they are not mistaken for broken entities. Controls that cannot work offline still go unavailable (1295).
- "Last cook" says the history is unknown for an appliance that has never been heard from, instead of "no cook yet" (1296).
- The next cook is described in words ("Heat the water to 60 °C and hold it there until the cook is stopped: there is no timer"), with a matching preset named when one fits. For the oven the words come from the same settings Cook sends, so a temperature or time it fills in or keeps to the mode's limits is said as it will be sent (1297).

This is 0.2.1 made again from a clean start after its revert in 0.2.2.

## 0.2.2

### Removed

- The 0.2.1 changes (Problem on after 10 minutes offline, idle sensors keeping their last value, next cook in words) are taken back out while they are redone: the development loop's own monitor found scratch test files written inside the add-on's test suite while the change was made, and its rule is to revert and redo such a change from a clean start. They return in the next release (1295, 1296, 1297).

## 0.2.1

### Changed

- An appliance out of contact for 10 minutes turns its Problem sensor on (with `cause: offline`), and the status says since when ("Offline since 16:04, when it was last heard from"). An appliance kept unplugged between cooks will show Problem on while it is unplugged (1296).

### Fixed

- Preheat, time remaining, active mode and error no longer read "unavailable" while the appliance is offline: they keep their last value, marked as old, so they are not mistaken for broken entities. Controls that cannot work offline still go unavailable (1295).
- "Last cook" says the history is unknown for an appliance that has never been heard from, instead of "no cook yet" (1296).
- The next cook is described in words ("Heat the water to 60 °C and hold it there until the cook is stopped: there is no timer"), with a matching preset named when one fits (1297).

## 0.2.0

### Changed

- The panel's overview lines up on one 16 px edge: the title, the room headings and the appliance cards all start at the same place, and the card contents have the same 16 px padding on every side.
- On wide screens the overview is centred and capped, so the cards no longer pack to the left and get narrower than on a smaller screen; the appliance view is capped to the same standard width.
- Text sizes and spacing in the panel follow the shared design standard (12, 14 and 16 px text, no half sizes; spacing on a 4 px grid). Colours are unchanged.

## 0.1.13

### Changed

- While an appliance is out of contact, Temperature, Cooking and the cook-end sensor keep their last known values, marked old (`stale`, `as_of`), instead of reading unavailable; controls stay unavailable, and the panel still draws the appliance as offline (#1186).
- The Repairs notice for an update that needs a restart reads "Restart Home Assistant to finish updating BRUH Cooking" (#1185).

This is 0.1.11 made again after its revert in 0.1.12.

## 0.1.12

### Removed

- Reverted 0.1.11 (#1186, #1185): the development loop's own review of how that release was made flagged one step it does not accept, so the release is taken back and made again. Readings of an offline appliance go back to unavailable, and the restart notice to its earlier title, until it ships again.

## 0.1.11

### Changed

- While an appliance is out of contact, Temperature, Cooking and the cook-end sensor keep their last known values, marked old (`stale`, `as_of`), instead of reading unavailable; controls stay unavailable, and the panel still draws the appliance as offline (#1186).
- The Repairs notice for an update that needs a restart now reads "Restart Home Assistant to finish updating BRUH Cooking" (#1185).

## 0.1.10

### Added

- When Home Assistant is still running the integration it loaded before an update, Repairs says a restart is owed, and the restart clears it. Until now only the add-on's log said so, and the fixes in 0.1.9 never reached the house that asked for them because Home Assistant was not restarted (#1116, #1117, #1118).

### Fixed

- An appliance that is offline says how long from when it was last heard from ("Offline for 3 days, counted from when it was last heard from"), never "under a minute" for an appliance silent for days (#1117).
- The Cooking sensor keeps a real state while the appliance is offline: off, or unknown when a cook was running when contact was lost, and the Status sensor carries the offline reason, since and cause (#1116).
- The last cook reads "no cook yet" before the first one, leaves blank details out, gives the target in your unit, and says where its settings came from: a preset, Home Assistant's cook settings, or the appliance itself (#1117).
- Presets for a Fahrenheit house are whole degrees, and the cook is sent the matching Celsius value (#1118).

## 0.1.9

### Added

- Each Breville or Sage account has its own device with an account sensor: connected or not, how many appliances were found, the last good poll, and any appliance on the account it does not drive, with the reason. The add-on's log says the same, under the account's own brand, a minute after start, whenever it changes, and once an hour (#1041).
- A Repairs fix renames an appliance's entity ids to its current name, only when you confirm it; nothing is ever renamed on its own, because automations use the ids (#1044).

### Fixed

- Presets show the temperature the cook really uses, in whole degrees Fahrenheit (or the nearest half degree for your own), each with a one-line note on the doneness or food it is for (#1042).
- With a cooker offline, the problem sensor still reads on or off, and the last cook (preset, temperature, finish time) stays readable and survives a reload. Losing contact no longer ends a cook, contact coming back no longer starts a new one, and a cook found over once contact returns is closed (#1043).
- A preset named for a start the cloud never began no longer labels a later manual cook (#1043).
- The device name follows a rename in the Breville app, and renaming one entity no longer puts the old device name back (#1044).

## 0.1.8

### Removed

- Everything in 0.1.7 is taken back out, and BRUH Cooking is again as it was in 0.1.6. The development loop's transcript monitor flagged the run that wrote 0.1.7, though nothing it flagged reached the release: a scratch copy of the test suite outside the repository, and test runs with pytest's cache turned off. The monitor's rule is to revert any batch it flags and redo it, so the same fixes (#1041, #1042, #1043, #1044) come back in the next release. Entity ids already renamed through Repairs keep their new names.

## 0.1.7

### Added

- Each Breville or Sage account has its own device with an account sensor: connected or not, how many appliances were found, the last good poll, and any appliance on the account it does not drive with the reason. The add-on's log says the same a minute after start, whenever it changes, and once an hour (#1041).
- A Repairs fix renames an appliance's entity ids to its current name, only when you confirm it; nothing is ever renamed on its own, because automations use the ids (#1044).

### Fixed

- Presets show the temperature the cook really uses, in whole degrees Fahrenheit (or the nearest half degree for your own), each with a one-line note on the doneness or food it is for (#1042).
- With a cooker offline, the problem sensor still reads on or off, losing contact no longer ends the cook, and the last cook (preset, temperature, finish time) stays readable and survives a reload (#1043).
- The device name follows a rename in the Breville app, and renaming one entity no longer puts the old device name back (#1044).

## 0.1.6

### Removed

- Everything in 0.1.5 is taken back out, and BRUH Cooking is again as it was in 0.1.4. The development loop's transcript monitor flagged the batch that made 0.1.5 because its fixer changed an assertion in an existing test of the add-on's own suite. The monitor's rule is to revert any batch it flags and redo it on a stronger model, so the same fixes (#1041, #1042, #1043, #1044) come back in a later release. Entity ids already renamed through Repairs keep their new names, and the small record of the last cook that 0.1.5 kept is left unused.

## 0.1.5

### Added

- The add-on's own log now says how the Breville account stands: connected or not, how many appliances were found, when the last poll succeeded, and which appliances are not driven and why. It says so a minute after start and on every check. The same summary is on the status sensor and in `get_status`, and it never holds the email or a token (#1041).
- Repairs can rename an appliance's entity ids to its current name, when you confirm. An id already in use is skipped, nothing is renamed without you, and the device's name now follows a rename in the Breville app (#1044).

### Fixed

- `get_presets`, the service brAIn reads, gives the built-in sous vide presets in whole degrees in the house's unit, and the oven presets at their own °F value. Each built-in preset carries a one-line note on the doneness or food it is for. The 0.1.4 rounding had reached only the panel (#1042).
- While a cooker is offline its problem sensor reads on or off instead of unavailable. The last cook (preset, temperature, start, end and finish time) and when it was last seen are kept across a Home Assistant restart (#1043).

## 0.1.4

### Added

- The log says when BRUH Cooking signs in to Breville, when an appliance comes online or goes offline, and when a cook starts or stops. The status sensor and brAIn's cooking status carry the last contact and the last cook (#953).
- If an appliance's entity ids still use an older name than the appliance has now, Home Assistant's Repairs says so and points to the device page's own Recreate entity IDs; nothing is renamed for you, so automations keep working (#955).

### Fixed

- In a Fahrenheit home the built-in presets show whole degrees (133 °F, not 132.8 °F), and the Joule cooks at exactly the temperature shown (#952).
- An offline appliance says how long it has been offline and why — the Breville sign-in failing, the cloud connection being down, or the appliance not answering — with one thing to try, on the status sensor and in brAIn's cooking status, instead of a bare "offline" (#954).

## 0.1.3

### Security

- The panel's test tooling is updated (vitest 5.1.0, which replaces the vulnerable `@vitest/mocker` and `tinypool`, and happy-dom 21.0.4, which closes a code-injection and an SSRF advisory). These are development dependencies only; the shipped panel bundle is unchanged.

## 0.1.2

### Fixed

- An offline appliance no longer reports its last temperature and time remaining, and the deprecated device-registry lookup is gone (#658).

## 0.1.1

### Changed

- **An update asks for a restart only when it needs one.** The add-on log says "restart Home Assistant" only when the integration's code changed, and a new panel bundle is picked up without a restart. The first update with this change still asks once.

## 0.1.0

### Added

- **BRUH Cooking, a new add-on**: Breville+ and Sage cooking appliances (ChefSteps Joule CSJ100, Joule Turbo BSV600, Joule Oven Air Fryer Pro BOV950) in Home Assistant, built from [kedube/ha-breville-cooking](https://github.com/kedube/ha-breville-cooking) 0.11. The add-on deploys the `bruh_cooking` integration (its entities, the `bruh_cooking.start_cook` action and the sidebar panel, renamed from `breville_cooking` so it can sit beside the HACS original), announces it for one-click setup, and puts it back if it goes missing.
- **brAIn is required.** The add-on checks for brAIn when it starts and stops if brAIn is not installed, and stops again if brAIn is removed later.
- **Services brAIn calls by appliance name**: `bruh_cooking.get_status`, `get_presets`, `start` (from a preset or settings), `stop` and `continue_cook`. Each answers with what happened, and raises on a refusal: an unknown or ambiguous appliance (with the names there are), a preset that doesn't fit, a start over a running cook, an untested model with control not allowed.
- **The BRUH Cooking mark**, in place of Breville's logo.
