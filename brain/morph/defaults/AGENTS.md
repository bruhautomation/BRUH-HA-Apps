# Morph — how this dashboard works (for brAIn)

This folder is **Morph**, the house's dashboard (Morph {{VERSION}}). Morph is in
Home Assistant's sidebar. You (brAIn) design it with the household: when
somebody holds something in Edit and tells you what to change (a **Tell**), when
you are asked in a chat or the terminal, and when a suggestion Morph made is
approved.

Morph rewrites this page when it is updated, so do not edit it: your notes
would be lost. What this household wants belongs in `LEARNED.md`.

The first part of this page is how Morph works, whatever face you are reached
through. The last part, **Answering a Tell**, is reference for the answer a
Tell asks for.

# How Morph works

## The files

| File | What it is | Who writes it |
|---|---|---|
| `dashboard.yaml` | The whole dashboard | Edit mode, you, a person with a text editor |
| `cards/*.js` | This house's custom card code: one Lovelace custom card per file | You |
| `frontend/*.js` | This house's changes to Morph's own panel (below) | You |
| `frontend/.base/` | Morph's own files as they were when each change was made | Morph |
| `LEARNED.md` | What this household has taught Morph, as rules | The household, a Tell, the learning pass |
| `AGENTS.md` | This page | Morph |

**Never run `git` here.** This folder is a git repository and Morph commits
every change itself: a Tell's change is one commit made the moment you answer,
and a change made in a chat or by hand is committed as *Edited outside Morph*.
That commit is what the person's **Undo** reverts; a commit of your own would
make Undo revert the wrong thing.

Morph reloads the dashboard live whenever `dashboard.yaml` changes. A changed
card file runs once the page reloads (a page can only define a card once), and
Morph offers the reload.

### LEARNED.md

Each line ends with who wrote it: `(you)` the household, `(tell)` you during a
Tell, `(learned)` Morph's learning pass. A line with no mark is the household's.
Follow these lines unless a request says otherwise. Never reword or drop a
`(you)` line: it is somebody's own rule, and Morph puts it back if a pass leaves
it out.

## dashboard.yaml

```yaml
title: Home
greeting: true       # "Good evening." at the top of the page
story: true          # the story line: what is going on right now, at the top
ask: true            # "Ask or tell the house…"
coming_up: true      # the Coming up strip: timers, sun, calendars, what usually happens
night_dim: false     # true: at night the rooms are dimmed a little (optional; off by default)
room_marks: true     # false: no door and motion marks at the right of a room's title (optional)
theme: auto          # auto | dark | light | medium (optional)
scenes: [scene.morning, scene.evening]   # house-wide scenes, shown as words
floors:
  - id: f_first_floor
    title: First floor
    heading: true        # false: no floor heading (a one-floor house has none either way)
    sections:
      - id: s_kitchen
        title: Kitchen
        area: kitchen        # optional: the HA area, so brAIn's notes land here
        color: sand          # amber sand sky violet teal lime rose peach indigo
        width: 3             # preferred columns, 1–4 (the layout may use one more or less)
        hidden: false        # true hides the section outside Edit (Edit shows it faded)
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
                type: custom:mushroom-chips-card   # ANY Lovelace card, written directly
                chips: [...]
      - id: s_porch
        title: Porch
        cards:               # shorthand: a section with one unlabelled group
          - entity: light.porch
```

Two more shorthands: a file with `sections:` and no `floors:` is one floor named
after the title, and a section may give `cards:` instead of `groups:`.

**Keep every existing `id`.** Notes, usage counts and Undo are keyed on ids, so
renaming one makes the card look new. A new card or section may leave `id` out
and Morph assigns one.

Optional keys on any card: `pin` (`true` keeps it in place whatever is
happening; `active` keeps it in place only while it is on, open or running),
`name`, `icon` (mdi:…), `span` (1–4 columns),
`color`, `unit` (kept for a card that reads it; built-in cards show the entity's
own unit), and `options` (a free mapping for card code to read). Three keys
in it mean something to Morph: `options.detail`, a Lovelace card config shown
only while the card is open (a performance chart under a thermostat: folded
away until somebody opens that card), `climate`'s `options.actions`, below,
and `switch`'s `options.header: true`, which puts the switch in its
section's title row as a small pill button named by the card's `name` (amber
while on, one tap toggles it, there even while the room is folded) instead
of a tile: the place for a setting about the room, like a pause toggle. It
is a tile again in Edit, so it can be edited.

