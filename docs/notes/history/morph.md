# Morph specifics: history moved out of docs/notes/morph.md

What each rule in `docs/notes/morph.md` cost to learn: the reports and walkthroughs that showed the failure, the owner's words, the first attempts that were wrong, the old rail, and pointers to tests and CI jobs. None of it is needed to follow the rules; it is here for the next person who wonders why a rule exists. Pointers to tests under `tests/` name files that were removed in November 2026 with the old suite, and the CI `layout`, `morph` and `morph-real-ha` jobs that once ran the measure scripts and the real-HA check are gone with it; the rules they enforced still hold. Each entry is the text as it stood in the note, cut out of the bullet named in its heading.

## 5.3.0 shipped one house's design as Morph's own, and retired what that house had switched off

- The owner ran copies of twelve modules that were paused by every release, so what ships was never what was tested.
- `icon` was being dropped while the house thought its rooms had icons (why `store.normalize` has to keep any new key).

## Morph is part of brAIn since 4.0, and the halves kept their jobs

- Its state is `/data/morph` (the retired add-on's `/data` is not reachable, so its settings and scorecard start again).
- `WRITE_KINDS` in `websocket.py` and the `kind ==` branches in `morphd.handle` were held equal by `tests/test_morph_addon.py`.
- Morph's Settings page is gone: ⚙ › Dashboard draws the service's mirror.
- **The name Morph says is the switch's, on both halves** (`tests/test_morph_case_parity.py`, `tests/test_personality_page_words.py`): the panel's `who()` fallback to `morph/personality` could never be reached, and would have said the stored name with the switch off, so it went with the `loadPersona` that fed it (the command stays, for an older copy a house may still run; only `morph-fixture.mjs`'s `morph/load`, which sent no `features` where `websocket._load` always does, ever reached it, and it now sends them). The service's `brain.who()` read `personality.json` alone and said "Vesper" while every other surface said "brAIn".

## Every change is one commit, and nothing else is history.

- `head()` and `log()` answered 12 and 7 characters, so the commit a Tell reported was not one the History page could name.

## Ids survive a round trip

- A fresh id on every save made every save read as a new dashboard (and `f_f_…` was the first cut).

## Every task Morph writes says it came from Morph

- brAIn's pill for Morph's conversations was #427.

## A person's words reach brAIn whole, from the first character

- Words over the bound used to keep their END behind "(the start of this message was cut to fit)", so a long request reached brAIn — and brAIn's chat — missing its opening, cut mid-word (#428).

## What brAIn is doing is read off brAIn's own hook

- A box rebuilt every second replayed its blur-in for as long as brAIn worked, which is why only the newest step has `rise`.

## A Tell is read back, never taken at its word

- Reported as *"it says it's making changes to the dashboard, but none of them are applied"*: a finished Tell ended on brAIn's own summary whether or not anything under /config/morph had moved, and the mirror waited for the watcher's next pass.
- A state file reading "done" was the panel's (and the tests') signal that the lesson and outcome have landed.
- "dashboard.yaml" used to send Undo to brAIn to put back a house change nobody made, before `_morph_file`.

## A dashboard change is a Tell wherever it is typed, and brAIn decides which it is

- Outside Edit the Ask line used to go to the house's conversation agent, which cannot write /config/morph and answered that it was making the change.
- The other half of the original report was brAIn's own: `brain-protect-hook.py` refused any YAML naming a protected entity, a dashboard names the locks, so `is_morph_dashboard` exempts that one file, on real paths.

## Ask is the one door to a Tell outside Edit, and the mark is only the brand.

- The hover mark, the opened card's mark and the section title's mark were three second doors beside Ask, and the vision folds them into it (§13.3); `test_morph_house_reports_two.TestARoomIsToldAboutThroughAsk` held that none comes back.
- The squares and tiles were exempted by `test_no_asset_is_the_gable_alone` and held by `test_morph_squares_are_its_own_mark_and_no_roof`.

## Ask stacks: every question keeps running and its answer stays

- The owner: *"make sure that when asking multiple commands everything keeps running and the answers stack up"*. Ask had ONE slot (`s.ask`), one conversation (`s.converse`) and one poll timer: a second question overwrote the slot and cleared the first poll, so the first answer never appeared, although the service went on running it.
- **A Tell replaced while it runs is parked, not lost**: the activity strip used to forget it the moment the service stopped listing it as running.
- `measure-morph`'s owner block asks two questions back to back (the fixture's `__convEcho` answers each by name and a "slow" one later).

