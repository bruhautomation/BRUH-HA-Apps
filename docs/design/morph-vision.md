> **Before writing, read AGENTS.md, LEARNED.md and dashboard.yaml in this folder, and use brAIn's tools to sample real data if needed.** Every number below that describes the house (what is normal, who does what when, how fast a room cools) is an example. The real figures come from `what_is_normal`, `habits`, `house_rhythm`, `door_habits`, `room_physics` and `appliance_status`, and nothing in this document may be hard-coded where one of those can answer.

# Morph — the design vision

*A home dashboard that shows what matters, when it matters, for the people looking at it.*

This is the one page we build. It is written against Morph as it ships today (the floors → rooms → tiles structure, the spring masonry engine at K = 150 and ζ = 0.82, the 56 px strips, the Coming up strip with its fixed reading point) and against the household's thirteen rules, which it does not bend. Where the page's own code has to change, the module is named.

---

## 1. The idea

Morph is the house's attention, not its inventory. Every other dashboard is a map of devices with the same weight at 3 AM as at 6 PM; Morph gives space in proportion to **distance from normal** — how far a thing is, right now, from what this house usually is at this hour, as brAIn has measured it — and to **how likely you are to reach for it next**. A thing earns its place on the page by being unusual, in progress, or about to be wanted; everything else is the floor plan, folded to a line and never more than two taps away. The page is still one design, the same lights, scenes and rooms in the same grammar, but it breathes with the day: wide and busy at dinner, a single rose sentence at 3 AM. The one principle is this: **the page is laid out by the house's own sense of normal, and it can always say why.**

---

## 2. The anatomy of the page

Top to bottom, every region, and what each is for. The regions are not separate features; they are five renderings of one ranked list, the *salience list* (§4), which is computed once and drawn five ways.

### 2.1 The verdict

The first 120 px of the page answer the two-second question. It is the greeting and the story sentence as they are today (`h1.hello` in Bricolage Grotesque at `clamp(36px, 5vw, 58px)`, the story under it at `clamp(20px, 2.3vw, 27px)`, weight 300), with one change that is the whole point: **the story's first clause is the top of the salience list, and it is set in that item's colour.**

- Nothing salient: *Good evening.* then *Everything is at rest.* in `--indigo`.
- One thing: *Good evening.* then **The front door is unlocked.** in `--rose`, then the rest of the sentence in `--muted`: *Kaz and Lev are asleep, the dryer finishes in 12 minutes.*
- Several things: the first in its colour, the rest as plain clauses, never more than three, ordered by the list.

The colour is the verdict and the words are the reason. Each clause is underlined 1 px in its colour at 50% and is a jump: tap it and the page scrolls so the thing it names sits under the sentence, already unfolded. The story is rewritten by `storyFacts` from the same list the Now layer is drawn from, so the sentence and the cards can never disagree about what matters.

### 2.2 Ask

One quiet line under the story, as today: a 1 px bottom rule in `--line`, 17 px Manrope, the placeholder *Ask or tell the house…*. It never moves and it is never a box with a button. What is new is what an answer does to the page (§7.3): it unfolds in place under the line in Bricolage 19 px weight 300, and if the answer is *about* something on the page, the page reshapes to show it.

### 2.3 Coming up — and Came up

The strip stays as built (`upcoming.js`: a fixed reading point a little left of centre, the day sliding behind it, dots that swell as they near the line, solid rings for the scheduled and dashed for the usual). Two changes make it a time dimension rather than a schedule:

1. It runs **24 hours back** as well as 24 ahead (`PAST_MIN` becomes 1440). Behind the line the dots are what happened: doors, scenes, people arriving, appliances finishing, read off the recorder and the logbook.
2. Sliding it into the past puts the whole page into **then** (§7.2). The strip is the only scrubber. There is no history page.

### 2.4 The Now layer

Under the strip, above the scenes line, a band holding **at most three** cards, lifted out of their rooms because the salience list put them there. The band has no heading and no border; it is recognisable only because its cards are the page's largest, sit on `--surface` at full opacity, and each carries a *because* line (§11). Examples at this house: the unlocked door at 11:30 PM, the dryer that finished, the water meter at 638 gal against a usual 180, the printer while it runs (if someone said so).

A lifted card is **moved, not copied** (rule 4). Its room keeps a one-word trace in its header line, in the card's colour — *Front door, above* — that is a jump, not a control. When the card's salience falls it goes home: the room unfolds just enough to receive it, it travels down, the trace disappears.

Empty, the band has zero height. No *Nothing to show*. The page simply starts with the scenes line, which is itself the quiet signal.

### 2.5 The scenes line

House-wide scenes as words, in Bricolage 19 px, the active one underlined in `--violet`, exactly as today. It is the one line that never moves, folds or changes order, because it is the thing a hand reaches for without looking.

### 2.6 The room line

A single line of words that is the whole house as an index, and the answer to rule 10 on a phone: the floor name in Bricolage 22 px, then that floor's rooms in Manrope 13 px `--muted`, separated by 14 px, nothing boxed. Tap a room word and the page scrolls that room to the top and unfolds it. On a phone the line is **sticky under the header** and shows the floor the viewport is in; swipe it sideways and it shows the next floor. On a laptop or wall tablet it is the floor heading itself, which already carries the floor's one-line summary (`.facts`), so the rooms' words follow the summary on the same line and nothing is added.

A room word takes its room's state: `--quiet` when folded and idle, `--text` when active, dimmed to 45% when asleep, and a 4 px dot before it in `--rose` when the room needs attention. The room line is the floor plan at one glance.

### 2.7 Floors and rooms

Overview, Downstairs, Upstairs, Outside, Media, as today, with rooms packed by the engine. The difference is that **the order of rooms within a floor and the fold state of each room come from the salience list**, within the stability rules of §4.4. A room is one of five states (§6). Fans and blinds sit after lights under the *Comfort* label; scenes sit above lights as words. None of that changes.

### 2.8 How the five form one system

One list, computed every ten seconds or on a salient event, drawn five ways:

| Rendering | Takes from the list | Cost of being wrong |
|---|---|---|
| The verdict (story) | the top three, as clauses, the first in colour | a sentence |
| The Now layer | items above 0.75, at most three | a card out of place |
| Room order and fold | each room's own score (the max of its items) | a room folded that someone wanted |
| The room line | each room's state | a dot |
| Floor summaries | each floor's top item, as the floor's one line | a phrase |

The story is the list as words, the Now layer is the list as controls, the rooms are the list as a map. A reader who only glances reads the story; a hand reads Now; a person looking for something reads the map. Nothing is drawn twice.

---

## 3. A day in the life

Every scene below is the kitchen wall tablet unless it says otherwise, at 1280 × 800, five columns.

### 6:45 AM — the kids wake

The house's measured weekday wake is 6:52 (`house_rhythm`). At 6:40 the page is still in its night form (§10.3): the time in Bricolage 96 px at the top right, the story *Everything is at rest.* in indigo, the rooms folded to lines at 30% opacity. At 6:44 the hall motion sensor fires upstairs and the page wakes over 300 ms. The verdict reads *Good morning.* **Lev is up.** *Kaz is still asleep; it is 48° outside, the kitchen is 66°.* The Now layer holds two cards: **Kids' bathroom** lights (because `habits` says Cailin turns them on at 6:48 ± 6 min on school days) and the **Downstairs** scene word *Morning*, lifted from the scenes line into a card with its because line *you usually do this now*. Upstairs is the first floor on the page because that is where the salience is; Kaz's room is folded and dimmed with its fan strip as its one visible control, because it is asleep. The kitchen is unfolded and leads Downstairs: scenes, lights, then the coffee maker's switch, which has a habit at 6:55.