**Any Lovelace card works.** A `type` that is not in the table below is a
Lovelace card: write its own YAML directly (`type: tile`, `type: custom:x`),
and Morph wraps it as `type: lovelace` with the config under `card:` and
draws it with Home Assistant's own card helpers, untouched. Writing that
wrapper yourself is the same thing:

```yaml
- id: c_energy
  type: lovelace
  card:
    type: energy-distribution
```

### Card types Morph draws itself

| `type` | Takes | Face · tap · slide · hold |
|---|---|---|
| `light` | `entity` | brightness strip in the light's colour · on/off · brightness · colour field and whites, history |
| `light_group` | `entity` (a light group) | one lane per bulb · all on/off · all · one strip per bulb |
| `fan` | `entity` | strip, the blades spin at speed · on/off · speed · direction, oscillate |
| `cover` | `entity` | strip, the slats close as you slide · open/close · position · tilt |
| `lock` | `entity` | switch · lock/unlock · — · logbook |
| `switch` | `entity` (switch, input_boolean, siren, automation); optional `options.header: true` (a pill in the section's title row instead of a tile) | switch · toggle · — · timeline |
| `button` | `entity` (script, button, input_button) | runs it on tap |
| `climate` | `entity`; optional `options.actions` (up to 4 scripts, buttons or scenes: an id, or `{entity, label}`) | current temperature, a target ruler, −/+, the actions as buttons (a script reads as pressed while it runs) · — · — · modes, history |
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
| `lovelace` | `card` (a Lovelace card's config) | whatever that card draws |

A card type that a copy of `cards.js` adds (below) is used the same way while
that copy is in use.

## What dashboard.yaml does not hold

- **The story line** is drawn by Morph's own code (`morph-panel.js`,
  `storyFacts`) from the house's state, led by brAIn's situation sentence when
  there is one. `story:` only switches it on or off.
- **Coming up** is drawn by Morph's own code (`upcoming.js` gathers the events,
  `morph-panel.js` places the strip, under the story or under the card whose
  Next chip opened it). `coming_up:` only switches it.
- **The personality** is brAIn's (`/config/.brain/personality.json`, edited in
  brAIn's ⚙ › Personality, and read only while ⚙ › Features › Personality is
  on); Morph keeps none of its own. Never write a personality into Morph's files. An old
  `frontend/personality.js` is retired: never import, read or write it — Morph
  pauses it, and any copy that still reads it, until it is removed.
- **What leads the page.** The verdict at the top, the **Now** row, which rooms
  are open and which are one folded line, and each card's "because" line are
  worked out by Morph (`salience.js`) from the house's state and what brAIn
  publishes (`/config/.brain/morph/feed.json`). A card moves up because it
  matters right now and goes back when it stops; `pin:` is how a person says a
  card stays where it is. Never write an order into `dashboard.yaml` to make
  something lead.
- **brAIn's cases and To Do.** A problem or a question brAIn has is drawn in
  the room it is about, with a reply line, from brAIn's own list
  (`/config/.brain/morph/cases.json`). Morph keeps no list of its own; never
  add a card for a case.
- **How anything looks or moves** — the header, the layout, a built-in card's
  face — is Morph's own code.

A change to any of these is a change to Morph's own code.

## Morph's own code (`frontend/*.js`)

Nothing about Morph is out of reach — not the dashboard and not Morph itself.
Never tell somebody you cannot change Morph's code. You can.

Morph's own panel modules are in `/config/custom_components/brain/morph/frontend/`:

| Module | What it is |
|---|---|
| `boot.js` | The loader: paints the page's outline, loads the panel, and falls back to Morph's own panel when a copy fails |
| `shell.js` | brAIn's sidebar entry: holds brAIn's own page in a frame and Morph as its Home tab. Never replaced |
| `morph-panel.js` | The page: the verdict, Now, the rooms, brAIn's cases, To Do, Ask, Edit, Tell, Settings |
| `cards.js` | The built-in card types (`TYPES`) |
| `engine.js` | The layout engine: springs, masonry, opening in place |
| `history.js` | History and charts |
| `upcoming.js` | The Coming up strip |
| `snap.js` | The picture a Tell takes of what was held |
| `styles.js` | The styles |
| `salience.js` | What matters right now: each card's score, its band (Now, Lead, Shown, Folded), its "because" line, and the room states |
| `cases.js` | brAIn's cases as Morph draws them in a room, and the To Do list |
| `then.js` | The house as it was at a moment in the last day (Coming up slid into the past) |
| `morph-dom.js` | Updating the page in place, so nothing a person is touching is rebuilt |
| `util.js` | Icons and small helpers |

That copy is Morph's: read it, never edit it there (an update replaces it). To
change one:

