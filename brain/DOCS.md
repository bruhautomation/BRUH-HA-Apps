# brAIn

**Your house already has nerves. Now give it a brAIn.**

Claude plus a suite of new tools hands it the keys. Stop programming your house — let it
think.

> ### Back up Home Assistant first — somewhere that isn't this machine.
>
> brAIn edits your real configuration: automations, dashboards, helpers, entities. It is
> built to be careful, it snapshots files before it changes them, and `brain undo` puts
> them back. None of that is a backup you can restore from if something goes wrong.
>
> **Settings → System → Backups**, then copy it off the device. A backup that only exists
> on the machine you are changing is the one you cannot use when that machine is the
> problem.

A Home Assistant add-on that runs Claude Code and a suite of tools inside HA, which builds
a permanent memory of your house.

It sees the whole system — every entity, device, area, floor, dashboard, helper and
automation — and it can change any of it. Explain a broken automation. Fix it. Write a new
one. Remember why, next time.

That memory isn't a black box. Open it, read it, edit it, correct it. An insights panel
shows what it knows about your house and what it's done there — in the sidebar, or
embedded straight into your dashboards.

Reach it however you want: as your conversation agent, through a full-featured chat
interface, or from native Claude Code. Your automations can call it too — which means your
house can ask for help before you notice anything's wrong.

One install, one sidebar panel, one login. Runs on the Claude **Pro** or **Max**
subscription — or your own API key.

---

