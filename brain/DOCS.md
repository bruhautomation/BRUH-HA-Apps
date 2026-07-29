# BRain

Your home's brain: a Claude Code terminal, an AI insights dashboard, and one shared
memory — in one add-on, behind one sidebar panel, on one Claude login.

- [Setup](#setup)
- [The panel](#the-panel)
- [Configuration options](#configuration-options)
- [The CLI](#the-cli)
- [Memory and learning](#memory-and-learning)
- [Undo and backups](#undo-and-backups)
- [The Home Assistant integration](#the-home-assistant-integration)
- [Ports](#ports)

## Setup

1. Install the add-on and start it.
2. Open the panel from the sidebar and authenticate Claude (a subscription login or an
   API key — the panel walks you through it). This is the **only** login; the terminal,
   insight generation, voice, and memory consolidation all share it.
3. Home Assistant will offer to set up the **BRain** integration via discovery. Accept
   it — that's what provides the services, sensors, and the voice assistant.
4. Press **Start learning**. A fresh install has **no cards**: BRain studies your home
   first, then proposes cards grounded in what it found. See below.

### First run

There are no default cards, deliberately. A generic "Energy" or "Climate" card about a
home BRain has never looked at says nothing useful and costs tokens on every run.

Instead the first run studies the house — naming and areas, occupancy rhythms, energy,
climate, device reliability — and then proposes a handful of cards specific to it, each
with a one-line reason citing what it found. You choose which to keep, and can add, edit
or remove cards at any time afterwards.

It takes a few minutes and runs in the background; the panel can be closed and reopened.

**If your home is too sparse to learn from**, BRain says what's missing rather than
inventing generic cards. Add more entities, let history accumulate, and run it again.

## The panel

One ingress panel with four faces:

- **Insights** — generated cards about your home. Ask a question and get an answer card;
  keep the ones you like as recurring cards, or drop any of them on a dashboard. Say
  "learn about…" in the same bar and it runs a study session instead.
- **Findings** — what BRain thinks is broken, and what it did about it. Each one is
  either fixed (BRain makes the change and reports back) or dismissed for good.
- **Terminal** — full Claude Code, reverse-proxied through the panel at `/terminal/`.
- **Memory** — what BRain knows about your house, editable.

`enable_terminal` and `enable_insights` turn either face off; the panel itself always
runs, because it is the ingress target.

## Configuration options

### Faces

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `enable_terminal` | bool | `true` | Run the ttyd terminal and expose the Terminal tab. Turn off for a dashboard-only install with no shell. |
| `enable_insights` | bool | `true` | Run insight generation and show the Insights tab. |

### Terminal

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
| `enable_assist_integration` | bool | `true` | Register BRain as a conversation agent for Assist. |
| `enable_automation_integration` | bool | `true` | Watch for task requests from automations. |
| `assist_fast_mode` | bool | `true` | Serve voice from a pool of pre-warmed persistent workers instead of spawning a CLI per request. |
| `assist_tool_access` | `mcp_only` \| `full` | `mcp_only` | Whether voice can only touch HA, or also run Bash and edit files. |
| `assist_max_turns` | 1–40 | `8` | Agentic turn cap for voice. Kept modest on purpose: voice has a hard latency expectation, and a twenty-turn voice command is a failed interaction whatever it answers. The cached area map means most commands take one or two turns anyway. |
| `automation_max_turns` | 1–200 | `30` | Turn cap for automation tasks. No latency pressure here, so it is generous. |

### Memory and learning

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `learning` | bool | `true` | Master switch for everything BRain learns: the consolidator, the end-of-conversation reflection pass, and study sessions. Turning it off leaves existing memory untouched. |
| `memory_injection` | bool | `true` | Splice learned memory into voice prompts. |
| `memory_max_kb` | 1–64 | `8` | Size cap for the memory document. |
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

These are also editable from the panel's Settings dialog, which writes back here through
the Supervisor — both screens always show the same value.

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
| `log_level` | enum | `info` | Add-on log verbosity. |

## The CLI

Two dispatchers, split by what they act on. BRain's own faculties are under `brain`;
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

ha log
ha reload automations
ha check configuration.yaml
ha context
ha entity list light
ha service call light.turn_on
ha addon list
ha notify "dishwasher finished"
```

Run `brain help` or `ha help` for the full list.

> If some other `ha` command is ever present on `PATH` inside the container, BRain
> installs its own as `hass` instead rather than shadowing it. The startup log says so
> when this happens.

## Memory and learning

BRain keeps a small, durable document about your home under `/config/.brain/memory/`.

| File | What it is |
| --- | --- |
| `memory.md` | The canonical document — preferences, nicknames, household patterns, device notes. **User-editable.** Capped at `memory_max_kb`. |
| `voice.md` | A ≤2 KB distillate spliced into voice prompts. Derived; don't edit. |
| `inbox/` | Candidate facts awaiting consolidation. |

Facts arrive from voice conversations (Claude calls a `remember_fact` tool when you
state a preference or correction), from insight runs, from study sessions, from
`brain memory add`, and from the `brain.add_memory` service. A background consolidator
folds the inbox into the document daily — or early once more than 20 facts are waiting,
or immediately when you press **⇪ File into memory now** on the Memory tab.

The document is plain markdown. Edit it freely — your edits are the source of truth, and
the consolidator preserves them.

## Findings

A finding is something **broken**: a dead battery, a sensor that stopped reporting, a
device stuck unavailable, an automation that can never fire. Insight runs and study
sessions file them into `/data/findings.json`; study sessions hand theirs over through
`/config/.brain/findings/inbox/`, the same way facts reach the memory inbox.

Pressing **Fix it** is the only place the add-on runs Claude *with tools* on its own
initiative — everywhere else insight generation is pure analysis over a data snapshot
with `--disallowedTools "*"`. A fix run is bounded to one finding, capped by
`BRAIN_FIX_MAX_TURNS` (30) and `BRAIN_FIX_TIMEOUT` (900s), runs under the same
`/config/.claude/settings.local.json` permissions as the Assist and Automation
listeners, and is snapshotted by the same `PreToolUse` hook — so `brain undo` restores a
file a fix got wrong. It never deletes anything it didn't create, never restarts Home
Assistant, and never runs on a schedule.

**Dismissing** a finding is durable: dismissed findings are injected into every future
analysis so the same non-problem is never raised twice.

## Undo and backups

**BRain does not back up your configuration.** Use Home Assistant's own backups; they're
whole-system and restorable, and duplicating them inside `/config` only made the backups
bigger.

What BRain keeps is an **edit journal**. Before Claude writes to any file under
`/config`, the previous contents are snapshotted to `/data/.brain/edits/`:

```bash
brain undo                # list recent edits, newest first
brain undo 3              # revert edit #3
brain undo --all-today    # revert everything Claude changed today
```

Snapshots are pruned after `edit_journal_days` and capped by total size. `secrets.yaml`
is never snapshotted.

If you previously ran BRUH Terminal, its `/config/.git` directory is left exactly as it
is — BRain never touches it. Delete it yourself if you don't want it.

## The Home Assistant integration

Deployed automatically to `/config/custom_components/brain/` at startup.

- A **conversation agent** named BRain, for Settings → Voice Assistants.
- Services: `brain.send_prompt`, `brain.run_task`, `brain.run_insight`,
  `brain.add_memory`, `brain.clear_conversation`.
- **BRUH Power Tools**: 56 admin-gated registry-management services under `brain.*`
  (areas, floors, labels, entities, devices, integrations, helpers, zones, persons,
  blueprints, statistics, users, dashboards, repair issues), adapted from
  [Spook](https://github.com/frenck/spook) (MIT).
- Usage-limit sensors reflecting real Anthropic account utilisation.

## Ports

| Port | What | Needed? |
| --- | --- | --- |
| 8099 | The ingress panel. Also reverse-proxies `/terminal/`. | Internal; ingress handles it. |
| 7681 | ttyd, direct access. | Optional — handy for a kiosk or a bookmarked full-screen terminal. |
| 8098 | The assist worker pool's internal API. | Internal only. |
