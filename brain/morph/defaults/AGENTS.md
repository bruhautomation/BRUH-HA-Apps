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
theme: auto          # auto | dark | light | medium (optional)
scenes: [scene.morning, scene.evening]   # house-wide scenes, shown as words
coming_up_lanes:     # optional: machines that get a lane of their own in Coming up
  - label: Laundry
    entities: [sensor.washer_status, sensor.dryer_status]
    not_running: [off, power_off]    # or running: [...]; default on/open/running/cleaning
  - label: Heating & cooling
    entities: [climate.upstairs]
    attribute: hvac_action           # read an attribute instead of the state
    running: [heating, cooling, drying]
    word: running                    # what a run is called (optional)
    color: peach                     # optional; one of the colours below
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
        icon: mdi:silverware-fork-knife   # optional: a faint icon before the room's name
        sleep_guard: false   # true: while the room's sleeper is asleep, its controls ask first
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
            when: {entity: input_boolean.party, state: [on]}   # optional: shown only then (or state_not)
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
while on, one tap toggles it) instead of a tile: the place for a setting about the room, like a pause toggle. It
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
| `climate` | `entity`; optional `options.actions` (up to 4 scripts, buttons or scenes on the control row: an id, or `{entity, label, short, running, icon, color, modes}` — `short` is the word when the row is narrow, `running` the word while a script runs, `modes` the hvac modes it is offered in) | current temperature, a target ruler, −/+, the actions as buttons (a script reads as pressed while it runs) · — · — · modes, history |
| `sensor` | `entity` | the value and a 24 h trace · opens history |
| `readings` | `entities` (several sensors of one kind; a thermostat counts as its own temperature) | ONE overlaid chart, one line per sensor across the day (from statistics, else recorded history); slide to read every value at that moment |
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
  `morph-panel.js` places the strip). `coming_up:` switches it, and
  `coming_up_lanes:` names the machines that get lanes of their own.
- **The personality** is brAIn's (`/config/.brain/personality.json`, edited in
  brAIn's ⚙ › Personality, and read only while ⚙ › Features › Personality is
  on); Morph keeps none of its own. Never write a personality into Morph's files. An old
  `frontend/personality.js` is retired: never import, read or write it — Morph
  pauses it, and any copy that still reads it, until it is removed.
- **The order is dashboard.yaml's.** Nothing on the page reorders itself:
  floors, rooms and cards keep the order they have in the file, and no room
  folds. The verdict at the top and each card's colour and "because" line are
  worked out by Morph (`salience.js`) from the house's state and what brAIn
  publishes (`/config/.brain/morph/feed.json`); they colour and word what is
  there, they never move it.
