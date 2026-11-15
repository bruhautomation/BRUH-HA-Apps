# Changelog

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
