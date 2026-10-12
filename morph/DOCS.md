# Morph — documentation

> ## ⚠️ Experimental — not recommended for general use yet
> **Morph is being built in the open and is not finished.** Expect missing
> cards, rough edges and changes between updates that move things around
> without warning. Install it to try it out alongside your normal
> dashboards, not to replace them. Morph only writes its own folder
> (`/config/morph`) — every change there is a version you can undo — but a
> Tell lets brAIn change the house too, so keep an eye on what it does.

Morph is a Home Assistant add-on and integration. The add-on runs a small
service that owns the dashboard file and its history; the integration
registers the **Morph** sidebar panel, which runs inside Home Assistant's own
frontend.

- [Installing](#installing)
- [Using the dashboard](#using-the-dashboard)
- [Edit mode](#edit-mode)
- [Tell brAIn](#tell-brain)
- [Learning](#learning)
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

## Using the dashboard

| Gesture | Does |
|---|---|
| **Tap** | The main thing: toggle a light, play, lock. A garage door and an unlock ask for a second tap. |
| **Slide** | A level: brightness, fan speed, blind position. |
| **Hold** | Opens the card in place with its options and its history. |
| **Tap outside** | Folds everything back. |

History is what Home Assistant records for that kind of thing: a light's day
as a strip of on and off, a sensor's readings as a line you can scrub, a
meter's week as bars. Tap a day or a bar to see its hours, and the logbook's
"who" for each change.

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
and say what should change. The box shows what brAIn will receive
(**What brAIn receives**) and **Send** hands it over.

brAIn **acts at once**. It may change:

- the dashboard (`/config/morph/dashboard.yaml`),
- Morph's card code (`/config/morph/cards/`),
- the house behind it: automations, scripts, helpers and scenes.

The steps appear in place as it works. When it answers, Morph commits the
dashboard half as one change and shows **Keep**, **Undo** and **Tell it
more**. Undo reverts that commit exactly, and if brAIn changed anything in
the house, asks brAIn to put that back too.

What still holds whatever you ask: brAIn's `protected_entities`, its action
gate and its edit snapshots (`brain undo`).

## Learning

Morph keeps a log of what you use: what you open, toggle and slide, when, and
what you ask brAIn for. It never leaves your house.

On a schedule (daily by default), Morph asks brAIn — **read-only**, so the
pass can look at the house but change nothing — how the dashboard could be
better for how it is actually used. What comes back:

- **Suggestions**, shown in place on the dashboard with **Do it**, **Not
  now** and **No**. Do it hands the suggestion to brAIn as an ordinary Tell.
  Not now hides it for a week. No (with a reason, if you like) means it is
  never suggested again.
- **Lessons**, rewritten each pass into `/config/morph/LEARNED.md`. Every Tell
  and every pass reads them. Edit them in **Settings → Learning** or in the
  file.

**Settings → Learning** shows the scorecard: how many suggestions were made,
done and declined, and how many of brAIn's changes were kept or undone.

Turn learning off in Settings, or with the `learning` option.

## When Morph's own code fails

A card that fails to draw, a layout that overlaps at rest, or a request Morph
could not carry out is a fault in Morph, not in your dashboard. Morph keeps a
ledger of them and publishes it to `/config/.morph/devloop/outbox.json`.
brAIn's development loop (brAIn ⚙ → Developer) reads it as its **Morph**
stream and files each fault once in your private reports repository, where
the cloud routine fixes it in Morph's code and the fix arrives as an update.

Nothing leaves your house unless brAIn's development loop is on. Turn
reporting off in Settings or with `report_code_issues`.

## Settings

The gear in Morph's top bar opens its Settings page.

| Section | What is there |
|---|---|
| **brAIn** | Whether brAIn is reachable, the model Tell uses, how long a hold takes. |
| **Learning** | On or off, how often, which model, **Learn now**, the scorecard, suggestions waiting, the lessons. |
| **Improving Morph itself** | Report Morph's own problems on or off, and when brAIn last picked them up. |
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
