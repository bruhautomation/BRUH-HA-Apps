# MORPH UI — design doc (proposed 2026-10-12)

**A predictive, organic interface built to handle the complex, beautifully.**

MORPH is a Home Assistant dashboard that lives in the sidebar. The whole page
moves to make room for whatever you are looking at. It hosts any Lovelace card,
and brAIn turns it from a dashboard you configure into a house that explains
itself and a UI you change by saying what you want.

- **Prototype:** [`morph-ui.html`](morph-ui.html). It is self-contained: open it
  in a browser, there is nothing to build. It is BRUH house's real room
  structure and real entity ids, with invented states and history.
- **Where it was designed:** the MORPH UI canvas,
  `https://claude.ai/artifact/CvXPWsssm2hg3NJkM4f6Th` (page *Home*, board *MORPH
  UI · BRUH house*). The note beside that board is the running vocabulary this
  doc is written from.
- **Status:** proposed. Nothing here has shipped. The prototype is the
  reference for behaviour and motion, not for code: it is one 200 KB file
  written to be looked at, not maintained.

Everything below is a rule the prototype already follows, unless it is marked
**(proposed)**.

---

## 1. The rules, in one place

Each of these came from looking at the prototype and saying "no, not like
that". They are the acceptance criteria.

1. **Nothing floats over anything.** No popups, no sheets, no overlays. Things
   open in place, and the rest of the page moves around them.
2. **One grammar.** **Tap** does the main thing (toggle, play, lock). **Slide**
   sets a level (brightness, fan speed, blind position). **Hold** opens the card
   in place with its options and its history. In **Edit**, **tap** edits and
   **hold** talks to brAIn (§7).
3. **No chrome.** No Done buttons, tabs, chevrons, instruction rows, hold rings
   or drag handles in normal use. A small hint pill on hover is the most a card
   gets.
4. **One control, one place.** Brightness lives on the strip. Nothing repeats
   it in a panel. A room's "Off" is a scene word, not a second button.
5. **Scenes sit above lights**, as words, in every room.
6. **Quiet by default.** Subsections are not boxed. A group gets a small tinted
   label only when it needs a name (Comfort, Party, Bathroom, Front/Back).
7. **Tiles don't waste space.** A row only holds things of the same height, so
   no short tile ever has a hole under it. Same-size things spread evenly over
   the rows they need (4 in a 3-wide room → 2 + 2, not 3 + 1). A lone strip or
   list fills its row.
8. **Opened things stay where they are.** An opened card keeps its row and
   column. It grows right (or left, if the row ends there) and down, and its
   neighbours step to the nearest free place.
9. **Make room first, then grow.** Neighbours move before the card expands.
   Anything that changes rows dips in opacity while it passes. Sections never
   jump sideways; they only slide up or down. Zero frames in which two
   sections overlap.
10. **Tap outside folds it back.** Anything open returns all the way to its
    compact face, including any history drilled into.
11. **History belongs to its device.** An opened card takes on the device's
    colour as one object, and its history trail starts with the device's icon
    and name.

---

## 2. Structure

```
view
└─ floors            First floor · Upstairs · Outside · Whole house
   └─ sections       rooms (Living Room, Kitchen …) and systems (Climate, Security, Media …)
      └─ groups      optional label (Comfort, Party, Front, 3D printer)
         └─ cards    morph cards, or any Lovelace card, untouched
```

**Floors** are the top level. Each has a heading with one line of what matters
on that floor: its temperature, what the HVAC is doing, how many lights are on,
and anything that needs you ("Garage freezer open", in rose). A floor that
grows pushes the floors below it down. A floor heading is drawn every frame
from the live position of its floor's highest section, so the two can never
drift apart mid-animation.

**Sections** are rooms or house-wide systems. Rooms hold scenes, lights and
that room's things. Climate holds every temperature and humidity reading.
Security holds alarm, locks, doors, presence and cameras. Media holds every TV
and speaker. Water holds usage, leaks and irrigation.

**The top of the page** holds, in order: the story (§6.1), "Ask or tell the
house" (§6.4), Coming up (§6.2), and the house-wide scenes.

### Config — `/config/morph/dashboard.yaml` (proposed path)

