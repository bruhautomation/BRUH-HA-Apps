# brAIn

**Your house already has nerves. Now give it a brAIn.**

Claude plus a suite of new tools hands it the keys. Stop programming your house — let it
think.

**📖 Full documentation: [bruhautomation.com/brain](https://bruhautomation.com/brain/)** —
install guide, every feature with worked examples, the service and tool reference, and the
changelog. This page is the short version.

## What it is

A Home Assistant add-on that runs Claude Code and a suite of tools inside HA, which builds
a permanent memory of your house.

It sees the whole system — every entity, device, area, floor, dashboard, helper and
automation — and it can change any of it. Explain a broken automation. Fix it. Write a new
one. Remember why, next time.

That memory isn't a black box. Open it, read it, edit it, correct it. An insights panel
shows what it knows about your house and what it's done there — in the sidebar, or embedded
straight into your dashboards.

Reach it however you want: as your conversation agent, through a full-featured chat
interface, or from native Claude Code. Your automations can call it too — which means your
house can ask for help before you notice anything's wrong.

One install, one sidebar panel, one login. Runs on the Claude **Pro** or **Max**
subscription — or your own API key.

![The brAIn Insights tab: an ask bar, tag filters, and insight cards — one answering "Why
did the hallway light come on at 3 am?" with a trace timeline, one showing a month of
electricity by device](../docs/images/panel-insights.webp)

## What it does

| | |
| --- | --- |
| **Runs Home Assistant** | 36 native tools for reading and controlling, 65 registry-management services for the parts that normally live behind the Settings UI, and a real shell in `/config` for everything that's still YAML. Areas, floors, labels, devices, entities, integrations, helpers, zones, people, users, dashboards, blueprints, statistics — create, rename, move, disable, delete. |
| **Finds what's broken** | A dead battery, a sensor that quietly stopped reporting, a device stuck unavailable, an automation that can never fire. Press **Fix it** and it makes the change; press **Not a problem** and it never raises that one again. |
| **Explains your house** | Insight cards with real interactive visualisations, chosen for *your* home rather than shipped as defaults. Ask anything and get a card back; keep the good ones as recurring, or drop any of them on a dashboard. |
| **Remembers** | One editable document of durable facts about your home — nicknames, household rhythms, the devices that are meant to behave oddly. Learned from conversations, insight runs and study sessions, and read by every part of brAIn. |
| **Talks** | A conversation agent for Assist, answering in a few seconds from a pool of pre-warmed workers, with your memory and an area map already in the prompt. |
| **Has a terminal** | The real Claude Code CLI in your browser, in two shapes: **Chat** renders it as a conversation that reflows to a phone, **Classic** is a true terminal for anything that draws its own screen. Same session behind both. |

![The brAIn Findings tab, headed "What brAIn thinks is broken", listing a dead back-door
battery sensor, thirteen orphaned entities, and two loft sensors that never rejoined after a
Zigbee channel change — each with Fix it, Discuss, I've fixed it, Remind me later and Not a
problem here](../docs/images/panel-findings.webp)

## Try it in one line

In the panel's ask bar:

```
why is the upstairs cold in the morning?     → an answer card, with a chart
which of my sensors have stopped reporting?  → the same, and anything broken
                                                lands in Findings
learn about my energy usage                  → a study session: minutes of
                                                digging, filed into Memory
```

In the terminal, or out loud to Assist:

```
build me a dashboard for the garage with the door, the freezer and the lights
rename every "Sonoff Switch 3" to what it actually is
why didn't the porch light automation fire last night?
```

![The brAIn Terminal tab in chat mode, tracing a 3 am light through the logbook and an
automation trace, then editing the automation, validating the YAML and reloading the
domain](../docs/images/panel-terminal.webp)

## The CLI

Two commands, split by what they act on:

```bash
brain memory add "The garage fridge is meant to run 24/7"
brain memory list             # what it knows
brain learn energy            # study a topic and write down what it finds
brain undo                    # review and revert Claude's file edits
brain doctor                  # end-to-end diagnostic

ha log                        # tail the Home Assistant log
ha reload automations
ha entity list light
ha context                    # regenerate /config/CLAUDE.md
```

`brain help` and `ha help` list the rest.

## Undo

Before Claude writes to any file under `/config`, the previous version is snapshotted;
`brain undo` puts it back — one edit, or everything from today.

brAIn does **not** back up your config. Use Home Assistant's own backups — they're
whole-system, restorable, and already solved.

## Documentation

**[bruhautomation.com/brain](https://bruhautomation.com/brain/)** is the full
documentation — a page per feature with worked examples, the configuration reference, and
the changelog.

Two offline copies ship with the add-on and say the same things: [DOCS.md](DOCS.md), which
Home Assistant renders on the add-on's **Documentation** tab, and the panel's own **Docs**
tab, which is searchable and works with no internet at all.

## License

MIT. BRUH Power Tools is adapted from [Spook](https://github.com/frenck/spook) (MIT).