- [What it can do](#what-it-can-do)
  - [It runs Home Assistant](#it-runs-home-assistant)
  - [It finds what's broken — and fixes it](#it-finds-whats-broken--and-fixes-it)
  - [It explains your house to you](#it-explains-your-house-to-you)
  - [It remembers](#it-remembers)
  - [It answers when you talk to it](#it-answers-when-you-talk-to-it)
  - [It has a full terminal](#it-has-a-full-terminal)
  - [It works while you're asleep](#it-works-while-youre-asleep)
  - [Everything it does can be undone](#everything-it-does-can-be-undone)
- [Setup](#setup)
- [The panel](#the-panel)
- [The CLI](#the-cli)
- [Configuration options](#configuration-options)
- [What it costs](#what-it-costs)
- [What it will not do](#what-it-will-not-do)
- [Ports](#ports)

---

## What it can do

### It runs Home Assistant

Most AI integrations can turn on a light. brAIn administers the installation.

It reaches Home Assistant three ways at once — a **native MCP server** (36 tools) for
reading and controlling, **65 registry-management services** for the parts of Home
Assistant that normally only exist behind the Settings UI, and a **real shell** in
`/config` for everything that is still a YAML file.

**Organisation.** Create, rename and delete **areas**, **floors** and **labels**; set
their icons and aliases; move devices and entities between them; put areas on floors.
Ask it to reorganise a house that grew by accident — "every light in the basement
should be in a Basement area under a Lower Floor" — and it does the whole sweep.

**Devices and entities.** Rename either. Change an `entity_id`. Set icons and voice
aliases. Hide, unhide, enable and disable. Find references to entities and devices
that no longer exist, and clean them up — dry-run by default, so you see the list
before anything goes.

**Integrations.** Reload one without restarting Home Assistant. Enable, disable, or
remove one entirely.

**Helpers, zones, people, users.** Create and delete input helpers, timers, counters
and schedules. Draw a zone or edit its radius. Add a person, attach their device
trackers. Create a user, disable one, remove one.

**Dashboards.** List them, read them, create them, rewrite them, restore a previous
version, reset one to defaults, and manage dashboard resources. brAIn can build you a
dashboard from a sentence describing what you want on it.

**Automations, scripts and scenes.** It reads and edits the YAML directly, validates
it, reloads the domain, and then reads the **traces** to see whether the thing
actually fired and why it didn't. That last part is what turns "write me an
automation" from a party trick into something that works on the second try.

**The house's own record.** History and long-term statistics, the logbook, the error
log, the Supervisor's view of your add-ons, weather forecasts, camera snapshots
(it *sees* the image), rendered templates, and every service any integration exposes.

**Add-ons.** List, start, stop, restart and read the logs of your other add-ons.

If it exists in Home Assistant, brAIn can look at it, and — with a handful of
deliberate exceptions listed [below](#what-it-will-not-do) — change it.

> **Nothing is create-only.** Every attribute a `create_*` service accepts has a
> service that changes it afterwards, and everything that can be created can be
> renamed and deleted. A test asserts that, because a tool that can make a mess and
> not clean it up is worse than no tool.

### It finds what's broken — and fixes it

A **finding** is something wrong with your house: a battery about to die, a sensor
that quietly stopped reporting three weeks ago, a device stuck `unavailable`, an
automation whose trigger can never fire.

brAIn files findings on its own, from scheduled analysis and from study sessions.
Each one gets a severity, a plain-English explanation, and what to do about it:

- **Fix it** — brAIn makes the change and reports back what it did. This is the *only*
  place the add-on runs Claude with tools on its own initiative, it is bounded to one
  finding, and it only ever happens because you pressed the button.
- **Discuss** — hands it to the chat with everything brAIn knows about it and asks
  whether it really is a problem *here*. The discussion changes nothing; the decisions
  ride along above the composer, so agreeing to the fix at the end of it is one press.
- **I did it** — you handled it yourself. brAIn remembers that you did.
- **Remind me later** — an hour, tomorrow, next week, next month. Not a decision: the
  finding stays exactly as open as it was and simply stops asking, and it waits under
  the **Later** filter with the date it comes back.
- **Not a problem** — dismissed for good. Dismissed findings are injected into every
  future analysis, so the same non-problem is never raised at you twice. The garage
  fridge that runs 24/7 gets flagged once.

### It explains your house to you

The **Insights** dashboard is a set of cards, each one a small piece of analysis with
a real interactive visualisation — not a paragraph of text with a number in it.

There are **no default cards**, deliberately. A generic "Energy" card about a home
brAIn has never looked at says nothing useful and costs tokens every time it runs.
Instead the first run studies *your* house — how it's named, when it's occupied, what
it uses, how its devices behave — and proposes cards grounded in what it found, each
with a one-line reason.

- **Ask anything.** Type a question and get a card back: "why is the upstairs cold in
  the morning", "which of my devices are costing the most", "did anyone open the back
  door while we were out". Keep the ones worth having weekly with **＋ Make recurring**.
- **Put them on your dashboard.** Any card gives you ready-to-paste YAML for a Webpage
  card, so an insight can live on your own dashboard next to everything else.
- **Tags and filters.** Cards carry tags brAIn assigns; the chips at the top filter by
  them, and you can edit any card's tags.
- **Feedback that sticks.** Tell a card what to do differently — "ignore the guest
  room", "show costs in dollars" — and the next run obeys.
- **Schedules you control.** Per-card, either an interval or fixed times of day.

### It remembers

Everything else here is a feature. This is the part that makes brAIn get *better*.

brAIn keeps one plain-markdown document of durable facts about your home. Not a chat
history — a curated document: your nicknames for rooms, which devices are meant to
behave oddly, when your household actually wakes up, what you've corrected it on.

Facts arrive from voice conversations (when you state a preference, it writes it
down), from insight runs, from study sessions, from the CLI, and from a service any
automation can call. A background consolidator folds them into the document, and
**you can edit the document yourself** — your edits are the source of truth.

Every part of brAIn reads the same memory. Tell the voice assistant something and the
Insights cards know it.

It also keeps a short list of **hypotheses** — things it thinks might be true and
isn't sure about. Never more than three waiting on you, each expiring in a fortnight.
Answer yes and it becomes a plain memory line; answer no and it stops guessing that.
It never interrogates you with a questionnaire.

**Study sessions** send it off to investigate: `brain learn energy`, or just type
"learn about the upstairs heating" in the ask bar. It digs through the registry,
history and long-term statistics for minutes at a time, and what it finds lands in
memory and in your findings list.

### It answers when you talk to it

brAIn registers as a **conversation agent**, so you can pick it in Settings → Voice
Assistants and talk to it from any Assist pipeline, satellite or the app.

- **Fast.** A pool of pre-warmed Claude workers answers in a few seconds rather than
  cold-starting a CLI per request, and an area→entity map is baked into the prompt so
  most commands skip lookup turns entirely.
- **It knows your house.** The same memory, spliced into every voice prompt. "Turn on
  the beacon" works if you once told it what the beacon is.
- **It follows a conversation.** Follow-up turns resume the same session.
- **Its reach is yours to set.** By default voice can only touch Home Assistant —
  states, services, the registries. One setting widens it to the full toolset, shell
  and file edits included.

### It has a full terminal — in two shapes

The **Terminal** tab is the real Claude Code CLI, in your browser, running as a
non-root user with your `/config` in front of it. Everything above, plus everything a
capable engineer with a shell can do: read logs, edit YAML, write scripts, install
packages, use git, take the long way round a hard problem.

It has two faces, and you switch between them with the **⌨/💬 button on the tab
itself** (or in ⚙ Settings). Both run the same Claude Code, on the same login, in the
same `/config`, with the same permissions — what differs is only how you see it.

**Chat** (the default) renders Claude Code's own output as a conversation:

- **Text reflows** to whatever screen you're on. A terminal is a grid of fixed
  columns; at the ~40 columns a phone has, that means sentences broken mid-word. This
  is ordinary text, so it wraps like text.
- **Code blocks keep the grid** — inside their own horizontal scroller, so a
  200-column log line never makes the whole page slide sideways.
- **Tool calls collapse to one line each.** `Read /config/automations.yaml`, with a
  dot that goes green or red; tap it for the arguments and the full result. In the
  grid terminal each of those was twenty lines you scrolled past.
- **Reasoning folds away** behind a "Thinking" line you can open.
- **Commands, both kinds.** Type **/** and you get the commands *your* Claude Code
  actually has — including anything you put in `/config/.claude/commands`. Type
  **brain** or **ha** and you get brAIn's own CLI, `brain memory add` through
  `ha reload`, with the same descriptions and argument hints the dispatchers print.
  ↑/↓ to move, Enter or Tab to pick. Both lists come from the thing that owns them, so
  neither can go stale.
- **⋯ holds the rest** — *New chat*, *Conversations* (every conversation in `/config`,
  started here or in the classic terminal; picking one replays it and carries on),
  *Session details*, *Model*, and the switch to Classic. Two buttons float over the
  terminal, not a column of them.
- **The chat picks its own model.** Press the model name under the message box (or
  ⋯ → *Model*) and choose — the current conversation carries straight on under the
  new model. It's the chat's own setting: insights and voice keep following the
  model on the Configuration tab, so a heavyweight model chosen for one
  conversation never quietly raises what everything else costs. *Default* follows
  the Configuration tab again.
- **Conversations can be deleted.** Every row in the list grows a **✕**, and the
  toast grows an **Undo** for the few minutes a mis-tap needs. The conversation
  you're in is refused — start a new chat first. (Old conversations that Claude
  Code itself has pruned can no longer be picked up mid-thought: reopening one
  shows its transcript and says plainly that the next message starts fresh,
  instead of erroring on every send.)
- **Yours, and everyone else's.** brAIn runs Claude in `/config` for voice, automation
  tasks and filing memory, so those conversations live beside yours. The list shows
  yours by default and puts the rest behind a chip each — *Voice*, *Automation*,
  *Memory*, *Study* — with a count, and only for the ones your house actually uses.
- **The input is a real text box**, so dictation, autocorrect and selection behave.
- **⏹ stops a running answer**, and **＋ starts a new chat**. The conversation
  survives a page reload, a phone locking, and the add-on restarting.
- **Session details** (under ⋯) shows the model, the project directory, how you're
  being billed, and the conversation's id. **Continue in the terminal** opens Classic
  *inside* this conversation: the chat releases it, and the terminal picks it up — a
  new tmux window if it's already open, otherwise the next time you open it.

Both faces stand in `/config`, which is what lets them see each other's
conversations at all: Claude Code files them per working directory. So `claude
--resume` in the terminal lists the chats you had in the panel, ⟲ in the chat lists
the ones you had in the terminal, and a conversation can move either way without
losing anything.

**Classic** is ttyd over tmux — a true terminal. Use it for anything that draws its
own screen (a TUI, `htop`, an installer), for running shell commands yourself, or
simply because you prefer it.

- **Native Home Assistant access** through the same MCP server the rest of brAIn uses.
- **`/config/CLAUDE.md` written for you** at startup, describing your actual
  installation, so a fresh session already knows your house.
- **Built for a phone**, not merely tolerable on one: a key toolbar that stays above
  the software keyboard, working copy/paste, swipe-scroll, an iOS dictation fix, and
  a top bar that folds away while you're typing so the terminal gets the screen.
- **Sessions survive.** tmux underneath, so a dropped connection doesn't kill your
  work, and the environment persists across restarts.

### It works while you're asleep

- Recurring insight cards regenerate on their own schedule.
- Memory consolidates in the background.
- Automations can hand brAIn work: `brain.run_task` gives it a job and lets it use
  tools, `brain.send_prompt` asks it a question, `brain.run_insight` regenerates a
  card, `brain.study` sends it off to research something, `brain.add_memory` teaches
  it a fact. Wire them to any trigger you like.
- Insight jobs render to `sensor.<name>_insight` with the markdown and ready-to-paste
  card YAML as attributes, so a report can drive a template, a notification, or a
  dashboard.

### Everything it does can be undone

Before Claude writes to any file under `/config`, brAIn snapshots the previous
contents. `brain undo` lists what changed and puts any of it back — one edit, or
everything from today. `secrets.yaml` is never snapshotted.

That covers Claude's edits. For the house as a whole, use Home Assistant's own
backups: they're whole-system and restorable, and brAIn deliberately does not
duplicate them (see [What it will not do](#what-it-will-not-do)).

---

## Setup

1. **Install and start the add-on.**
2. **Open the panel** from the sidebar and connect your Claude account. Easiest route:
   open the **Terminal** tab, run `claude`, and sign in there — the rest of brAIn
   picks that login up. The panel also offers a guided sign-in and a paste-a-token
   box. This is the **only** login; terminal, insights, voice, findings and memory all
   share it.
3. **Accept the integration.** Home Assistant offers to set up **brAIn** via
   discovery. That's what provides the services, the sensors and the voice assistant.
4. **Press Start learning.** brAIn studies your home for a few minutes in the
   background, then proposes the cards this particular house should have. You pick
   which to keep.

A **Claude Pro or Max subscription** is the cheapest way to run brAIn — it uses the
plan you already pay for rather than API credits. An API key works too.

> **If your home is too sparse to learn from**, brAIn says what's missing rather than
> inventing generic cards. Add entities, let some history accumulate, run it again.

## The panel

One ingress panel, five tabs.

| Tab | What's there |
| --- | --- |
| **Insights** | Your cards, and the ask bar that makes new ones. A question becomes a card; a line starting "learn about…" starts a study session instead. |
| **Findings** | What brAIn thinks is broken, with **Fix it** and **Not a problem**. A count on the tab means something is waiting on you. |
| **Terminal** | Full Claude Code, served through the panel — no second sidebar entry, no second login. Two faces: **Chat** (the default: the same session rendered as messages) and **Classic** (ttyd + tmux). Switch with the button on the tab, or in ⚙ Settings. Press ⤢ to give either the whole screen. |
| **Memory** | The memory document, editable, plus the queue behind it and any hypotheses waiting on a yes/no. |
| **Docs** | This guide, in the panel. |

`enable_terminal` and `enable_insights` switch either face off; the panel itself
always runs, because it is the ingress target.

## The CLI

Two dispatchers, split by what they act on. brAIn's own faculties are under `brain`;
anything that acts on Home Assistant is under `ha`.

```bash
brain memory add "We call the office lamp the beacon"
brain memory list                  # what it knows
brain memory edit                  # open the document in $EDITOR
brain memory log                   # what it learned recently
brain memory hypotheses            # pending guesses awaiting a yes/no
brain learn energy                 # study a topic
brain ask "why is the garage cold" # same engine as the Ask card
brain undo                         # review and revert Claude's edits
brain doctor                       # end-to-end diagnostic

ha log                             # tail the Home Assistant log
ha reload automations
ha check configuration.yaml
ha context                         # regenerate /config/CLAUDE.md
ha entity list light
ha service call light.turn_on
ha addon list
ha notify "dishwasher finished"
```

Run `brain help` or `ha help` for the full list.

> If some other `ha` command is ever present on `PATH` inside the container, brAIn
> installs its own as `hass` instead rather than shadowing it. The startup log says so
> when this happens.

## Configuration options

Everything below is also editable from the panel's Settings dialog, which writes back
through the Supervisor — both screens always show the same value.

### Faces

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `enable_terminal` | bool | `true` | Run the ttyd terminal and expose the Terminal tab. Turn off for a dashboard-only install with no shell. |
| `enable_insights` | bool | `true` | Run insight generation and show the Insights tab. |

### Terminal

The **Chat / Classic** choice is not here — it lives in the panel's ⚙ Settings (and on
the Terminal tab itself), because it changes nothing about how the add-on runs.

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `auto_launch_claude` | bool | `true` | Start Claude Code automatically when the terminal opens. |
| `auto_generate_context` | bool | `true` | Regenerate `/config/CLAUDE.md` with your HA system context at startup. |
| `enable_ha_mcp_server` | bool | `true` | Give Claude native HA access (states, services, history, statistics, registries, dashboards, logs, templates). |
| `enable_mobile_ui` | bool | `true` | Splice the mobile toolbar and iOS dictation fix into ttyd's UI. |
| `dangerously_skip_permissions` | bool | `false` | Skip Claude Code's tool-permission prompts in the interactive terminal. Background listeners never use this. |

### Voice and automation

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `enable_assist_integration` | bool | `true` | Register brAIn as a conversation agent for Assist. |
| `enable_automation_integration` | bool | `true` | Watch for task requests from automations. |
| `assist_fast_mode` | bool | `true` | Serve voice from a pool of pre-warmed persistent workers instead of spawning a CLI per request. |
| `assist_tool_access` | `mcp_only` \| `full` | `mcp_only` | Whether voice can only touch HA, or also run Bash and edit files. |
| `assist_max_turns` | 1–40 | `8` | Agentic turn cap for voice. Kept modest on purpose: voice has a hard latency expectation, and a twenty-turn voice command is a failed interaction whatever it answers. The cached area map means most commands take one or two turns anyway. |
| `automation_max_turns` | 1–200 | `30` | Turn cap for automation tasks. No latency pressure here, so it is generous. |

### Memory and learning

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `learning` | bool | `true` | Master switch for everything brAIn learns: the consolidator, the end-of-conversation reflection pass, and study sessions. Turning it off leaves existing memory untouched. |
| `memory_injection` | bool | `true` | Splice learned memory into voice prompts. |
| `memory_max_kb` | 1–64 | `32` | Size cap for the memory document. A pass that cannot fit under it files nothing, so this is the setting to raise when the log says the document is full. |
| `study_max_turns` | 0–500 | `60` | Turn cap for `brain learn`. **`0` removes the cap.** See the note below. |
| `study_timeout_minutes` | 2–120 | `30` | Wall-clock limit for a study session. |

> **Why the study limits are generous.** A turn cap is not a safety valve — it
> *truncates*. A study session that hits it stops mid-thought and produces no
> parseable result, so the whole run is wasted after paying for every token.
> Depth is the entire point of a study session, so the honest guard is
> wall-clock time and your account's own usage budget, not turn count. Raise
> `study_max_turns`, or set it to `0`, if you want it digging harder.

### Insights

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `auto_refresh_hours` | 0–168 | `24` | How often recurring cards regenerate. `0` disables. |
| `history_days` | 1–30 | `7` | How much history each analysis reads. |
| `history_keep_runs` | 0–200 | `40` | Past runs kept per card. |
| `history_keep_days` | 0–365 | `30` | Age limit on past runs. |
| `model` | string | `""` | Override the Claude model. Empty uses the default. |
| `generation_timeout_minutes` | 2–30 | `8` | Per-generation timeout. |

### Undo and access

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `edit_journal_days` | 0–365 | `14` | How long to keep snapshots of files Claude edited. `0` disables the journal. |
| `access_share` | bool | `true` | Mount `/share`. |
| `access_media` | bool | `true` | Mount `/media`. |
| `access_backup` | bool | `true` | Mount `/backup` read-only. |
| `access_addon_configs` | bool | `true` | Mount other add-ons' config directories. |
| `access_addons` | bool | `true` | Mount add-on source directories. |
| `additional_directories` | list | `[]` | Extra paths to expose. |
| `persistent_apk_packages` | list | `[]` | Alpine packages reinstalled on every start. |
| `persistent_pip_packages` | list | `[]` | Python packages reinstalled on every start. |
| `log_level` | enum | `info` | Add-on log verbosity. At `debug` the panel logs every HTTP request (polls included) and ttyd its own connection chatter; below that a successful poll is silent and only failures are logged. |

## What it costs

brAIn runs on **your** Claude account, so it costs whatever your plan costs and
nothing more. There is no brAIn subscription and no middleman.

To keep it from eating the plan you also use for your own work:

- The top bar shows both usage windows — the **5-hour session** and the **week** —
  live. Press the pill for when each one resets, what the budget gates, and whether
  automatic work is currently paused by it.
- The chat terminal shows a **per-message price only if an API key is paying**. On a
  subscription there is no per-message charge, so it shows the duration and turn count
  instead of a figure that would look like money and isn't.
- A **budget** (Settings) caps how much of the session window automatic work may
  spend. Past it, scheduled cards pause and say so in the bar; anything you ask for by
  hand still runs.
- Usage is also exposed as Home Assistant sensors, so you can chart it or alert on it.
- Fixed daily times ("07:00, 19:00") cost far fewer tokens than a short refresh
  interval, and cards you never look at can simply be deleted.

## What it will not do

An honest list, because a tool that can edit your house should be clear about its
edges.

- **It does not back up your configuration.** Home Assistant's own backups are
  whole-system and restorable; duplicating them inside `/config` only made the backups
  bigger. brAIn keeps an edit journal of its own changes instead.
- **It never touches an existing `/config/.git`.** If you version your config
  yourself, that's yours.
- **It does not run with tools on a schedule.** Scheduled insight generation is pure
  analysis over a data snapshot, with every tool disabled. The one exception is the
  Findings **Fix it** button, which runs only because you pressed it.
- **It does not restart Home Assistant by itself**, and a fix never deletes anything
  it didn't create.
- **Voice is limited to Home Assistant by default.** Widening it to Bash and file
  editing is a setting you turn on deliberately.
- **The registry services are admin-gated**, and destructive sweeps (orphan cleanup)
  are dry-run by default.
- **It is not affiliated with Anthropic or the Open Home Foundation.** It runs the
  official Claude Code CLI under your own account.

## Ports

| Port | What | Needed? |
| --- | --- | --- |
| 8099 | The ingress panel. Also reverse-proxies `/terminal/`. | Internal; ingress handles it. |
| 7681 | ttyd, direct access. | **Off by default.** Optional, for a kiosk or a bookmarked full-screen terminal. |
| 8098 | The assist worker pool's internal API. | Internal only. |

### About port 7681

Before 1.19.0 this port was published on every install and ttyd ran without
a password, so anyone on your network could open a root shell with `/config`
read-write and your signed-in Claude. It is unpublished now, and the
terminal you use in the panel does not need it — the panel proxies ttyd over
loopback, which is what makes Terminal a tab.

If you do want the direct port (a wall tablet, a bookmark), assign it under
the add-on's **Network** settings. It asks for a password either way:

- Username `brain`; the password is generated on first start.
- It is printed in the add-on log, and stored at `/data/terminal-credential`.
- To rotate it, delete that file and restart the add-on.

Please don't forward this port through your router. It is a shell.

## Security

brAIn runs with real authority over your Home Assistant: `/config`
read-write, admin access to the Home Assistant API, and — depending on the
options you enable — `/share`, `/media` and other add-ons' configuration.
That is the point of it, and it is worth knowing where the edges are.

- **Home Assistant's login is the boundary.** Everything brAIn exposes sits
  behind ingress, which means behind your Home Assistant account. Nothing
  should be reachable without it; if you find something that is, that is a
  vulnerability and [SECURITY.md](https://github.com/bruhautomation/BRUH-HA-Apps/blob/main/SECURITY.md)
  is how to report it privately.
- **AppArmor is on.** The profile denies the container the things a host
  escape needs — mounting, kernel modules, raw sockets, kernel tunables, the
  Docker socket. It deliberately does not restrict what brAIn does *inside*
  the container, because an agent that can only run a fixed list of commands
  is an agent that breaks the first time you ask it something new.
- **Your Claude credential stays out of your backups.** Home Assistant
  backups are unencrypted unless you opt in, and they travel. Restoring a
  backup costs you one sign-in.
- **Claude Code runs as an unprivileged user** (UID 1000), not root.
- **`dangerously_skip_permissions` does what it says.** Off by default. On,
  Claude stops asking before it edits a file or runs a command in the
  interactive terminal.
- **The panel's rating is 6/6** in the add-on store — the highest the
  Supervisor gives, and it is worth knowing that `hassio_role: admin` costs
  two points that ingress and AppArmor pay back. brAIn needs that role
  because `ha addon` manages your other add-ons.

## Where things live

| Path | What |
| --- | --- |
| `/config/.brain/memory/memory.md` | The memory document. Yours to edit. |
| `/config/.brain/memory/voice.md` | A ≤2 KB distillate spliced into voice prompts. Derived; don't edit. |
| `/config/.brain/memory/inbox/` | Candidate facts awaiting consolidation. |
| `/config/.brain/findings/inbox/` | Problems study sessions found, awaiting filing. |
| `/config/CLAUDE.md` | The generated description of your installation. |
| `/data/chat_transcript.json` | The chat terminal's scrollback. Losing it costs a scrollback, never context — Claude Code keeps the conversation itself. |
| `/config/custom_components/brain/` | The Home Assistant integration, deployed at startup. |
| `/data/findings.json` | The findings list and its history. |
| `/data/.brain/edits/` | The edit journal `brain undo` restores from. |

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