- **brAIn's cases and To Do** live in brAIn's own Needs you, never on the
  page. Morph keeps no list of its own; never add a card for a case.
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
| `morph-ha.js` | Loaded on every Home Assistant page: loads Morph's cards, card types and the brAIn layer. Never replaced |
| `morph-cards.js` | Morph's card kinds as Home Assistant custom cards (`custom:morph-<kind>-card`), with HA's visual editor and card picker |
| `morph-types.js` | Card types (`types/*.yaml`) as Home Assistant custom cards (`custom:morph-type-<slug>`), redrawn everywhere when a type changes |
| `brain-layer.js` | The brAIn button on a Home Assistant dashboard: Tell brAIn about a card or the dashboard, History, and letting brAIn keep a dashboard |
| `morph-features.js` | Morph on a Home Assistant dashboard: the older `custom:morph-view` view type, the cases card and the Ask card |
| `morph-view-layer.js` | The room rail on Home Assistant's own sections view (`morph: {rail: true}` on a view) |
| `morph-panel.js` | The page: the verdict, the rooms, Ask, Edit, Tell (Feed and Settings are brAIn's own tabs) |
| `cards.js` | The built-in card types (`TYPES`) |
| `engine.js` | The layout engine: springs, masonry, opening in place |
| `history.js` | History and charts |
| `upcoming.js` | The Coming up strip |
| `scrub.js` | The room rail, on Morph's page in place of the scroll bar and on a Home Assistant view with `morph: {rail: true}`: one notch per room, floors set apart; a swipe left opens it, then the same finger slides room to room |
| `haptics.js` | Haptics in the Home Assistant app (a tick per detent, a bump at an end, a tap per action) |
| `polish.js` | Morph's motion language: the self-drawing mark, rolling numbers, the touch light, a tile's glow on a change made elsewhere |
| `pull.js` | Morph's own pull to refresh |
| `snap.js` | The picture a Tell takes of what was held |
| `styles.js` | The styles |
| `salience.js` | What matters right now: each card's score, colour and "because" line, and the room states (asleep, occupied) |
| `cases.js` | brAIn's cases as the Lovelace layer's cases card draws them |
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
- **Coming up is always shown** under the top of the page while `coming_up:`
  is on; a card never opens or moves it.
- **Render with no data at all**: `hass` may arrive late, and an entity may be
  unavailable.
- **An entity that is `unavailable` or `unknown` has no reading now.** Its
  attributes may still hold its last temperature, target or timer: grey that
  figure, leave out the targets, controls and running timers, and say when it
  was last heard from ("last seen 4:02 PM", from its `last_changed`). A name
  is whole: it wraps, it is never cut off with an ellipsis.
- **History, as Home Assistant sends it.** `history/history_during_period`
  answers compressed rows, `{s, a, lu}` with `lu` in SECONDS (and `lc` only
  when it differs), never `state`/`last_changed`: a chart that reads those
  draws nothing. `recorder/statistics_during_period` has rows only for a
  sensor with a `state_class`, and none for a thermostat, whose temperature
  is its `current_temperature` attribute (ask history with attributes for
  it). For temperature or humidity by room, use the `readings` card, which
  takes thermostats and sensors alike. With nothing to draw, say so in
  words, never an empty plot.
- **Controls sit in their own row**, above or below a chart, never on it:
  chips and toggles that wrap push the chart down rather than lying over it.
- **A moisture reading that drops straight to exactly 0** (from 10% or more
  within 15 minutes) is a probe that stopped answering, not dry soil: say
  "Sensor offline · check the probe" (with its battery when one is known) and
  no percentage. Soil that dried to 0 over hours is a real 0%.
- **Say what the reading is, not what the card is usually.** A reading outside
  its target, hold or comfort band is stated in the card's status line, with
  how far outside ("11° below its hold band"): never "Idle", "OK" or
  "Normal" over a number the card itself shows outside its band, and a status
  worked out from the mode alone is wrong the moment the reading and the mode
  disagree. Compare the reading with its band before choosing the word.
- **A tile's status is ONE line, composed to fit.** A name and one short line
  under it ("20 of 31 on"), never two lines of status: a tile is one row tall
  and a status that wraps runs over its edge and its texture. Say the fact
  that matters first and add the rest only when the tile is wide enough
  ("20 of 31 on · mixed · 2 unavailable" on a wide tile, "20 of 31 on" on a
  narrow one), by leaving the later parts out, never by letting the line wrap
  or be cut in the middle of a fact. What a tile has no room for (which lights
  are unavailable, each brightness) belongs in the opened card, labelled.
  Morph's own tiles do this with `statusHtml` (`cards.js`); a built card does
  it with a container query (`@container (min-width: …)`) that shows the
  later parts, and `white-space: nowrap` on the line.
- **A group's summary leads with what is on, and is never a list of every
  member.** A tile for several things (lights, equipment, switches, covers,
  media players, people) says how many are on and, while it fits, which:
  "2 on: Crawl fan, Dryer blower", "20 of 31 on", "All equipment off", "3 of 4
  open", "Dana home, Eli away". Never "Crawl dehum off · Crawl fan off · Dryer
  blower off · …": that hides the one fact that matters behind the ones that
  are the default, and it ends in a bare ellipsis. Say the count first, then
  at most two names, then "and 3 more"; put the full list in the opened card.
  Every tile of a kind uses one format ("N of M on" for all of them, a level
  labelled "avg 62%", never "mixed" on one tile and "1%" on another), and a
  count of members that cannot be reached is labelled ("2 unavailable") or
  moved to the opened card.
- **A thing's state is said once in a card.** The tile, a row and the opened
  card each say what a thing is doing in one place: not "Off" in the header
  and "Off" on a badge beside it, not "Zone 2 on" over a row that says "On",
  not a switch's word and the same word on its button. A control that sets
  the state shows it by being pressed. Two controls for the same thing (a pump
  and the button that runs it) agree about when it last ran, or each says what
  its date is ("pump last ran", "run pump last pressed").
- **A part with nothing in it is left out, or says how to fill it.** An empty
  list ("Sequence · Empty") is not drawn as a dimmed tile: it is hidden, or in
  one line says what to add ("Add zones to build a sequence").
- **No empty space.** The card is as tall as what it draws: no `min-height`,
  padding or spacer kept for a row that is not there, and a part with
  nothing to show is left out, not drawn blank.
- **Fields are 16px or larger.** A text box, textarea or select under 16px
  makes a phone zoom the page when it is touched. Morph raises them in a
  card's own shadow root, but write them right.
- **A card stays inside its own width.** At 390px nothing a card draws is
  wider than the card: a diagram is one SVG that scales with a `viewBox` and
  its readings are drawn inside it (never positioned outside the card's box),
  and a long row wraps. A sum or summary is built from parts that each stay
  whole ("3h 20m" in a `white-space:nowrap` span) with a separator between
  them, so it wraps at the separator and never in the middle of a figure.
  Morph clips a built card at its edge as a last resort; that hides a
  reading, it does not fix it.
- **A figure that disagrees with its neighbour says why.** Two numbers about
  one thing that cannot both be the whole story (asleep 1h beside in bed 7h,
  a total beside a part that is far smaller) get a one-line note naming the
  likely reason ("the tracker recorded only part of the night"), or a dash
  for the doubtful one. When asleep is under about half of in-bed time, say so.
- **Every button and chip is a 40px target.** A scene chip, a mode button or
  a word you can press is at least 40px tall and 40px wide (`min-height` and
  `min-width`, never a fixed `height` under it), with a gap between
  neighbours, so a finger on a phone hits the one it means. A row of chips
  wraps rather than shrinking them.
  Morph does not resize a built card's buttons for it (a blanket rule pushed a
  twelve-column hour grid out of its card), so a grid of buttons that does not
  fit at 40px has fewer columns, wraps, or scrolls sideways inside its own box:
  never smaller buttons, never buttons pushed past the card's edge.
- **Text is 4.5:1 against what it sits on, in light and dark themes.** Take
  colours from the theme's variables (`--primary-text-color`,
  `--secondary-text-color`), never a fixed colour picked on one theme: an
  accent chosen on a dark page is unreadable on a light one. A small label
  ("History", an hour tick, "1 change") is text too: it uses the same
  variable, never a grey mixed toward the background or dimmed with `opacity`.