### 8:30 AM — school run, trash day

The story: **Trash goes out today.** *Ben and Lev have left; Cailin and Kaz are home. The garage is open.* The first clause is amber because it is a calendar fact with a deadline, not a fault. The Now layer: the **garage door** (open, amber, *usually closed by 8:40*), the **front door lock** card showing *Unlocked 7 min ago, Ben*, and the trash calendar item from Coming up, drawn as a card for the morning only. Outside has risen to second floor on the page. Upstairs has folded entirely, every room a line, because nothing up there is off its normal and nobody is there. At 8:41 the garage closes; its card's because line changes to *closed, back to normal* and it sinks home over the next quiet window.

### 2:00 PM — an emptyish house, printer running, irrigation

Cailin is home working. The story: **The printer is 62% through a 3 h 10 m print.** *Zone 3 is watering until 2:20. Upstairs is 74°, a degree warm for a Tuesday.* The Now layer: the **3D printer** card (progress in warm, the nozzle temperature and bed temperature as two small tabular numbers, a because line *in progress*), and **Irrigation** with its sky-coloured flow bar running right to left while water moves. Upstairs' heading carries *74° · a degree warm* in amber, from `what_is_normal`: the usual is 72.4 ± 0.8 at 2 PM on a Tuesday. Nobody is promoted for that; a degree is under the threshold. The rooms are all folded; the house is a quiet index. On Cailin's phone the same page leads with her office's lights and the thermostat, because her habits at 2 PM are there, and the printer sits second.

### 6:00 PM — dinner, everyone home

The busiest page of the day, and still calm. Story: *Good evening.* **Everyone is home.** *Dinner time is on downstairs; the dishwasher is running; sunset is at 6:41.* Nothing is rose, nothing is amber, so the verdict is set in `--indigo`… no: it is `--text`, because *at rest* is indigo and *busy and fine* is simply ink. The Now layer holds one card: the **Media** card for the kitchen speaker (playing, violet), because it is in progress. Downstairs is wide open: Kitchen, Dining, Living Room all unfolded, scenes above lights, lights at their colour-track fills, fans spinning at speed under Comfort. The scenes line has *Dinner time* underlined. Upstairs is folded except the kids' bathroom, which has a bath habit at 6:30 and a *usually about now* dashed dot on the strip. Outside shows the sunset dot swelling toward the line.

### 9:00 PM — kids asleep, TV on

Story: **Kaz and Lev are asleep.** *The living room TV is on; the back door is open.* The first clause is indigo. The second is plain. The third is plain too, and that is the measurement at work: `door_habits` says the back door is open at 9 PM on 70% of evenings (the dog), so an open door is not news; it will be at 10:30. The Now layer: the **Living room TV** (violet, what is playing, transport), and **Master bedroom lights**, lifted at 9:35 because Cailin dims them at 9:40 ± 7 min on 23 of the last 28 nights. Its because line: *you usually do this now*. If nobody touches it by 10:05 it sinks, and that habit's weight halves for next time (§4.3). The kids' rooms are asleep (§6.4): dimmed, folded, each showing only its fan strip and sound machine switch. Upstairs' heading reads *2 asleep · 68°*.

### 11:30 PM — the alarm is armed

This is the failure the brief starts from, answered. Arming the alarm sets the house's `armed_night` state; Morph reads *armed, everyone asleep* as night. The page dims to its night form over 2 s. Every floor folds. And the salience list is now computed under the night weights (§4.2), where an unlocked lock scores 1.0 by construction. So the page is: the time, **The front door is unlocked.** in rose at the top, and under it one card — the **Front door** lock, 2 columns wide, indigo surface with a rose left edge, the shackle lifted, *Unlocked since 7:12 PM · Ben* — and a single word on its right, **Lock**, which takes a second tap to confirm (rule 9: the word becomes *Lock?* for 3 s, in rose). Twenty rooms are twenty lines at 30%. There is nothing else on the screen. From across the kitchen the page is dark with one rose line, and that is the whole message.

### 3:00 AM — a door opens

The back door opens while the alarm is armed. `eventbus` admits it as hot. Within 200 ms the page wakes from its night form (no fade: a cut, because this is the one moment speed matters more than grace), the story reads **The back door just opened.** in rose, and the Now layer holds the **Back door** list card (open, rose, *3:02 AM*), the **Alarm** card with its modes as words and *Disarm* needing its second tap, and the nearest **camera** (the patio), live. A rose ripple travels from the door's chip on the Outside floor line up to the Now card in 300 ms, so the eye is led from where it happened to what to do. If the door closes within 30 s and nothing else fires, the story changes to *The back door opened at 3:02 and closed at 3:02.* in amber, stays 10 minutes, then the page returns to night. The event stays on the Came up strip behind the line.

### A guest visit

Ben's mother arrives Saturday for the weekend. Her phone is not a person entity; she is a guest. The guest room, which has been folded for weeks, is occupied (motion), so it unfolds and rises to the top of Upstairs, with its scenes and its two lights. `what_is_normal` has nothing for a guest room's weekend wake, so its because line says *in use* and nothing more. The kitchen tablet shows the page for the family, not for her, and that is deliberate: a wall tablet is the family's and does not learn a visitor. When she asks it *where is the thermostat for this room*, the answer unfolds under Ask: *The guest room is on the upstairs zone; it is 70° and set to 70.* and the climate card lifts into Now for ten minutes with *because you asked*.

### A storm

A severe thunderstorm warning arrives from the weather integration at 4:10 PM. The story: **A severe thunderstorm warning until 7 PM.** in amber. Outside rises to the first floor on the page. The Now layer: **Weather** (the forecast card, the wind figure in tabular Bricolage), the **Garage** and the **Blinds** that are open on the west side, lifted together as one card titled *Open to the weather* with a single word *Close all*. The sump pump's power sensor, which usually reads 0 W at this hour, starts cycling; at the second cycle `what_is_normal` says that is unusual for a Tuesday afternoon and the pump lifts with *running, unusual for 4 PM*. Irrigation's scheduled 5 PM dot on the strip gets a strike-through when the irrigation integration skips it for rain; the because line reads *skipped, rain*.

---

## 4. The morph engine

This is the part an engineer builds first. It lives in a new module, `salience.js`, pure over the inputs it is handed, and the layout engine reads its output. `engine.js` keeps doing what it does; what changes is the order and fold state it is handed.

### 4.1 Inputs, per item

Every card and every room is an *item*. For each item the engine computes six numbers in [0, 1], each from a named source, and a missing source contributes 0 and says so (§4.6).

