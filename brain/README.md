# brAIn

**Your house already has nerves. Now give it a brAIn.**

Claude plus a suite of new tools hands it the keys. Stop programming your house — let it
think.

**📖 Full documentation: [bruhautomation.com/brain](https://bruhautomation.com/brain/)** —
install guide, features with worked examples, the service and tool reference, and the
changelog. This page is the short version.

> ### Back up Home Assistant first — somewhere that isn't on the same machine it runs on.
>
> brAIn edits your real configuration: automations, dashboards, helpers, entities. It is
> built to be careful, it snapshots files before it changes them, and `brain undo` puts
> them back. None of that is a backup. Something could still go wrong — be prepared.
>
> **Settings → System → Backups**, then copy it off the device.

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

![The brAIn Insights tab: an ask bar, tag filters, and two insight cards — "Why did the
hallway light come on at 3 am?" with a trace timeline, and "Downstairs dries 15 min before it
cools" with humidity and temperature charts](https://raw.githubusercontent.com/bruhautomation/BRUH-HA-Apps/main/docs/images/panel-insights.webp)

## What it does

| | |
| --- | --- |
| **Runs Home Assistant** | 71 native tools for reading and controlling (ESPHome devices and Music Assistant included), 65 registry-management services for the parts that normally live behind the Settings UI, and a real shell in `/config` for everything that's still YAML. Areas, floors, labels, devices, entities, integrations, helpers, zones, people, users, dashboards, blueprints, statistics — create, rename, move, disable, delete. |
| **Finds what's broken** | A dead battery, a sensor that quietly stopped reporting, a device stuck unavailable, an automation that can never fire. Every card takes the same answers: **Fix it** (it shows you the plan first and changes nothing until **Apply**, and **Undo** puts the files back), **Add to list**, **Dismiss** and **Not a problem** — say why, and it never makes that mistake again in new words. Every one waiting on you is also on Home Assistant's own Repairs page and your phone, with the same buttons. |
| **Explains your house** | Ask anything and get a card: the answer first, the numbers it rests on, and a chart drawn for your data. **Refine** a card by saying what should change; **Share** it as a picture or add it to a dashboard in one press. **Ideas** suggests the cards your house is missing. |
| **Remembers** | One editable document of durable facts about your home — nicknames, household rhythms, the devices that are meant to behave oddly. Learned from conversations, insight runs and study sessions, and read by every part of brAIn. |
| **Measures** | Seven things it works out for itself, overnight, from what Home Assistant already records and with no Claude run at all: when the house gets up, what each reading normally is at this hour of this week, how fast each room loses heat, how much of each hour a door is open, what each machine's own power looks like, what you keep doing by hand, and what the electricity did. The **Knowledge** tab shows all seven and how far along each one is — because every one has a floor under it, and weeks of honest silence looks exactly like something being broken. |
| **Says when it breaks** | The moment a run fails, a daemon dies or a notification cannot be delivered, brAIn writes the evidence down by itself — one plain-text file under `/share/brain/reports/`, redacted, listed under ⚙ → **Problems** with a Copy button, and mirrored as an entry on Home Assistant's own Repairs page. |
| **Talks** | A conversation agent for Assist, answering in a few seconds from a pool of pre-warmed workers, with your memory and an area map already in the prompt. |
| **Runs your devices** | **ESPHome**: edit, validate, flash over the air and stream logs for every device, from the panel or by asking. **Music Assistant**: control players and clear out the stale speakers Home Assistant can't delete. |
| **Has a terminal** | The real Claude Code CLI in your browser, in two shapes: **Chat** renders it as a conversation that reflows to a phone, **Classic** is a true terminal for anything that draws its own screen. Same session behind both. |

![The Findings tab, headed "What's waiting on you": a "Back door battery has reported nothing
since 26 July" card and a "Two loft sensors never rejoined after the Zigbee channel change"
card, each with its evidence, how you'd fix it, and Add to list, Dismiss and Not a
problem](https://raw.githubusercontent.com/bruhautomation/BRUH-HA-Apps/main/docs/images/panel-findings.webp)

## Try it in one line

In the ask bar on **Home → Insights**:

```
how quickly does downstairs dry out when the AC turns on?   → a card with the answer
which of my sensors have stopped reporting?                 → the same, and anything
                                                              broken lands in Findings
whenever the front door opens after dark, turn on the hall  → a rule, replayed over the
light                                                         last month before it's offered
learn about my energy usage                                 → a study session, filed
                                                              into memory
```

![An insight card, "Downstairs dries 15 min before it cools": the answer in bold, five
number tiles and two charts of humidity and temperature over three cooling
cycles](https://raw.githubusercontent.com/bruhautomation/BRUH-HA-Apps/main/docs/images/insight-card.webp)

Not quite right? **✎ Refine** → *"compare it with upstairs"*. Want it elsewhere? **↗ Share**
copies it as a picture or adds it to a dashboard:

![The Share dialog: the card drawn as a picture with Copy picture and Download, and an "On a
dashboard" section with Dashboard, View and Show pickers and an Add card
button](https://raw.githubusercontent.com/bruhautomation/BRUH-HA-Apps/main/docs/images/insight-share.webp)

In **Ask** (the chat, or a real terminal), or out loud to Assist:

```
build me a dashboard for the garage with the door, the freezer and the lights
rename every "Sonoff Switch 3" to what it actually is
add a DHT22 on GPIO4 to the garage ESPHome sensor and install it
why didn't the porch light automation fire last night?
```

![The Ask tab in chat mode, tracing a 3 am light through the logbook and an automation
trace, then editing the automation, validating the YAML and reloading the
domain](https://raw.githubusercontent.com/bruhautomation/BRUH-HA-Apps/main/docs/images/panel-terminal.webp)

## The CLI

Two commands, split by what they act on:

```bash
brain memory add "The garage fridge is meant to run 24/7"
brain memory list             # what it knows
brain learn energy            # study a topic and write down what it finds
brain undo                    # review and revert Claude's file edits
brain check                   # run the house checks now — no Claude run
brain findings                # what's waiting on you, and answer it from here
brain doctor                  # end-to-end diagnostic (--json for a verdict)
brain doctor --deep           # every face, one real round trip each
brain report                  # one redacted text file for a bug report

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
Home Assistant renders on the add-on's **Documentation** tab, and the panel's own **Help**
tab, which is searchable and works with no internet at all.

## Credits

The web terminal at the heart of this add-on began as
[Claude Terminal](https://github.com/heytcass/home-assistant-addons) by Tom
Cassady — that add-on is what showed Claude Code could live inside Home
Assistant behind ingress at all. BRUH Terminal was built on it, and brAIn is
what BRUH Terminal grew into.

BRUH Power Tools is adapted from [Spook](https://github.com/frenck/spook) by
Franck Nijhof (MIT).

## License

MIT.