1. Copy it to `/config/morph/frontend/` under the same name, and edit the copy.
   A new module of your own can go there too, imported by a copy.
2. Morph serves your copy in place of its own. The page has to reload to run
   it; Morph offers the reload.
3. Copy only the files you change, and keep every export the other modules
   import: they import by name, and a missing export stops the panel loading.
4. Never replace `boot.js`. It is the loader, and it is what runs Morph's own
   panel when your copy fails to load — so a broken copy never blanks the page.
   Check your JavaScript anyway: a copy that fails is a page running without
   your change.
5. A card type your copy of `cards.js` adds to `TYPES` can be used in
   `dashboard.yaml` like a built-in one while that copy is in use. While it is
   paused, Morph treats it as a Lovelace card, which cannot draw it.

A change to Morph's code is a change to the design, so it needs a reason the
household gave. The design's numbers — the springs (K = 150, ζ = 0.82), the
130 ms / 170 ms make-room-first delays, the three themes' backgrounds
(`#0A0C0E`, `#2A2D31`, `#ECEBE6`), the type sizes, the floors' summaries and
the room line's meta on a phone — are changed only when a `(you)` line in
`LEARNED.md` asks for it, and that line is written in the same change. A
copy that changes them with no such line is drift: put it back.

When Morph is updated and its own copy of a file you changed moves (or another
module your copy builds on moves), your change is **paused**: Morph's own runs
until somebody asks you to make it again on the new file. Morph keeps its file
as it was when the change was made in `frontend/.base/<name>`, so making it
again is a three-way merge. **Merge all** hands you every paused copy at once.

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
// Guarded: a card file that changes is loaded again, and a page can only
// define a name once (the new version runs after the page reloads).
if (!customElements.get("morph-pets")) customElements.define("morph-pets", MorphPets);
```

Then use it in `dashboard.yaml` as `type: custom:morph-pets`. The contract:

- **`hass` is set on every state change in the whole house**, many times a
  second in a busy one. Re-render only when something the card shows has
  changed (compare the states you read), or the card costs the page its
  frame rate.
- **Plain DOM only.** No imports from the network and no frameworks: the page
  must work offline, and a CDN that is down is a card that is blank.
- **Morph's look, through its variables**: `--bg --surface --sunk --line --text
  --muted --quiet --amber --sand --sky --violet --teal --lime --rose --peach
  --indigo`. They change with the theme (dark, light, medium), so never hard-code
  a colour. Fonts: `'Bricolage Grotesque'` for big numbers, `'Manrope'` for
  text.
- **Size**: the card fills the width its tile gives it (`span` sets the
  columns) and is as tall as its content; `getCardSize()` is a hint in rows of
  about 50 px. Never set a fixed width.
- **Nothing floats.** No popups, dialogs or overlays (design rule 1): open
  things in place, inside the card.
- **Act** through `this._hass.callService(domain, service, data)`.
- **Talk to brAIn** (a card with its own question box) through Morph's
  conversation, which is brAIn's chat:
  `this._hass.callWS({type: "morph/request", kind: "converse", payload: {text, context, session}})`.
  `text` is ONLY what the person said; put everything the card adds (the
  readings it shows, its history, who is asking) in `context`, never in
  `text`. The two together hold 16,000 characters, and when they are longer
  it is the context that is cut (and the cut is said), never the person's
  words. The answer carries an `id`; follow it with
  `{type: "morph/tell_status", tell: id}` until `phase` is `done` or
  `failed` (`say` is brAIn's answer), and send its `session_id` as `session`
  on the next turn to carry the conversation on.
- **Open Coming up from a card** (a "Next" chip) with an event, never by
  moving Morph's elements yourself:
  `const e = new CustomEvent("morph-coming-up", {bubbles: true, composed: true, detail: {}}); this.dispatchEvent(e);`.
  Coming up unfolds directly under the tile the event came from, across its
  row, and the board makes room; the same press again folds it.
  `detail.open: true/false` says which outright, and after the dispatch
  `e.detail.shown` says whether it is showing, so the chip can draw itself
  pressed. A card that is not on the board opens it in its usual place under
  the story.
- **Render with no data at all**: `hass` may arrive late, and an entity may be
  unavailable.
- **A broken card is this house's to fix**, by a Tell or in a chat, not a bug
  in Morph: Morph offers the fix as a suggestion on the dashboard rather than
  sending it to Morph's developers.

## The design rules (these are the acceptance criteria)

1. **Nothing floats over anything.** No popups, sheets or overlays. Things open
   in place, and the rest of the page moves around them.
2. **One grammar.** Tap does the main thing. Slide sets a level. Hold opens the
   card in place, with its options and its history. In Edit, tap edits and hold
   talks to brAIn.
3. **No chrome.** No Done buttons, tabs, chevrons, instruction rows or drag
   handles in normal use.
4. **One control, one place.** Never repeat a control in a second card.
5. **Scenes sit above lights**, as words, in every room.
6. **Quiet by default.** A group gets a label only when it needs one. Fans and
   blinds sit after a room's lights in a group labelled **Comfort**.
7. **Tiles don't waste space.** Things of one kind go together, and a row only
   holds things of the same height.
8. **Opened things stay where they are.** An opened card keeps its row and
   column, grows right (or left, at the end of a row) and down, and its
   neighbours step to the nearest free place.
9. **Make room first, then grow.** Neighbours move before the card expands;
   sections never jump sideways and never overlap.
10. **Tap outside folds it back**, all the way to the compact face.
11. **History belongs to its device**, in the device's colour, starting with
    its icon and name.

12. **One Now and one list of brAIn's cases.** The Now layer is the salience
    list's, and brAIn's cases are drawn in their rooms by Morph; never a
    hand-built card or page that lifts doors and locks, lists findings again,
    counts them or carries Yes/No/Snooze. Never hand-set what is normal (a
    "96 h" threshold): brAIn measures it.
13. **No empty-state text and no tooltips.** A section with nothing in it is
    not drawn; nothing says "All quiet", and no control carries a `title=`
    hover text (nothing floats).

When a request conflicts with a rule, do what was asked and say which rule it
bends.

## Making a change well

- **Look first.** A request from the editor comes with a picture of what was
  held, taken the moment it was held: "this" means what is on the screen, and
  the YAML only says what is configured.
- Make the smallest change that does what was asked. Moving a card is moving
  one item between lists, not rewriting the file.
- Put a new section on the floor where it belongs, near related sections.
- **Do the whole thing.** You are brAIn, the same one as the chat, with the
  same reach. When what was asked needs Home Assistant to change too (a
  template sensor the card reads, an automation the button runs, a helper, a
  script, a renamed entity), make those changes as well, check them, and list
  each one in `home_assistant` so Undo can hand it back. Never stop at the
  dashboard half and leave the rest for somebody to do by hand. Leave alone
  anything in the house the request does not need.
- `protected_entities` still applies to acting on an entity. Showing one on
  the dashboard is fine.
- What you learn about the house (what a device is, where it is, which sensor
  measures what) is brAIn's memory, not `LEARNED.md`. In a chat, remember it
  as you always do; a Tell carries it in its answer.

## Checking your change

- **The YAML parses.** A file that does not read is not applied: Morph keeps
  showing the last version that did and says why.
- **Every entity exists.** Check ids against the house with your tools; a card
  for an entity that does not exist draws as "unavailable".
- **Morph reads it back.** After a Tell, Morph compares the file with how it
  was and tells the person what is different on screen. A change that is not
  in the file is shown not to have happened.
- **Code loads.** A copy in `frontend/` or a card in `cards/` that throws is
  reported; read it once more before you answer.

## When to ask instead of act

Act on what was asked. Ask only when what is left is a choice that is the
person's, never yours to guess:

- **A merge with more than one reasonable answer** (an update rewrote the code
  a change was in): ask, one option per way, plus one that uses Morph's own.
- **Something only the household knows**: which of two rooms a device is in,
  whether a card nobody uses should go.

Never ask for confirmation of what was asked, and never ask about a detail you
can read off the house.

A number a card works out from other sensors (a difference, a sum, a rate, a
cost) is not a question: Home Assistant records entities, so make a template
sensor that holds it, show that sensor on the card, and say so. A value
calculated only in the card has no history and nothing an automation can use.

# Answering a Tell (reference)

A Tell is a task: the prompt says what was held and asked, and the answer is a
JSON object whose schema travels with the task. The schema's own descriptions
say when each field is filled; in short:

| Field | What it is |
|---|---|
| `summary` | What you did, for the person |
| `files` | Each file under /config/morph you changed |
| `home_assistant` | Each change made in Home Assistant itself; Undo hands it back to you |
| `saw` | With a picture only: what in it the request is about |
| `needs_person` | What is left for a person to do by hand |
| `question` | A choice that is the person's, as two or three buttons |
| `lesson` | A lasting rule about this household's dashboard |
| `facts` | What you learned about the house, for brAIn's memory |
| `code_issue` | What you changed in Morph's own code, for Morph's developers |

Morph asks the person whether to send a `code_issue`; never file one yourself.
