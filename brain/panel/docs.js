// Documentation tab content.
//
// Kept as data rather than markup so the same source drives the sidebar,
// the search index, and the rendered page — a docs page whose nav can drift
// out of sync with its own body is worse than no nav.
//
// `body` is a small markdown subset (headings, lists, tables, fenced code,
// inline code, bold, links) rendered by renderDocs() in app.js. It is
// authored here, never user-supplied, but the renderer escapes anyway.

window.BRAIN_DOCS = [
  {
    id: "start",
    icon: "🚀",
    title: "Getting started",
    body: `
# Getting started

BRain is three things sharing one brain: a **Claude Code terminal**, an **AI insights
dashboard**, and a **memory** of your home that both of them read and write.

## 1. Sign in once

Open the **Insights** tab and connect your Claude account. A Claude **Pro** or **Max**
subscription is the cheapest way to run BRain — it uses your existing plan rather than
API credits.

Three ways in, in order of least effort:

- **Terminal tab → type \`claude\`** — sign in there and everything else picks it up.
- **Guided sign-in** — the panel walks you through an Anthropic sign-in link.
- **Paste a token or API key** — for when you already have one.

Whichever you use, one sign-in covers the terminal, insights, voice, and memory.

## 2. Let it look around

Insight cards generate on their own schedule, but you don't have to wait:

- Press **↻ Refresh all** to generate everything now, or **Generate** on a single card.
- Ask a question in the ask bar — you get a card back, and can make it recurring.

## 3. Teach it something

Open **Memory** and tell it one thing that isn't in the data:

> The garage fridge is meant to run 24/7 — it's not a fault.

That single fact stops it flagging the same false alarm every week. Memory is where BRain
gets genuinely useful over time.

## 4. Give it a voice

Settings → **Voice assistants** → pick **BRain** as the conversation agent. It answers
about your home and controls it, using the same memory.
`,
  },

  {
    id: "tabs",
    icon: "🗂",
    title: "The three tabs",
    body: `
# The three tabs

## Insights

Claude analyses your Home Assistant data and writes interactive cards.

- **Nine built-in categories** — Overview, Energy, Climate, Lighting, Security, Presence,
  Media, Device Health, Automations.
- **Ask anything** — a free-form question becomes a one-off card. Turn it into a
  recurring one with **＋ New insight**.
- **Feedback** — 💬 on any card tells Claude what to do differently next time
  ("ignore the guest room sensor", "show costs in dollars"). It sticks.
- **Dashboard cards** — ▦ gives you YAML for a Webpage card so an insight lives on your
  own dashboard.

Each card's ✎ dialog sets its own schedule. Fixed daily times ("07:00, 19:00") use far
fewer tokens than a short interval.

## Terminal

Full Claude Code in the browser, with native Home Assistant access — read states, call
services, check history, edit YAML, reload config.

It's the same terminal the add-on runs, served through this panel, so there's no second
sidebar entry and no second login.

## Memory

What BRain knows about your home, and the queue behind it. See **Memory** in this guide.
`,
  },

  {
    id: "memory",
    icon: "🧠",
    title: "Memory",
    body: `
# Memory

One rule governs the whole design:

> **The memory document is the only thing that is "memory."** Everything else is a queue
> or an audit trail.

That is what keeps it readable. You can open the document, read it top to bottom, and
know exactly what BRain believes about your house.

## The document

Preferences, entity nicknames, household patterns, device notes. Plain markdown, and
**yours to edit** — your edits are the source of truth.

Every part of BRain reads it: insight runs, voice conversations, study sessions, and the
terminal (\`brain memory list\`).

## How facts get in

Nothing writes the document directly except the consolidator. Everything else queues:

| Source | What it queues |
| --- | --- |
| You, in the Memory tab | what you type |
| Voice conversations | preferences and corrections you state out loud |
| Insight runs | durable discoveries about the home |
| Study sessions | whatever \`brain learn\` finds |
| \`brain memory add\` | what you type in the terminal |

One writer means the terminal, the panel, and voice can all feed the same memory without
fighting over the file.

## Guesses, not questionnaires

BRain proposes things it believes and asks you to confirm:

> The garage fridge is meant to run 24/7 — right?

**Never more than three at once**, and they expire after 14 days. Confirming one files it
as a plain fact and the guess is forgotten. Rejecting one records a dead end so that line
of enquiry is not revisited.

This replaced an open-ended question list that grew without limit and was never clearly
part of memory.

## Seeing what changed

\`\`\`bash
brain memory log        # what it learned recently
brain memory undo 1     # revert a change
\`\`\`

Every consolidation records what it added and removed, so "what did it learn this week"
is a real question with a real answer.

## Studying on demand

\`\`\`bash
brain learn energy      # study one topic
brain learn             # study whatever has gone stalest
brain learn --list      # the curriculum
\`\`\`

A study session investigates a topic — registry, live state, history, long-term
statistics — and files what it finds. Its output is **knowledge, not a dashboard card**.

Topics: naming, presence, energy, climate, devices, automations, lighting. You can also
pass free text.
`,
  },

  {
    id: "cli",
    icon: "⌨️",
    title: "Command line",
    body: `
# Command line

Two commands, split by what they act on. \`brain\` is BRain's own faculties; \`ha\` is
Home Assistant operations. That split is why there's no ambiguity about what
\`ha log\` means.

Run \`brain help\` or \`ha help\` for the full list.

## brain

\`\`\`bash
brain memory add "We call the office lamp the beacon"
brain memory list                  # what it knows
brain memory edit                  # open the document in $EDITOR
brain memory forget "<text>"       # queue a line for removal
brain memory log                   # what it learned recently
brain memory undo [n]              # revert a memory change

brain memory hypotheses            # guesses waiting on you
brain memory confirm "<text>"      # yes — file it as a fact
brain memory reject "<text>"       # no — record a dead end

brain learn [topic]                # study the home
brain ask "why is the garage cold" # one-shot question
brain undo                         # revert Claude's file edits
brain doctor                       # end-to-end diagnostic
\`\`\`

A distinctive fragment is enough for \`confirm\` and \`reject\` — you don't have to retype
the whole sentence.

## ha

\`\`\`bash
ha log                    # tail the Home Assistant log
ha reload automations     # reload config
ha check configuration.yaml
ha context                # regenerate /config/CLAUDE.md
ha entity list light
ha service call light.turn_on
ha addon list
ha notify "dishwasher finished"
ha share push <file>
ha login                  # share this login with other BRUH add-ons
\`\`\`

> If some other \`ha\` command is ever present in the container, BRain installs its own as
> \`hass\` instead rather than shadowing it. The startup log says so when that happens.
`,
  },

  {
    id: "undo",
    icon: "↩️",
    title: "Undo & backups",
    body: `
# Undo & backups

## BRain does not back up your configuration

Use Home Assistant's own backups — they're whole-system and restorable, and they already
work. Earlier versions kept a git repo inside \`/config\`, which duplicated those backups
*into* those backups. That's gone.

## What it does keep

Before Claude writes to any file under \`/config\`, the previous contents are snapshotted.

\`\`\`bash
brain undo                # list recent edits, newest first
brain undo 3              # revert edit #3
brain undo --all-today    # revert everything changed today
\`\`\`

Each entry shows when, which file, and whether it was created or modified. Reverting
restores the file exactly as it was immediately before that edit.

- Scoped to what **Claude** touched — not your whole config.
- Stored under \`/data\`, so it never lands inside your Home Assistant backups.
- Pruned on \`edit_journal_days\` (default 14) and capped by size.
- \`secrets.yaml\` is never snapshotted.

> Upgrading from BRUH Terminal? Its old \`/config/.git\` is left exactly as it is — BRain
> never touches it. Delete it yourself if you don't want it.
`,
  },

  {
    id: "voice",
    icon: "🎙",
    title: "Voice & automations",
    body: `
# Voice & automations

## Voice

Settings → **Voice assistants** → set the conversation agent to **BRain**.

By default voice runs on a pool of pre-warmed workers, so commands land in a few seconds
rather than waiting for a cold CLI start. The area→entity map is cached, so most commands
skip lookup turns entirely.

Voice reads the same memory as everything else — nicknames and preferences you've taught
it apply here without further setup.

When you state a durable preference out loud ("actually, we call that the beacon"), it's
queued into memory automatically.

## Tool access

\`assist_tool_access\` decides how far voice can reach:

- **\`mcp_only\`** (default) — control the house, nothing else.
- **\`full\`** — also run Bash and edit files.

Leave it on \`mcp_only\` unless you specifically want voice editing your config.

## Watching it learn

Learning is a markdown file on disk, which is invisible to everything outside BRain. So it
also surfaces where you already look:

- **The logbook.** Every new fact fires a \`brain_learned\` event, so "BRain learned: the
  hallway sensor drops offline around 2am" appears in your home's timeline next to lights
  and doors.
- **\`sensor.brain_facts_learned\`** — how much it knows.
- **\`sensor.brain_last_learned\`** — when, with the facts as an attribute.
- **\`binary_sensor.brain_waiting_on_you\`** — on when a guess needs a yes/no, with the
  text in \`pending\`.

That last one exists to be automated. A guess sitting in a panel nobody has open expires
unanswered; pushed to a phone, it costs one tap:

\`\`\`yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.brain_waiting_on_you
    to: "on"
actions:
  - action: notify.mobile_app_phone
    data:
      message: "{{ state_attr('binary_sensor.brain_waiting_on_you', 'oldest') }}"
\`\`\`

## Studying on a schedule

\`\`\`yaml
action: brain.study
data:
  topic: energy      # omit to study whatever has gone stalest
\`\`\`

Returns immediately — a session runs for minutes, and what it finds arrives in memory
rather than in a response. A nightly automation with no topic works its way through the
curriculum on its own.

In the terminal, **\`/learn\`** does the same thing where you can watch it and correct it
mid-flight. **\`/memory\`** shows what it knows and anything waiting on you.

## Watching it learn

Learning is a markdown file on disk, which is invisible to everything outside BRain. So it
also surfaces where you already look:

- **The logbook.** Every new fact fires a \`brain_learned\` event, so "BRain learned: the
  hallway sensor drops offline around 2am" appears in your home's timeline next to lights
  and doors.
- **\`sensor.brain_facts_learned\`** — how much it knows.
- **\`sensor.brain_last_learned\`** — when, with the facts as an attribute.
- **\`binary_sensor.brain_waiting_on_you\`** — on when a guess needs a yes/no, with the
  text in \`pending\`.

That last one exists to be automated. A guess sitting in a panel nobody has open expires
unanswered; pushed to a phone it costs one tap:

\`\`\`yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.brain_waiting_on_you
    to: "on"
actions:
  - action: notify.mobile_app_phone
    data:
      message: "{{ state_attr('binary_sensor.brain_waiting_on_you', 'oldest') }}"
\`\`\`

## Studying on a schedule

\`\`\`yaml
action: brain.study
data:
  topic: energy      # omit to study whatever has gone stalest
\`\`\`

Returns immediately — a session runs for minutes, and what it finds arrives in memory
rather than in a response. A nightly automation with no topic works through the curriculum
on its own.

In the terminal, **\`/learn\`** does the same where you can watch it and correct it
mid-flight. **\`/memory\`** shows what it knows and anything waiting on you.

## From automations

\`\`\`yaml
action: brain.run_task
data:
  task: >-
    Check whether any door has been open more than 20 minutes
    and notify me if so.
\`\`\`

Other services: \`brain.send_prompt\`, \`brain.run_insight\`, \`brain.add_memory\`,
\`brain.clear_conversation\`.

**BRUH Power Tools** adds 56 admin-gated registry services under \`brain.*\` — areas,
floors, labels, entities, devices, helpers, zones, persons, dashboards and more. Adapted
from [Spook](https://github.com/frenck/spook).
`,
  },

  {
    id: "settings",
    icon: "⚙️",
    title: "Settings & cost",
    body: `
# Settings & cost

## Keeping token use sane

BRain runs on your Claude subscription, and a subscription has a usage window. The
defaults are deliberately modest, and ⚙ **Settings** is where you tune them.

**The usage budget** is the important one. Your plan refills every 5 hours; the budget
caps what share of that window BRain's *automatic* runs may consume. Hit the cap and
background generation pauses until the window rolls over. **Manual clicks are never
blocked** — pressing Generate always works.

Biggest levers, in order:

1. **Fixed daily times** on a card ("07:00, 19:00") instead of an interval.
2. **Disable cards you don't read.** Each card's ✎ dialog has an Enabled switch.
3. **A smaller model.** Settings → Claude model. Smaller models cost far fewer tokens;
   the bigger ones dig deeper.
4. **Fewer history days.** Settings → History analyzed.

## How deep it digs

A turn cap is not a safety valve — it **truncates**. A run that hits one stops mid-thought
and produces nothing usable, so you pay for every token and get no result. That makes a
tight cap the most expensive setting in the add-on.

So the limits are set by what each job is actually for:

| Job | Default | Why |
| --- | --- | --- |
| Voice | 8 turns | Latency is the point. A twenty-turn voice command is a failed interaction whatever it answers — and the cached area map means most take one or two. |
| Automation tasks | 30 turns | No one is waiting, so it can afford to be thorough. |
| Study sessions | 60 turns, 30 min | Depth **is** the deliverable. Set \`study_max_turns\` to \`0\` to remove the cap entirely. |

If a study session reports hitting its limit, raise it — that message means the run found
things and then lost them.

## Turning faces off

- \`enable_terminal: false\` — dashboard only, no shell.
- \`enable_insights: false\` — memory and terminal only, no generation.

The panel always runs; it's the ingress target.

## Options

Everything in ⚙ Settings is also in the add-on's Configuration tab, and they stay in
sync — the panel writes changes back through the Supervisor. Only \`log_level\` is
Configuration-only, since it takes effect at startup.

See the add-on's **Documentation** tab for every option with its range and default.
`,
  },

  {
    id: "trouble",
    icon: "🔧",
    title: "Troubleshooting",
    body: `
# Troubleshooting

Start here:

\`\`\`bash
brain doctor
\`\`\`

It checks the Supervisor token, the HA REST API, the MCP handshake, the custom
integration, both background listeners, the worker pool API, and your Claude login — then
smoke-tests the CLI.

## The terminal tab won't load

Give it a few seconds after a restart and reload — ttyd starts slightly after the panel.
If it stays down, check \`enable_terminal\` is on, and look at the add-on log.

## Voice is slow or fails

\`brain doctor\` reports the worker pool's health. If it's not answering, the pool falls
back to spawning a CLI per request — slower, but working. Restarting the add-on
re-warms it.

## It asks me to log in again

One sign-in should cover everything. If the terminal prompts after you signed in through
the panel, run \`brain doctor\` — it reports which credential source is active.

## An insight is wrong

Don't fight it in the prompt — use **💬 Feedback** on the card. That's remembered and
applied to every future run of that card.

If it's wrong about a *fact* rather than a presentation choice, fix it in **Memory**.
Delete the wrong line and BRain is asked to drop it from the document too.

## It keeps flagging something that's fine

Tell it once, in Memory:

> The garage fridge is meant to run 24/7.

Or confirm/reject the guess it's already showing you.

## Claude's login expired

Open the Terminal tab and run \`claude\` once. Background tasks, voice, and insights pick
the fresh login up automatically.
`,
  },
];
