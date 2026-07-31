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
    id: "what",
    icon: "🏠",
    title: "What brAIn can do",
    body: `
# What brAIn can do

brAIn puts Claude inside Home Assistant with **full run of the place** — every entity,
every device, every area, floor, label, dashboard, helper, automation and add-on. It
reads your history, edits your configuration, fixes what's broken, remembers what you
tell it, and answers when you speak to it.

One add-on, one panel, one Claude login, running on **your** Claude subscription.

## It runs Home Assistant

Most AI integrations can turn on a light. brAIn administers the installation. It
reaches Home Assistant three ways at once — **36 native tools** for reading and
controlling, **65 registry-management services** for the parts of Home Assistant that
normally only exist behind the Settings UI, and a **real shell** in \`/config\` for
everything that is still a YAML file.

- **Organisation** — create, rename and delete areas, floors and labels; set icons and
  voice aliases; move devices and entities between them; put areas on floors. Ask it to
  reorganise a house that grew by accident and it does the whole sweep.
- **Devices and entities** — rename either, change an \`entity_id\`, hide, unhide,
  enable, disable. Find references to things that no longer exist and clean them up —
  dry-run first, so you see the list before anything goes.
- **Integrations** — reload one without restarting Home Assistant; enable, disable or
  remove one entirely.
- **Helpers, zones, people, users** — create and delete input helpers, timers, counters
  and schedules; draw a zone; add a person and attach their device trackers; create,
  disable or remove a user.
- **Dashboards** — read, create, rewrite, restore a previous version, reset to
  defaults, manage resources. It can build a dashboard from a sentence.
- **Automations, scripts and scenes** — it edits the YAML, validates it, reloads the
  domain, and then reads the **traces** to see whether the thing actually fired and why
  it didn't. That last part is what makes "write me an automation" work on the second
  try instead of never.
- **The house's own record** — history and long-term statistics, the logbook, the error
  log, your other add-ons, weather forecasts, camera snapshots it can actually *see*,
  rendered templates, and every service any integration exposes.

**Nothing is create-only.** Everything that can be created can be renamed and deleted,
and every attribute a \`create_\` service accepts has a service that changes it later.

## It finds what's broken

A **finding** is something wrong with your house — a dying battery, a sensor that
quietly stopped reporting three weeks ago, a device stuck unavailable, an automation
whose trigger can never fire. brAIn files them on its own, and each one gets **Fix it**
(it makes the change and reports back) or **Not a problem** (dismissed for good, and
never raised at you again).

## It explains your house

Insight cards with real interactive visualisations, chosen for **your** home rather
than shipped as defaults. Ask anything and get a card back; keep the good ones as
recurring, or put any of them on your own dashboard.

## It remembers

One editable document of durable facts about your home — your nicknames, your
household's rhythms, the devices that are meant to behave oddly. Learned from
conversations, insight runs and study sessions, and read by **every** part of brAIn.
Tell the voice assistant something and the cards know it.

## It talks

Pick brAIn in **Settings → Voice assistants** and talk to it from any Assist pipeline,
satellite or the app. Answers land in a few seconds from a pool of pre-warmed workers,
with your memory and an area map already in the prompt.

## It has a terminal, in two shapes

The real Claude Code CLI in your browser, running with your \`/config\` in front of it.
**Chat** renders it as a conversation — text that reflows to your screen, tool calls
folded into a line each, a normal text box — and **Classic** is a true terminal for
anything that draws its own screen. Same session, same permissions, one button between
them. Press **⤢** to give either the whole screen.

## It can be undone

Before Claude writes to any file under \`/config\`, the previous version is snapshotted.
\`brain undo\` puts it back — one edit, or everything from today.
`,
  },

  {
    id: "start",
    icon: "🚀",
    title: "Getting started",
    body: `
# Getting started

Four steps, and the longest one runs in the background while you do something else.

## 1. Sign in once

Open the **Insights** tab and connect your Claude account. A Claude **Pro** or **Max**
subscription is the cheapest way to run brAIn — it uses your existing plan rather than
API credits.

Three ways in, in order of least effort:

- **Terminal tab → type \`claude\`** — sign in there and everything else picks it up.
- **Guided sign-in** — the panel walks you through an Anthropic sign-in link.
- **Paste a token or API key** — for when you already have one.

Whichever you use, one sign-in covers the terminal, insights, voice, and memory.

## 2. Let it learn your home

There are no cards yet, and that's deliberate. brAIn studies your house first — how it's
named, when it's occupied, what it uses, how its devices behave — and only then proposes
cards. A generic "Energy" card about a home it has never looked at says nothing useful.

Press **Start learning**. It takes a few minutes and runs in the background, so you can
close the tab. When it's done you get a handful of suggestions specific to your home, and
you pick which to keep.

If your home is too new or too sparse to learn much from, brAIn says so rather than
inventing generic cards. Add more entities, let some history build up, and try again.

## 3. Teach it something

Open **Memory** and tell it one thing that isn't in the data:

> The garage fridge is meant to run 24/7 — it's not a fault.

That single fact stops it flagging the same false alarm every week. Memory is where brAIn
gets genuinely useful over time.

## 4. Give it a voice

Settings → **Voice assistants** → pick **brAIn** as the conversation agent. It answers
about your home and controls it, using the same memory.
`,
  },

  {
    id: "tabs",
    icon: "🗂",
    title: "The tabs",
    body: `
# The tabs

## Insights

Claude analyses your Home Assistant data and writes interactive cards.

- **Cards chosen for your home.** A fresh install ships **none**. brAIn studies the house
  first, then proposes cards grounded in what it actually found — you pick which to keep.
  Delete one you don't want with ✕; ask for it again whenever you like and brAIn builds it
  fresh, for the house it now knows.
- **The ask bar makes cards.** Every question you ask becomes a card. If the answer is
  worth having every week, press **＋ Make recurring** on it and the question becomes a
  scheduled insight. There is no separate "new insight" dialog — asking *is* the way in.
- **The ask bar also learns.** Start a line with **"learn about…"** or **"study…"** and
  brAIn runs a study session instead of drawing a card: it digs through the registry,
  history and long-term statistics for that corner of the house, and what it finds lands
  in **Memory** and **Findings**. It runs for minutes in the background.
- **Tags are yours.** Each card carries a few \`#tags\` — the chips at the top of the
  dashboard filter by them, so \`#batteries\` surfaces every card that found a battery
  problem, whatever category it came from. Press ✎ on a card's tag row to drop a bad tag
  or add your own. Your edits survive regeneration; new tags a later run discovers still
  appear.
- **Feedback** — 💬 on any card tells Claude what to do differently next time
  ("ignore the guest room sensor", "show costs in dollars"). It sticks.
- **Dashboard cards** — ▦ gives you YAML for a Webpage card so an insight lives on your
  own dashboard.

Each card's ✎ dialog sets its own schedule. Fixed daily times ("07:00, 19:00") use far
fewer tokens than a short interval.

## Findings

Things brAIn thinks are **broken**, and what it did about them. See **Findings** in this
guide. A number on the tab means something is waiting on your decision.

## Terminal

Full Claude Code in the browser, with native Home Assistant access — read states, call
services, check history, edit YAML, reload config.

It's the same terminal the add-on runs, served through this panel, so there's no second
sidebar entry and no second login.

**It has two faces**, and the button in the corner switches between them (so does
⚙ Settings). Both run the same Claude Code, on the same login, in the same \`/config\`,
with the same permissions — the difference is entirely how you see it.

**Chat** is the default. Claude Code's output rendered as a conversation: text that
reflows to your screen, code blocks that scroll inside their own box, tool calls folded
into one line each (tap for the arguments and the result), reasoning behind a "Thinking"
line, and a real text box so dictation and autocorrect behave. **⏹** stops an answer
in progress and **＋** starts a new chat. It survives a reload, a locked phone, and the
add-on restarting.

**Type / for commands.** The palette lists what *your* Claude Code actually has,
including anything you put in \`/config/.claude/commands\` — the list comes from the CLI
itself, so nothing has to be told about a command you add. ↑/↓ to move, Enter or Tab to
pick. A few are REPL-only (\`/help\` among them) and say so rather than failing.

**ⓘ shows the session** — the model, the project directory, how you are being billed,
and this conversation's id. **Continue in the terminal** releases the session and hands
you \`claude --resume <id>\` so Classic picks up the exact conversation. Both faces stand
in \`/config\`, which is what lets each see the other's conversations: Claude Code files
them per working directory.

**A per-message price only appears if an API key is paying.** On a Pro or Max
subscription those tokens are already bought, so there is nothing to charge and the
footnote shows the duration and turn count instead.

**Classic** is a true terminal — ttyd over tmux. Use it for anything that draws its own
screen (a TUI, \`htop\`, an installer), for running shell commands yourself, or just
because you prefer it.

**On a small screen it takes the room it needs.** The bar above folds away by itself
while the keyboard is up and comes back when you dismiss it; **⤢** in the corner folds
it away for good, and the same button brings it back. tmux drops its status line on a
narrow terminal too — one row of about twenty, spent on the date.

## Memory

What brAIn knows about your home, and the queue behind it. See **Memory** in this guide.
A number on the tab means brAIn has a guess waiting on a yes/no.

## Docs

This guide.
`,
  },

  {
    id: "findings",
    icon: "⚠️",
    title: "Findings",
    body: `
# Findings

Three things sound similar and are not:

| | Question it answers | How it ends |
| --- | --- | --- |
| **Memory** | What is *true* of this home? | It's a document; it just gets better |
| **Guesses** | What might brAIn have *wrong*? | Yes or No, once |
| **Findings** | What is *broken* in this home? | Fixed, or dismissed |

A finding is a work list item. A dead battery. A sensor that hasn't changed value in six
days. A device stuck unavailable. An automation whose trigger entity was renamed, so it
can never fire again. Something is wrong and somebody has to do something about it.

Findings come from insight runs and from study sessions — the same passes that fill
memory. brAIn only reports a problem **once**: the same finding in different words is
recognised and dropped.

## The two ways out

**✦ Fix it** sends Claude to make the change, in your actual Home Assistant. It confirms
the problem is still real, finds the cause rather than the symptom, makes the smallest
change that resolves it, verifies the change took, and reports back with a list of exactly
what it touched.

It is bounded on purpose:

- **One finding per run.** Anything else it notices along the way becomes its own finding
  rather than an edit you didn't ask for.
- **It never deletes** an entity, automation, dashboard or file it didn't create — it
  disables or corrects instead.
- **It never restarts Home Assistant.** Reloading one config domain is fine; a restart is
  your call.
- **It never touches secrets** or credentials.
- **Nothing runs until you press it.** brAIn will not change your house on a schedule.

Every change it makes is snapshotted first by the same hook the terminal uses, so
\`brain undo\` puts a file back if a fix goes wrong.

**Not a problem** dismisses it, permanently. This is the important one: the dismissal is
fed back into every future analysis, so brAIn stops raising it rather than raising it
again next week for you to dismiss again. If the garage freezer is *supposed* to sit at
-30°C, one press ends that conversation for good.

**✓ I did it** is for anything with hands in it — replacing a battery, re-pairing a
device. brAIn marks findings like these **needs you** rather than offering to fix them,
because inventing a software substitute for a dead battery is worse than saying so.

## After a fix

Fixed and dismissed findings don't vanish — switch the filter at the top of the tab to see
them. That archive is how you check what brAIn changed in your house last week, and
**Put it back on the list** reopens anything that turned out not to be fixed.

Successful fixes are also written into memory, so a later analysis doesn't rediscover a
problem brAIn resolved itself.
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
know exactly what brAIn believes about your house.

## The document

Preferences, entity nicknames, household patterns, device notes. Plain markdown, and
**yours to edit** — your edits are the source of truth.

Every part of brAIn reads it: insight runs, voice conversations, study sessions, and the
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

## Filing the queue now

The consolidator runs **daily**, and early once more than 20 things are waiting. That's
the right cadence for a background job and the wrong one for someone who has just taught
brAIn something and wants to see it land.

**⇪ File into memory now** runs the same pass immediately: it merges everything queued
into the document, dedupes, and resolves contradictions newest-wins. It says how much is
waiting before you press it, and costs one small Claude call. Same script, same safety
checks — the consolidator stays the only writer either way.

Filing empties **Waiting to be filed**, and what was in it is then part of the memory
document beside it. It is not listed twice: once a discovery is in the document, the
document is where you read it, and where you edit or delete it. If the pass keeps the
facts instead — it does that rather than write a document it isn't happy with — it says
so, and the queue stays where it was.

Manual edits are rewritten by a consolidation, so if you have unsaved edits in the
markdown editor below it asks before filing.

## Guesses, not questionnaires

brAIn proposes things it believes and asks you to confirm:

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
statistics — and files what it finds. Its output is **knowledge, not a dashboard card**:
durable facts go to this queue, anything broken goes to **Findings**, and at most a few
guesses come back for you to settle.

Topics: naming, presence, energy, climate, devices, automations, lighting. You can also
pass free text.

You don't need the terminal for this. Type **"learn about my heating"** into the ask bar
on the Insights tab and it runs the same session.
`,
  },

  {
    id: "cli",
    icon: "⌨️",
    title: "Command line",
    body: `
# Command line

Two commands, split by what they act on. \`brain\` is brAIn's own faculties; \`ha\` is
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

> If some other \`ha\` command is ever present in the container, brAIn installs its own as
> \`hass\` instead rather than shadowing it. The startup log says so when that happens.
`,
  },

  {
    id: "undo",
    icon: "↩️",
    title: "Undo & backups",
    body: `
# Undo & backups

## brAIn does not back up your configuration

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

> If something else already keeps a \`/config/.git\`, brAIn leaves it exactly as it is —
> your version control is yours.
`,
  },

  {
    id: "voice",
    icon: "🎙",
    title: "Voice & automations",
    body: `
# Voice & automations

## Voice

Settings → **Voice assistants** → set the conversation agent to **brAIn**.

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

Learning is a markdown file on disk, which is invisible to everything outside brAIn. So it
also surfaces where you already look:

- **The logbook.** Every new fact fires a \`brain_learned\` event, so "brAIn learned: the
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

Learning is a markdown file on disk, which is invisible to everything outside brAIn. So it
also surfaces where you already look:

- **The logbook.** Every new fact fires a \`brain_learned\` event, so "brAIn learned: the
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

**BRUH Power Tools** adds 65 admin-gated registry services under \`brain.*\` — areas,
floors, labels, entities, devices, helpers, zones, persons, dashboards and more. Every
registry object it can create it can also rename, change and delete; the destructive
ones take \`dry_run\` and tell you the blast radius first. Adapted from
[Spook](https://github.com/frenck/spook).
`,
  },

  {
    id: "settings",
    icon: "⚙️",
    title: "Settings & cost",
    body: `
# Settings & cost

## Keeping token use sane

brAIn runs on your Claude subscription, and a subscription has a usage window. The
defaults are deliberately modest, and ⚙ **Settings** is where you tune them.

**The usage budget** is the important one. Your plan refills every 5 hours; the budget
caps what share of that window brAIn's *automatic* runs may consume. Hit the cap and
background generation pauses until the window rolls over. **Manual clicks are never
blocked** — pressing Generate always works.

The pill in the top bar reads \`Session 19% · Week 64%\`: the 5-hour window the budget
is set against, and the seven-day window that is usually what actually ends your week.
Hover it and it tells you when each one resets — that and nothing else. Nothing is budgeted against the weekly number — it is
there because a session that looks fine tells you nothing about a week that doesn't.
Both come from your Anthropic account when you signed in with a subscription; with an
API key there is no account usage to read, so the session figure falls back to an
estimate of brAIn's own spending and the weekly one isn't shown.

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
Delete the wrong line and brAIn is asked to drop it from the document too.

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