```yaml
views:
  - title: Home
    type: custom:morph-view
    story: true
    coming_up: true
    scenes: [scene.morning, scene.dinner_time, scene.evening, scene.upstairs_dim, scene.outside_late, scene.interior_off]
    floors:
      - title: First floor
        sections:
          - title: Kitchen
            color: sand
            width: 3
            groups:
              - cards:
                  - type: custom:morph-scenes
                    entities: [scene.kitchen_bright, scene.kitchen_dim, scene.kitchen_off]
              - cards:
                  - type: custom:morph-light-group
                    entity: light.kitchen_cans
                  - type: custom:morph-light
                    entity: light.kitchen_countertop
              - title: Party
                cards:
                  - type: custom:mushroom-chips-card   # any Lovelace card, passed through
                    chips: […]
```

Edit mode writes this file. brAIn writes this file. Keep it in a git
repository at `/config/morph/` so every change, by a person or by brAIn, is one
commit that Undo can revert (§7.4).

---

## 3. Cards — one per Home Assistant domain

| Domain | Face | Tap | Slide | Hold (opens in place) |
|---|---|---|---|---|
| `light` | strip, filled to brightness in the light's colour; the bulb icon breathes when on | on/off | brightness | colour field (§3.2) + whites, sleep timer, compact history |
| `light` (group) | one thin **horizontal lane per bulb**, stacked, each filled sideways to its own level (§3.1) | all on/off | all lanes follow the finger, with a top-to-bottom ripple | one small strip per bulb, group colour, history |
| `fan` | strip; blades spin at speed | on/off | speed | direction, oscillate, history |
| `cover` | strip; slats close as you slide | open/close | position | tilt, history |
| `lock` | switch; shackle lifts when unlocked | lock/unlock | — | logbook (who/what), battery |
| `cover` (garage) | switch; door rolls up | open/close | — | logbook |
| `switch`, `input_boolean` | switch | toggle | — | timeline |
| `climate` | current temperature, a 58–82° ruler, ±target | — (± buttons) | — | modes, schedule, runs |
| `sensor` (temp/humidity) | big value + 24 h trace; **many of one kind overlay** (§3.3) | open | — | stats, then week → day → hour |
| `sensor` (meter: water, energy) | today's total + 7-day bars | open | — | daily sums → hourly → events |
| `media_player` | now playing, transport, progress | play/pause | — | source, volume, recently played |
| `camera` | live still | open | — | events timeline |
| `binary_sensor` (doors, leaks, motion) | a list, open items first in rose | open | — | logbook, battery |
| `person` | avatar, home/away, since | open | — | today's comings and goings |
| `weather` | now + 5 days; sun turns, cloud drifts | open | — | next 24 h, wind, UV, sunrise |
| `vacuum`, appliance (washer, dryer, printer) | strip with progress; drum turns while running | start/stop | — | cycle options, runs |
| `alarm_control_panel` | the modes as words | pick | — | logbook |
| `scene` | words, the active one underlined | apply | — | — |
| *anything else* | **any Lovelace card YAML**, rendered as-is inside the section | its own | its own | — |

Icons are a still outline plus one moving part that tells the state. They are
subtle, and they respect `prefers-reduced-motion`.

### 3.1 Light groups
The strip is drawn as its members. Each lane fills **sideways**, the same
direction the finger slides; vertical columns were tried and rejected because
they moved against the gesture. Mixed levels show as a ragged right edge.
Holding the strip opens one small strip per bulb, each with the same tap and
slide. Brightness is never repeated in a panel.

### 3.2 Colour
The light's colour picker is a field: hue runs across, saturation runs down
(pastel at the top, vivid at the bottom). It is stored as `hs_color`. Warm,
soft and daylight whites sit beneath it as swatches. Brightness stays on the
strip. For a group, the colour applies to every bulb.

### 3.3 Many of one reading, overlaid
Five rooms' temperatures are one chart, not five tiles:
- **One line per room**, coloured by how warm that room is now.
- **Behind the lines**, the thermostats' target band, which follows their
  schedule.
- **Under the lines**, a strip of when the system actually ran (cooling,
  dehumidifier).
- **Labels** sit at the end of each line, nudged apart so they never collide.
- **Slide** a finger along it: every room's value at that moment, plus the
  target then.
- **Tap a label**: that line stands out and the rest step back.
- **Extremes go on one quiet line below** (attic, crawl space, outside), so
  they don't flatten the indoor lines.

Humidity works the same way, with a comfort band.

---

## 4. History — what Home Assistant actually records, per domain

History opens in two layers, both inside the card:

1. **Compact** (on hold): one small summary in the device's colour and icon.
   It is either a day strip (lights, locks, covers, thermostat runs, binary
   sensors, people, cameras) or a 7-bar week (temperature, humidity, meters,
   sleep, appliances), with one line of context.
