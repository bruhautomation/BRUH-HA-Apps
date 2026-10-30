# Changelog

## 0.1.1

### Changed

- **An update asks for a restart only when it needs one.** The add-on log says "restart Home Assistant" only when the integration's code changed, and a new panel bundle is picked up without a restart. The first update with this change still asks once.

## 0.1.0

### Added

- **BRUH Cooking, a new add-on**: Breville+ and Sage cooking appliances (ChefSteps Joule CSJ100, Joule Turbo BSV600, Joule Oven Air Fryer Pro BOV950) in Home Assistant, built from [kedube/ha-breville-cooking](https://github.com/kedube/ha-breville-cooking) 0.11. The add-on deploys the `bruh_cooking` integration (its entities, the `bruh_cooking.start_cook` action and the sidebar panel, renamed from `breville_cooking` so it can sit beside the HACS original), announces it for one-click setup, and puts it back if it goes missing.
- **brAIn is required.** The add-on checks for brAIn when it starts and stops if brAIn is not installed, and stops again if brAIn is removed later.
- **Services brAIn calls by appliance name**: `bruh_cooking.get_status`, `get_presets`, `start` (from a preset or settings), `stop` and `continue_cook`. Each answers with what happened, and raises on a refusal: an unknown or ambiguous appliance (with the names there are), a preset that doesn't fit, a start over a running cook, an untested model with control not allowed.
- **The BRUH Cooking mark**, in place of Breville's logo.