- **Every button shows an icon or words, and has a name.** Icons are inline
  SVG you draw yourself: an `<ha-icon icon="mdi:…">` or any icon font is
  blank when its set is not loaded in the card, which leaves a round button
  with nothing on it. An icon-only button carries an `aria-label`. A button
  that cannot be pressed right now is dimmed or not drawn, never left
  looking like the others.
- **A broken card is this house's to fix**, by a Tell or in a chat, not a bug
  in Morph: Morph offers the fix as a suggestion on the dashboard rather than
  sending it to Morph's developers.

## The design rules (these are the acceptance criteria)

1. **Nothing floats over anything.** No popups, sheets or overlays. Things open
   in place, and the rest of the page moves around them.
2. **One grammar.** Tap does the main thing. Slide sets a level. Hold opens the
   card in place, with its options and its history. In Edit, tap edits and hold
   talks to brAIn. The short pull left that opens the room rail on a
   touch screen's right edge is an opening gesture, not a slide (it sets no
   level): keep it, and never make the rail answer a plain touch or a vertical
   swipe, which is the page scrolling.
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
    The one exception is a hosted Lovelace card that has nothing to draw
    (a conditional card whose condition is false): it says so in one quiet
    line rather than vanishing from the page.

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

# Home Assistant dashboards (brAIn 5.0)

