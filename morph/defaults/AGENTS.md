# Morph — how this dashboard works (for brAIn)

This folder is **Morph**, the house's dashboard (Morph {{VERSION}}). Morph is in
Home Assistant's sidebar. You (brAIn) design it with the household: you change
it when somebody holds something in Edit and tells you what to change, when you
are asked in a chat, and when a suggestion you made is approved.

Read this file before you change anything here. Morph rewrites it when it is
updated, so do not edit it. Your notes belong in `LEARNED.md`.

## The files

| File | What it is | Who writes it |
|---|---|---|
| `dashboard.yaml` | The whole dashboard | Edit mode, you, a person with a text editor |
| `cards/*.js` | Custom card code: one Lovelace custom card per file | You |
| `LEARNED.md` | What this household has taught Morph, as rules | Morph's learning loop, you, the household |
| `AGENTS.md` | This page | Morph |

**Never run `git` here.** This folder is a git repository, and Morph commits
every change the moment you finish. The commit message says what the change
was for. That commit is what the person's **Undo** reverts. If you commit
yourself, Undo will revert the wrong thing.

Morph reloads the dashboard live whenever `dashboard.yaml` or a card file
changes. You do not need to reload anything.

## dashboard.yaml

```yaml
title: Home
story: true          # brAIn's one-paragraph summary of right now, at the top
ask: true            # "Ask or tell the house…"
coming_up: true      # the timeline: timers, sun, calendars, what usually happens
theme: auto          # auto | dark | light | medium (optional)
scenes: [scene.morning, scene.evening]   # house-wide scenes, as words
floors:
  - id: f_first_floor
    title: First floor
    sections:
      - id: s_kitchen
        title: Kitchen
        area: kitchen        # optional: the HA area, so brAIn's notes land here
        color: sand          # amber sand sky violet teal lime rose peach indigo
        width: 3             # preferred columns, 1–4 (the layout may use one more or less)
        groups:
          - cards:
              - id: c_kitchen_scenes
                type: scenes
                entities: [scene.kitchen_bright, scene.kitchen_dim]
          - cards:
              - id: c_kitchen_cans
                type: light_group
                entity: light.kitchen_cans
                name: Cans
              - id: c_countertop
                entity: light.kitchen_countertop   # type is inferred from the domain
          - label: Party       # a group gets a small tinted label only when it needs a name
            note: optional short note beside the label
            cards:
              - id: c_party_chips
                type: custom:mushroom-chips-card   # ANY Lovelace card, passed through as-is
                chips: [...]
```

**Keep every existing `id`.** Notes, usage counts and Undo are keyed on ids, so
renaming one makes the card look new. A new card or section may leave `id` out
and Morph will assign one.

### Card types Morph draws itself

| `type` | Takes | Face · tap · slide · hold |
|---|---|---|
| `light` | `entity` | brightness strip in the light's colour · on/off · brightness · colour field and whites, history |
| `light_group` | `entity` (a light group) | one lane per bulb · all on/off · all · one strip per bulb |
| `fan` | `entity` | strip, the blades spin at speed · on/off · speed · direction, oscillate |
| `cover` | `entity` | strip, the slats close as you slide · open/close · position · tilt |
| `lock` | `entity` | switch · lock/unlock · — · logbook |
| `switch` | `entity` (switch, input_boolean, siren, automation) | switch · toggle · — · timeline |
| `button` | `entity` (script, button, input_button) | runs it on tap |
| `climate` | `entity` | current temperature, a target ruler, −/+ · — · — · modes, history |
| `sensor` | `entity` | the value and a 24 h trace · opens history |
| `readings` | `entities` (several sensors of one kind) | ONE overlaid chart, one line per sensor; slide to read every value at that moment |
| `meter` | `entity` (an energy or water total) | today's total and 7-day bars |
| `media` | `entity` | now playing, transport · play/pause |
| `camera` | `entity` | a live still, refreshed |
| `list` | `entities` (doors, windows, leaks, motion) | open or wet items first, in rose |
| `person` | `entity` | home or away, and since when |
| `weather` | `entity` | now and the next days |
| `vacuum` | `entity` | state and battery · start/return |
| `alarm` | `entity` | the modes as words · pick one |
| `scenes` | `entities` | the scenes as words · apply |
| `entity` | `entity` | the plain state of anything else |
| `note` | `text` | a short line of text |

Optional keys on any card: `name`, `icon` (mdi:…), `span` (1–4 columns), `color`,
and `options` (a free mapping a card type may read).

Anything whose `type` is not in the table is a **Lovelace card**. It is
rendered by Home Assistant's own card helpers, untouched. A Lovelace card's
YAML is therefore always valid here, including any custom card the house has
installed.

## Custom card code (`cards/*.js`)

When nothing that exists will do, write a card. Each `cards/<name>.js` is an ES
module that Morph loads automatically, and each one defines a standard Lovelace
custom card:

```js
class MorphPets extends HTMLElement {
  setConfig(config) { this._config = config; }
  set hass(hass) {            // called on every state change in the house
    this._hass = hass;
    this.render();
  }
  render() { /* draw into this (or a shadow root) — no external libraries, no network */ }
  getCardSize() { return 2; }
}
customElements.define("morph-pets", MorphPets);
```

Then use it in `dashboard.yaml` as `type: custom:morph-pets`. Rules for card code:

- No imports from the network and no frameworks. Plain DOM only.
- Use Morph's colours through CSS variables: `--bg --surface --sunk --line --text
  --muted --quiet --amber --sand --sky --violet --teal --lime --rose --peach
  --indigo`. Fonts: `'Bricolage Grotesque'` for big numbers, `'Manrope'` for text.
- Act through `this._hass.callService(domain, service, data)`.
- The card must render with no data at all; `hass` may arrive late.

## The design rules (these are the acceptance criteria)

1. **Nothing floats over anything.** No popups, sheets or overlays. Things open
   in place, and the page moves around them.
2. **One grammar.** Tap does the main thing. Slide sets a level. Hold opens the
   card in place, with its options and its history.
3. **No chrome.** No Done buttons, tabs, chevrons or drag handles in normal use.
4. **One control, one place.** Never repeat a control in a second card.
5. **Scenes sit above lights**, as words.
6. **Quiet by default.** A group gets a label only when it needs one.
7. **Tiles don't waste space.** Things of one kind go together, and a row only
   holds things of the same height.
8. **History belongs to its device**, in the device's colour.

When a request conflicts with a rule, do what was asked and say which rule it
bends in your `summary`.

## How to make a change well

- Make the smallest change that does what was asked. Moving a card is moving one
  item between lists, not rewriting the file.
- Check entity ids against the house with your tools before you add them. A card
  for an entity that does not exist draws as "unavailable".
- Put a new section on the floor where it belongs, near related sections.
- If the change needs something in Home Assistant (an automation, a helper, a
  script), make it, then add the card that uses it. That is allowed and
  expected.
- `protected_entities` still applies. If a request needs one, say so in
  `needs_person`.
- Read `LEARNED.md` and follow it. If the request teaches a lasting preference,
  return it as `lesson`.