## Morph is brAIn's face, and the page is ONE salience list drawn five ways

- As first written the inputs were deviation off brAIn's `feed.json` normals and door habits, urgency, progress, habit, recency and viewer, with Now ≥.75 leaving at .60, Lead ≥.45/.35, Shown ≥.20; the verdict's coloured first clause, the Now layer (≤3, ≤2 under 480px, deduped by entity so a lock carried by two rooms is lifted once, `twin`), the room order and fold, the room line and the floors' summaries all read that one result. Three rules kept it calm. 5.3.0 removed habits, the viewer, every reorder and room folding.
- **It is pure** — so `tests/test_morph_vision.py` drove it under node.
- **At night Now holds only what the night floors lift**: the vision's test is *armed at 11:30 PM with one unlocked lock shows exactly one card*, which `measure-morph`'s `night` asserted.

## brAIn's cases are drawn where their subject is, and a reply is read, not pressed

- **A card reads as brAIn's Needs you reads it** (#452: *"wherever I'm looking at things … it feels like the same surface"*): it said *To Do* where brAIn says *Add to To Do*, wore no chip, dropped the detail and kept ids where brAIn shows names. `tests/test_morph_case_parity.py` built a house's cases with brAIn's own `answers` and `morph_bridge.case_row` and drew them with `caseFace` under node.
- The bullet also said Morph's words name the assistant by the household's name (`MorphPanel.who()`, `brain.who()` in the service, off `/config/.brain/personality.json`), never a second name beside brAIn's. That was superseded by *The name Morph says is the switch's, on both halves*, which is where the rule now lives.

## Two learning loops, the way brAIn has them.

- A `read_only` task is denied Read and was being told to read AGENTS.md.
- `learning.send_code_reports()` came with the self-learning plan (section 0, no human in the loop).
- The fingerprint was once written up front, so a failed pass marked the evidence read and every later pass skipped.
- `ack.json` was written back so Morph's Settings could say when a report was picked up; that page is gone.

## A lesson is never cut

- A flat `[:300]` and later a cap by writer cut lines mid-sentence on each pass, so the rules brAIn read back were half rules.

## An answer to a proposal is kept against the card or section it was about

- #825, #851: the declined list stopped only a proposal's own words, so a removal or reorder came back reworded, and a card whose entity was unavailable came back after the owner said No or undid the removal.
- **A Restore counts as an undo, a kept card keeps its section, and the keeps are on screen**: `record_reverted` read only `git revert`, so a card the owner got back with History › Restore was proposed again.

## "What do you want to fix?" is Ask, and Morph's own reports are still a ledger

- The Settings box went with the vision. A Tell's issue sent by a press was dressed as "Morph reported this N times" and could not be taken back.

## Morph's service faults are Morph's own to report

- The ledger held what the PANEL reported (a card that threw, an overlap at rest) and the service's four `except` blocks logged and moved on, so a request loop failing on every poll was in the add-on log and nowhere brAIn's `morph` stream could read. `tests/test_morph_service_faults.py` raised inside a service module and grepped that every handler in `morphd.py` files what it catches.

## The screenshot preview unfolds every room