Morph is now also a layer on **Home Assistant's own dashboards**. A
dashboard the household has let brAIn change ("Let brAIn change it" on the
brAIn button, bottom right of any dashboard) stays an ordinary Home
Assistant dashboard, drawn by Home Assistant: every built-in card, every
HACS card, the visual editor, the sidebar and themes work exactly as they
do anywhere else. What Morph adds is that you can change it, and that every
change is kept.

## The files

| File | What it is | Who writes it |
|---|---|---|
| `dashboards/<key>.yaml` | One Home Assistant dashboard (`default` is the default one, otherwise its url path): its Raw configuration editor YAML, `views:` at the top | You, Home Assistant's own editor (Morph copies it here), a person |
| `types/<slug>.yaml` and `types/<slug>.js` | Card types: a card built once and used anywhere | You |
| `themes/*.yaml` | Home Assistant themes, loaded into Home Assistant | You, a person |

- **Edit `dashboards/<key>.yaml`, never Home Assistant's `.storage`.** The
  moment you write the file Morph saves it to Home Assistant and every open
  screen redraws. Do not use `update_dashboard` for a dashboard kept here.
- A change made in Home Assistant's own editor is written back into the
  file and committed as *Edited in Home Assistant*.
- A file that does not read as YAML is not sent: Home Assistant keeps the
  last version that did until the file is fixed.
- Keep every card you were not asked about exactly as it is.

## What to use for a card

1. **A card Home Assistant already has** (tile, thermostat, entities,
   heading, grid, conditional…), or **a HACS card this house has**
   installed (check `lovelace_resources` first; never install one without
   asking).
