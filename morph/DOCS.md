# Morph — documentation

> ## ⚠️ Experimental — not recommended for general use yet
> **Morph is being built in the open and is not finished.** Expect missing
> cards, rough edges and changes between updates that move things around
> without warning. Install it to try it out alongside your normal
> dashboards, not to replace them. Morph only writes its own folder
> (`/config/morph`) — every change there is a version you can undo — and a
> Tell changes Home Assistant itself only when you ask for that in words.

Morph is a Home Assistant add-on and integration. The add-on runs a small
service that owns the dashboard file and its history; the integration
registers the **Morph** sidebar panel, which runs inside Home Assistant's own
frontend.

- [Installing](#installing)
- [Using the dashboard](#using-the-dashboard)
- [What leads the page](#what-leads-the-page)
- [brAIn's cases and To Do](#brains-cases-and-to-do)
- [Ask](#ask)
- [Edit mode](#edit-mode)
- [Tell brAIn](#tell-brain)
- [Learning](#learning)
- [Changing Morph itself](#changing-morph-itself)
- [When Morph's own code fails](#when-morphs-own-code-fails)
- [Settings](#settings)
- [The dashboard file](#the-dashboard-file)
- [Options](#options)
- [Security](#security)
- [Troubleshooting](#troubleshooting)

## Installing

1. Install **Morph** from this repository and start it.
2. Home Assistant offers a **Morph** integration under **Settings → Devices &
   services**. Accept it.
3. Restart Home Assistant once (**Settings → System → Restart**).
4. Morph appears in the sidebar.

There is no *Show in sidebar* switch on the add-on's page. That switch exists
only for ingress add-ons, whose page is an iframe; Morph's page runs inside
Home Assistant's own frontend instead, which is what gives it the live state,
your theme and Lovelace's card helpers, so any card you already use can be
hosted. The integration is what registers the panel.

On the first start Morph builds a dashboard from your house: one section per
area, grouped by floor (or Home and Outside when you have no floors), and a
**Whole house** floor with climate, weather and security. Rebuild it any time
from **Settings → Dashboard**.

Tell and learning need **brAIn** with its *Automation integration* switched
on (brAIn's Configuration tab). Morph checks that and says so in Settings.

### Updating, and when to reload

A page left open does not change by itself when Morph's code does. When the
code on screen is no longer what Home Assistant would serve, a bar at the top
of the dashboard says so, with **Reload**. That happens after an update, or
when brAIn changes your copy of Morph's code. When the add-on has been
updated but Home Assistant is still running the older Morph integration, the
bar asks you to restart Home Assistant instead, because a reload alone would
not finish the update. Nothing else needs a reload: changes to the dashboard
itself appear on their own.

Morph's code is cached by your browser under a name for exactly that
version, so opening Morph again downloads nothing. While it opens, you see
the outline of the dashboard rather than a blank page.

## Using the dashboard

| Gesture | Does |
|---|---|
| **Tap** | The main thing: toggle a light, play, lock. A garage door and an unlock ask for a second tap. |
| **Slide** | A level: brightness, fan speed, blind position. |
| **Hold** | Opens the card in place with its options and its history. |
| **Tap outside** | Folds everything back. |

An opened card also offers **Details**, which opens Home Assistant's own
dialog for that entity (its history, attributes, settings and what it is
related to), and **Device page** for an admin, which goes to the device in
Home Assistant's settings. On a card that lists several things, tap one row
first.

History is what Home Assistant records for that kind of thing: a light's day
as a strip of on and off, a sensor's readings as a line you can scrub, a
meter's week as bars. Tap a day or a bar to see its hours, and the logbook's
"who" for each change.

## What leads the page

Morph is brAIn's face: the page is laid out by what matters in the house
right now, and it can always say why.

- **The verdict.** The first line says what is going on, its first clause in
  the colour of what it means: rose for something wrong, amber for
  something worth a look, indigo when the house is at rest.
- **Now.** Up to three cards (two on a phone) are lifted to the top: a door
  open longer than it usually is, a machine that finished, a light you
  usually dim about now. A lifted card is **moved**, not copied; its room
  keeps a faint trace where it was. Under it, one quiet line says why
  (*open at this hour on 1 night in 20*, *you usually do this now*). Hold
  that line for **Keep it here** and **Not this**.
- **Rooms.** A room with something on, moving or unusual is open; a quiet
  room folds to one line with its name, its scenes and anything open. Tap a
  room's name to open it. A room where somebody is asleep is dimmed.
- **Night, away and still.** With the alarm armed for the night (or
  everyone asleep) the page dims and shows only what is wrong, usually
  nothing: *Everything is at rest.* With everybody away it says so. A
  family tablet left untouched settles into a page readable across the room.
- **Then.** Slide Coming up into the past and every card shows the house as
  it was at that moment; dots behind the line are what happened.

The page rearranges only at a quiet moment: never under your finger, while
you scroll, while a card is open, or within a few seconds of the last
change, unless something urgent (a door opening at night) needs it.

What Morph reads to decide is brAIn's: what is normal for each sensor and
door at this hour, your habits and the house's rhythm (published in
`/config/.brain/morph/feed.json`). Without brAIn, the page still works from
the house's own state.

**Settings → This device** says whether this screen is somebody's own (it
leads with their habits) or the family's (a wall tablet), and **Fold quiet
rooms** turns folding off.

## brAIn's cases and To Do

A problem or a question brAIn has is drawn **in the room it is about**: the
claim, what brAIn wants from you, and a reply line. Answer in your own words
— "yes, but call it Sump Pump Current", "it is meant to be off in winter",
"put it on my list" — and brAIn reads the reply and ends the case the way
the words say, or answers with a question in the card. **Fix** (where brAIn
could make the change), **Dismiss** and **To Do** are there for when a word
is quicker. A case about nothing on the page is drawn at the top of its
floor.

**To Do** is brAIn's list, the same one Home Assistant's To-do app shows.
Tap a line to tick it off; slide it right to snooze it a week; hold it for
**Delete**.

Morph's own suggestions for the dashboard are brAIn's cases too, answered the
same way; a yes makes the change as a Tell.

## Ask

The line under the verdict is brAIn's chat with the dashboard in front of it.
brAIn decides what the words are:

- **A question** is answered under the line, and the page lifts what the
  answer names. Answer again to carry on: it is one conversation, also in
  brAIn's Ask tab.
- **Something to remember or a rule** ("remember the sump pump is in the
  laundry", "tell me when the dryer is done") is done and said in a line.
- **A change to the dashboard or to Morph** is a Tell, with Undo.

Without brAIn's integration, Ask falls back to the house's own assistant.

## Edit mode

Press **Edit** in the top bar.

- **Tap a section** to rename it, recolour it, move it to another floor (or a
  new one), widen it, add a group, hide it or remove it.
- **Tap a card** to rename it, resize it, move it, edit its JSON, or remove
  it.
- **Drag a section** to reorder it or move it between floors.
- **Add card** in each section offers the entities in that room first, then
  any entity, then **Lovelace card** — paste any card's YAML or JSON.

Every save is one commit. The toast after a change offers **Undo**.

## Tell brAIn

In Edit, **hold** anything — a card, a section, a floor, the whole dashboard —
and say what should change. **Send** hands it over.

You do not need Edit to change the dashboard. Type the change into the Ask
line ("remove the Coming up timeline", "put the porch light in Entry", "the
kitchen header is too tall") and brAIn reads it as a change to the dashboard
or to Morph itself, and makes it as a Tell. If an answer was not what you
wanted, **Change the dashboard instead** sends the same words as a change.

**brAIn looks first.** The moment you hold something, Morph takes a picture
of it and shows it in the box (**What brAIn will see**). brAIn reads that
picture before anything else, so "this is cut off" or "the colours are
wrong" mean what is on your screen. If the picture cannot be taken (an
embedded web page, for instance), the box says so and brAIn is given the
card's text instead.

**It changes Morph.** brAIn acts at once on:

- the dashboard (`/config/morph/dashboard.yaml`),
- Morph's card code (`/config/morph/cards/`),
- Morph itself: its header, its layout, its built-in cards, its styles (see
  [Changing Morph itself](#changing-morph-itself)).

It changes Home Assistant itself — entity ids, names, areas, automations,
scripts, helpers — only when you ask for that in words: "change the entity
ID", "rename the device", "make an automation that…". When a request would
need a house change you did not ask for, brAIn does the dashboard part and
says what would have to change under **Left for you**, so you can ask.

**A choice that is yours comes back as buttons.** The commonest one: a card
that works a number out from other sensors (a difference, a total, an
efficiency) has no history, because Home Assistant only records entities.
When you might want that history, brAIn builds the card with the number
worked out in it and asks: **Calculate it in the card**, or **Make a Home
Assistant sensor** so it is recorded. The button that changes Home Assistant
says so, and pressing one sends it as your next request.

**You can see it working.** brAIn's own steps appear in the box as it takes
them (looking at the picture, reading `dashboard.yaml`, checking an entity,
editing a file) with how long it has been at it. Close the box and the work
carries on; a strip at the top of the dashboard says what brAIn is doing,
and **Show** opens it again.

**It is a conversation.** When brAIn answers, Morph commits the dashboard
half as one change and shows what brAIn did, what it saw, and the card
**before and after**.

**It says where every change landed.** The result has one line for each
place a request could reach, whether or not anything happened there:
**Dashboard**, **Home Assistant**, **Morph's code** (when it changed),
**brAIn's memory** (facts it queued about the house) and **GitHub** (*Nothing
sent* unless you say yes to an issue).

**Morph checks the result.** It reads the dashboard back and lists what is
different on screen on the **Dashboard** line, worked out from the file,
not from what brAIn said. If nothing changed it says *Nothing on the
dashboard changed* and quotes brAIn. If brAIn left `dashboard.yaml` unreadable
it says *Not applied* (Morph keeps showing the last version that read) and
**Undo** puts the file back. If your screen has not caught up, **Refresh**
loads it. **Keep**, **Undo** and **Tell it more**: Undo reverts
that commit exactly (and, if you asked for a change in Home Assistant, asks
brAIn to put that back too); Tell it more keeps the conversation above,
takes a new picture of how it looks now, and asks what should be different.

**Changing Morph itself, then asking.** When what you asked needs Morph's
own code changed (a switch in the header, a built-in card that cannot do
it), brAIn changes it here, in your copy of Morph. The box offers **Reload to
see it** and **Undo**, and then asks **Would you like to open an issue to
update Morph's code?** so everybody can have it. Nothing is sent unless you
press **Open an issue** (see
[When Morph's own code fails](#when-morphs-own-code-fails)).

What still holds whatever you ask: brAIn's `protected_entities`, its action
gate and its edit snapshots (`brain undo`). What brAIn learns about the
house along the way goes into brAIn's own memory, not Morph's lessons.

## Learning

Morph keeps a log of what you use: what you open, toggle and slide, when, and
what you ask brAIn for. It never leaves your house.

On a schedule (daily by default), Morph asks brAIn — **read-only**, so the
pass can look at the house but change nothing — how the **dashboard** could
be better for how it is actually used. This loop is about the dashboard
only: learning the house is brAIn's own job, so a pass suggests no
automations or renames and its lessons are rules about how you want your
dashboard. What comes back:

- **Suggestions**, filed as brAIn's cases and drawn in the room they are
  about. Answer in words or with the buttons: a yes hands the suggestion to
  brAIn as an ordinary Tell, Dismiss hides it for now, and a no (with a
  reason, if you like) means it is never suggested again.
- **Lessons**, revised each pass in `/config/morph/LEARNED.md`. Every Tell
  and every pass reads them. Each line ends with who wrote it: **(you)**,
  **(tell)** (brAIn during a Tell) or **(learned)** (a pass). A line you
  write — or any line with no mark — is never reworded or dropped by Morph.
  A pass adds a lesson only with two pieces of evidence or a reason you
  typed; a reason you give for No is read as evidence, not written down as a
  rule. Edit them in **Settings → Learning** or in the file.
- **A broken card of your own**: when a file in `cards/` will not load,
  Morph offers **Fix the card code …** as a suggestion, since that code is
  this house's and a Tell fixes it.
- **A change to Morph itself**: something the pass thinks Morph's own code
  should do differently, with **Do it** (brAIn changes your copy of Morph,
  then asks whether to open an issue), **Send as issue** (only report it) and
  **No**. Nothing is sent until you press Send or Open an issue.

A pass that fails (brAIn stopped, signed out, out of time) is tried again on
the next schedule; it does not count as having read what you did.

**Settings → Learning** shows the scorecard: how many suggestions were made,
done and declined, and how many of brAIn's changes were kept or undone.

Turn learning off in Settings, or with the `learning` option.

## Changing Morph itself

Nothing about Morph is out of reach. Morph's own panel is a handful of
modules in `/config/custom_components/morph/frontend/`. To change one, brAIn
copies it into `/config/morph/frontend/` and edits the copy, and Morph serves
your copy in place of its own after a page reload.

- **It is one change like any other.** It is in History, and Undo puts
  Morph's own back.
- **A copy that does not load is not a blank page.** Morph runs its own copy
  for that page load and says what went wrong.
- **An update can pause a copy.** If a Morph update changes one of the files
  you changed, or another of Morph's modules your copy builds on, your change
  is **paused** and Morph's own runs, because an old copy beside new modules
  is how a panel breaks. One note says so and names what changed, with two
  choices: **Update** merges your changes into the new version — every
  paused file in one press and one change you can undo — and **Not now**
  keeps Morph's own version running, with your changes paused until you
  update them later. Where the update rewrote the same code a change was
  in, brAIn does not guess: it asks how to bring them together, with a
  button for each way and one for Morph's own, merges everything else, and
  only that file stays paused until you pick. Your dashboard and your own
  cards (`cards/`) are never touched by an update.

**Settings → Improving Morph itself** lists every change, whether it is in
use or paused, with **Update** for a paused one (and **Update all** when
there are several) and **Remove my change** to go back to Morph's own.

## When Morph's own code fails

A card that fails to draw, a layout that overlaps at rest, or an answer from
brAIn that Morph could not read is a fault in Morph, not in your dashboard,
and is recorded on its own. A request that needs Morph's code changed is
recorded only when you press **Open an issue** or **Send as issue**, in the
Tell box or on a note. A change brAIn made to Morph's code goes with the
issue as a patch. brAIn being slow or signed out is not Morph's
fault and is not recorded. Morph keeps a ledger of these and publishes it to
`/config/.morph/devloop/outbox.json`.
brAIn's development loop (brAIn ⚙ → Developer) reads it as its **Morph**
stream and files each fault once in your private reports repository, where
the cloud routine fixes it in Morph's code and the fix arrives as an update.

**Report something yourself.** Settings → Improving Morph itself → *What do
you want to fix in Morph?* takes your own words. Tick *It is about how Morph
looks* when it is, and **Send**. They go as they are, by the same route, and
are listed with **Take back** until brAIn picks them up.

Nothing leaves your house unless brAIn's development loop is on. Turn
reporting off in Settings or with `report_code_issues`.

## Settings

The gear in Morph's top bar opens its Settings page.

| Section | What is there |
|---|---|
| **brAIn** | Whether brAIn is reachable, the model Tell uses, how long a hold takes. |
| **Learning** | On or off, how often, which model, **Learn now**, the scorecard, suggestions waiting, the lessons. |
| **Improving Morph itself** | Report Morph's own problems on or off, the changes this house made to Morph's code, and when brAIn last picked reports up. To report something yourself, say it in Ask. |
| **This device** | Whether this screen is somebody’s own or the family’s, whose habits lead on it, and **Fold quiet rooms**. |
| **Appearance** | Theme (auto, dark, medium, light) and reduced motion. |
| **History** | Every change with who made it, and **Undo** or **Restore** for each. |
| **Dashboard** | **Rebuild from the house** (itself a commit you can undo). |

## The dashboard file

`/config/morph/` is a git repository:

| File | What it is |
|---|---|
| `dashboard.yaml` | The dashboard: floors → sections → groups → cards. |
| `AGENTS.md` | How Morph is built, for brAIn: the schema, the card types, the design rules. |
| `LEARNED.md` | What this household has taught Morph. |
| `cards/` | Custom card code brAIn writes (a Lovelace custom element per file). |

You can edit any of them by hand; Morph commits your edit as *Edited outside
Morph*. If the file stops parsing, the panel keeps showing the last version
that did, with the parser's message and line above it, until the file is
fixed.

A minimal `dashboard.yaml`:

```yaml
title: Home
floors:
  - title: Ground
    sections:
      - title: Kitchen
        color: amber
        width: 2
        groups:
          - cards:
              - type: scenes
                entities: [scene.kitchen_cook, scene.kitchen_off]
              - entity: light.kitchen_countertop
              - type: lovelace
                card:
                  type: custom:mushroom-entity-card
                  entity: sensor.fridge_temperature
```

## Options

| Option | Default | What it does |
|---|---|---|
| `enable_ha_integration` | on | Install the `morph` integration, which is what puts Morph in the sidebar. |
| `learning` | on | The learning loop. Also in Settings. |
| `report_code_issues` | on | Hand Morph's own faults to brAIn's development loop. Also in Settings. |
| `log_level` | info | The add-on's own logging. |

## Security

Morph publishes no port and uses no ingress: its page is a Home Assistant
panel, served by Home Assistant to signed-in users, and its writes need an
administrator. The add-on runs under its own AppArmor profile, and its
service listens only on loopback for its own health check. The dashboard
folder is handed to brAIn's `claude` user so brAIn can edit it.

## Troubleshooting

**Morph is not in the sidebar.** Accept the Morph integration under
**Settings → Devices & services**, then restart Home Assistant once. After an
update, restart Home Assistant again so the new integration loads. If the tile
never appears, check that *Install the Morph integration* is on in the
add-on's Configuration tab.

**Tell says nothing is listening.** Switch on brAIn's *Automation
integration* and restart brAIn.

**A Lovelace card shows an error.** The card's own resource has to be loaded
in Home Assistant (HACS, or **Settings → Dashboards → Resources**); Morph
uses the same card registry as every other dashboard.