- A picture of the dashboard left out cards (the assistant's own overview card among them).

## Morph can change itself, one module at a time

- The complaint was brAIn answering that Morph's header "is Morph's own code, and I can only change the dashboard's files". The whole point is that nothing about Morph is out of reach.
- **So does an update that moves any OTHER module**: pausing only on its own file let a copied morph-panel.js run beside a new engine. A record from before `others` existed is filled in on the next commit.
- **A copy that reads the retired `personality.js`, and that file itself, are paused whatever the record says**: a house that customised Morph before the personality was brAIn's kept reading the old file through an accepted copy of morph-panel.js, whatever Morph shipped (#391); Settings › Personality said in one sentence to remove it.
- **Making a paused copy again is a press with a box, and a three-way merge.** Its first tell went out with only a header toast and an unchanged note, which read as "nothing happens". 0.5.2's in-place "Handing it to brAIn…" was redrawn back to Make it again at once.
- **Then it asks.** `devloop` no longer fences a detail that carries its own fence.

## A per-house addition to a built-in card is an option, not a copy of Morph's code

- A house got script buttons on its thermostats and a performance chart folded under them by brAIn copying `cards.js` and `morph-panel.js` into `/config/morph/frontend` and patching them.
- The actions took the place of the ruler's end labels, with padding cancelled by negative margins, because same-row tiles must stay one height and a button still needs its 40px target; the layout batch of 2026-11-07 moved them to a 40px row of their own (see *Every `.wd` rule keeps the 40px floor*).
- `tests/test_morph_climate_actions.py`, `measure-morph`'s detail block.

## A card file that changes is defined once per PAGE, and the page's record lives on the window

- The record of what was loaded was module-level, and an update serves Morph's own modules from a new URL, which runs them again without a reload: the fresh, empty record read a card file running again as its first run, and four cards' "name already used" were filed as four faults.
- `measure-morph` serves a card file twice and fails on a report; `tests/test_morph_card_loader.py`.
- **A card file gets a second fetch, and a copy's card type is Morph's**: `tests/test_morph_house_reports_two.py`.

## The frontend is plain ES modules with no build

- A chart that blanked on a minute rollover changed a card's height mid-motion and showed as an overlap.
- Importing the style module as `CSS` shadowed the global `CSS.escape`.

## Opening Morph paints at once, and a reload is something Morph says

- boot.js awaited the whole panel, so the page was blank (white in a light theme) for seven modules' worth of round trips, each a `no-cache` revalidation discovered one import level at a time.
- An unstamped boot.js was also what a test loaded.
- `measure-morph` delays every module 1.5s and fails on no shell, no outline, a white outline, an outline left over the dashboard, a module outside `s/<stamp>/`, or any of the three bar states missing. It failed both shell checks with boot.js awaiting the panel again.

## The page updates in place

- The board's removal pass once removed every `[data-key]` it had not just drawn, which took the To Do rows and a range input's key with it.

## A resting spring outlives its element

- Leaving Edit left each "Add section" ghost's spring where the ghost stood and the audit reported the room that moved there as overlapping it. `tests/test_morph_house_reports.py` drove `Engine.overlaps` under node.

## A cached layout is checked against what was drawn

- A section that was beside another could end up alone in its band at 80% of the floor while the section below spanned it (reproduced by making the cached width one column short; the natural trigger is a card that loads later). Walkthrough of 2026-11-13 (#886 #887 #888 #889).

## The prototype (`docs/design/morph-ui.html`) is the reference for how Morph looks, and `measure-morph`'s `design()` holds the parts that drifted once.

- `measure-morph`'s `comingUp` drives the drag, a tap, a swipe, Now and the arrow keys.

## The reports of 2026-11-04, one class each

- #662 #664 #676 #677 #678 #679 #682 #683; `tests/test_morph_house_reports_four.py`, the "reports" block of `measure-morph`. Its rules now live in the note as separate bullets.
- **There is no Then mode** (the owner: *"I want to get rid of Then mode. That is completely useless."*): `then.js` and everything that drew the house in the past are gone.
- **A region with nothing in it is hidden, not drawn empty**: an empty section still took a 30px flex gap.

## The room rail opens with a slight pull left, and says so

- `frontend/rail.js`, deleted in 5.3.0 for `scrub.js`. The owner: *"before you scroll with the Morph scroll rail you should have to open it by very slightly dragging left first; add responsive tips that make it clear"*. A rail that took any touch on the right edge and jumped rooms at once turned a scroll that began at the edge into a jump.
- On a coarse pointer (`any-pointer: coarse`) the rail was a 28px column of the page beside `.wrap`, inside `.scroll` (then a flex row) and `position: sticky`, so at rest it was never over the content (rule 1); elsewhere it was not drawn. It was `touch-action: pan-y`: more than `PASS_PX` (8) of vertical movement before a pull was the browser's scroll, untouched. The tips were vertical words INSIDE the rail, above the finger (a finger covers what is under it): resting `REST_MS` (220) said *Pull left to open the rooms*, a pull said *Keep pulling left*, a tap or a short pull left *Pull left to open the rooms* with *A little further left, then slide up or down to a room* for `HINT_MS` (2.2s). The pull left is an opening gesture, not a level change (rule 2's slide), and morph-ui.md §1 and AGENTS.md said so.

## The rail is the notched rail, one gesture, and the room meets the thumb

- #541; the owner, iterating on a phone on the house's own copy, latest wins: *"keep the scroll rail look like we had before with the vertical rectangles. I don't need the card labels there because you're highlighting the active card"*, *"go back to the swipe left to open and then just scrolling and releasing normally. Keep the highlighting mechanism"*, *"the card isn't where my thumb is, it's staying at the top of the window. Can you make my thumb and the card line up?"*.
- In rail.js: a `selection` tick at a third and two thirds of `OPEN_PX` (14) and a `heavy` tap when it opened; open, `OPEN_W` (44px) wide with no overshoot, wave or lean, no notch scaling out, and no room name by the finger; a `selection` tick per room, `medium` on a new floor (`railJumps` counted them); a non-passive `touchmove` stopped the page scrolling under the scrub; lifting closed it with a `light` tap. The rooms left out `__` bands and rooms not drawn or under 24px.
- **The rooms and their order come from the engine's model**: re-reading `getBoundingClientRect` on every repaint while the layout springs moved was the floor labels jumping under the thumb.
- **The highlight has to win over three things the house found**: the other rooms dimmed to .55 under `.morph.railing`, the ring an inset 1.5px line plus an inset glow in `--rc`, the title tinted. On release the others returned at once (the dim had a transition in, none out) and the ring faded after `FADE_MS` (900).
- **The glide**: K 230 on the real frame time, capped at 120ms and split into 8ms steps; the engine's K 110 with `dt` clamped to 32ms turned into slow motion when frames dropped.
- **The room's title meets the finger**: held no closer than 12px to the top and 160px to the bottom of the window.
- `measure-morph`'s owner block drove it with CDP touch events at 390px: notches that are vertical rectangles and no words at rest, a vertical swipe on the rail scrolls the page and opens nothing, a rest and a tap show their words, a 10px pull widens the rail with two ticks and does not open, 16px opens it wider with a heavy tap and the floor names beside it, and sliding to rooms in the middle of the screen rings one, dims the rest below .6, keeps its title within 15px of the finger and leaves the notches and floor names exactly where they were; lifting closes it, clears the dimming, gives a light tap and the ring is gone 1.5s later. At 1200px on a fine pointer the rail is not drawn.

## A switch can ride in its room's title row

- The owner asked for a pause toggle to be named by its entity and to go "in the header of the card as a button". When it was written such a card was also kept out of Now and was not the "something on" that kept a room unfolded (both systems went in 5.3.0).
- `tests/test_morph_header_switch.py`; `measure-morph`'s owner block adds one to the Yard and drives it.
- **Edit offers it** (a #833 repeat: the option existed only for a Tell, so a house that never asked never found it).

## `tests/manual/measure-morph.mjs`

- At 1440 and 400: no section or tile overlaps at rest or in any 30ms sample while 12 kinds open and fold, same-row tiles are one height, tap toggles, slide sets ~70%, the garage needs two taps, Edit → hold → Tell → Keep/Undo works, a case's reply becomes a turn, a reply that ends a case and asks for a page change runs that Tell and says brAIn's last word, a quiet room folds and opens on its name, and armed-night with the front door unlocked shows exactly that door (the tour turns `fold_rooms` off so every kind of card is on the page). It ran in CI's `layout` job when `morph/` changed.
- **`measure-morph-cards`, `measure-brain-layer` and `measure-morph-features`** ran in CI's morph group beside `measure-morph`. `measure-brain-layer` counted the card's clicks for *A press is never a Tell's way in to a card*.

## The design rules a grep can check are checked on every change

- `tests/test_morph_design_rules.py`. The shipped frontend had drifted from rule 13 unseen: a light's name, a white swatch, a meter's day bars and a camera's name carried `title=` hover text. The test failed on any `title=` but an `<iframe>`'s accessible name, on rule 1's overlay constructs, on Morph's bar carrying a brand, ☰, ⚙ or Feed inside brAIn's shell, and on the design's numbers. `measure-morph`'s design block failed on any rendered element with a `title` outside a hosted Lovelace card. The file's docstring listed which rules are judgement and left to review.

## A scene button on a room's title row is a 40px target, like every `.wd`

- `.secscenes .wd` had its own `min-height:32px`, which measured 30px on a phone; `test_morph_design_rules`. A per-element override of the shared `.wd` floor is how a control slips under it.

## Every `.wd` rule keeps the 40px floor, a routine chip is a chip, and a row is one height

- The layout batch of 2026-11-07; the "layout batch" block of `measure-morph`, `batch: true` in `morph-fixture.mjs`. The scene buttons "came back" at 30px because a thermostat's routines (`options.actions`) had their own `.cl-acts .wd{min-height:0;margin:-12px 0}`, a second per-element override of the floor beside the one fixed in `.secscenes`; the negative margins also put the chips over the ruler and the tile's edge. `test_no_wd_rule_of_any_kind_sets_a_height_under_the_floor` held every `.wd` rule to the floor.

## Morph's own targets are 40px; a built card's are its own, held by the contract

- #965. A blanket 40px floor handed to a built or hosted card's shadow roots (as `FIELD_FLOOR` is for fields) was tried and removed: it grew a dense card's hour grid from 292 to 502px and overlapped its icon columns.

## The field floor reaches a card handed over in a wrapper, every word button is 40px wide, and the Lovelace cards' accents follow the theme

- #820 #821 #861, the walkthrough of 2026-11-12. `floorFields` returned at once for an element with no shadow root of its own, so a card the devloop harness wraps in a `display: contents` box kept a 15px talk box. An alarm's Off was 24px wide. The `HA_THEME` accents were fixed mid-tones at 2.6–3.7:1 on white and on near-black.

## Morph's small controls follow four rules, each learned from a house report (2026-11-09).

- Acting on every `ll-rebuild` announcement re-made every card on every render, which was the flashing. A floor given once missed Home Assistant's fields that upgrade later. Opacity at a third took every small label in a dimmed room to 1.5:1. The measure was `measure-morph.mjs`'s `batch-ui` block.

## The walkthrough of 2026-11-13: a status is one line chosen by width, a section alone in its band fills it, and the secondary label colour is 4.5:1 on an opened card

- #886 #887 #888 #889. The bullet's rules now live in the note as separate bullets: *A strip's status is ONE line*, *A group says it ONE way*, *A cached layout is checked against what was drawn*, *`--quiet` is the opened card's label colour in all three themes* and *A list says its state once and an empty one is not drawn*.
- **A strip's status is ONE line**: a name of two lines over a status of two ran over its edge and its texture ("Unavailable · last seen Tue 3:58 AM" in a one-column tile, #764).
- **A group says it ONE way** (#887 #967): "mixed" and a bare "1%" beside a count were three formats for one thing.
- **`--quiet` is the opened card's label colour in all three themes**: it was 4.49:1 on dark and 4.1:1 on medium on the opened card's own surface.

## The walkthrough of 2026-11-14: identical members fold, Coming up's two marks are 40px, and a house card's faults go to the contract

- 5.3.10 reports. The bullet's rules now live in the note under *A group says it ONE way*, *Morph's own targets are 40px* and *A list says its state once*.
- **An opened group whose members all say the same thing folds them**: eight rows of "60% · Soft" pushed the All slider and the colour to the bottom of a 640px card.
- **Coming up's zoom and fold are 40px boxes on a coarse pointer**: centred where the 25×22 and 32×32 marks were.
- **The irrigation panel ("Sequence · Empty", a hose valve saying Off twice), Tune, Look again, the People rows and the Now card's restart headline were the house's own cards** (`/config/morph/cards`), not Morph's code: `defaults/AGENTS.md` already asked for a state said once and an empty part left out, and then also asked for a setting labelled as one and left a pending restart to Morph's own bar. The one shipped path to an empty cell, an `options.details` reading whose state is "", threw in `detailValue`.

## A tile says only what is so now: a dead entity's figure is greyed with when it was last seen, a chart of rooms reads a room from its history when it has no statistics, and a moisture probe that fell straight to 0 is a probe to check

- 2026-11-09, #764 #757 #766 #787; `tests/test_morph_tiles_gone.py`, the "tiles" block of `measure-morph`, `tiles: true` in `morph-fixture.mjs`. The three cards the house reported were its own card code in `/config/morph/cards`.
- **Unavailable or unknown**: the climate card drew a freezer's last 52°, its target and −/+ as live. A readings label printed `NaN°` for one.
- **No lines**: the readings card read statistics alone, so such a room had a label and no line, and a card of only such rooms drew the target band over an empty plot. The most likely cause in the house's own chart was the same shape question (reading `state`/`last_changed` from compressed rows gives NaN times and no line while the values still scale the axis), which AGENTS.md now spells out.
- **Dead probe**: 35% read as 35 °C was rose.

## A sentence about a door is checked against the door as it is now, and only for what it asserts about now; an outdoor reading that disagrees with the weather and has not moved says so; the Minecraft server reads its status on whichever card it gets

- 2026-11-07, #719 #734 #688 #686; `tests/test_morph_claims_and_age.py`, the #719 block of `measure-morph`. brAIn's cached sentence said a lock was unlocked beside a locked lock and told the owner to close a closed garage. A first attempt read the bare word "lock" as an unlocked claim and hid "the front door lock battery is low".
- For #688, the first attempt read `last_reported` and never ran.

## A dashboard is HA's, and its YAML is Morph's copy kept in step

- `tests/test_morph_lovelace_core.py` held the two halves' hashes equal.

## Rule 1 does not apply to the layer, and the exemption is bounded

- `test_morph_design_rules.TestRule1NothingFloats` failed on a fifth floating thing.
- #840: `morph-view-layer.js`'s room rail was a fixed, full-height box on `document.body`, and on an iPhone a vertical swipe that started on it went to the document, which in the Home Assistant app is not what scrolls the dashboard, so the page stuck. After a landing the rail's glide (`rail.js` `go`) pulled the page back to the room for up to 1.5s.

## morph-dom never descends into a custom element, so `<ha-card>` is made once

- The first cut drew `<ha-card>` as part of the HTML it redrew, and every redraw after the first left the card's insides as they were: hold "opened" the card in state and nothing changed on screen.

## A converted dashboard is HA's own sections view, and Morph's extras are switches on it (5.1)

- 5.0 converted every floor to `custom:morph-view`, and a house found the dashboard could not be edited (checked in HA's source).
- In 5.1 the switches were `morph: {rail, order, fold}`, drawn through CSS `order` and attributes; a converted view started `{rail: true, order: false, fold: false}`. 5.3.0 took order and fold away.
- Reading only `path` made the switches do nothing on 2025.1: the real-HA check on 2025.1 is what found it.

## Size is Home Assistant's, and a Morph card fills it

- A card answered `rows: 'auto'` and drew Morph's fixed faces (a strip is 56px) inside `ha-card{height:100%}`, so a light set to two rows was half empty and a sensor set to one row was cut off. A grid wrapper of no height (the `div` inside `ha-card`) was the one link that kept the face at its own size.

## Opening a card at a fixed size grows its cell

- Measuring a card that is the cell's height fed the cell its own growth.

## And Morph is checked in a REAL Home Assistant

- It ran as CI's `morph-real-ha` on 2025.1.4 and 2026.11.0.