2. **Morph's own cards**, which are Home Assistant cards too, each with
   Home Assistant's visual editor: `custom:morph-<kind>-card` where kind is
   one of `light`, `light-group`, `fan`, `cover`, `lock`, `switch`,
   `button`, `vacuum`, `climate`, `sensor`, `readings`, `meter`, `media`,
   `camera`, `list`, `person`, `weather`, `alarm`, `scenes`, `entity`,
   `note`. They take `entity` (or `entities` for `readings`, `list`,
   `scenes`), `name`, `icon` (an `mdi:` icon in place of Morph's moving
   one), `room` (names starting with it are shortened), `color` (amber
   sand sky violet teal lime rose peach indigo), `tap_action`,
   `hold_action` and `double_tap_action` (Home Assistant's own actions:
   left out, tap does the main thing and hold opens the card in place),
   `detail` (any Lovelace card config, shown under the card while it is
   open), and a thermostat takes `actions` (up to four scripts, scenes or
   buttons). Every one of these is in the card's visual editor.
   A house's own kind (a copy of `cards.js` that adds one) is
   `custom:morph-<its kind>-card` too.
   `custom:morph-cases-card` (brAIn's cases; `area:` or `entities:` for one
   room's) and `custom:morph-ask-card` are Morph's too.
3. **A card type** (below), when the card will be wanted again or in more
   than one place.

A **HACS card** is changed through its own config and, for looks, a
`card_mod:` block when card-mod is installed (ask before installing it).
Never edit a HACS card's JavaScript: HACS overwrites it on update. When the
change needs its code, make a card type that wraps it (`kind: template`) or
copies it (`kind: element`), and say so.

## Size and layout

A dashboard tab is Home Assistant's **sections** view: sections of a
12-column grid whose rows are 56px (with 8px gaps), laid out by Home
Assistant. A card's size is its `grid_options`:
`{columns: 1-12, rows: <number> | "auto"}` (half a section is 6, the
whole of it 12; `"auto"` is as tall as the card's own content). Every
Morph card has a size of its own (a strip one row and six columns, a
reading two rows, a thermostat two rows the whole width, a camera or
forecast three) and FILLS whatever it is given: change `grid_options`
to make one bigger or smaller, never a style. A section is
`{type: grid, cards: [...]}` with an optional `column_span` (how many of
the view's columns it takes); the view's `max_columns` caps the columns.

Morph's switch is on the view, under `morph:` (off unless set): `rail`
(the room rail down the right edge of a touch screen). Nothing on a view
reorders itself or folds. A section's name is its first `heading` card.
In edit mode the rail is off.

To SEE a dashboard as Home Assistant draws it, use `screenshot_panel`
with addon `Home Assistant` and screen `<url_path>/<view path>` (no
screen lists every tab): look before you answer about how one looks, and
again after you change it.

## Card types (`types/`)

A card type is built once and used anywhere as `custom:morph-type-<slug>`;
it appears in Home Assistant's card picker as "Morph · <name>" with a
visual editor for its variables. A copy holds only its variables, so
**changing the type changes every copy on every dashboard at once**.

```yaml
# types/thermo-buttons.yaml
name: Thermostat with buttons
description: A thermostat with the scripts that go with it.
kind: template
variables:                       # what a copy sets; the editor draws these
  - name: entity
    label: Thermostat
    required: true
    selector: {entity: {filter: [{domain: climate}]}}
  - name: boost
    label: Boost script
    selector: {entity: {filter: [{domain: script}]}}
  - name: title
    default: Climate
card:                            # any Lovelace card config; [[name]] is a variable
  type: vertical-stack
  title: "[[title]]"
  cards:
    - type: thermostat
      entity: "[[entity]]"
    - type: button
      entity: "[[boost]]"
```

A copy: `{type: custom:morph-type-thermo-buttons, entity: climate.downstairs, boost: script.boost}`.
`"[[name]]"` alone is the value itself (a list stays a list); inside longer
text it is the value as text; a variable nobody set leaves its key out.

For a card nothing existing can draw, `kind: element` and
`types/<slug>.js`, whose **default export** is the card's class (the
contract in "Custom card code" below: `setConfig` gets the copy's
variables, `hass` is set on every change). A new version of the code is
picked up by every open page without a reload.

When a Tell is about a copy, the request says whether the person wants
**just this one** (change its variables in the dashboard, or make it a
plain card) or **every copy** (change the type). When it does not say,
change only that copy and say the type could be changed instead.

## Themes (`themes/`)

Ordinary Home Assistant theme files (`Name: {variable: value, modes: {light:
…, dark: …}}`), loaded into Home Assistant beside its own themes and
repainted live. `Morph` (light and dark) and `Morph Medium` are here. A
view's look is its `theme:` key; the house's is `frontend.set_theme`. Every
Morph card reads Home Assistant's variables (`primary-background-color`,
`card-background-color`, `primary-text-color`, `secondary-text-color`,
`divider-color`, `primary-color`, `ha-card-border-radius`) and Morph's
palette as `morph-amber`, `morph-sand`, `morph-sky`, `morph-violet`,
`morph-teal`, `morph-lime`, `morph-rose`, `morph-peach`, `morph-indigo`.

## Morph's older view

`type: custom:morph-view` was Morph's own view type, and a 5.0 conversion
wrote it. Morph changed every such tab to Home Assistant's `sections` once
(5.1), keeping its `morph:` switches, because Home Assistant's own sections
view edits, sizes and arranges cards and Morph's view did not. Do not
write `custom:morph-view` for a new tab: use `type: sections` with the
`morph:` switches above.

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
