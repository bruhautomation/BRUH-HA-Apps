# brAIn

**Give your smart home a mind.**

brAIn puts Claude inside Home Assistant with full run of the place — every entity,
every device, every area, floor, label, dashboard, helper, automation and add-on. It
reads your history, edits your configuration, fixes what's broken, remembers what you
tell it, and answers when you speak to it.

One add-on. One panel. One Claude login. It runs on your own Claude subscription.

## What it does

| | |
| --- | --- |
| **Runs Home Assistant** | 36 native tools for reading and controlling, 65 registry-management services for the parts that normally live behind the Settings UI, and a real shell in `/config` for everything that's still YAML. Areas, floors, labels, devices, entities, integrations, helpers, zones, people, users, dashboards, blueprints, statistics — create, rename, move, disable, delete. |
| **Finds what's broken** | A dead battery, a sensor that quietly stopped reporting, a device stuck unavailable, an automation that can never fire. Press **Fix it** and it makes the change; press **Not a problem** and it never raises that one again. |
| **Explains your house** | Insight cards with real interactive visualisations, chosen for *your* home rather than shipped as defaults. Ask anything and get a card back; keep the good ones as recurring, or drop any of them on a dashboard. |
| **Remembers** | One editable document of durable facts about your home — nicknames, household rhythms, the devices that are meant to behave oddly. Learned from conversations, insight runs and study sessions, and read by every part of brAIn. |
| **Talks** | A conversation agent for Assist, answering in a few seconds from a pool of pre-warmed workers, with your memory and an area map already in the prompt. |
| **Has a terminal** | The real Claude Code CLI in your browser, in two shapes: **Chat** renders it as a conversation that reflows to a phone, **Classic** is a true terminal for anything that draws its own screen. Same session behind both. |

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

[DOCS.md](DOCS.md) covers every capability and every option, and the same guide is in
the panel's **Docs** tab.

## License

MIT. BRUH Power Tools is adapted from [Spook](https://github.com/frenck/spook) (MIT).