| Input | Symbol | Source | How it is read |
|---|---|---|---|
| Deviation | `d` | `what_is_normal`, `door_habits` | For a numeric sensor, `z = |value − usual| / spread` for this hour of this weekday; `d = clamp((z − 2) / 4, 0, 1)`, so two spreads is nothing and six is full. For a door, lock, light or switch, `d = 1 − p` where `p` is the share of this hour the entity is usually in its current state. An entity with no measurement has `d = 0`. |
| Urgency | `u` | `findings`, the safety classes | A finding waiting on somebody about this entity: critical 1.0, serious 0.7, warning 0.4, info 0.15. A tripped safety class (smoke, CO, gas, leak) is 1.0 whatever else is true. |
| Progress | `g` | `appliance_status`, the entity's own state | Running 0.5; finished and not yet attended 0.9; idle 0. A vacuum, printer, timer or irrigation zone counts as running from its own state. |
| Habit | `h` | `habits` | The probability that **the viewer** (§4.5) acts on this item in the next 30 minutes, from its measured times on this kind of day. `h = p`, capped at 0.9, so a habit alone never outranks a fault. |
| Recency | `r` | the state's `last_changed` | `r = e^(−Δt / τ)`, τ = 10 min for doors and locks, 20 min for lights, 60 min for appliances, 5 min for media. |
| Viewer | `v` | the device | 1.0 for the device's own person, 0.35 for another person's habit on that device; on a family device, each person's habit is weighted by whether they are home. |

### 4.2 The score

```
core = 1 − (1 − u) · (1 − d) · (1 − 0.8·g) · (1 − 0.7·h·v)
S    = clamp(core + 0.15 · r · (d + u + g > 0), 0, 1)
```

The product form means two weak reasons add up to a moderate one without any single input having to win, and recency only ever **boosts** something that already has a reason; a light that merely changed is not news.

Time of day reweights the inputs. The house has four periods, read from `house_rhythm` and the alarm, never from the clock alone:

| Period | How it is known | Reweighting |
|---|---|---|
| Day | after wake, before settle | none |
| Evening | after settle begins (the kids' rooms asleep) | media `g` × 1.2; kids' rooms' `d` × 1.5 |
| Night | alarm armed, or every tracked person asleep | locks, doors, garage: `d` floors at 1.0 if open or unlocked; every light's `d` × 0.5; `h` × 0.3 |
| Away | nobody home | locks, doors, cameras, leaks: `d` × 1.5; lights and media `h` × 0 |

A room's score is the max of its items' scores, plus 0.1 if it is occupied (motion within 10 min or a person's room at night).

### 4.3 Thresholds, hysteresis and decay

| Band | Enter at | Leave at | What happens |
|---|---|---|---|
| Now | S ≥ 0.75 | S < 0.60 | lifted into the Now layer (at most 3; the fourth waits in its room at the top) |
| Lead | 0.45 ≤ S < 0.75 | S < 0.35 | the room unfolds and this item leads it |
| Shown | 0.20 ≤ S < 0.45 | — | the room is unfolded if anything in it is Shown; the item sits in its ordinary place |
| Folded | every item < 0.20 | — | the room is a line |

An item that enters a band stays at least **90 s** before any lower band can take it (`MIN_DWELL`). An item in Now that nobody touches for the whole of its habit window (for a habit) or 20 minutes (for anything else) **decays**: its `S` is multiplied by 0.5 per further 10 minutes until it leaves. For a habit this is also learning: when a predicted control is ignored, the stored weight for that habit on that viewer's device is multiplied by 0.5 and written to `LEARNED.md` as a `(learned)` line (*Cailin's phone: the bedtime dim prediction was ignored twice*); one use restores it to 1.0. Nothing is unlearned faster than it was learned.

### 4.4 Stability — when the page may rearrange

The page is allowed to rearrange **only at a quiet moment**, and a quiet moment is all of:

- no pointer down, and more than **1.2 s** since the last touch anywhere on the page;
- no card open (an open card freezes the whole page's order until it folds);
- no scroll for **600 ms**, and the page not scrolled into a region whose contents would move (a change above the viewport is applied and the scroll position compensated so nothing in view moves);
- no rearrangement in the last **8 s** (`REARRANGE_SPACING`), except for an item entering Now with `u ≥ 0.7` or a safety trip, which goes at once.

Between quiet moments, changes **accumulate**; the next quiet moment applies them all in one layout pass, so the page moves once rather than drifting. A value change (a strip's fill, a number, a fan's speed) is **never** a rearrangement: it paints in place at once.

Daily-use positions are protected by **anchors**. An item the viewer has used on four of the last seven days is an anchor within its room: it keeps its slot in the room's row order whatever its score, and the room keeps its position in its floor unless something outranks it by two full bands. The scenes line, the Ask line and the Coming up strip never move at all.

### 4.5 Who is looking

Home Assistant tells the panel the logged-in user; the household maps each user to a person and each device to *personal* or *family* in Morph's Settings (`device: personal` on a phone, `family` on a tablet). On a personal device the owner's habits weigh 1.0, the others' 0.35, so Cailin's phone leads with Cailin's evening and Ben's phone with Ben's, and a lifted light says *you usually do this now* on one and *Cailin usually does this now* on the other. On a family device every home person's habits weigh 1.0, and the because line names the person. The salience list is computed on the device, so three devices never disagree about the house, only about who is holding them.

### 4.6 Performance budget

The house sends many state changes a second and the page must not care.

| Work | Budget | When |
|---|---|---|
| Painting a value change in place | ≤ 1 ms per change, batched per animation frame; a card re-renders only when a state it reads changed (compare, as `cards.js` already does) | every change |
| The salience pass | ≤ 8 ms on a wall tablet, over at most 400 items | every 10 s, or at once on a change in a salient domain (lock, door, safety, alarm, person, appliance finish) |
| The layout solve | ≤ 16 ms, one pass, targets only; springs animate | at a quiet moment with accumulated changes |
| `what_is_normal` | one call per candidate entity per hour, candidates = the entities with a measurement, ≤ 40; cached for the hour | hourly, and once at load |
| `habits`, `house_rhythm`, `door_habits`, `room_physics` | once at load, refreshed every 6 h, cached on disk for 7 days | 6 h |
| `findings` | pushed by `brain_case` / `brain_case_ended` events, never polled | event |
| Frame rate | 60 fps during any animation, measured by the existing overlap test extended to count dropped frames; zero frames in which two sections overlap | always |

### 4.7 Graceful degradation

- **brAIn has not measured something yet:** `d = 0` for it and its because line, if it is ever shown, says *no usual yet*. Safety classes and the night-period floors still work, because they need no measurement.
- **brAIn is offline:** the last cached rhythm, habits and door habits are used for up to 7 days, and the verdict carries a small `--quiet` suffix *· brAIn offline* on the first line. Findings freeze at the last list. After 7 days the page falls back to state-only salience: progress, safety, the night and away floors, nothing else.
- **brAIn is not installed:** Morph does not run. The page is one sentence, *Morph needs brAIn. Install it from the add-on store.*, because a face without the mind behind it would be a dashboard pretending to be this one (§13).

Nothing is ever invented to fill a gap. A page that said *unusual for a Tuesday* without a Tuesday behind it would be the one lie that breaks the whole idea.

---

## 5. Every level of depth

Every thing on the page opens in the same four steps, each answering the next natural question, with nothing repeated between steps. The steps are reached by one grammar: a glance costs nothing; **tap** does the main thing; **slide** sets a level; **hold** opens in place to focus; a tap on the opened card's own history summary goes to detail and then history; a tap outside folds all the way back.

| Level | Question | A light | A room | A person | A system (HVAC, water, security) | The house |
|---|---|---|---|---|---|---|
| **Glance** | What is it? | the 56 px strip filled to brightness in the light's colour, the bulb icon, the name | the room line: name, scene words, door and motion chips | the person card: home or away, since when | the floor heading's one line for that system | the verdict sentence |
| **Focus** (hold) | What can I do? | the colour field and the whites, a sleep timer, a compact day strip | the room unfolded: scenes, lights, comfort, its things | today's comings and goings, the room they are in now | the system's card unfolded: HVAC's two zones with airflow, water's meter and flow, security's locks, doors, cameras | the Now layer and the floors |
| **Detail** (tap the summary) | Why, and what else? | the day strip grows to a timeline with who or what changed it, from the logbook and brAIn's own ledger | the room's physics: how fast it warms and cools (`room_physics`), what is usual here at this hour, what brAIn has noticed about it | the week's pattern: usual wake and settle on this kind of day | the path: HVAC's supply → zone → return as a drawn line with temperatures at each point; water's day as hourly bars; security's logbook | the house's rhythm: wake and settle for weekdays and weekends, the week's energy and water against normal |
| **History** (tap deeper) | What happened? | week → day → hour, in the light's colour, the trail starting *Kitchen › Cans › Tue* | the room's day: every change, who made it | every day of the week | runs per day → per hour | the Came up strip scrubbed |

The pattern is symmetrical because each level is drawn by the same function with a different subject: `open(item, level)` in `cards.js`, where `item` may be a card, a section, a person, a system section or the page. A level never redraws what a shallower level already shows. A light's opened face does not redraw its brightness strip (the strip stays, above, and remains the only brightness control); a room's detail does not relist its lights; a person's history does not repeat today, which focus already showed.

---

## 6. Rooms

A room is one of five states, decided by its score and its occupancy, and in every state its lights are at most two taps away: one tap on the room word (the room line or its own header) unfolds it, one tap on a strip acts.

### 6.1 Idle (folded)

One line, 44 px tall: the name in Bricolage 22 px `--text`, then the room's scenes as words in `--muted` 15 px (so a scene is one tap even when the room is folded), then at the right the door and motion chips as 6 px dots with a word only when open or moving. No chevron. The line's background is the room's tint at 3%. If any light is on, a 2 px warm underline runs under the name for the share of the room's lights that are on (three of six lights on is half an underline). That underline is the glance; it is not a control.

### 6.2 Active

Unfolded, as the room is today: scenes above lights, strips at 56 px in the light's own colour track, Comfort after, the room's things after that. The header line keeps the scene words and the chips.

### 6.3 Occupied

Active, plus: the tint deepens from 3% to 6%, the motion chip's dot is filled, and the room's header line gains the room's temperature and what it usually is, in 13 px `--quiet`: *70° · usually 69*. On a family device an occupied room rises one place in its floor at the next quiet moment.

### 6.4 Asleep

Folded, at 45% opacity, the tint indigo at 4%, the name followed by a small *asleep* in `--indigo` 13 px. Below the line, one control stays visible at full opacity: the thing this room's sleeper usually needs at night, read from `habits` (a fan strip, a sound machine switch, a night light). It is the only control on the page drawn under a folded line, and it is there because a parent reaching for it at 1 AM should not have to unfold a dark room. Tapping the name unfolds the room exactly as any other, at full opacity, and it refolds at the next quiet moment after 2 minutes untouched.

### 6.5 Needing attention

Unfolded, a 3 px rose rule down its left edge, the attention item leading the first row, and a because line under the header in 13 px `--rose`: *The window has been open 40 minutes; it is 38° outside.* If the item has been lifted into Now, the room keeps the rule and the trace *Window, above* and does not repeat the card.

### 6.6 Lights in every state

The room line and the room header carry the scenes as words in every state. The strips are under the header in every unfolded state and one tap under the name in every folded one. A light-group strip is still its lanes; a hold on it still opens one small strip per bulb. Nothing about a strip changes with the room's state except, when the room is asleep, the strip's fill is drawn at 45% with the rest of the room.

---

## 7. Anticipation, time and conversation

### 7.1 Anticipation

A prediction is a control arriving early, never a message. At the start of a habit's window (its measured time minus one spread, so 9:33 for a 9:40 ± 7 min dim), the control lifts to where it will be wanted: into Now on a phone, to the top of its room on a tablet. It looks exactly like itself with one addition, the because line *you usually do this now* in `--violet` 13 px, and a dashed violet dot on the Coming up strip at the predicted time. It is never underlined, never pulses, never counts down. If it is used, the dot fills and the because line disappears for the night. If it is not, it sinks at the end of the window plus 20 minutes, and the habit's weight halves (§4.3). Two ignored windows in a row and the prediction stops; one use brings it back. A habit under four occurrences in 28 days never predicts.

The same mechanism places the garage card in Now when a person's device tracker enters the home zone, the kids' fans at the measured 8 PM, the coffee maker at 6:55. Every one of these is read from `habits`; no rule is hand-set.

### 7.2 Time

The Coming up strip is the scrubber. Slide it left and the reading point moves into the past; the page enters **then**:

- The page desaturates 35% and the verdict is rewritten in the past tense from the recorder: *At 2:14 PM the back door opened. Cailin was home; the printer was at 40%.*
- Every card shows its state at that moment (from `history/period`, fetched for the visible cards only, cached per hour), its strip filled to its brightness then, its lock shackle where it was.
- Every person card shows the room they were in (from their room's motion and their presence).
- A 2 px `--violet` rule at the very top of the page spans the share of the day scrubbed to, so the eye knows how far back it is.
- Now's cards are the things that were salient then.

Tap the strip's *Now* word, let it drift back (the strip already glides to now after 60 s untouched, `IDLE_BACK_MS`), or tap outside, and the page returns over 400 ms. Sliding ahead shows the next hours as predictions: the scenes that usually run, the rooms that will warm (from `room_physics` and the thermostat schedule), the calendar. Hold on a dot behind the line asks brAIn `explain_change` about it and the answer unfolds under Ask. Nothing about this is a mode; it is the same tap, slide and hold on a strip the page already has.

### 7.3 Conversation

Ask is the page's other input, and its answers are shapes as well as sentences.

- **A question** (*why is it warm upstairs?*) is answered under the line in words, and if the answer names something on the page, those things lift into Now with the because line *because you asked*, for ten minutes or until tapped away. For this question: the upstairs climate card, opened to its detail level with the supply → zone → return path drawn, and the upstairs room whose temperature is furthest from normal. The sentence ends with **Show me**, in violet, which scrolls to the first of them; it does not need to be pressed for the page to have changed.
- **A tell** (*always show the printer while it runs*) is a change to the design. It writes one line to `LEARNED.md` (*The printer stays in Now while it is printing (you)*), the salience engine reads LEARNED.md's `(you)` lines as **standing overrides** (a pin with a condition), and the answer under the line is one sentence: *Done. The printer will stay at the top while it prints.* with **Undo** in violet beside it. A tell that needs the house to change (*turn the porch light off when everyone is asleep*) goes to brAIn as a task through the same door a Tell uses, and the answer carries brAIn's plan in words with **Do it** beside it.
- **A command** (*kitchen off*) runs and the room's lights sweep off in order (§8.4); the answer is the sentence *Kitchen off.* that fades after 4 s.

Which of the three a sentence is, brAIn decides (`interpret`); Morph only draws the answer.

---

## 8. Motion

The engine's springs (K = 150, ζ = 0.82) stay as the carrier of every position. What follows is the choreography written on top of them.

| Movement | Duration | Curve | Rule |
|---|---|---|---|
| A value painting in place (a fill, a number) | 180 ms | ease-out | never waits for anything |
| A strip following a finger | 0 | — | the fill is under the finger on the same frame |
| A fan changing speed | 600 ms | ease-in-out on angular velocity | the blades ease between speeds and never jump; a fan that is off may stop (rule 12) |
| Neighbours making room | spring, after 130 ms (section) or 170 ms (tile) | the spring | as today: neighbours move first, then the growing thing grows |
| A card lifting into Now | 420 ms | the spring, with opacity 1 throughout | the card travels along the page; it never fades out and in, because a thing that teleports cannot be followed |
| A card sinking home | 420 ms, after a 300 ms pause | the spring | the room it returns to unfolds first |
| A room folding or unfolding | 260 ms | the spring | the line is the last thing to move |
| Night form in and out | 2 s in, 300 ms out | ease | in is slow because it is leaving; out is fast because somebody is there |
| A safety wake | 0 (a cut) then 300 ms | — | the one moment that may not be graceful |

### 8.1 What moves first

Cause before effect, always. When a scene word is tapped, the word underlines first (80 ms), then the lights change; when a door opens, its chip fills first, then the ripple, then the Now card. The thing a person touched acknowledges them before the page responds to the house.

### 8.2 A scene sweeping a room

Tapping *Dinner time* changes the lights in order of distance from the tapped word across the page, 40 ms apart, capped at 480 ms for the whole sweep, each strip's fill animating 180 ms. The room fills with the scene the way a hand would set it, left to right and down. A light-group's lanes ripple top to bottom within the strip, as they do when slid.

### 8.3 A door rippling into security

A door opening at night draws a 2 px rose line from the door's chip in its room line, up the left edge of the page, to the Now card, over 300 ms, then fades over 600 ms. It is drawn once per event. The eye is taken from where it happened to what to do about it.

### 8.4 Water flowing

While the water meter's flow is above zero, its card's bar carries a sky gradient drifting right to left at 24 px/s; the irrigation card's zone bars do the same. A drip reads as a drip and a running tap as a running tap, because the drift speed scales with flow (`speed = 8 + 16 · flow / usual_peak` px/s).

### 8.5 Reduced motion

Under `prefers-reduced-motion`, every spring becomes a 200 ms crossfade at its target position, fans stop spinning and show speed as the share of blades drawn solid, ripples become an instant tint on the destination that fades over 600 ms, water bars become a static gradient with a 1 px moving tick, and the night form fades in 400 ms. Nothing is removed from the page; only travel is.

---

## 9. Visual language

### 9.1 Surfaces and tints

The page is `--bg`, cards are `--surface`, an opened card's history well is `--sunk`, hairlines are `--line`. The three themes are the ones in `styles.js`, unchanged: dark (`#0A0C0E` on `#15181B`), medium (`#2A2D31` on `#34383D`), light (`#ECEBE6` on `#FFFFFF`). A room's tint is its colour at 3% over `--surface` idle, 6% occupied, 4% indigo asleep. The Now layer's cards are untinted `--surface` at full opacity so they read as nearer. Nothing is boxed inside a card: groups are labelled, never bordered.

### 9.2 Colour carries meaning (rule 11)

| Colour | Token | Means | Where it appears |
|---|---|---|---|
| warm | `--amber`, `--sand`, `--peach` | light and power | strip fills, the fan's blades, the printer's progress, an energy total |
| sky | `--sky`, `--teal` | air, water, climate | thermostat rulers, airflow, the water meter, irrigation, humidity |
| indigo | `--indigo` | secure, at rest | locks, the alarm, asleep rooms, the night form, *Everything is at rest* |
| amber | `--amber` | caution | a deadline, a door open to weather, a degree too warm |
| rose | `--rose` | needs attention | an unlocked door at night, a leak, a finding waiting, a room's attention rule |
| violet | `--violet` | media, scenes, and the house's own suggestions | the scenes line, playing media, predictions, Ask's answers, pins |
| green | `--lime` | the garden, only | irrigation zones watered, the lawn |

A colour never appears outside its meaning. Caution amber and light amber share a token on purpose: a light that is on is a warm fact, and a caution is a warm fact that wants a look; the difference is carried by the word beside it, never by the hue alone.

### 9.3 Type

Two faces, as today. **Bricolage Grotesque** for anything read as a number or a heading: the greeting at `clamp(36px, 5vw, 58px)` weight 400, the story at `clamp(20px, 2.3vw, 27px)` weight 300, floor headings at `clamp(24px, 2.6vw, 30px)` weight 300, room names at 22 px weight 400, the scene words at 19 px, big values at 28 px, the night clock at 96 px weight 200. **Manrope** for everything else: body 15 px, a tile's name 14 px weight 600, a tile's value 12 px tabular, because lines 13 px, labels 11 px weight 700 with `.14em` tracking in caps (the one place caps are allowed: a group label). Numbers are always tabular. Nothing on the page is bold except a tile's name and a label.

### 9.4 Density and the details that make it this house's

- 56 px strips, 12 px gaps below 700 px and 16 above, as the engine has them.
- The icon watermark on every tile: the device's icon at 72 px, 11% opacity, bottom right, clipped by the tile. Kept, because the household loves it, and extended: a lifted Now card's watermark is 96 px.
- The slim colour track on a light: 3 px, the light's actual colour, the full width of the strip under the fill. Kept.
- The fan's blades spin at the fan's speed, easing between speeds. Kept.
- Each room's tint comes from `dashboard.yaml`'s `color`, so Kaz's room is peach and the kitchen sand because the household said so; the page is theirs in colour before it is theirs in content.
- The verdict's first clause in its meaning's colour is the page's signature: a glance at the top line is a glance at the house.
- Light theme is not an inversion: tints drop to 2%, the rose rule becomes 2 px, the watermark 8%, and the night form uses `--sunk` rather than black so a light-themed tablet at night is a soft grey page with one indigo line.

---

## 10. Devices and rest states

### 10.1 A phone in hand

Two columns (the engine's `N = max(2, …)`). The room line is sticky under the header. The Now layer holds at most two cards. Strips are full width in a one-column room. Every target is 44 px. The verdict's greeting shrinks to 36 px and the story wraps to at most three lines. The whole page is reachable with one thumb: Ask at the top is the only thing above the fold that needs two hands, and it is a line, not a box.

### 10.2 A laptop

Four to six columns. The floor heading carries the room words. The Now layer is a row of up to three. Keyboard: arrow keys scrub the strip (already), `/` focuses Ask, Escape folds whatever is open, Tab walks the room line.

### 10.3 A wall tablet

Five columns at 1280 px, type scaled 1.1×, the Now layer's cards drawn at 1.25× with 1.5× type so they read from across a room. After **90 s** untouched the page enters its **still** form: the rooms fade to 35%, the verdict grows (the greeting to 64 px, the story to 32 px), the time appears in Bricolage 96 px weight 200 at the top right in `--quiet`, the weather's temperature in 48 px beside it, and the Now layer stays at full size. It is a page readable from the kitchen doorway: the time, the verdict in its colour, the one to three things in progress or wrong. A touch, or motion within the tablet's room, returns it in 300 ms.

At **night** (the alarm armed, or everyone asleep) the still form goes further: the rooms fold entirely (a dashboard that sets `night_dim: true` also dims everything but the Now layer and the verdict a little, to 80%; the 40% this page first asked for was unreadable in a real house, #343), the clock stays, and if nothing is salient the only words on the screen are the time and *Everything is at rest.* in indigo. A room's motion wakes it to 70% for 2 minutes, not full, because the person is walking past, not looking.

**Away** (nobody home) is its own form on every device: the verdict reads *Nobody is home.* then the security facts; Now holds the locks (one card, *All locked* in indigo or the unlocked ones in rose), the doors and the cameras; rooms are folded; lights and media never predict. A person's tracker entering the zone ends it, and the garage lifts into Now for the car.

---

## 11. Trust and control

Every lifted, led, dimmed or folded thing can say why, in one line, drawn from the data and never from a rule somebody typed. The **because line** is 13 px under the title, in the item's meaning colour at 80%, one of a closed set of sentences so it never rambles:

| Reason | Wording |
|---|---|
| deviation (sensor) | *638 gal today, usually about 180 on a Tuesday* |
| deviation (door, lock, light) | *open at this hour on 1 night in 20* / *unusual for 11 PM* |
| urgency | the finding's own claim, from `answers` |
| progress | *in progress · 62%* / *finished 12 min ago* |
| habit | *you usually do this now* / *Cailin usually does this now* |
| asked | *because you asked* |
| pinned | *kept here* |
| standing override | *you said: show the printer while it runs* |
| no measurement | *no usual yet* |
| folded (shown on hold on a room line) | *nothing unusual here; last used Tuesday* |

Control is the same three gestures and no new vocabulary:

- **Hold** on any lifted or led card opens it in place as always, and its options row carries two extra words: **Keep here** (a pin: the card stays in Now until unpinned, a 4 px violet dot after its name; it is written to `LEARNED.md` as a `(you)` line so it survives) and **Not this** (the card sinks at once, the reason that lifted it is suppressed for today, and if it was a habit its weight halves).
- **Hold** on a because line asks brAIn **Why?** — `explain_change` for a change, the finding's detail for a finding, the measurement for a deviation — and the answer unfolds under the line, in place.
- **Hold** on a folded room line shows its because line and *Unfold* is not offered, because tap already does it.
- **Slide** on a because line does nothing, because a reason has no level.

The page never asks for confirmation of its own choices and never shows a dialog about them. Nothing it does is irreversible: a pin has Undo in Ask's answer, a Not this is for today, a learned weight recovers with one use, and a `(you)` line in `LEARNED.md` is the household's to delete.

---

## 12. Signature moments

1. **The one rose line at 3 AM.** A dark tablet in a dark kitchen, and one sentence appears: *The back door just opened.* A rose thread runs up the page from Outside to the door's card, and the word *Disarm* waits for its second tap. Nothing else is on the screen, and nothing else needs to be.
2. **The scene sweeps the room.** Tap *Dinner time* and the kitchen's strips fill one after another, left to right and down, 40 ms apart, each in its own colour, the fans easing up to speed, the whole room arriving in half a second the way a hand would set it.
3. **Scrubbing the day backwards.** Slide the strip left and the page desaturates and turns into yesterday afternoon: the people cards move room to room, the printer's bar unwinds, the back door's chip opens and closes at the times it did, and the verdict rewrites itself in the past tense as you go.
4. **The control that is already there.** At 9:33 PM Cailin picks up her phone and the master bedroom's lights are the first thing under her thumb, with *you usually do this now* in violet. She dims them with one slide and the dashed dot on the strip fills. The page learned that from her and never asked.
5. **Asking why, and watching the answer draw itself.** *Why is it warm upstairs?* The HVAC card opens to its path, a sky line from the supply through the upstairs zone to the return with a temperature at each point, the warm room lifts beside it with *74°, usually 72 at 2 PM*, and the sentence under Ask says *The upstairs damper has been at 20% since the 1 PM schedule.* — the page reshaped into the answer.

---

## 13. One mind, one face: brAIn and Morph

Morph cannot run without brAIn, and brAIn does not need Morph. That asymmetry is the design: **brAIn is the house's mind and Morph is its face.** Everything brAIn knows, notices, asks, proposes or can do reaches the household through Morph, in the same grammar as a light, and nothing a person can do in brAIn's own panel is out of reach from Morph except brAIn's own settings and diagnostics, which are brAIn's about itself. There are no "Morph findings" and no "brAIn findings". There is one list, kept by brAIn, drawn by Morph.

### 13.1 One list

brAIn's case store (`cases.list_cases` over findings, questions, suggestions and chores) is the only list of things waiting on a person. Morph keeps none of its own:

- **Morph's learning suggestions** (*move Kitchen above Dining; you open it first every morning*, a card brAIn thinks the house is missing) are filed into brAIn's store as cases with `source: morph` and kind `opportunity`, through `triage.gate` like every producer. Morph's `learning.py` stops holding a suggestion list and becomes a producer.
- **Morph's own faults** (a card that threw, an overlap at rest) stay on brAIn's development loop as they are today. They are not findings, they are bug reports, and a person never answers one.
- **Morph's "What do you want to fix?" box** is Ask. Words about Morph itself (*the kitchen header is too tall*) are a Tell about Morph's code, which Ask already routes (§13.3).

Every case therefore has one id, one set of answers decided once by `answers.situation`, and one ending wherever it is given: a phone's button, the Repairs dialog, the To-do app, brAIn's Today, or Morph. Answering it in Morph is answering it everywhere, within the fifteen seconds the request drain already takes.

### 13.2 Where a case lives on the page

A case is a card, and it obeys the salience engine like any card: its urgency `u` is its severity (§4.1), and its deviation `d` is whatever measurement raised it. So a critical finding is in the Now layer and in the verdict's first clause; a warning leads its room; an info-level question sits in its room's ordinary place; and a suggestion about the dashboard sits at the top of the section it is about, in violet.

**A case is placed where its subject is.** A finding about the hallway sensor is a card in the Hallway, under the hallway's lights, after its things, with a 3 px rule on its left in its colour: rose for a problem, violet for a question or a suggestion, amber for caution. A case about the whole house (the week's one thing, a usage note) sits on the Overview floor in a section that exists only while there is something in it, titled by nothing, because its cards say what they are. A case about brAIn itself (signed out, a credential refused) is the verdict's first clause and one card at the top of Now, since nothing else works until it is answered.

The room's header line counts them: *Hallway · 1 needs you* in `--rose` 13 px when folded, so a folded room never hides a question. The verdict's story ends with the count when there is one: *…and 3 things need you.* as a jump to the first.

### 13.3 Ask does everything

Ask is brAIn's chat, with a dashboard in front of it. Anything that can be typed into brAIn's Ask tab can be typed into Morph's line and does the same thing, plus one more:

| You type | What happens | Where it lands |
|---|---|---|
| *why is it warm upstairs?* | a question | the answer unfolds under the line; the page reshapes to show it (§7.3) |
| *turn the porch light off when everyone is asleep* | a standing rule | brAIn drafts it, simulates it over the recorder, and offers it as a case with its grade (`authoring`); **Try it for a week** and **Do it** are its words |
| *when the guests leave, turn the porch light off* | a one-off | armed, with its card saying it fired |
| *rename the basement sensor to Sump Pump Current* | a change to the house | brAIn does it; the answer is one sentence with **Undo** |
| *fix the dead reference in the pool automation* | a fix | brAIn plans it; the plan is one line with **Apply**, or is applied at once when *Let brAIn act without asking* is on; **Undo** either way |
| *remember that the garage fridge is the beer fridge* | a fact | filed; *Remembered.* |
| *always show the printer while it runs* | a rule about this page | a `(you)` line in LEARNED.md; the page obeys at once (§7.3) |
| *move the kitchen above the dining room* | a change to the dashboard | the Tell fast path: one commit, **Undo** |
| *the kitchen header is too tall* | a change to Morph itself | a Tell about Morph's code; brAIn edits the copy, Morph offers the reload |

Which of these a sentence is, brAIn's interpreter decides, on a new surface `morph` whose vocabulary is the ask bar's plus the Tell's two kinds (`dashboard`, `code`). The interpreter never guesses between a house change and a dashboard change: *make the kitchen warmer* is the thermostat and *make the kitchen warmer-looking* is the tint, and a sentence it cannot place is answered with the question, in place, as a conversation turn (§14.3). A conversation started in Morph is a conversation in brAIn's Ask tab too, the same session, and it can be picked up on either face.

When a change needs the household's permission, the approval card that brAIn's chat already renders (the `can_use_tool` card) is drawn in place under Ask, in Morph's own type, never floating, with the same **Allow · Always allow · No** words. A change under a protected entity is refused in brAIn and the refusal is the answer; nothing in Morph routes round it.

### 13.4 The wire

The two add-ons do not share a process, and brAIn's panel port is deliberately not on the network. The wire is the one that exists, plus one addition:

- **Cases reach Morph** through the mirror brAIn already publishes at `/config/.brain/findings_state.json` (every live row with its `answers` list) and the `brain_case` / `brain_case_ended` / `brain_change` events. Morph's integration subscribes to the events and reads the mirror; the page needs no poll.
- **Answers reach brAIn** through `finding_requests`, the same queue a phone's button and the To-do app write to, with one new field: `surface: morph` and free `text`. The drain hands a Morph request to the interpreter on the `morph` surface before applying anything, which is what lets *yes, but name it this* be a single request.
- **Conversations** ride brAIn's task folder as Tells already do, with the progress hook streaming steps, and the task result carrying a `session_id` so the next turn resumes it. This is the one addition: a task kind `conversation` that may continue. The task's `channel` is `chat`, so the action gate asks rather than denies, and the approval question comes back through the same progress file for Morph to draw.
- **The one decision the owner makes:** whether brAIn's panel API is published to the hassio network for Morph to stream chat directly (faster, one more thing on the network) or stays file-only (what exists; a turn costs a second of latency). This vision assumes file-only and says nothing a person would notice differently.

### 13.5 What stays in brAIn's own panel

Settings about brAIn (model, usage, permissions, notifications, cameras, memory), diagnostics, reports, the house book, the memory document, the corpus and the developer loop. These are brAIn's about itself, and Morph links to them in one place: hold on the verdict's *· brAIn offline* or on a case about brAIn, and the option **Open brAIn** appears. Nothing else in Morph sends a person to another screen.

---

## 14. A finding is a conversation

Today a finding is a card with buttons, and the household's complaint is exact: the buttons force a yes or a no onto something that is usually *yes, but…* or *not that one* or *which do you mean?* The redesign makes every case a short conversation with a person who already knows the house, and keeps the three endings that need no words as words.

### 14.1 The card

A case card has four parts and nothing else:

1. **The claim**, in Manrope 15 px `--text`, under twenty words, with the device by its friendly name: *The basement humidity sensor has read 61% for nine days.*
2. **The ask**, one line in `--muted`, present only when brAIn wants something from you: *Should I rename it to Basement Humidity?* / *Is the garage freezer meant to be off?* / *Replace its battery, or tell me it is mains-powered.* A problem brAIn can fix itself asks *Fix it?* and says in one line what it would do.
3. **The reply line**: a 1 px rule in the case's colour and the placeholder *Reply…*, 15 px, the same line Ask is. This is the primary control. Tap it and type; Enter sends.
4. **Two words at the right of the reply line**, in `--quiet` 13 px: **Dismiss** and **To Do**. On a problem brAIn could fix, a third word leads them: **Fix**.

No Yes button, no No button, no Wrong, no Snooze, no ⋯. Hold the card for its history, its evidence and *Why?* (§11), as any card.

### 14.2 What a reply does

The reply is read by brAIn's interpreter on the `morph` surface, and the words decide the ending. The closed set of endings is the one brAIn already has; what changes is that a sentence reaches them, and that a sentence can carry more than an ending.

| You type | What brAIn hears | What happens |
|---|---|---|
| *yes* / *ok* / *do it* / *sure* | consent to the ask | the case's primary ending: the rename is made, the fix is applied (or planned, with **Apply**, when the switch is off), the question is confirmed and filed as a fact. The card says what happened in one sentence with **Undo**. |
| *yes, but call it Sump Pump Current* | consent with an instruction | the ending, with the words as the agreed change (`{change}` on the fix route): the rename uses that name. The card shows the name it used. |
| *no* / *no, please don't* / *leave it* | a refusal of the ask | the case ends as **Wrong** with those words as its note, which teaches brAIn (a correction fact, and for a check an exception rule on that entity), and it is not raised again. The card says *Okay, I'll leave it.* |
| *no, it's mains-powered* | a refusal with the fact | the same ending, and the fact is filed; the check stands down for that entity for good. |
| *not now* / *later* / *ask me next week* | a deferral | snoozed; brAIn picks when it comes back unless a time was named. The card says when. |
| *I replaced it* / *done* | the claim it is fixed | **Done**, the memory line in your words, and the check verifies it on its next pass. |
| *which sensor is that?* / *why?* | a question | a conversation turn (§14.3): brAIn answers under the reply line and the card stays open. |
| *rename it and add it to the kitchen card* | more than the ask | the ending plus a Tell, in one reply; brAIn does both and says so. |

A reply whose words brAIn cannot place is never guessed at. It is answered with a question (§14.3).

### 14.3 When brAIn needs to ask back

A case is not a form, so brAIn may answer a reply with a question, and the question is a turn under the reply line in the same card: *Two sensors match "basement" — the one on the wall by the stairs, or the one on the sump? (Both read 61%.)* The reply line is still there; *the sump* resolves it and the ending proceeds. The thread is drawn as alternating lines, brAIn's in `--muted`, yours in `--text`, at most the last three visible with the rest under a one-word fold *earlier*. It is brAIn's own chat, attached to the case (a Discuss session with `finding_ts`), so brAIn can read the house with its tools while it answers, and every turn is a turn you could have had in brAIn's Ask tab. A case brAIn offers endings for from inside the conversation (`offer_resolutions`) shows them as words under its turn, which is the one time a case shows more than three words.

A thread with no reply for 24 hours folds to its claim and ask; the thread is kept and reopens on the next reply.

### 14.4 Dismiss

**Dismiss** is for now. It is brAIn's own Dismiss: the row is deleted, nothing is settled, no memory line, no rule, and if brAIn sees the same thing again it raises it again. It is the right word for a device that was offline for a minute, a question that is not worth answering today, a thing that has passed. The card sinks over 420 ms and the toast line under the verdict says *Dismissed · Undo* for 10 s. Typing *no* is the ending that lasts; Dismiss is the one that does not, and the card never has to explain the difference, because the word for *for good* is a sentence and the word for *for now* is a word.

### 14.5 To Do

**To Do** moves the case onto the household's list, which is brAIn's `todo_store` and Home Assistant's `todo.brain`, one list. The item's wording is **exactly what needs to be done**, imperative, naming the thing: *Replace the battery in the hallway motion sensor.* / *Reset the garage Z-Wave node.* / *Close the window in Lev's room.* Never the finding's claim (*Battery at 9%*), never the check's name, never a question. brAIn writes that sentence when it files the case (`todo_text`, beside `fix`; the Resident's look rewrites it in the specific words when it has looked), and Morph's To Do word uses it. A typed *add it to my list, and note the model number is CR2032* moves it with the note appended.

To Do is a section on the Overview floor, present only while it holds something, each item one line: the sentence, the room in `--quiet`, and nothing else. **Tap** ticks it off (the memory line is written then, in the sentence's words); **slide** right snoozes it a week (the row shows the date as it slides); **hold** opens *Put it back as a finding*, *Delete* and the item's evidence. A ticked item sinks and the check that filed it verifies it on its next pass, exactly as brAIn does for a chore today. The same list is in the To-do app and on a phone, and a tick anywhere is a tick everywhere.

### 14.6 Questions brAIn asks on its own

A hypothesis (*I think the office lamp is on a timer — right?*), a house-book gap (*Where is the "Loft" sensor?*), a mute offer (*The frozen-sensor rule has been wrong 3 of 3 times here. Stop raising it?*) and a notification pattern (*You dismiss the dryer notice most evenings. Stop sending it?*) are all the same card: a claim, an ask, a reply line, Dismiss and To Do. *yes*, *no*, *it's in the attic*, *only on weekdays* all work, because the interpreter maps them to the ending the store understands and the words ride as the note or the fact. A question that does not apply is *doesn't apply*, which brAIn already has as an ending; typing it is enough. On a wall tablet a question shows no reply line until tapped, so a child cannot answer it by leaning on the counter; the Dismiss and To Do words need a hold there.

### 14.7 The two-second test, again

A finding in Morph passes the same test as the house: a glance says whether something is waiting (the verdict's count, the room's *1 needs you*, the rule on the card's edge), and a thumb answers it in one line of typing or one word. Nothing about a case is a binary a person has to squeeze a real answer into; and nothing about it is a form.

---

## 15. What it never does

- It never floats anything: no popup, sheet, overlay, toast, modal or tooltip. An answer, an option and a reason are all in place.
- It never rearranges under a finger, during a scroll, while a card is open, or within 8 s of the last rearrangement, except for a safety trip.
- It never moves a value change into a layout change: a fill fills where it is.
- It never shows a control twice. A lifted card leaves its room.
- It never hand-sets what is normal. A threshold the household did not measure is a threshold Morph does not have.
- It never invents a reason. No measurement, no because line claiming one.
- It never nags: a prediction is a control arriving early, with no badge, no count, no pulse, and it leaves when ignored.
- It never adds chrome: no tabs, chevrons, Done buttons, drag handles, instruction rows, empty-state text or *Nothing to show*.
- It never uses a colour outside its meaning, and never carries a state by colour alone.
- It never asks the household to confirm its own choices, and never makes one it cannot undo.
- It never learns a guest, and a family tablet never carries one person's habits over another's.
- It never keeps a list of its own: a finding, a question, a suggestion or a chore is brAIn's, drawn here.
- It never forces a yes or a no: every case takes a sentence, and a sentence it cannot place is answered with a question.
- It never sends a person to brAIn's panel for anything but brAIn's own settings.

---

## Appendix — what changes in Morph's code

| Module | Change |
|---|---|
| `salience.js` (new) | the inputs, score, bands, hysteresis, dwell, decay, anchors, viewer weighting; pure over what it is handed; its cache of brAIn's answers |
| `morph-panel.js` | the verdict (the story's first clause in colour, from the list), the Now layer, the room line, the five room states, the still, night and away forms, the because line and its hold options, Ask's three kinds of answer, *then* |
| `engine.js` | takes a section order and fold state from the list instead of the file order; the quiet-moment gate; a lifted card's travel between a room and the Now band without a fade |
| `upcoming.js` | `PAST_MIN` to 1440, the past's dots from the recorder and logbook, the *then* cursor exported to the panel |
| `cards.js` | `open(item, level)` for the four levels; the asleep room's one control; the because line as a part of every card's face |
| `history.js` | state-at-time for the visible cards during *then*, cached per hour |
| `styles.js` | the still, night and away forms; the room states' tints; the Now layer's scale on a tablet |
| `dashboard.yaml` | `device: personal | family` in Settings, not the file; `pin:` on a card as the written form of Keep here |
| `LEARNED.md` | `(you)` lines are standing overrides the engine reads; `(learned)` lines are halved habit weights |
| `morph-panel.js` (cases) | the case card: claim, ask, reply line, Dismiss and To Do, the thread, the in-place approval card; the To Do section; *Open brAIn* |
| `morph/service/learning.py` | files its suggestions as brAIn cases (`source: morph`) instead of keeping a list |
| `morph/custom_components/morph` | subscribes to `brain_case` / `brain_case_ended` / `brain_change`, reads the findings mirror, writes `finding_requests` with `surface: morph` and `text` |
| brAIn `panel/interpret.py` | a `morph` surface: the ask bar's kinds plus `dashboard` and `code` (the Tell), and every ending; a reply with an instruction carries `change` |
| brAIn `panel/finding_requests.py` | `surface` and free `text` on a request; the drain interprets a Morph request before applying it; a question back opens the case's Discuss session |
| brAIn `panel/findings_store.py` / `checks` / `resident` | `todo_text` on every row: the imperative sentence To Do shows, written by the producer and rewritten by the look |
| brAIn `integrations/automation-listener.sh` | a `conversation` task kind that resumes by `session_id`, channel `chat`, its approval questions relayed through the progress file |

Tests, in the manner of `measure-morph.mjs`: the night form at 11:30 PM with one unlocked lock shows exactly one card and one rose sentence; a lifted card's room carries its trace and no copy; no rearrangement happens within 1.2 s of a pointer event or while a card is open, sampled every 30 ms; a page with brAIn stubbed as absent shows no because line that names a measurement; every light in the fixture house is reachable in two taps from the top of the page at 390 px; and the overlap test still reports zero frames.