2. **Extended** (tap the summary): the trail starts with the device's icon and
   name (*Kitchen › History › Tue*); tap the name to fold back.

**Line charts are read by sliding a finger**: value and time follow it. **Bar
charts are what you tap to go deeper**: day → hours → that hour's events.

| Kind | Source | Compact | Extended |
|---|---|---|---|
| light, switch, lock, cover | `history/period` (state timeline) + `logbook` (who/what changed it — brAIn's `actions.jsonl` names its own) | day strip | timeline segments → logbook → who |
| numeric sensor | `recorder/statistics_during_period` (mean/min/max, 5-min + hourly) | week bars | day → hour → readings around it |
| climate | `hvac_action` state history | runs strip | runs per day → per hour |
| meter | statistics `sum` | week bars | daily → hourly → usage events |
| media | state + `media_title` attribute history | recently played | sessions |
| binary_sensor, person | state history + logbook | day strip | events |

---

## 5. Layout engine

The prototype's engine is the part most worth porting faithfully. Every
section, group label and tile is a **spring** (x, y, w, h; K = 150, ζ = 0.82)
driven by one `requestAnimationFrame` loop. Layout only ever sets targets.

1. **Columns:** `N = max(2, floor((W + G) / (205 + G)))`, gap `G = 12` below 700 px, else 16.
2. **Sections, per floor:** masonry. Each section tries its preferred width and
   one either side, takes the spot that sits highest, and pays a penalty for
   blank space; then a stretch pass widens into free columns. This base
   arrangement is cached per column count and section order. When something
   opens, sections only move **down**; they never widen and never jump
   sideways.
3. **Inside a section:** groups (optional label) → rows. Things of one kind
   (strip, reading, camera, thermostat, media, other) are gathered in
   first-appearance order, and each new kind starts a new row. Same-span items
   spread evenly; the last item of a row grows up to its `grow`.
4. **Opening:** the opened item keeps its row and column and grows right (or
   left at the row's end). Items it covers are packed into the lowest,
   leftmost free fit; everything else stays put.
5. **Timing:** a growing section waits 130 ms and a growing tile 170 ms, so the
   neighbours move first. A tile that travels more than 30 px dips to 12%
   opacity mid-flight (WAAPI). Upward moves of a section are delayed the same
   way.

**Tests the prototype passes, and the real one must:**
- Hold-open then tap-outside on nine card kinds, at 1440 px and 400 px,
  sampling every 30 ms: **0 frames** where two sections, or a section and a
  floor heading, overlap.
- At rest: no tiles overlap, and no two tiles on one row differ in height.
- An opened card's top-left is unchanged.

---

## 6. brAIn — what it unlocks that Lovelace can't

Lovelace shows the state you configured. brAIn knows the house's history,
notices things, and can act with permission. MORPH gives each of those a place
in the UI, and every one of them already has a producer in brAIn.

### 6.1 The story
The paragraph at the top is brAIn's live summary of right now: lights by
floor, temperatures, what needs you, who is asleep, what finishes next. Each
underlined phrase folds open in place to say more, with an action where one
fits ("Turn off downstairs").
*Stands on:* `panel/brief.py`, `panel/today.py`, `panel/situation.py` — needs a
**"now" summary endpoint (proposed)** rather than the morning brief.

### 6.2 Coming up — scheduled and predicted
The timeline mixes what is scheduled (solid ring: timers, automations,
appliance finish times) with **what usually happens** (dashed ring,
"Bedtime · usually"). Tapping a prediction asks brAIn about it, which offers
to make it automatic.
*Stands on:* `panel/routines.py`, `panel/habits.py`, `panel/rhythm.py`; making it
automatic is the existing proposal → trial → `automation_writer` path.

### 6.3 Notes in place
When brAIn notices something, it says so **once, inside the section it is
about**, with one action word ("Turn it off when the room empties" / "Not
now"). Saying yes writes the automation, and the note becomes "Done · Undo".
The prototype has four: a fan light left on, a hot attic making upstairs cool
40% longer, a freezer door that doesn't latch, and a sensor battery at 23%.
*Stands on:* findings and cases (`custom_components/brain/findings.py`,
`panel/findings_store.py`, `panel/cases.py`, `panel/answers.py` — "a card's
buttons are decided from the case, once, and every surface renders that list").
MORPH is one more surface. It places a finding in the section that contains its
entity or area, and its words come from `answers`.

### 6.4 Ask or tell the house
One quiet line under the story. The answer unfolds right there with the next
step: "Why is upstairs warm?" → the cause, plus **Show me**, which scrolls to the
temperature chart with Upstairs picked out.
*Stands on:* brAIn's conversation agent (`custom_components/brain/conversation.py`)
or `panel/intents.py` for one-off intents.

---

## 7. Tell brAIn — hold anything in Edit to change it **(the critical one)**

**In Edit mode, holding on anything opens a prompt in place that tells brAIn how
to change it.** That covers a card, a section's title, a floor heading, the
story, Coming up, or the scenes line. This is how the UI evolves on the fly:
the person describes the change, brAIn makes it, the view reloads. It is meant
to be almost unrestrained. If somebody can describe it, brAIn should be able to
do it: the dashboard, the card's own code, or the house behind it.

### 7.1 What the person sees
1. Hold for 540 ms. The thing held gets a violet ring or wash, then a prompt
   opens **inside it**: the card grows, the section header grows, the floor
   heading grows, and everything else moves to make room.
2. The prompt shows the path of what was held, for example
   `First floor › Kitchen › Cans · light.kitchen_cans`, plus a text box with
   two or three suggestions that fit that target. Enter sends.
3. While it works, steps appear one by one: *Reading …*, *Handed to brAIn as
   task morph-…*, then what changed.
4. It ends with a sentence a person reads, and either **Keep · Undo · Tell it
   more**, or **Done · Tell it more**.
5. In Edit mode, the top line becomes **"Tell brAIn how to change this
   dashboard…"** for changes that belong to no one element ("Add a Pets section
   with Cece's feeder and water bowl").
6. Tap outside or Escape folds the prompt away. The work continues; the result
   shows up in place.

Tap still opens the plain editor (name, size, YAML, remove). **Hold always
talks.**

### 7.2 Fast path — done at once, as config
Rename, colour (section), bigger/smaller (card or section), move to a floor
(section) and hide apply immediately to `dashboard.yaml`, with Undo. They need
no model run. Anything with more than one clause goes to brAIn.

### 7.3 Everything else — a brAIn task
MORPH hands brAIn a task through **the same door BRight already uses**: write
`/config/.brain/tasks/<id>.json`; brAIn's automation listener claims it by
renaming it, runs Claude Code with its MCP tools, and writes
`/config/.brain/task_results/<id>.json` back with `status` and `error`.
`bright/panel/director/claude_director.py` is the working example of a client,
and `bright/panel/director_check.py` is the six-link health check MORPH should
copy.

```json
{
  "id": "morph-3yy3bo",
  "prompt": "MORPH UI · change request from the dashboard editor.\n\nTarget: card “Cans”\nWhere: First floor › Kitchen › Cans\nEntity: light.kitchen_cans\nAsked: “…”\n\nCurrent YAML of the target:\n…\n\nDo whatever this takes. You may change the MORPH dashboard (/config/morph/dashboard.yaml), MORPH card code (/config/morph/cards/), and anything in Home Assistant behind it …",
  "ts": 1791602160,
  "timeout": 900,
  "source": "morph",
  "schema": {
    "type": "object",
    "required": ["summary", "changed", "reload"],
    "properties": {
      "summary": { "type": "string" },
      "changed": { "type": "array", "items": { "type": "string" } },
      "reload": { "type": "boolean" },
      "needs_person": { "type": "string" }
    }
  }
}
```

The prompt always carries:
- the target's kind, label, path and entity;
- the person's words verbatim;
- the target's current YAML;
- what brAIn may touch.

The prototype's **"What brAIn receives"** shows this exact payload for any
prompt.

### 7.4 "Almost unrestrained" — what that means here
The scope is not limited: layout, look, behaviour, new card types, new
sections, and automations, scripts, helpers and scenes behind a card. Three
things still hold, because brAIn already enforces them and MORPH should not
route around them:

- **Every dashboard or card-code change is a git commit in `/config/morph`.**
  Undo is `git revert` of that commit, and it is offered in place in the same
  prompt.
- **A change to the house itself (automations, entities, helpers) says what it
  will do first.** It reuses brAIn's plan → do → undo path (`fixer.PLAN_SYSTEM`,
  `panel/unfix.py`), shown inside the same prompt as "brAIn will: … **Do it**".
  **(proposed — the owner's call; see §10)**
- **`protected_entities` still applies.** It is enforced at the MCP chokepoint
  and by `scripts/brain-protect-hook.py`, and nothing in MORPH bypasses either.

For brAIn to edit MORPH well, MORPH must ship **its own instructions for
Claude**: `/config/morph/AGENTS.md`. It describes the dashboard schema, the card
SDK, the rules in §1, and how to test a change (render, overlap check). It is
the MORPH equivalent of this repo's CLAUDE.md. **(proposed)**

### 7.5 Live reload and progress **(proposed)**
- MORPH watches `/config/morph/` and reloads the view when a commit lands, so
  the change appears without a refresh.
- brAIn's listener writes a result only at the end. For live steps, add an
  optional `task_results/<id>.progress.jsonl` that the listener appends to;
  until then, MORPH shows its own two local steps and then waits.

---

## 8. Architecture **(proposed)**

**Recommendation: a new add-on in this repo, `morph/`, that installs a
`morph` integration. The integration registers a custom panel in the
sidebar.** The panel runs inside Home Assistant's own frontend, so it gets the
live `hass` object, the websocket, and Lovelace's card helpers. That is what
"host any Lovelace card" needs: an ingress iframe has none of those. It follows
the house pattern: brAIn, BRight and BRUH Print all install their integration
from the add-on, and BRUH Print already ships a Lovelace card.

- **Frontend:** one ES module, `morph-panel.js`, with the layout engine, the
  springs and the `morph-*` cards. Each card is also a standard Lovelace custom
  card, so a MORPH card works on any dashboard.
- **Hosting Lovelace cards:** `window.loadCardHelpers().createCardElement(config)`,
  with `hass` passed down on every update.
- **Config:** `/config/morph/dashboard.yaml`, as a git repo (§2), written by
  Edit mode and by brAIn.
- **brAIn bridge:** the task folder (§7.3) for tell; the brAIn integration's
  entities and services for findings, story and predictions; a capability
  check like BRight's, so MORPH degrades to a plain, good dashboard when brAIn
  is not installed.
- **Alternative:** ship `custom:morph-view` as a Lovelace custom view type
  inside an ordinary dashboard. It is simpler to install and stores config in
  Lovelace's storage. The cost: no git history for brAIn's edits, and HA's own
  edit mode competes with MORPH's.

---

## 9. Phases and acceptance

| Phase | Ships | Done when |
|---|---|---|
| 0 | Add-on + integration + empty panel in the sidebar; config loader; layout engine ported with springs | The §5 tests pass on a fixture house at 1440 px and 400 px |
| 1 | Cards for light, light group, fan, cover, lock, switch, climate, sensor, media, camera, binary_sensor list, person, weather; tap/slide/hold; tap outside folds | Live `hass` on a real install; one control in one place, checked card by card against §1 |
| 2 | History, both layers, from recorder/logbook/statistics; scrub and drill; overlaid readings | Each row of the §4 table backed by a real query |
| 3 | Edit: drag sections (across floors), section editor, card editor, add card (entity or any Lovelace YAML), YAML view; git-backed config | A pasted Mushroom card renders inside a section; Undo reverts a commit |
| 4 | Tell brAIn (§7) via the task folder; fast path; AGENTS.md; live reload | "Add a Pets section with Cece's feeder" produces a commit, reloads and Undo works; a protected entity is refused |
| 5 | Notes in place, story, Coming up predictions, Ask the house | Each surface reads a real brAIn producer named in §6 |
| 6 | Phone polish, reduced motion, keyboard and screen-reader paths | `brAIn`'s Screens devloop stream run against MORPH comes back clean |

---

## 10. Open questions for the owner

1. **Add-on + custom panel, or a Lovelace custom view?** §8 recommends the panel.
2. **House changes from tell:** apply at once with Undo, or plan-first like the
   rest of brAIn (§7.4)? The doc assumes plan-first for the house, and at-once
   for the dashboard and card code.
3. **Predictive ordering:** should floors reorder by time of day (Upstairs first
   at bedtime)? It costs muscle memory, so the doc leaves it out unless you
   want it as an option.
4. **Name and slug:** `morph`, domain `morph`? The canvas still says "BRUH
   house" in places, and the product name is MORPH UI.

## What the prototype invents
Every state, history value and brAIn sentence in it. These are also invented:
zone names, the kids' room modes (Awake/Nap/Sleep), bin timing, the Telluride
values, what is playing, and the four notes. Ask only answers its three
suggestions plus anything about warmth, movies, locks or bedtime. Tell's fast
path is real (it edits the prototype's config); the brAIn path stops at the
hand-off and shows the task it would send.
