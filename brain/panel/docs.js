// GENERATED from brain/DOCS.md by panel/build-docs.py — do not edit.
//
// Run `python3 panel/build-docs.py` after editing DOCS.md; CI runs it with
// `--check` and fails if this file is out of date.
//
// Kept as data rather than markup so the same source drives the sidebar, the
// search index, and the rendered page — a docs page whose nav can drift out of
// sync with its own body is worse than no nav.
//
// `body` is a small markdown subset (headings, lists, tables, fenced code,
// inline code, bold, links) rendered by renderDocs() in app.js.

window.BRAIN_DOCS = [
  {
    id: "brain",
    icon: "🏠",
    title: "brAIn",
    body: `
# brAIn

**Your house already has nerves. Now give it a brAIn.**

Claude plus a suite of new tools hands it the keys. Stop programming your house — let it
think.

> **Back up Home Assistant first — somewhere that isn't this machine.**
>
> brAIn edits your real configuration: automations, dashboards, helpers, entities. It is
> built to be careful, it snapshots files before it changes them, and \`brain undo\` puts
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
`,
  },
  {
    id: "it-runs-home-assistant",
    icon: "🏡",
    title: "It runs Home Assistant",
    body: `
# It runs Home Assistant

Most AI integrations can turn on a light. brAIn administers the installation.

It reaches Home Assistant three ways at once — a **native MCP server** (40 tools) for
reading and controlling, **65 registry-management services** for the parts of Home
Assistant that normally only exist behind the Settings UI, and a **real shell** in
\`/config\` for everything that is still a YAML file.

**Organisation.** Create, rename and delete **areas**, **floors** and **labels**; set
their icons and aliases; move devices and entities between them; put areas on floors.
Ask it to reorganise a house that grew by accident — "every light in the basement
should be in a Basement area under a Lower Floor" — and it does the whole sweep.

**Devices and entities.** Rename either. Change an \`entity_id\`. Set icons and voice
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
(it **sees** the image), rendered templates, and every service any integration exposes.

**Add-ons.** List, start, stop, restart and read the logs of your other add-ons.

If it exists in Home Assistant, brAIn can look at it, and — with a handful of
deliberate exceptions listed below — change it.

> **Nothing is create-only.** Every attribute a \`create_*\` service accepts has a
> service that changes it afterwards, and everything that can be created can be
> renamed and deleted. A test asserts that, because a tool that can make a mess and
> not clean it up is worse than no tool.
`,
  },
  {
    id: "it-finds-whats-broken-and-fixes-it",
    icon: "🔧",
    title: "It finds what's broken — and fixes it",
    body: `
# It finds what's broken — and fixes it

A **finding** is something wrong with your house: a battery about to die, a sensor
that quietly stopped reporting three weeks ago, a device stuck \`unavailable\`, an
automation whose trigger can never fire.

brAIn files findings on its own, from scheduled analysis and from study sessions.
Each one gets a severity, a plain-English explanation, and what to do about it:

- **Fix it** — brAIn makes the change and reports back what it did. This is the **only**
  place the add-on lets Claude act on your house on its own initiative, it is bounded
  to one finding, and it only ever happens because you pressed the button.
- **Discuss** — hands it to the chat with everything brAIn knows about it and asks
  whether it really is a problem **here**. The discussion changes nothing; the decisions
  ride along above the composer, so agreeing to the fix at the end of it is one press.
- **I fixed it** — you handled it yourself. brAIn remembers that you did, and there
  is an optional box for **how** ("replaced the CR2032 — it's a 3-monthly job on that
  one"), which goes into memory beside the fact.
- **Check again** — run the one house check that filed this, right now. The only
  press on a finding that says nothing about your house: a check reads a single
  instant, so it can report something that was true while a hub rebooted or a printer
  was hot and has since passed. Rather than making you claim you fixed it or that it
  was never a problem, this asks the check to look again — and if it no longer sees
  it, the row goes, along with anything else that check has stopped reporting. If the
  problem is still there you are told so, with today's numbers — and the row keeps a
  **confirmed just now** mark, because a finding filed on Tuesday and one confirmed a
  minute ago are different things and only one is evidence about your house now. The
  button says **Checking…** while it runs, which takes a second or two. If the check
  could not look this time, nothing changes and it says why: "I could not look" and
  "it went away" are different answers. It appears only on findings a house check
  raised; one the analyst wrote is re-run with **Regenerate** on its card.
- **Remind me later** — an hour, tomorrow, next week, next month. Not a decision: the
  finding stays exactly as open as it was and simply stops asking, and it waits under
  the **Later** filter with the date it comes back.
- **Dismiss** — off the list now, and free to come back. It teaches the analyst
  nothing, so the next run may well raise it again. That is the whole difference
  between this and Wrong.
- **Wrong** — brAIn has misread your house, and the box asks why. That reason is the
  half that teaches: it goes verbatim under the finding in every future analysis and
  into memory as a correction, so the same non-problem is never raised at you twice
  in new words. The garage fridge that runs 24/7 gets flagged once.

The three that end a finding — **I fixed it**, **Wrong** and **Got it** after an
automated fix — each do the same three things: a plain line into memory, a key in the
settled ledger so it is never re-raised, and the row deleted. The buttons on a
**notification** are the same endings under their own wording (**I've fixed it**,
**Not a problem**, **Later**), because that message is written for a lock screen rather
than for a list.

An **Answered** filter appears once the settled ledger holds something — capped,
hidden until then, no badge, and one verb on each row: **Let brAIn raise it again**,
which stops the suppression and nothing more. Nothing "comes back" unless the next
analysis finds it still there.
`,
  },
  {
    id: "it-checks-the-house-without-spending-a-token",
    icon: "✅",
    title: "It checks the house without spending a token",
    body: `
# It checks the house without spending a token

Not every problem needs a model to find. brAIn runs a set of **house
checks** on a schedule (every \`checks_interval_hours\`, six by default) and on
**Run checks now** on the Findings tab: they read Home Assistant directly —
the registries, the states, your \`automations.yaml\`, the traces Home
Assistant keeps, a week of statistics, the dashboards, and the Supervisor's
own view of backups, add-ons and the disk — and file what they find as
ordinary findings under a "check" label, with no Claude run at all.

- **Automations** naming an entity that no longer exists, or calling a service
  that is not registered (the old phone's \`notify.mobile_app_*\`, with the
  replacement named); whose last run failed; that trigger but never get past
  their condition; that keep being skipped on \`mode: single\`; that have never
  fired, or were switched off and forgotten; that are copies of each other; or
  that use a blueprint that is missing.
- **Devices** unavailable for more than a day (one row per device, not per
  entity); batteries low, or gone quiet — a dead device stops reporting its
  own battery, which a threshold never notices; impossible readings; sensors
  frozen on one value for a week; entities left behind by a removed
  integration.
- **An automation whose trigger has died** — the failure with no symptom at
  all: the automation is switched on, nothing errors, no trace is written,
  and it can never fire again, because the entity in its trigger has been
  unavailable for days.
- **Radios**: Z-Wave nodes the controller has marked dead (a mesh problem
  with a mesh fix, so it is reported instead of the plain "unavailable" row,
  not beside it), and Zigbee devices that have stopped checking in — ZHA's
  own \`last_seen\`, because a sleepy sensor is "available" between check-ins
  and availability alone says nothing about it.
- **The registry**: entities still named after their hardware (a name like
  \`0x00158d0001abcdef Temperature\` is unfindable in a picker and unsayable
  to Assist); devices in no area, which "turn off the kitchen" and every
  area card cannot see; helpers nothing refers to; device rows with no
  entities behind them.
- **The machine underneath**: nothing backed up, or nothing in a week; an
  add-on in an error state, or set to start on boot and stopped; a disk
  nearly full; a recorder database that has outgrown its headroom.
- **Dashboards** showing entities that no longer exist.
- **Forecasts**: a battery running down, from the slope of its last sixty
  days, three weeks before it is flat.

- **A reading well outside what your house normally does at this hour** —
  see below.
- **An automation you keep undoing.** A rule did something and somebody put
  it straight back. Nothing else can see it — the automation ran, nothing
  errored, and the light is off — and it is the clearest signal a house
  gives about a rule being wrong for it. Two shapes count: three times in a
  day, **measured against how often that rule actually ran** (three undos of
  something that ran three hundred times is you having an unusual Tuesday,
  not a broken rule), and the slower one — putting the same thing back once
  a day for weeks, which never reaches three in any single day and so is
  invisible to a daily count.

  When there is a pattern in **when** you override it, the finding says so,
  because that is the condition the automation is missing: *"almost always
  between 08:00 and 09:00 and only on weekdays"* is something you can write
  a condition around. When there isn't one, it says nothing rather than
  reading a shape into a coincidence.

- **Two automations undoing each other.** Both ran, neither failed, and the
  light is in whichever state the later trigger happened to leave it — so
  the result is different from one day to the next depending on the order
  two triggers fired in, which is not something anybody designed. No trace
  shows it, because nothing went wrong in either run.

A check's finding clears itself when the check stops finding it — the device
came back, the battery was changed — and it is simply removed, so it can be
raised again if the problem returns. What a person ends stays ended, exactly
as before. And every ending teaches the **scorecard** under the filters: "I
did it" and "Got it" say the report was right, "Wrong" says it was not, and
once a producer has a few endings the tab says how right it has been.

Findings reach you outside the panel too. The integration exposes an
**Open findings** sensor (the count, with the severity split and the texts as
attributes) and fires a **\`brain_finding\` event** for each new one, so an
automation can react the moment brAIn files something. And if you set
\`findings_notify_service\` in the add-on configuration to one of your
\`notify.*\` services, new findings at or above \`findings_notify_min_severity\`
(default \`serious\`) are pushed straight to it — a dead battery rings your
phone; a naming nitpick waits on the tab. The whole tab is also scriptable as
\`brain findings\` (list / fix / done / wrong / ack / snooze) from the terminal.

Between \`notify_quiet_start\` and \`notify_quiet_end\` (22 to 7 by default, in
your home's own timezone) only the **urgent** ones get through: a device that
has gone offline, an add-on that has stopped, a disk about to fill, a reading
that is impossible. Everything else is **held**, not dropped, and arrives as a
single message when the quiet ends. Urgency is not severity — a \`critical\`
battery forecast is three weeks away and a \`warning\` about a boiler that has
stopped answering is now — so it is a property of the check that raised the
row, not of the row's wording. Anything you fixed or dismissed overnight is
dropped from the queue rather than announced: being told at seven about a
problem that went away at four is how these messages stop meaning anything.
Set both to the same value (or leave both empty) to notify at any hour.
`,
  },
  {
    id: "it-explains-your-house-to-you",
    icon: "📊",
    title: "It explains your house to you",
    body: `
# It explains your house to you

The **Insights** dashboard is a set of cards, each one a small piece of analysis with
a real interactive visualisation — not a paragraph of text with a number in it.

There are **no default cards**, deliberately. A generic "Energy" card about a home
brAIn has never looked at says nothing useful and costs tokens every time it runs.
Instead the first run studies **your** house — how it's named, when it's occupied, what
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
`,
  },
  {
    id: "it-remembers",
    icon: "🧠",
    title: "It remembers",
    body: `
# It remembers

Everything else here is a feature. This is the part that makes brAIn get **better**.

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

**Study sessions** send it off to investigate: \`brain learn energy\`, or just type
"learn about the upstairs heating" in the ask bar. It digs through the registry,
history and long-term statistics for minutes at a time, and what it finds lands in
memory and in your findings list.

A study session **reads and never acts**. Since 1.48.0 it runs with the same
read-only tool lists the scheduled card runs use — read from one place, so there
is one answer to "what may an unattended run touch" — and if those lists cannot
be read it **refuses to run at all** rather than running unscoped. That is a
correction worth stating plainly: before 1.48.0 it passed no tool flags, so it
inherited the project's own permissions, which include Bash, Write and Edit — on
a path an automation can reach through the \`brain.study\` service. What it writes
is still written by brAIn afterwards, out of the JSON the session returned.

And everything it has learned is **portable**: \`brain memory export\` writes one
JSON file carrying the memory document, the findings list, the settled answers
and the facts ledger (the Knowledge tab's ⬇ Export does the same), and
\`brain memory import\` folds one back in on another install — ledgers merge with
the local entries winning, and the document itself is only replaced when the
local one is empty or you say \`--replace-memory\`. Migrating to new hardware no
longer means starting the learning over.
`,
  },
  {
    id: "it-answers-when-you-talk-to-it",
    icon: "🗣️",
    title: "It answers when you talk to it",
    body: `
# It answers when you talk to it

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
`,
  },
  {
    id: "it-has-a-full-terminal-in-two-shapes",
    icon: "💻",
    title: "It has a full terminal — in two shapes",
    body: `
# It has a full terminal — in two shapes

The **Terminal** tab is the real Claude Code CLI, in your browser, running as a
non-root user with your \`/config\` in front of it. Everything above, plus everything a
capable engineer with a shell can do: read logs, edit YAML, write scripts, install
packages, use git, take the long way round a hard problem.

It has two faces, and you switch between them with the **⌨/💬 button on the tab
itself** (or in ⚙ Settings). Both run the same Claude Code, on the same login, in the
same \`/config\`, with the same permissions — what differs is only how you see it.

**Chat** (the default) renders Claude Code's own output as a conversation:

- **Text reflows** to whatever screen you're on. A terminal is a grid of fixed
  columns; at the ~40 columns a phone has, that means sentences broken mid-word. This
  is ordinary text, so it wraps like text.
- **Code blocks keep the grid** — inside their own horizontal scroller, so a
  200-column log line never makes the whole page slide sideways.
- **Tool calls collapse to one line each.** \`Read /config/automations.yaml\`, with a
  dot that goes green or red; tap it for the arguments and the full result. In the
  grid terminal each of those was twenty lines you scrolled past.
- **Reasoning folds away** behind a "Thinking" line you can open.
- **Commands, both kinds.** Type **/** and you get the commands **your** Claude Code
  actually has — including anything you put in \`/config/.claude/commands\`. Type
  **brain** or **ha** and you get brAIn's own CLI, \`brain memory add\` through
  \`ha reload\`, with the same descriptions and argument hints the dispatchers print.
  ↑/↓ to move, Enter or Tab to pick. Both lists come from the thing that owns them, so
  neither can go stale.
- **⋯ holds the rest** — **New chat**, **Conversations** (every conversation in \`/config\`,
  started here or in the classic terminal; picking one replays it and carries on),
  **Session details**, **Model**, and the switch to Classic. Two buttons float over the
  terminal, not a column of them.
- **The chat picks its own model.** Press the model name under the message box (or
  ⋯ → **Model**) and choose — the current conversation carries straight on under the
  new model. Refused while **that** conversation is being answered, because the model
  is an argv flag and applying it is a restart that would lose the answer: stop it,
  or switch to another chat and pick the model there. It's the chat's own setting: insights and voice keep following the
  model on the Configuration tab, so a heavyweight model chosen for one
  conversation never quietly raises what everything else costs. **Default** follows
  the Configuration tab again.
- **Several conversations stay open at once, and switching stops nothing.** Each
  one holds its own Claude Code process, the way a terminal tab does — so picking
  another in the list is instant, and the one you left carries on writing its
  answer into its own transcript. Ask a long question, go and deal with something
  else, come back to it finished. A row says what its own session is doing:
  **answering…** while a reply is being written, **Needs your OK** when it is
  waiting on a permission (and the chat you **are** in says so too, with a button
  that takes you there, because a phone has no room for the list). A row with no
  mark is the ordinary case.
- **brAIn keeps three of those processes alive** — ⚙ Settings, one to eight. That
  is a count of processes, not of conversations: you may have as many
  conversations as you like and Claude Code keeps every one. Open a fourth and the
  one untouched for longest is closed to make room, with a note in its own
  transcript so going back to it explains the gap; your next message there picks
  the conversation straight up again. A conversation that is mid-answer is never
  the one closed. The only switch that is refused is when every open chat is still
  answering and there is nothing idle to close — it says exactly that, with the
  count and the setting.
- **Conversations can be deleted.** Every row in the list grows a **✕**, and the
  toast grows an **Undo** for the few minutes a mis-tap needs. One the chat is
  holding open is refused, and the ✕ offers to close it first rather than leaving
  you with a no — closing one mid-answer loses what it was writing, so it asks.
  (Old conversations that Claude Code itself has pruned can no longer be picked up
  mid-thought: reopening one shows its transcript and says plainly that the next
  message starts fresh, instead of erroring on every send.)
- **Yours, and everyone else's.** brAIn runs Claude in \`/config\` for voice, automation
  tasks and filing memory, so those conversations live beside yours. The list shows
  **Chats** by default — everything you started yourself, in the chat or the
  classic terminal, including a finding you opened for discussion — and puts the
  rest behind a chip each, alphabetically:
  **Automation**, **Cards**, **Fixes**, **Memory**, **Study**, **Voice** — with a count, and
  only for the ones your house actually uses. Each row's time is when something
  last **happened in** the conversation — opening one just to look at it doesn't
  bump it to the top.
- **Cards and Fixes open read-only.** Every insight run (scheduled or a question
  you asked) and every Fix-it run is a Claude conversation too, and its chip lists
  them all — pick one and it opens as a record: exactly what brAIn sent to Claude
  about your house, every tool call it made, and what came back. Read-only on
  purpose: those runs happen under the analyst's read-only tool scoping (or the
  fixer's), and quietly continuing one under the chat's permissions would change
  the conversation's rules mid-thread. Want to talk about what a run found? Ask
  in the chat — memory and the findings list already carry what it learned.
- **The input is a real text box**, so dictation, autocorrect and selection behave.
- **⏹ stops a running answer**, and **＋ starts a new chat**. The conversation
  survives a page reload, a phone locking, and the add-on restarting.
- **Session details** (under ⋯) shows the model, the project directory, how you're
  being billed, and the conversation's id.
- **The face switch carries the conversation, and it is the only control that does.**
  Switching to Classic releases the chat's process and the terminal picks the same
  conversation up — a new tmux window if it's already open, otherwise the next time
  you open it; switching back adopts whatever the terminal was last doing. There is
  deliberately no second "continue in the terminal" button beside a switch that
  already moves you, because two controls for one thing is how you end up unsure
  which one actually moved.
- **Every conversation says what state it is in.** A row in the rail (and in the ⋯
  dialog, which is the only surface a phone has) carries one of seven:

  | State | What it means |
  | --- | --- |
  | **Live** | A Claude Code process is running and idle. Type and it answers. |
  | **Answering…** | It is writing. **Stop** is the control above the composer. |
  | **Needs your OK** | It has asked to use a tool. Answer the card; an unanswered one declines itself. |
  | **(no pill)** | Paused: no process, and your next message resumes it with its context. |
  | **Paused to make room** | brAIn keeps \`chat_max_sessions\` chats running at once (3, settable 1–8). This one was the quietest and was stopped; **Resume now** brings it back. Only an **idle** conversation is ever taken, never one that is answering. |
  | **Context lost** | Claude Code no longer holds this conversation. You can read it; a new message starts fresh from here (**Start fresh**). |
  | **Record** | A card or fix run, kept to be read. It ran under the analyst's or the fixer's rules, so it can never be resumed — **Ask about it** opens a new chat about it instead. |

  A status line above the composer says what sending will do, and offers the one
  control that fits that state — **Stop**, **New chat**, **Resume now**, **Start fresh**,
  **Ask about it**, or nothing at all while an approval card is the thing to answer.
  The state is derived in one place and kept in the
  conversation's own metadata, so a reload agrees with what you were just looking at.

Both faces stand in \`/config\`, which is what lets them see each other's
conversations at all: Claude Code files them per working directory. So \`claude
--resume\` in the terminal lists the chats you had in the panel, ⟲ in the chat lists
the ones you had in the terminal, and a conversation can move either way without
losing anything.

**Classic** is ttyd over tmux — a true terminal. Use it for anything that draws its
own screen (a TUI, \`htop\`, an installer), for running shell commands yourself, or
simply because you prefer it.

- **Native Home Assistant access** through the same MCP server the rest of brAIn uses.
- **\`/config/CLAUDE.md\` written for you** at startup, describing your actual
  installation, so a fresh session already knows your house.
- **Built for a phone**, not merely tolerable on one: a key toolbar that stays above
  the software keyboard, working copy/paste, swipe-scroll, an iOS dictation fix, and
  a top bar that folds away while you're typing so the terminal gets the screen.
- **Sessions survive.** tmux underneath, so a dropped connection doesn't kill your
  work, and the environment persists across restarts.
`,
  },
  {
    id: "it-works-while-youre-asleep",
    icon: "🌙",
    title: "It works while you're asleep",
    body: `
# It works while you're asleep

- Recurring insight cards regenerate on their own schedule.
- Memory consolidates in the background.
- Automations can hand brAIn work: \`brain.run_task\` gives it a job and lets it use
  tools, \`brain.send_prompt\` asks it a question, \`brain.run_insight\` regenerates a
  card, \`brain.study\` sends it off to research something, \`brain.add_memory\` teaches
  it a fact, and \`brain.intent\` turns one sentence into an automation that runs
  once and switches itself off — which is how a voice command reaches it. Wire
  them to any trigger you like.
- Insight jobs render to \`sensor.<name>_insight\` with the markdown and ready-to-paste
  card YAML as attributes, so a report can drive a template, a notification, or a
  dashboard.
- Findings surface as \`sensor.brain_findings_open_findings\` and a \`brain_finding\`
  event per new one — and \`findings_notify_service\` pushes them to a phone with no
  automation at all.
- The same findings are the \`todo.brain_system_brain\` list in Home Assistant's own
  **To-do** panel and mobile app: one list, two views. Ticking one off is "I've fixed
  it" and deleting one is "not a problem here" — the Findings tab's own two endings,
  so answering from your phone teaches brAIn exactly what pressing the button would
  have.
- \`sensor.brain_usage_limits_health\` says whether brAIn itself is working, so an
  automation can tell you the add-on is in trouble rather than you noticing the
  insights stopped.

Those entity ids are what Home Assistant derives from the device and entity names,
so they are what a fresh install gets. If you have renamed anything, yours differ —
the surest way to find them is Settings → Devices & services → brAIn → entities.
`,
  },
  {
    id: "it-knows-what-unusual-means-here",
    icon: "📈",
    title: "It knows what \"unusual\" means here",
    body: `
# It knows what "unusual" means here

"Unusual" is behind most of what people want a smart home to notice — water
running at night, a freezer drifting, a boiler on for twice as long as it
usually is. Until there is a number behind it, every rule that uses it is a
threshold somebody guessed.

So brAIn measures your house. Overnight, for every numeric sensor, it works
out what that sensor normally reads **at this hour of this day of the week**
and how much it normally varies, from a month of Home Assistant's own
long-term statistics. It costs no Claude turn.

A few things it deliberately will not do:

- **It won't call a sensor that never moves "unusual".** A thermostat
  setpoint that has read 20.0 for a month has no variation to measure
  against, so it gets no baseline rather than one where 20.5 is an
  emergency.
- **It won't build a normal out of two readings.** An hour of the week it
  has only seen twice is an anecdote, and it says so instead.
- **It won't report an impossible reading as an odd one.** A thermometer at
  99°C is broken, not unusual, and the device check says so with the right
  fix on it.
- **It won't hand you fifty rows.** More than a handful at once means the
  **baseline** has stopped describing your house — a heating season starting,
  a meter replaced — and reporting them all would be reporting the
  measurement rather than the home.

- **It won't report a meter for going up.** A \`total_increasing\` energy
  total is higher than it has ever been every hour of its life; that is
  what the class means, so "far above its usual" would be a statement
  about arithmetic rather than about your house.

**And it watches the slow ones**, which is the failure with no bad reading
in it. A freezer 6°C warmer than it was a month ago has never once been
outside its usual range — because the range is built from the same weeks
the drift happened in and moved along with it. Measured on a real-shaped
month, that freezer reads 2.3 spreads to the "unusual" check, which needs
six, and 16 to the trend. Nobody notices until something spoils.

So brAIn also fits a line through the month, to what is left once the
week's own pattern is taken out, and tells you when a reading has been
walking one way for weeks — with the same discipline. Something that
turned around in the middle of the window is not a drift. A step change
is not weeks of drifting. A move smaller than the noise it sits in is not
a move. And when five thermometers drift together that is the weather
rather than a device, so the whole class stands down: what you get is the
one room that is doing something the others are not.

Claude can read it too: ask **"is the utility room damp?"** and it looks up
what damp normally is in your utility room rather than picking a number.
`,
  },
  {
    id: "it-knows-what-is-normally-open",
    icon: "🚪",
    title: "It knows what is normally open",
    body: `
# It knows what is normally open

A door being open is not wrong. It is wrong at half past eleven in a home that
always has it shut then, and it is nothing at all in one that leaves it open
all summer — and until brAIn measured that, the difference was a threshold
somebody would have had to guess.

So it measures: for every door, window, lock, cover and garage, how much of
each hour of the week it is normally open, from a month of your own history.
Time-weighted, not sampled — a door open for ten minutes and one open for ten
hours look identical to anything that just checks now and then.

Then **at your own bedtime** (the hour brAIn measured you settle, or a late
fallback until it has), it files one finding if something is open that usually
is not. One row, not one per door: it is a single thing to do before bed.

It stays quiet in the cases that would make it noise. Not in the afternoon —
a door open at four is a door somebody is using. Not about an hour it has
never watched, which is a different thing from an hour it has never seen the
door open in. Not about a door that is **usually** open then. And not at all
when half the house is open at once, because that is you airing the place out
rather than a door left ajar.

Only closures are measured — a motion sensor being on at midnight is not
something anybody wants told about, and including it would bury the row that
matters.
`,
  },
  {
    id: "it-knows-when-your-house-gets-up",
    icon: "⏰",
    title: "It knows when your house gets up",
    body: `
# It knows when your house gets up

Everything scheduled used to happen at a time somebody typed into a box,
which is a timer, not a rhythm — 07:00 is early on a Sunday and late on a
Tuesday in the same home. So brAIn measures it instead: the first thing a
**person** does each day is the house waking up, and the last is it settling.
Not a motion sensor (which fires for a cat and for the heating) and not a
light (an automation does that at dawn) — somebody actually doing something.

It keeps two numbers a day and nothing else, and it will not answer until it
has **10 separate days** of them. Weekdays and weekends are measured apart,
because one number over both is wrong on all seven days rather than on none —
so the weekday answer takes about two weeks and the weekend one about five,
since a weekend is two days a week. And a home that stirs anywhere between 05:00 and 11:00 has no
usual time, so it says so rather than reporting the middle of that as one.
`,
  },
  {
    id: "a-morning-brief-when-there-is-something-to-say",
    icon: "☕",
    title: "A morning brief, when there is something to say",
    body: `
# A morning brief, when there is something to say

Turn on **Send a morning brief** and brAIn sends one short message a day to
your notify service, at the hour your home actually starts moving.

The part that matters is when it **doesn't**. The decision to send is made
before Claude is asked anything, out of things already counted: findings filed
since the last brief, brAIn itself not working, an odd night. A quiet morning
costs nothing and sends nothing — "all quiet" every day is the message people
mute, and each one that **is** sent costs a Claude turn, which is why this is
off by default.

What Claude is for is the sentence: under eighty words, one paragraph, no
greeting and no headings, because this is read on a lock screen. It can look
things up to make a reason specific ("the freezer is at -12, usually -18") but
it is not handed your house and it may not invent a number.

Until brAIn has watched for a couple of weeks it uses the fallback hour you
set. If it has been restarted and missed the window it waits for tomorrow
rather than delivering breakfast at lunchtime.
`,
  },
  {
    id: "one-report-a-week",
    icon: "📰",
    title: "One report a week",
    body: `
# One report a week

Turn on **Send a weekly report** and brAIn sends one message a week — by
default on a Sunday, at the same hour the brief would go. It is the report
meant for everybody in the house, so the notify service to point it at is
usually \`notify.notify\`.

It carries four things: what you used against the week before, what was found
and what was answered, what brAIn learned, and **one thing to do this week**.

That last one is chosen **before** Claude sees anything — the worst open
severity, then the one open longest. Asked to pick, a model picks the finding
it can write the best sentence about, which is the one carrying the most
detail rather than the most consequence.

It is not the morning brief with a longer timer. The brief asks *is there
anything**; the report asks **what happened*, and its failure is the opposite
one — a report that lists everything is the pile of unread cards it replaced.
So every section is gathered and capped before Claude runs, and Claude's job
is to say those things rather than to choose them.

A week with nothing in it — nothing found, nothing answered, nothing learned
and no meter to read — sends nothing. And unlike the brief, a report that
missed its hour still goes out later that day: a weekly report on Sunday
afternoon is still that week's, and skipping a week to protect an hour is the
wrong trade.

\`brain weekly\` prints what this week holds without sending; \`brain weekly
send\` sends one now — which **moves the week**, so the next scheduled report
is a week from now rather than a week from Sunday.
`,
  },
  {
    id: "what-the-house-used",
    icon: "⚡",
    title: "What the house used",
    body: `
# What the house used

The energy half needs one thing from you: **Home Assistant's own Energy
configuration**. brAIn reads the grid sources you declared there and nothing
else. It deliberately does not gather up every sensor with a device class of
\`energy\` — a whole-home clamp, an inverter and every smart plug behind them
all carry that class, so a house with six plugs would report roughly twice
what it used and nothing on screen would say so. No energy configuration
means no energy section, and a sentence saying which.

Cost appears only where the Energy dashboard has a cost **statistic**. If you
gave it a price to multiply instead, Home Assistant makes its own cost sensor
under a name brAIn would have to guess at, and a guessed name quotes somebody
else's number.

Both weeks are seven complete days ending at last midnight — never a partial
today, which would report a 45% fall that is nothing but the clock. If a meter
was reset or replaced mid-week those days are dropped, and with them the
comparison: you get the total it could measure and "no comparison to make"
rather than a plausible-looking drop.
`,
  },
  {
    id: "it-knows-when-the-washing-finished",
    icon: "🧺",
    title: "It knows when the washing finished",
    body: `
# It knows when the washing finished

Nothing in Home Assistant says a cycle ended. A smart plug reports watts, and
every rule written on one is a number typed into a box — \`> 10 W\` is a running
dishwasher in one house and a phone charger in the next.

So brAIn measures each machine instead, overnight, from ten days of its own
five-minute history. What it looks for is a **shape**: hours near a floor,
punctuated by runs well above it. A sensor that does not have that shape — a
router, a fridge's standing draw — gets no profile at all rather than a
guessed threshold.

The part that matters is the waiting. A dishwasher's dry phase draws almost
nothing for twenty minutes, so a machine that reported "done" the moment the
power dropped would report it three times a cycle. That quiet phase is
measured too: the gaps between draws are themselves in two groups — lulls of
minutes inside one cycle, idles of hours between them — and the jump between
the groups is the machine telling brAIn how long its own quiet phases last.

You need a power sensor on the appliance (a smart plug is enough) and about
ten days for it to have run a few times. \`GET /api/appliances\` shows what was
measured; ⚙ Diagnostics shows how many machines have a shape.

**The chore** is narrower than the measurement. brAIn will tell you a washing
machine, a tumble dryer or a dishwasher has finished and is still full — and
nothing else, matched on the sensor's name. That is a deliberate guess in the
cheap direction: not recognising your machine costs a missing reminder, while
recognising the wrong one means a notification telling you to go and empty
your television.

It waits before saying anything (a cycle that ended four minutes ago is
somebody standing at the machine), it stops asking after about half a day
(yesterday's washing is not a chore), and it is never urgent — so quiet hours
hold it until morning.

**It cannot see that you emptied it.** An empty machine and a full one draw
exactly the same power. So the chore ends the way every finding ends: tick it
off in the To-do app, press the button on the notification, or press it on
the Findings tab. It also clears itself if the machine runs again.
`,
  },
  {
    id: "it-knows-how-your-house-holds-its-heat",
    icon: "🌡️",
    title: "It knows how your house holds its heat",
    body: `
# It knows how your house holds its heat

Every climate question people actually want answered is the same two numbers
about a room, and until now brAIn held neither. *Start the heating so the
bedroom is warm when we get up. Is a window open, or is it just cold? Will
the pipes freeze by morning? What would a 17°C setback cost?* Each of those is
a threshold somebody guesses at, and a threshold that is right in one house is
wrong in the next — a stone cottage and a new flat lose heat an order of
magnitude apart, and so do two rooms of one house.

So brAIn measures them, per room, overnight, from a month of hourly history:

- **How fast the room falls towards outside.** Its reciprocal is the number
  people have an intuition for — *this room holds its heat for about eight
  hours.*
- **How fast anything puts it back**, in degrees per hour, from the hours the
  room was seen to be gaining.

You need one outdoor temperature sensor and at least one indoor one in an
area. Without an outdoor reference there is no model at all and ⚙ Diagnostics
says so in as many words — every number here is a **difference** from outside,
so there is nothing to measure a room against.

**The measurement is taken at night on purpose.** A south-facing room warms
with the heating off, and a fit that includes an afternoon reports a room that
gains heat as it gets colder outside. Deep night has no sun and, in most
houses, no schedule.

Two findings come out of it, and both are floored hard because both are
extrapolations from a fit.

**A room that never reaches the temperature it is set to.** Nothing errors:
the thermostat calls, the valve opens, the boiler runs, and the room sits two
degrees under its setpoint all winter. brAIn will only say so when the
arithmetic **and** the evidence agree — the room must never once have been seen
at the temperature it is asked for, over a month of hours. That second half is
what keeps it off healthy houses: a thermostat that switches off at its
setpoint never lets a room show what it could have done, so the measured
ceiling of a well-heated room understates it. It also says nothing at all if
the month held no cold night, because a January answer cannot be extrapolated
out of an August.

**A room that empties much faster than the rest of the house** — a draught, a
loft hatch, an open flue. It needs four measured rooms before it will compare
one against the others, and the room has to be fast in absolute terms too:
twice the loss rate of a very well insulated house is still a good room. If
half the house fires at once it says nothing, because that is the measurement
and not a room.

Neither is ever urgent. A room that has been two degrees short all winter is
not two degrees shorter at three in the morning, so quiet hours hold both.
`,
  },
  {
    id: "what-the-thermal-model-is-for",
    icon: "♨️",
    title: "What the thermal model is for",
    body: `
# What the thermal model is for

Three more findings come out of the same two numbers, and each answers a
question no single state can.

**Your heating starts too late.** A schedule set to a fixed hour warms the
bedroom to its setpoint at 07:40 in a house that is up at 07:00 — every
weekday, with nothing anywhere recording a fault, because the automation ran
and the room did get warm. brAIn needs three of its own measurements to agree
before it will say so: when this house **actually** gets up, what the room reads
at that hour of an ordinary week, and how long the climb takes. Then it names
the time the heating would have to start.

It reports weekday mornings only — that is where a schedule exists, and where
the wake time has enough days behind it — and it says nothing at all until
that wake time is measured rather than assumed. A preheat time pinned to a
typed-in 07:00 is a guess wearing a number.

**A window is open.** A room falling more than twice as fast as its own
insulation allows is losing heat by a route the walls do not have. This one is
only sayable **because** the model exists: the same half-degree in ten minutes is
a draught in one room and an ordinary evening in another, and no fixed
threshold can tell them apart.

**The pipes are at risk.** From the current reading and the current outdoor
temperature, when does this room reach 5 °C — the point water in an outside
wall starts to be at risk, well before the room's own thermometer reads
freezing. It only reports a room that is **already falling**, rather than
assuming nothing is heating it: no state in Home Assistant says the heating is
off, so the fall is the evidence.

The last two read five-minute history rather than hourly, because an hourly
average cannot see a window opened forty minutes ago — it is still inside the
hour that has not finished. Both are urgent enough to break quiet hours; the
preheat one is not, because a schedule that starts late will start late again
tomorrow.
`,
  },
  {
    id: "where-a-proposal-comes-from",
    icon: "💡",
    title: "Where a proposal comes from",
    body: `
# Where a proposal comes from

The first thing brAIn proposes is **what you already do by hand.** Somebody
walks over and turns the hall lamp on at about twenty to seven every weekday.
No check can report that — the light works, the switch works, nobody has
complained — and it is nonetheless the most useful thing a house knows about
itself.

So the checks pass keeps the changes a **person** caused, and only those: an
automation moving a light says nothing about a habit, and a wall switch reaches
Home Assistant with no record of who pressed it, which brAIn reports as
\`unattributed\` rather than guessing. Two months are kept, in the domains a
timer can sensibly act on.

Five things have to hold before any of it is offered, and each one answers
"would this fire on a house with no habit in it":

- **Six separate days**, not six presses. Twelve presses on one Monday is one
  Monday.
- **A share of the days it could have happened on.** Six times in a fortnight
  is a habit; six times in two months is a coincidence, and a count with no
  denominator reports both identically. Weekdays and weekends are counted
  apart, so a weekday habit is graded against weekdays.
- **A time, not a stretch of evening.** The times are averaged *around the
  clock* — half past eleven and half past midnight are forty minutes apart, and
  a plain average of them is noon — and anything more scattered than about
  three quarters of an hour is not a time of day.
- **It has to still be happening.** A habit you dropped in the spring has a
  beautiful spring in the record.
- **Nothing must already do it.** A second automation moving the same thing to
  the same state is not a helpful duplicate; it is two rules that will disagree
  the first time their triggers land in the wrong order.

What it writes is a plain time trigger, with a weekday or weekend condition
when the habit has one — never a condition it did not measure. A pass offers at
most three, strongest first; the rest are still there next time.
`,
  },
  {
    id: "it-suggests-things-and-proves-them-first",
    icon: "🧪",
    title: "It suggests things, and proves them first",
    body: `
# It suggests things, and proves them first

The **Proposals** tab is the only list in the panel that is not about something
being wrong. It gets its own tab rather than a row on Findings: a list of things
you might want, sitting beside a list of things that are broken, makes both
worse — the broken things stop looking urgent and the nice-to-haves start to.

\`\`\`
proposed  ──"Try it for a week"──▶  trialling  ──▶  accepted
          └──"No thanks"──────────────────────────▶  declined
\`\`\`

**Nothing brAIn writes is enabled on its own.** You can accept a proposal
straight away — it is your house and your yes — or press **Try it for a week**
first, and what you give up by skipping the trial is the evidence: a trial is
a replay of the week as you live it: every few hours brAIn replays the proposed
automation over the days since you started it and grades each firing against
what you **actually did**, from the record of your own presses it already keeps.
Nothing is called and nothing is enabled. The card fills in as the week goes
on — *"three days in: it would have fired three times, and you did the same
thing yourself on two of them"* — rather than staying blank until Sunday.

Each firing gets one of three answers. **Agreed**: you did the same thing
within a quarter of an hour. **Nothing happened**: weak evidence either way,
and it says so rather than counting against the change. **You did the
opposite**: you would have undone it, which is the one answer worth having and
is deliberately not folded into the second.

Some automations cannot be replayed at all, and the trial says which rather
than reporting a confident zero — see **What a replay can and cannot answer**
below. When the week is up the trial stays where it is with its report
attached: ending it is your press, not brAIn's.

An automation you accepted after watching it be right five times out of six is
a different object from one you accepted because it sounded reasonable.
`,
  },
  {
    id: "saying-yes-and-taking-it-back",
    icon: "↩️",
    title: "Saying yes, and taking it back",
    body: `
# Saying yes, and taking it back

**Accept writes a real automation.** It is appended to \`automations.yaml\` with
an \`id\` of \`brain_<proposal id>\`, the proposal's title as its alias, and a
description saying where it came from. Your file is not reformatted — the
automation is added at the end and everything above it is left exactly as you
wrote it, comments and all.

Then three things have to be true before the proposal is marked accepted:
Home Assistant reloads its automations, the new \`automation.<name>\` entity
turns up, and only then does the row leave the list. If any of them fails,
brAIn **puts the file back**, reloads again, and tells you what it tried — a
yes it could not honour is not a yes it records, so the proposal is still
there to press again once the reason is fixed.

**Undo is on the toast, and it reverses all three.** The automation is removed,
Home Assistant is reloaded, and the proposal comes back on the list under its
own id. If the file cannot be put back — the snapshot has aged out of the edit
journal — it says so rather than claiming a success, because the automation is
still running.

The file is snapshotted into the same edit journal that records Claude's own
edits **before** it is touched, so \`brain undo\` in the terminal reverts an
accepted proposal exactly as it reverts anything else Claude changed.

**Four things stop an accept, each in a sentence.** An automation acting on
something in your **protected entities** list — asked here as well as in the
MCP server, because a file the panel writes never passes through that
chokepoint, and refused outright when it targets an **area** rather than named
entities, since brAIn cannot expand one safely. A \`configuration.yaml\` with no
\`automation: !include automations.yaml\` line: your automations live somewhere
brAIn cannot find, and appending to a file Home Assistant does not read would
be a change that silently does nothing. An \`automations.yaml\` that is not a
list of automations. And a duplicate \`id\` or name.

**Every proposal carries its evidence**, because a suggestion from nowhere
deserves a no. That is the reason it was raised, plus a **replay** — brAIn runs
the automation against the last month of your own recorded history and tells you
what it would have done. Answered in seconds, before anything is enabled.

**Saying no teaches it more than saying nothing.** The reason box is optional
(a required field turns a one-press dismissal into a chore and fills up with
"no"), but a sentence like *"the hall light stays on because my partner works
nights"* is a fact brAIn did not have, and it stops the same suggestion coming
back in different words next month. It goes into memory exactly as a finding's
**Wrong** does.

A declined proposal is remembered by the **change** it described, not by the
sentence describing it — so a miner that rewords its own explanation is still
offering something you already answered, and it will not be offered again.
`,
  },
  {
    id: "what-a-replay-can-and-cannot-answer",
    icon: "⏪",
    title: "What a replay can and cannot answer",
    body: `
# What a replay can and cannot answer

\`POST /api/replay\` takes an automation and a window and reports when it would
have fired.

It covers **\`time\`, \`state\`, \`numeric_state\` and \`template\`** triggers — the
four Home Assistant's recorder can reconstruct. Anything else is refused **in as
many words**, and refused **whole**: an automation with a state trigger **and** a
webhook trigger is not replayed for the half that can be read, because
reporting "this would have fired twice" about something whose webhook fires
forty times a day is a confident wrong number that looks exactly like a right
one.

A template is replayed only when every entity it names has recorded history, and
only using a named set of Home Assistant's own helpers. Rendering against a
half-built world gives a blank; a blank reads as \`unknown\`, which reads as
\`false\`, which is a confident **no**.

Three details decide whether a number is right, and each is tested against the
version that gets it wrong:

- **\`for:\` is a promise about a stretch of time.** A three-minute door blip does
  not clear a ten-minute hold.
- **\`numeric_state\` is a crossing, never a level.** Home Assistant fires on the
  way in, not for every sample spent inside the range.
- **An area or device target is recorded and not resolved.** Expanding one needs
  the entity registry as it was at the time, and a wrong expansion would tell you
  a proposal touches lights it does not.

The window reaches back at most 30 days, because the recorder's default purge is
ten days and most houses leave it there.
`,
  },
  {
    id: "the-house-acts",
    icon: "🛠️",
    title: "The house acts",
    body: `
# The house acts

Two things brAIn does that nothing else on this page does: it fixes a small,
fixed set of problems while you are asleep, and it writes the automation you
would want on a bad night. Both are off until you switch them on, and both are
built around what they refuse to do.

**Three things it may fix overnight** — and only three, and only with
\`self_healing\` turned on:

| What is wrong | What it does |
| --- | --- |
| An add-on set to start on boot is not running | Starts it |
| A Z-Wave node the controller has marked dead | Pings it |
| An integration that did not finish setting up | Reloads that entry |

Each is a call you would have made yourself, and each fails into nothing. There
is **no power-cycling of anything**, no restart of Home Assistant, no restart of
brAIn, and **no Claude run anywhere on this path** — a model deciding what to
restart in your house at 3am is a guess wearing a repair.

It runs **once a night, inside your quiet hours**. With no quiet hours set it
runs an hour after the time brAIn has **measured** your house going quiet; with
neither, it does not run at all, and the ⚙ Diagnostics section says so — running
at an hour nobody set would be acting on a guess about when nobody is looking.

- **At most three repairs a night.** Nine broken things at once is not a house
  to fix unattended.
- **One try per problem per night**, written down as it goes, so restarting the
  add-on at 3am does not start the same thing twice.
- **Never anything on your protected entities** — the node's whole device is
  checked, not just the sensor, because a ping reaches the box and the box might
  be a lock. If brAIn cannot work out what a repair would touch, it skips it
  rather than guessing.
- **Never something you have already answered.** If you pressed **Fix it** or
  **Wrong** on that finding, it is yours.

**Nothing here checks its own work, and that is deliberate.** A call the
Supervisor accepted is not a working add-on. What proves a repair is the next
house-checks pass: the finding clears, or it does not — and the morning brief
tells you which, with the time: *"started the Mosquitto broker add-on at 03:10;
it is working now."*

**Emergency playbooks** are the other half, and brAIn never runs one. It
**writes** one and offers it on the Proposals tab; Home Assistant runs it if you
accept it. Three, and each only when your house has the sensor for it:

- **Smoke or CO** — every light to full brightness, heating and cooling off,
  blinds and curtains open, and a notification naming the room the detector is
  in.
- **Water leak** — water valves closed, water switches off, water heaters off,
  and a notification naming the room.
- **Freeze with the heating stopped** — the coldest room brAIn has measured
  falls below 5 °C **and** its thermostat has been doing nothing for half an hour.
  **This one only tells you.** Nothing here turns a boiler on: brAIn cannot know
  why the heating stopped.

**No playbook unlocks a door or disarms an alarm.** Not as a setting, not ever.
A smoke detector is the sensor in a house most likely to go off over burnt
toast, and a false alarm that opens the house at three in the morning is a worse
outcome than any it could prevent.

**Every entity it would act on is on the card, by name**, grouped by what
happens to it — and anything on your protected list is shown as *skipped:
protected* rather than quietly left out, so you can see that brAIn knows it is
there and knows it may not touch it. If protection leaves a playbook with
nothing to do but send a message, it is not offered at all.

Which valve, which lights, which thermostats: all of that is read straight from
your registries. **No model chooses any of it** — a model picking which valve to
close is a guess you could not check afterwards, because the automation would
look exactly the same either way. Claude writes one thing, optionally: the
paragraph on the card explaining it in plain English, and if that run fails the
card still says what it does.

**Rehearse it** shows every call it would make with each target's state right
now — **"12 lights → on (3 already on), 1 valve → closed (open now)"** — and
**changes nothing**. It deliberately does not use Home Assistant's
\`automation.trigger\`, which would run the actions; that is not a rehearsal, it
is the emergency. A real rehearsal is setting the detector off on purpose and
reading the automation's trace afterwards.

**There is no trial button on a playbook.** A trial replays the week you have
just lived, and that week had no smoke alarm in it — a button that cannot answer
the question is worse than a sentence saying why.

Accepting one goes through the same path as any other proposal: written to
\`automations.yaml\`, reloaded, verified, reverted if it did not take, and
undoable from the toast. Declining one is remembered by the **change** rather
than the sentence, so it comes back if you fit another detector — the automation
is genuinely different then — and not because the wording moved.
`,
  },
  {
    id: "the-condition-it-is-missing",
    icon: "🧩",
    title: "The condition it is missing",
    body: `
# The condition it is missing

When brAIn has watched you put the same automation back, at the same sort of
time, on enough separate days, it can say more than **"you keep undoing this"**.
It offers the **condition the automation does not have**: *"Stand Evening
lights down between 21:00 and 23:00 on weekdays."*

The card carries two numbers, because one on its own is a fact about an
automation rather than a reason to change it — *"over the last 30 days it ran
30 times; with this condition it would have run 22, 8 fewer, in the hours you
keep putting it back."*

Accepting this one **changes your automation** rather than adding another, and
the card says so with a pill. brAIn edits exactly the bytes of that one entry:
your ordering, your comments, your quoting and every other automation in the
file are untouched, byte for byte. Undo puts the file back exactly as it was.

What it writes is one \`time\` condition inside a \`not\`. That is not decoration.
A plain \`time\` condition passes only when the clock is in its window **and**
the day is in its weekday list, so adding one directly would stand the
automation down every Saturday and Sunday too, at every hour — which is not
what you have been telling brAIn by undoing it on weekday evenings.

Four things stop it being offered. A refusal is not a card — there is nothing
to answer — so ⚙ → Diagnostics names which automations were skipped and why:

- **The automation has no \`id\`.** Home Assistant's own editor cannot change one
  either — there is nothing stable to address it by. Open it in the automation
  editor and save it once, and brAIn will offer this again.
- **It already stands down over those hours.** You wrote the condition; a
  second copy of it is noise.
- **Its existing time condition names an entity** (an \`input_datetime\`) rather
  than a clock time, so brAIn cannot read what it already forbids — and "I
  could not tell" is not "there is nothing there".
- **It acts on a protected entity.**
`,
  },
  {
    id: "something-that-happens-once",
    icon: "🎯",
    title: "Something that happens once",
    body: `
# Something that happens once

**"Turn the porch light off when the guests leave."** *"Tell me when the tumble
dryer finishes."* These are the sentences people already try to say to their
house, and no automation fits them: an automation is a standing rule, and this
is a thing to do next time.

Type one into the ask bar — anything beginning **when…**, **once…**, *the next
time…**, **tell me when…* — or call \`brain.intent\` with a \`sentence\`, which is
how a voice command reaches it. Claude reads your house (searching only; it
cannot act) and works out the automation, and it arrives on **Proposals** with
your sentence, what brAIn understood, and a replay saying how often that
trigger would have fired over the last month. That replay is a sanity check on
a trigger that has never fired — for a one-off it is not evidence that you want
it, it is evidence that brAIn read the right thing.

Accepting writes an ordinary automation with one extra action brAIn adds
itself: it switches itself off after it runs. So Home Assistant does the
running, and there is nothing still going afterwards.

Then the card says **armed**. When it fires, the card says so and the time, and
offers **Remove**. Nothing removes it for you — an automation that vanished
from your file while you were not looking is a file you cannot trust — and one
that has been waiting a fortnight without firing is offered the same Remove
with **"it has never fired"** rather than being cleaned up.

brAIn will not arm a sentence it cannot do properly, and it says so on a card
rather than in a log:

- **It sounds like a standing rule.** **"Turn the porch light on at sunset"** is
  something that should keep happening, and it is a good thing to want — ask
  for it as an ordinary change and it gets a replay, a trial week and a report.
  The card shows what brAIn understood, so you can see which half it misread.
- **The trigger cannot be replayed** (a \`webhook\`, a \`device\` trigger). Without
  a replay there is no check at all on a trigger that has never fired.
- **The sentence named nothing brAIn could find**, or nothing it could act on.
- **It touches a protected entity.**
- **You already have six one-offs waiting.** A list of things about to happen
  is only useful while it is short.
`,
  },
  {
    id: "four-scenes-for-a-room",
    icon: "🎨",
    title: "Four scenes for a room",
    body: `
# Four scenes for a room

**"Design my evening for the living room"**, or pick a room from **Design scenes
for** at the top of the Proposals tab. brAIn composes four — morning, day,
evening, night — from the lights that room actually has.

What each bulb gets is read from what it can be told. A bulb that takes a
colour temperature gets one; a colour-only bulb gets the nearest colour; a
dimmable one gets a level; a bulb that only switches gets on or off, and the
card says which. A bulb whose capabilities cannot be read at all is included as
on/off rather than left out.

Morning is cool and bright, day is neutral and full, evening is warm and
dimmed. **Night turns the room off except anything named like a nightlight** —
a bedside lamp, a hall light. There is no attribute for "this is the one I
leave on", so the name is what brAIn goes on; a room with nothing named that
way goes fully dark at night, which is what night means in a room without one.

The card shows the four as **swatches**, one per light per mood, so you see the
moods before saying yes. A light that is off in a scene is drawn as an empty
outline rather than a dark square. Anything on your protected list is left out
and listed as skipped.

There is no trial button: nothing in the last month set these scenes, so there
is no week to replay. Accepting writes them to \`scenes.yaml\` — appended, with
your file above them untouched — reloads scenes, checks all four really
appeared, and puts the file back if any of that did not happen. Undo takes them
straight out again.

Once the four are really there, brAIn offers a **second** proposal: the
schedule that moves between them. That one is an ordinary automation, so it
gets a replay and a trial week like any other. Morning and night use the times
brAIn has measured for when this house gets up and settles; the middle two are
fixed guesses and the card says so.

Two rooms are refused, each with the reason: one with fewer than two lights
brAIn can set (four scenes over one bulb is four ways of saying the same
thing), and one with more than forty (that is a floor, not a room — split it
into areas). Claude is used for exactly one thing here: naming the four. If
that run fails you get **Morning**, **Day**, **Evening**, **Night**, which work fine.
`,
  },
  {
    id: "answering-without-opening-anything",
    icon: "📱",
    title: "Answering without opening anything",
    body: `
# Answering without opening anything

Two places show brAIn's work list, and both of them can end an item.

**\`todo.brain_system_brain\`** is the open findings in Home Assistant's own To-do
panel and mobile app — the same list the Findings tab shows, as items. Completing
one is the tab's **I fixed it**; deleting one is its **Wrong**. Both are the tab's
own endings, so the memory line, the settled key and the row leaving the list all
happen exactly as they would have — the To-do app has its own two verbs and there
is no third vocabulary here.

You cannot **add** an item. There would be nothing behind it and it would vanish
on the next refresh, and a list that silently deletes what you put on it is
worse than one that does not offer to take it. There are no due dates yet
either: a forecast's date lives in the prose of its detail ("about 9 days
left"), and a date parsed out of a sentence is a guess with a calendar entry
attached to it.

The list needs Home Assistant 2023.11 or newer (the To-do panel's own floor).
On anything older it is simply absent.

**Notifications get buttons** — **I've fixed it**, **Not a problem**, **Later** —
when two things are true: the notify service is the Home Assistant companion
app (\`notify.mobile_app_*\`), and the message is about exactly one finding.
Every other notifier means something different by the payload the buttons ride
in, or nothing at all, and a guess there is how a working notification stops
arriving; and a digest about three problems could not say which one a button
answered. In both cases the message is the one you were already getting.

Either way the answer reaches the add-on through a small file on
\`/config/.brain/\`, not over the network — brAIn's panel port is deliberately
not published — so if the add-on is stopped when you tick something off, the
answer waits for it rather than being lost.
`,
  },
  {
    id: "it-knows-what-changed-and-what-changed-it",
    icon: "🕵️",
    title: "It knows what changed, and what changed it",
    body: `
# It knows what changed, and what changed it

A state does not carry a cause. Nothing in \`light.kitchen\` being on says
whether somebody pressed a switch, an automation fired, a voice command
asked, or brAIn did it — and that is the question behind most of what people
ask their house.

The **Activity** tab reads Home Assistant's own logbook and puts a cause on
every row: the automation by name, the script, the scene, the person, the
voice assistant, or brAIn. Tap a row for that entity's own recent history.
Page back a day at a time; filter by cause. It costs nothing — no Claude run,
no stored copy — and it needs the \`logbook\` integration, which is part of
Home Assistant's default config.

Some rows say **no cause recorded**. That is deliberate: a press on a wall
switch and a push from a device's own integration arrive identically, so
naming either would be a guess, and a timeline that guesses is not evidence.

brAIn's own actions are the one thing it does not have to read out of the
logbook. It calls Home Assistant with the Supervisor's token like every other
add-on, so its changes are indistinguishable there from any integration's —
it writes down what it did instead, in \`/config/.brain/actions.jsonl\`, and
matches that against the logbook.

Claude can read all of this too: ask **"why did the hall light come on"** in
the chat or the ask bar and it looks up the cause rather than reasoning from
a state.
`,
  },
  {
    id: "it-says-when-it-is-not-working",
    icon: "❤️",
    title: "It says when it is not working",
    body: `
# It says when it is not working

\`sensor.brain_usage_limits_health\` is \`ok\`, \`degraded\` or \`failed\`, with the reason and
what to do about it in its attributes. It never goes unavailable — Home
Assistant hides the attributes of an unavailable entity, and this is the
entity you look at when the others have gone — and a verdict that has gone
stale reports **that** rather than serving you its last good answer.

It is a state and a sentence, never a score: one number over a house hides
its worst problem inside an average. A face you have switched off is never
counted as a fault. The same verdict appears at the top of **Diagnostics**
under ⚙ and in \`brain doctor\`.
`,
  },
  {
    id: "everything-it-does-can-be-undone",
    icon: "🔙",
    title: "Everything it does can be undone",
    body: `
# Everything it does can be undone

Before Claude writes to any file under \`/config\`, brAIn snapshots the previous
contents. \`brain undo\` lists what changed and puts any of it back — one edit, or
everything from today. \`secrets.yaml\` is never snapshotted.

That covers Claude's edits. For the house as a whole, use Home Assistant's own
backups: they're whole-system and restorable, and brAIn deliberately does not
duplicate them (see What it will not do).
`,
  },
  {
    id: "setup",
    icon: "🚀",
    title: "Setup",
    body: `
# Setup

1. **Install and start the add-on.**
2. **Open the panel** from the sidebar and connect your Claude account. Easiest route:
   open the **Terminal** tab, run \`claude\`, and sign in there — the rest of brAIn
   picks that login up. The panel also offers a guided sign-in and a paste-a-token
   box. This is the **only** login; terminal, insights, voice, findings and memory all
   share it.

   Afterwards, everything about that login lives in **⚙ Settings → Claude account**:
   which credential is in use and where it came from, whether Claude still accepts
   it, **Sign in again**, **Sign out**, and whether to share it with the other BRUH
   add-ons. Come back here when the top bar says **Claude auth failed** — pressing
   that chip goes straight to the sign-in screen.
3. **Accept the integration.** Home Assistant offers to set up **brAIn** via
   discovery. That's what provides the services, the sensors and the voice assistant.
4. **Say where brAIn may speak.** The first screen asks for a notify service and,
   optionally, quiet hours. It is asked first because the morning brief is the one
   thing that reaches you where you already are, it is off by default, and it is
   gated on a service existing — so on a fresh install the most useful thing the
   add-on does was switched off behind two options nobody had been told about. A
   home with no notify service is told so; nothing is invented.
5. **Press Start learning.** brAIn studies your home for a few minutes in the
   background, then proposes the cards this particular house should have. You pick
   which to keep. Two things happen alongside it: **one card starts generating
   immediately** — an overview, from the cheap orientation map — because an empty
   Insights tab for the twenty minutes the syllabus takes is indistinguishable
   from a broken one; and the five opening study sessions run a **lighter**
   syllabus than \`brain learn\` does, because somebody is watching a progress bar.
6. **Pick your cards.** A fresh install now creates **only** what you ticked. The
   nine shipped categories are offered as suggestions like everything else, and
   the ones you did not accept are not created — including when you accept none,
   which is an answer and gives you the empty dashboard you asked for. (An install
   that onboarded before 1.48.0 is untouched: it keeps every card it has.)

A **Claude Pro or Max subscription** is the cheapest way to run brAIn — it uses the
plan you already pay for rather than API credits. An API key works too.

> **If your home is too sparse to learn from**, brAIn says what's missing rather than
> inventing generic cards. Add entities, let some history accumulate, run it again.

## Signing in, and sharing that login

A Claude credential can live in **four** places. Three are read by everything that
authenticates, in this order; the fourth is a safety net brAIn keeps for itself:

| Where | Written by | Notes |
| --- | --- | --- |
| Claude Code's own store | \`claude\` / \`claude /login\` in the Terminal tab | The only one that records an expiry — and a **session** token, which the CLI refreshes for itself |
| The panel's store | the ✨ Connect screen, ⚙ Settings → Claude account | Lives in the add-on's own storage |
| The shared file | **Share it**, or \`ha login --share\` | On \`/config\`, so it is the one other BRUH add-ons can read |
| The backup copy | the add-on, at every start | The last known-good copy of Claude Code's own store, put back if that file goes missing. **Sign out clears this one too** — otherwise signing out and restarting, which is the first thing anybody locked out tries, would put the old credential straight back. |

Sharing is **off unless you turn it on**. \`/config\` is included in Home Assistant
backups, and those are not encrypted unless you turned that on — so a shared login
travels with your backups. Claude Code's own session token is deliberately **not**
shareable: the shared file records no refresh token, so a copy would work for a few
hours and then break every add-on reading it with nothing to say why. Sign in from
the panel (or run \`ha login\`) to mint a long-lived token that can be shared.

A long-lived token has one thing it cannot do: **read your account's usage limits.**
The permission for that is only asked for by the interactive sign-in, so a box whose
only credential came from \`ha login\` or the panel will show the usage pill as an
estimate and report \`oauth_token_lacks_usage_scope\`. That is not a broken sign-in and
running \`ha login\` again cannot change it — run \`claude /login\` in the **Terminal**
tab as well, which does not replace the shared file.

From a terminal, \`ha login\` and \`brain login\` are the same command:

\`\`\`bash
ha login              # sign in — needs a real terminal (it is an OAuth round trip)
ha login --status     # all three stores, and which one is in use
ha login --share      # publish a login you already have
ha login --token …    # paste a token minted elsewhere
ha login --revoke     # withdraw the shared copy
\`\`\`

The interactive flow needs a terminal, so run it in the panel's **Terminal** tab —
not the separate **Terminal & SSH** add-on, which is a different container whose \`ha\`
is the Supervisor CLI, an unrelated tool. Without a terminal at all, use \`--share\`,
\`--token\`, or the panel.
`,
  },
  {
    id: "what-to-expect",
    icon: "🗓️",
    title: "What to expect",
    body: `
# What to expect

Most of what brAIn eventually tells you is **measured**, and a measurement has a
floor under it: a confident answer over data that holds none is worse than no
answer at all. So a fresh install is quiet, deliberately, and the silence is the
one thing that looks exactly like being broken. This is the table that says which
is which.

Every number below is the floor that is actually in the code — \`MIN_DAYS\`,
\`MIN_SAMPLES\`, \`MIN_BUCKETS\`, \`HISTORY_DAYS\` — not a guess. The **Knowledge** tab
shows the same thing live, per measurement, with a date when it can estimate one.

The four measurement stores (baselines, thermal, closures, appliances) are all
built by one pass that runs about five minutes after the add-on starts and then
once a day. What takes weeks is not the pass; it is the **history** each floor
needs, which is why the column below is about days of your house and not about
brAIn's schedule.

| Feature | Default | What it needs | When it first says something |
| --- | --- | --- | --- |
| **House checks** | on | nothing | Two minutes after the add-on starts, then every \`checks_interval_hours\` (6). They read Home Assistant directly and cost no Claude run. |
| **Findings from analysis** | on | a Claude sign-in | With the first card run. |
| **Battery and decline forecasts** | on | ~10 daily statistics rows per sensor (\`BATTERY_MIN_POINTS\`) | About **10 days**, and only for a battery whose runway is under 21 days. |
| **Baselines** — what is normal here | on | long-term statistics; 28 days is the window it reads | The first pass runs about five minutes after the add-on starts and then daily, so there is a **whole-history** answer as soon as there is any history to read. The **per-hour-of-the-week** answer needs 3 samples in one bucket (\`MIN_SAMPLES\`) and a bucket fills once a week — so about **3 weeks**. The two are different answers and every reading says which it came from. |
| **Thermal model** — how a room holds heat | on | an outdoor temperature sensor, indoor sensors in areas, and cold nights | About **4 weeks** (\`HISTORY_DAYS = 28\`). With no outdoor sensor it says so and stops, rather than waiting forever. |
| **Rhythm** — when the house gets up | on | person-caused changes in the logbook | 10 separate days (\`MIN_DAYS\`). Weekdays arrive five times in seven, so about **2 weeks**; weekends accrue twice a week, so about **5 weeks**. |
| **Closures** — what is normally open | on | doors, windows, locks or covers | 24 watched hours of the week on one entity (\`MIN_BUCKETS\`), read from 28 days of history — so the first pass usually answers on a house that already has history, and a rarely-changing door takes longer. |
| **Habits and routines** | on | things you do by hand | 6 separate days (\`MIN_DAYS\`) plus a share of the days it could have happened on, which in practice is **2–3 weeks**. |
| **Appliance chores** | on | a power sensor on the machine | 10 days of its own 5-minute statistics (\`HISTORY_DAYS\`), and only for a washer, dryer or dishwasher matched by name. |
| **Energy — last week vs the week before** | on | Home Assistant's own Energy dashboard configured | 6 complete local days (\`MIN_DAYS\`); the comparison needs a second week behind it. |
| **Notifications about findings** | **off** | \`findings_notify_service\` | As soon as a service is set. Onboarding asks for one on its first screen. |
| **Morning brief** | **off** | a notify service **and** \`morning_brief\` | Within 45 minutes of the measured wake time, and only when there is something worth saying. Until rhythm has answered it uses \`morning_brief_hour\`. |
| **Weekly report** | **off** | a notify service **and** \`weekly_report\` | On \`weekly_report_day\`, once there is material. |
| **Overnight self-healing** | **off** | \`self_healing\`, plus quiet hours or a measured settle time | The first night after it is switched on. With neither a quiet window nor a rhythm it does **not** run, and says so in Diagnostics. |
| **Usage sensors** | on | \`claude /login\` in the **Terminal** tab | Within five minutes of that sign-in. A pasted token or \`ha login\` cannot read them — see below. |

Two of these are worth spelling out.

**The usage sensors need the interactive login specifically.** \`ha login\` and the
panel's paste box mint a long-lived token, which is the only kind that can be
shared with the other BRUH add-ons — and the permission to read your account's
usage windows is only ever asked for by \`claude /login\`. Without it the pill in the
top bar shows brAIn's own local estimate, prefixed \`~\`, and the tracker reports
\`oauth_token_lacks_usage_scope\`. That is not a broken sign-in and running \`ha login\`
again cannot change it.

**"Not started", "collecting" and "not available" are three different answers.**
A measurement this house cannot supply — no outdoor thermometer, no doors, no
energy dashboard — says **not available** with the reason, and no date, because a
date beside it would be a promise nothing is going to keep. One that has stopped
being rebuilt says **stale**, and that one is worth going and fixing.
`,
  },
  {
    id: "the-panel",
    icon: "🖥️",
    title: "The panel",
    body: `
# The panel

One ingress panel, seven tabs.

| Tab | What's there |
| --- | --- |
| **Insights** | Your cards, and the ask bar that makes new ones. A question becomes a card; a line starting "learn about…" starts a study session instead. A **Today** strip across the top says when the checks last ran, when the measurements were last rebuilt, when memory was last filed, and how many problems have been written up since yesterday. |
| **Findings** | What brAIn thinks is broken. Seven controls on each one — **Fix it**, **Discuss**, **Check again**, **I fixed it**, **Remind me later**, **Dismiss**, **Wrong**. A count on the tab means something is waiting on you. |
| **Proposals** | Changes brAIn would like to make: a habit worth automating, a condition an automation you keep undoing is missing, an emergency playbook, four scenes for a room. Nothing here has happened yet. |
| **Activity** | What changed in your house and what caused it — a person, an automation, a script, voice, brAIn itself — plus the overrides that are evidence rather than history. Fetched fresh every visit and never cached. |
| **Terminal** | Full Claude Code, served through the panel — no second sidebar entry, no second login. Two faces: **Chat** (the default: the same session rendered as messages) and **Classic** (ttyd + tmux). Switch with the button on the tab, or in ⚙ Settings. Press ⤢ to give either the whole screen. |
| **Knowledge** | What brAIn knows: this morning's brief, the seven measurements and how far along each is, the memory document, and the queue waiting to be filed into it. |
| **Docs** | This guide, in the panel. |

\`enable_terminal\` switches the Terminal tab off. \`enable_insights\` switches off
everything that only a scheduled Claude run ever fills: the scheduler stops, and
the **Insights** and **Proposals** tabs go from the strip. **Findings stays**,
because the house checks cost nothing to run and still file there. The panel
itself always runs, because it is the ingress target.

## What's on a card

One control sits on the card and the rest are behind **⋯**, because on a phone six
icon buttons in the card's head are what squeezes the title out.

- **⤢ Expand** — the only one on the card itself, because it is the only one that
  acts on what is on screen rather than on the card's definition.
- **⋯ → Regenerate** — run this card again now.
- **⋯ → Edit** — name, icon, prompt and schedule. Fixed daily times ("07:00, 19:00")
  use far fewer tokens than a short interval.
- **⋯ → Give feedback** — tell Claude what to do differently next time ("ignore the
  guest room sensor", "show costs in dollars"). It sticks, for every future run.
- **⋯ → Add to dashboard** — YAML for a Webpage card, so an insight lives on your own
  Home Assistant dashboard.
- **⋯ → Delete** — the card and its history.

There is no "refresh everything" button. It used to sit in the top bar, where it was
a circular arrow that read like a page reload and in fact queued a Claude run for
every card you had — minutes of work and a real bite out of the usage the pill beside
it was reporting.

## When a card actually re-runs

A card has an interval, and past 1.48.0 clearing that interval is only half of what
lets it spend a run. The other half is that **something it reads has moved**: a new
or ended finding in its domains, an edit to \`memory.md\`, a measurement rebuilt
overnight, feedback you added, a rewritten focus. A card whose inputs are identical
would produce the same card at full price, and a dashboard that changes nothing on a
timer teaches people it is a timer.

Every card records **why it was made** — "on its refresh interval", "a finding it
reads changed", "first run since inputs were tracked" — and a card that skipped a run
records the hold instead, so a quiet dashboard can say which of the two it is.

**When to refresh a card** in ⚙ Settings (\`refresh_mode\`) picks the rule. It is
brAIn's own setting and is not on the Configuration tab:

| Mode | What has to be true |
| --- | --- |
| \`changed\` | The interval has passed **and** something the card reads has moved. The default. |
| \`always\` | The interval alone, which is what every release before 1.48.0 did. |
| \`never\` | Nothing is scheduled at all. **Generate** and **Regenerate** still work, because pressing a button is an explicit ask. |

If the inputs cannot be read for some reason, the card refreshes anyway: "I could not
tell" must not become a card that never updates again.

## Seeing the whole prompt, and changing your half of it

A card's **Edit** dialog has an **Analysis focus** box, and that box is one
paragraph of what Claude is actually sent. The rest — the output contract and its
design system, your standing feedback, what brAIn has measured, what is already on
your work list, what this card said last time, the hypothesis budget, and the data
itself — is assembled at run time, and until now was shown nowhere. So a card that
kept coming back wrong could only be argued with by guessing.

**See the whole prompt** under the focus box opens exactly what would be sent if you
pressed **Save & regenerate** right now: every block named, with what it is for and how
big it is, the full text underneath, and what the run would cost. It is rebuilt each
time you open it rather than being a copy stored when the card was made — half those
blocks are live, so a stored copy would be showing you a house that has moved on.

Two of the blocks are yours and are marked as such: the **focus**, and the **feedback**
you leave with the 💬 button on a card. Those are the ones to edit. The rest is shown
so you can see what the card is reading, not as an invitation — freezing the assembled
text would mean the card stopped seeing new findings and went on citing a measurement
from March, with nothing on screen to say so.

In the default **search** mode the analyst also has read-only Home Assistant tools and
fetches what your focus actually asks for, so a focus about something outside this
card's usual data does work.

## A card that keeps up: \`live\`

A card is one Claude run rendered to a document, written once — right for "last week's
energy", wrong for the ones people pin to a dashboard: a door that is open, a machine
that is running, a room being held at a temperature. Those read as current and are not.

A card may now declare the entities whose state its visualization wants kept up to
date. While the card is on screen brAIn refreshes those — and only those — every 15
seconds and hands them to the visualization, which updates in place. Nothing else
changes: the analysis, the numbers and the story are still from the run.

You do not configure this. Claude decides whether a card is about something happening
now and declares the entities itself; most cards declare none, which is the honest
answer for a card about a period that has already ended. If you want one to be live,
say so in the focus or in feedback ("keep the door states current").

The list is fixed when the card is written and capped at 12. A card cannot ask for an
entity its own run did not declare, which is what keeps a page of generated HTML from
being able to read the rest of your house.

**⚙ > Diagnostics** opens with **Anything wrong?** — one flat list of everything
brAIn can currently see that is not working, gathered from every surface it has: the
health verdict, runs that failed in the last day, house checks that could not run,
snapshot keys that could not be fetched, a measurement store that measured nothing,
the rehearsal and the deep check, notifications that would not deliver, the usage
tracker's own verdict, the producers you keep marking **Wrong**, and any daemon that
is down. On a healthy install it is one sentence saying so. A refusal doing its job —
an overnight repair that stood down on a protected entity, a producer that could not
read a file — is deliberately not in it, because a list that includes those is one
people learn to skim. The same list is the **first section of every report**, above
the log and the JSON.

The rest of it is the read-only half of the settings dialog: versions, whether
the Claude sign-in is holding, the last 24 hours of Claude runs counted by how they
ended with the failures behind those counts, and the last house-checks pass —
including **which checks could not run, and why**. That last line is the one worth
reading: a skipped check did not find nothing, it could not look, and it is also the
check that is not allowed to clear a row. **Copy for a bug report** puts the payload
on the clipboard (it falls back to putting the text on screen, selected, when an
ingress iframe is refused the clipboard). It is the same payload behind **Download
diagnostics** on the brAIn integration page, and the one \`brain report\` bundles.
Since 1.48.0 it also draws six things its payload had always carried and the
dialog had never rendered: when the house wakes and settles, how rooms hold heat,
doors and windows, machines, habits, and the background daemons. The **Knowledge**
tab is where those numbers belong; they are here because a bug report has to carry
them too — a rhythm that never gathered enough days and one that did were, on this
screen, the same silence.

**Measure the house now** is beside them. All of those stores are written by one
nightly pass, so a number that looks wrong could not be re-asked and a change to how
one is measured was invisible until the next night. The button starts a pass — it
reads a month of statistics, so it takes a few minutes and the panel tells you when
it lands — and it costs no Claude turns.

**⚙ > Problems** is the other half. Every incident brAIn has written up is listed
there with a checkbox; **Copy selected**, **Copy all** and **Write a report now**
put the text where you can paste it. See Reports.
`,
  },
  {
    id: "what-brain-is-measuring",
    icon: "📐",
    title: "What brAIn is measuring",
    body: `
# What brAIn is measuring

The **Knowledge** tab is what brAIn knows about your house, as opposed to what it
thinks is broken (Findings), what it would like to change (Proposals) or what
happened (Activity). Four sections, in this order.

**This morning.** The brief that went out, or one sentence saying why there wasn't
one. "The brief is switched off" and "there was nothing worth saying" are different
answers and only the first has something to do about it.

**What brAIn has measured.** Seven rows, always, in the same order — rhythm,
baselines, thermal, closures, appliances, habits, energy — whatever state each is
in. A store missing from the list would be a store nobody can ask about, and on the
day you install this six of the seven have not started. Nothing on this list costs a
Claude run: it is all built overnight from what Home Assistant already records.
Press a row to open the numbers behind it.

**What it remembers.** The memory document, editable in place.

**What is waiting to be filed.** The inbox queue: facts that have been learned and
not yet folded into the document. It drains itself; **File into memory now** runs
the same consolidator by hand.

There is no badge on this tab. Everything on it is a queue that files itself and
things you read — nothing is waiting on a person, and a badge counting work nobody
has to do is how the badge next to it stops being read.

## The five states a measurement can be in

Each of the seven rows carries one chip, and the five words mean different things:

| Chip | What it means |
| --- | --- |
| **not started** | No pass has run yet, or nothing has been filed. On a fresh install this is most of the list. |
| **N of M days · first answer ~date** | Collecting. The number is in that measurement's own unit — days, entities, rooms, hours of the week, machines — and the date is when the floor is met at the rate that unit accrues. |
| **updated *date*** | Ready. The row's sentence is the measurement's own answer about your house. |
| **stale since *date*** | It was ready and the nightly pass has stopped running. This is the one worth going and fixing. |
| **not available** | This house cannot supply it, with the reason underneath — no outdoor thermometer, no door or window, no energy dashboard configured. Never a date, because there is nothing to wait for. |

The first time a measurement becomes ready, brAIn writes **one card about it** —
what your house's wake time turned out to be, which room loses heat fastest — and
that card lives here, on the row it belongs to. It fires once. Milestone cards never
appear on the Insights tab, which holds only the cards you asked for.

Claude reads the same answers through the \`get_house_model\` tool, and the analyst,
the morning brief and the weekly report are all handed a short block of them (2 KB,
one line per ready measurement, in the measurement's own words) so a card does not
re-derive "what is normal here" from a week of readings on every run.
`,
  },
  {
    id: "checking-brain-itself",
    icon: "🩺",
    title: "Checking brAIn itself",
    body: `
# Checking brAIn itself

Three of these, and they cost three different amounts.

| | What it answers | What it spends |
| --- | --- | --- |
| \`brain doctor\` | Is the plumbing connected? | nothing |
| \`brain doctor --deep\` | Does each face work end to end, right now? | ~5 Claude turns |
| \`brain doctor --rehearse\` | Do the checks and the analyst find a defect planted in **this** house? | 1 analyst run |

\`brain doctor\` is unchanged and is still the one to run first. It reads what is
there — a token, an MCP handshake, the panel, the daemons, the three stores a
sign-in is read from — and calls Claude never. It also warns about anything a
\`--rehearse\` run left behind. \`--json\` gives the same report as one object,
which is what \`brain report\` bundles.

## \`brain doctor --deep\`

Eight stages, in order. Each is a real round trip with its own budget, and each
has a sentence that names the switch or the log to look at when it fails. Every
stage is reported, not just the first break — "the chat works and the automation
listener does not" is the answer. A stage whose precondition failed is *skipped
with the reason* rather than run, because eight identical authentication
failures is a report nobody reads past line one.

| Stage | What it does | What it proves |
| --- | --- | --- |
| Claude, no tools | Asks for a fixed JSON object and reads it back | The credential works for a plain run, and the JSON extractor can read a real reply — the step every insight card depends on |
| Analyst tools | Asks for the area count **and** attempts a \`call_service\` | MCP reaches the model, the allow list lets a read through, and the deny list blocks an acting tool. An acting call that **ran** is the loudest failure here |
| Chat session | Opens a session of its own, sends one message, closes it | The stream-json session spawns, speaks and ends a turn |
| Automation listener | Writes a task the way the integration does | The listener is alive, the claim-by-rename contract holds, and a result arrives inside the bridge's window |
| Assist | \`conversation/process\` with brAIn's own agent id | The worker pool answers through Home Assistant's front door, not just its health endpoint |
| Memory | Queues a fact, consolidates, then removes it again | A fact reaches \`memory.md\` and can be taken out |
| Findings and undo | Files a finding, ends it, undoes it, ends it again | The store, the settled ledger, the memory line and the undo token all round-trip |
| Fixer | One real fix run renaming a \`brain_test_\` helper | The one path that can change the house can, and it is verified in Core |

**It never runs on its own.** There is no option that schedules one and no timer
anywhere: it costs real Claude turns, so it happens when you ask.

**Everything it creates it removes, and it checks that it did.** The synthetic
fact is not in \`memory.md\` afterwards, the synthetic finding is in neither the
store nor the settled ledger, the helper is deleted. A leftover is reported as a
failure of the stage that left it.

**A skipped stage is not a failure.** Assist with the Assist integration
switched off, the automation task with the Automation integration off, and the
fixer with \`protected_entities\` covering the helper it would rename are all
**skipped**, and each says which switch. The chat stage skips rather than closing
somebody's conversation to make room for itself.

Run it from the terminal (\`brain doctor --deep\`, \`--json\` for the whole object,
non-zero exit on any failed stage), or from **⚙ Settings → Diagnostics → Run
deep check**, which fills the stage list in as it goes. The last run's verdict
rides in the diagnostics bundle, so a bug report carries it without anybody
having to ask.

## \`brain doctor --rehearse\`

The test suite checks every house check against fixture houses. What it cannot
see is **this** install's Home Assistant version, its integrations and its data
shapes — which is where every late bug has lived. A rehearsal plants a small set
of defects in your house, runs the checks and the analyst against them, scores
both, and removes everything.

**It asks first, and the question names exactly what it would create.** Nothing
is created before you answer. \`--yes\` skips the question for scripted use; the ⚙
button shows the same list in a confirm dialog.

Everything it plants is named \`brain_test_*\` and goes in through paths brAIn
already owns — automations through the same write-reload-verify path an accepted
proposal uses — so the rehearsal is also a real round trip of the writer.

What it reports:

- **Checks** — of the defects planted, how many the checks found, and whether
  anything **else** fired on a \`brain_test_\` row. A check firing on a healthy
  planted row is a false positive worth knowing about.
- **Analyst** — the automations card's own prompt, run against the same house,
  scored for precision and recall over the planted rows. That number — "on this
  house, this Home Assistant version, this model, the analyst found 3 of 4
  planted defects and reported 1 thing that was not there" — is the reason the
  rehearsal exists.
- **Not rehearsable** — the checks whose floor is measured in days
  (\`auto.forgotten_off\` needs 30 days off, \`dev.frozen\` needs a week of
  statistics) are named with the reason rather than counted as missed.
- **Cleanup** — what was removed, and loudly if anything could not be.

The removal runs in a \`finally\`, so a rehearsal that fails halfway still cleans
up. And **cleanup is the first thing the plain \`brain doctor\` verifies on its
next run**: it warns if any \`brain_test_*\` automation, entity or helper is still
there, and names the command that removes it.

The rehearsal never runs on its own either, and it refuses before asking for
consent if \`protected_entities\` would match a \`brain_test_*\` id.

## Reports

Everything above is something you have to go and run. Every failure this add-on
has shipped was a quiet one, and by the time anybody looked, the journal row that
would have explained it was one of two thousand and the log line had scrolled off.

So the moment something fails, brAIn writes the evidence down by itself — as **one
plain-text file** under \`/share/brain/reports/\`, which is where the File editor and
the Samba share can see it. Not a directory of five files, and not a tarball.

Three things write one:

- **A run that failed.** Every Claude run, checks pass, baseline build and overnight
  heal already passes through the run journal, so a single listener there covers all
  of them — a timeout, a crash, an unparseable answer, an authentication failure. A
  refusal doing its job is not a fault and writes nothing.
- **The health verdict leaving \`ok\`.** This is the one that catches a daemon that
  died and a credential that expired on a Tuesday afternoon.
- **A notification that could not be sent** — the one failure whose only symptom was
  silence on a phone.

The same problem inside 24 hours appends a \`seen again at HH:MM\` line to the file it
already has rather than making a new one, and the folder is capped at 30. Every file
is redacted as a whole before it is written: anything credential-shaped, and the
JSON fields that carry tokens. Prompts and replies are never in them in the first
place. Entity names **are** — a report about "a sensor" is not a report — and
\`brain report --no-names\` hashes them if that matters to you.

Read them in **⚙ → Problems**: a checkbox each, **Copy selected**, **Copy all**, and
**Write a report now** for the case where nothing failed but something is wrong.
\`brain report\` from a terminal writes the same single file and prints its path,
and it assembles it itself when the panel is down — which is exactly when a report
is most needed.

While the health verdict is not \`ok\`, Home Assistant's own **Settings → Repairs**
carries a **brAIn hit a problem** entry with the reason. It is not fixable from there
on purpose: the fix is in ⚙ → Problems, where the add-on has already written the
file about it. The entry deletes itself when the verdict goes back to \`ok\`.

These files are on \`/share\` rather than in \`/data\` precisely so you can reach them
without the panel — which also means they are **not** covered by the add-on's
\`backup_exclude\`. That is why the redaction runs over the whole file every time,
rather than over the sections that "could" hold a token.
`,
  },
  {
    id: "capture-corpus-and-replay",
    icon: "🔬",
    title: "Capture, corpus and replay",
    body: `
# Capture, corpus and replay

Everything above tests brAIn's **plumbing**. The one part no test can reach is the
**prompts** — the framing and the output contract behind every insight card —
because nothing in the project runs them against a real house or a real model.
A prompt edit ships on somebody's judgement.

This is the machinery that changes that, and every part of it is off, optional
or invisible until somebody chooses otherwise.

## Capture

**⚙ Settings → Diagnostics → Capture runs for the corpus.** Off by default.

With it on, every card run writes one file under \`/data/capture\`:

- the data brAIn gave Claude (the map for a search run, the slimmed home for a
  snapshot one),
- the card that came back — its findings, what it learned, the fields you read,
  never the rendered chart,
- what it cost,
- and later, **the ending you gave each finding it raised**.

That last part is the whole point. An ending on the Findings tab is already a
label: **I fixed it** and **Got it** say the report was right, **Wrong** says
it was not. Pairing that with the prompt that produced it turns a house into a
graded example, and a directory of graded examples is something a prompt change
can be scored against before it ships.

Four things about what it does and does not do:

- **Anything credential-shaped is stripped as the file is written**, not as it
  is exported — a redaction applied on the way out is one that never ran for the
  file somebody found by another route. It is the same scrub \`brain report\`
  applies to every file in a bundle.
- **Your entity and area names ARE in these files.** They are a floor plan.
  That is why the switch is off, why the list has a **View** button, and why
  step three below is **read one**.
- **Nothing leaves the add-on until you press Export.** \`/data\` is not visible
  from the file editor, from Samba or from Home Assistant, and \`backup_exclude\`
  names the folder so a backup does not carry it either.
- **The newest 50 runs are kept**, oldest deleted first.

The list under the switch gives you three buttons per run. **View** shows the
whole file exactly as it is on disk. **Export** copies that one file to
\`/share/brain/corpus/<run id>.json\`, where the file editor and Samba can reach
it. **Delete** removes it.

\`/api/diagnostics\` carries the numbers — whether capture is on, how many files,
how many have an ending on them — and never the captures themselves, because a
diagnostics bundle is what gets attached to a public issue.

## The corpus

\`tests/corpus/\` in the repository holds contributed houses with their labels.
Two ship with it, and neither is hand-written: the clean fixture house, whose
whole label is **every check must be silent here**, and that same house with the
rehearsal's own planted defects in it, whose labels are the rehearsal's plan.
Ground truth by construction in both cases.

Contributing one from your own house is four steps and the third is the
important one: switch capture on, use brAIn normally and answer its findings,
**read the file**, then export it and open a pull request adding it to
\`tests/corpus/entries/\`. \`tests/corpus/README.md\` is the whole procedure. It is
entirely optional, and it should be.

## Replay

\`python tests/corpus/replay.py\` scores this release's producers against the
corpus, in two halves.

The **free half** runs every house check against each entry and compares what it
found with what the entry says should be found. No model, no tokens, no network
— it runs in ordinary CI on every pull request, and it is what fails when
somebody changes a threshold: a check that gains a condition stops finding a
defect that was planted for it, and one that loses a condition starts firing on
a house that is meant to be quiet.

The **analyst half** rebuilds the prompt with the **current** builder and asks a
real model, then scores its findings against the endings people gave. It is
capped by \`--max-entries\`, \`--max-tokens\` and \`--model\`, runs nightly in CI when
a \`BRAIN_REPLAY_TOKEN\` secret is present (and does the free half and says so in
the log when it is not), and is never required for a pull request. A capture
from a **search** run is skipped there and says why: that run read the house with
Home Assistant tools, and replaying the prompt where those tools reach nothing
would grade a model that cannot look anything up.

## Shadow mode

A house check that is new goes into shadow first: it runs on every pass, files
to a store of its own, and reaches nothing you look at — not the Findings tab,
not the badge, not a notification, not the To-do list, not the analyst's own
prompt.

For as long as it is there, ⚙ → Diagnostics shows a line per trialled check:
*"\`dev.example\`: 14 rows over 9 days, 11 agree with what was filed"*. Agreement
means something else — the analyst, or another check — reported the same thing,
which is the only corroboration available for a row nobody can press Wrong on.

**Nothing is promoted automatically.** A check moves onto the visible list when
somebody reads those numbers, and the corpus numbers beside them, and decides it
has earned a place. A rule that promoted itself on a threshold would be a
threshold nobody can see deciding what your house is told about.

No check is in shadow in this release. Every one that ships has earned its
place, and the set is empty on purpose.
`,
  },
  {
    id: "the-cli",
    icon: "⌨️",
    title: "The CLI",
    body: `
# The CLI

Two dispatchers, split by what they act on. brAIn's own faculties are under \`brain\`;
anything that acts on Home Assistant is under \`ha\`.

\`\`\`bash
brain memory add "We call the office lamp the beacon"
brain memory list                  # what it knows
brain memory edit                  # open the document in $EDITOR
brain memory log                   # what it learned recently
brain memory hypotheses            # pending guesses awaiting a yes/no
brain memory export                # everything learned, as one portable file
brain memory import backup.json    # fold an export back in
brain findings                     # what it thinks is broken
brain findings fix 1786715730      # let Claude fix one
brain findings wrong 1786715730 "that sensor is meant to sit closed"
brain learn energy                 # study a topic
brain ask "why is the garage cold" # same engine as the Ask card
brain undo                         # review and revert Claude's edits
brain check                        # run the house checks now (no Claude run)
brain doctor                       # end-to-end diagnostic
brain doctor --json                # the same verdict as one JSON object
brain doctor --deep                # every face, one real round trip each (~5 turns)
brain doctor --rehearse            # plant defects here, score the checks, clean up
brain weekly [send]                # the week's report: what it holds, or send one
brain report                       # redacted diagnostics bundle for a bug report

ha log                             # tail the Home Assistant log
ha reload automations
ha check configuration.yaml
ha context                         # regenerate /config/CLAUDE.md
ha entity list light
ha service call light.turn_on
ha addon list
ha notify "dishwasher finished"
\`\`\`

Run \`brain help\` or \`ha help\` for the full list.

> If some other \`ha\` command is ever present on \`PATH\` inside the container, brAIn
> installs its own as \`hass\` instead rather than shadowing it. The startup log says so
> when this happens.
`,
  },
  {
    id: "configuration-options",
    icon: "⚙️",
    title: "Configuration options",
    body: `
# Configuration options

**Six of these are also editable from the panel's ⚙ Settings dialog**, which writes
them back through the Supervisor so both screens always show the same value:
\`auto_refresh_hours\`, \`history_days\`, \`history_keep_runs\`, \`history_keep_days\`,
\`model\` and \`generation_timeout_minutes\`. Everything else on this page is the
Configuration tab's alone.

⚙ Settings also holds things that are **not** add-on options at all, because they
are changed while looking at the panel rather than at a restart: the master pause,
your plan and usage budget, the Chat/Classic face, the chat's own model and how many
chats may run at once, \`gather_mode\`, \`refresh_mode\`, and the capture switch.

Onboarding's first screen asks for a notify service and quiet hours, which **are**
add-on options — and the panel cannot write those four
(\`findings_notify_service\`, \`notify_quiet_start\`, \`notify_quiet_end\`,
\`morning_brief\`). It stores your answer in its own settings instead and every
reader consults that as a **fallback under** the Supervisor's value, so the choice
takes effect immediately and **an entry on the Configuration tab always wins**.
The step tells you exactly what to paste there if you would rather keep it with
the rest of your options.

## Faces

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| \`enable_terminal\` | bool | \`true\` | Run the ttyd terminal and expose the Terminal tab. Turn off for a dashboard-only install with no shell. |
| \`enable_insights\` | bool | \`true\` | Run the card scheduler and show the **Insights** and **Proposals** tabs. Off stops every scheduled Claude run; **Findings stays**, because the house checks cost nothing and still file there. |

## Terminal

The **Chat / Classic** choice is not here — it lives in the panel's ⚙ Settings (and on
the Terminal tab itself), because it changes nothing about how the add-on runs.

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| \`auto_launch_claude\` | bool | \`true\` | Start Claude Code automatically when the terminal opens. |
| \`auto_generate_context\` | bool | \`true\` | Regenerate \`/config/CLAUDE.md\` with your HA system context at startup. |
| \`enable_ha_mcp_server\` | bool | \`true\` | Give Claude native HA access (states, services, history, statistics, registries, dashboards, logs, templates). |
| \`enable_mobile_ui\` | bool | \`true\` | Splice the mobile toolbar and iOS dictation fix into ttyd's UI. |
| \`dangerously_skip_permissions\` | bool | \`false\` | Skip Claude Code's tool-permission prompts in the interactive terminal. Background listeners never use this. |

## Voice and automation

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| \`enable_assist_integration\` | bool | \`true\` | Register brAIn as a conversation agent for Assist. |
| \`enable_automation_integration\` | bool | \`true\` | Watch for task requests from automations. |
| \`assist_fast_mode\` | bool | \`true\` | Serve voice from a pool of pre-warmed persistent workers instead of spawning a CLI per request. |
| \`assist_tool_access\` | \`mcp_only\` \\| \`full\` | \`mcp_only\` | Whether voice can only touch HA, or also run Bash and edit files. |

## Memory and learning

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| \`learning\` | bool | \`true\` | Master switch for everything brAIn learns: the consolidator, the end-of-conversation reflection pass, and study sessions. Turning it off leaves existing memory untouched. |
| \`memory_injection\` | bool | \`true\` | Splice learned memory into voice prompts. |
| \`memory_max_kb\` | 1–64 | \`32\` | Size cap for the memory document. A pass that cannot fit under it files nothing, so this is the setting to raise when the log says the document is full. |
| \`study_timeout_minutes\` | 2–120 | \`30\` | Wall-clock limit for a study session. |
| \`findings_notify_service\` | string | **(empty)** | A \`notify.*\` service (with or without the prefix) that gets a push when brAIn files a new finding. Empty means no notifications — the Findings tab, the sensor and the \`brain_finding\` event work either way. |
| \`findings_notify_min_severity\` | \`info\` \\| \`warning\` \\| \`serious\` \\| \`critical\` | \`serious\` | Only findings at or above this severity are pushed. The default means dying batteries and silent sensors ring your phone while naming nitpicks wait on the tab. |
| \`notify_quiet_start\` | string | \`22\` | The hour (0–23, your home's timezone) from which only urgent findings ring your phone. Everything else is held and delivered as one message when the quiet ends. |
| \`notify_quiet_end\` | string | \`7\` | The hour held findings are delivered. A window that crosses midnight (22 to 7) is the normal case. Set both the same, or both empty, for no quiet hours. |
| \`morning_brief\` | bool | \`false\` | One short message a day, at the hour your home actually starts moving, and only when there is something to say. Each one sent costs a Claude turn; a quiet morning costs nothing. Needs \`findings_notify_service\` set. |
| \`morning_brief_hour\` | string | \`7\` | When to send it until brAIn has measured your home's own hour (10 weekdays, so about two weeks), or if your days are too irregular for there to be one. |
| \`weekly_report\` | bool | \`false\` | One message a week: what the house used against the week before, what was found and answered, what brAIn learned, and the one thing worth doing. Needs \`findings_notify_service\` set — point it at \`notify.notify\` and it reaches everybody. |
| \`weekly_report_day\` | list | \`sunday\` | Which day it goes out. The hour is \`morning_brief_hour\`, or your home's own measured hour once brAIn knows it. |

> **There are no turn-limit options any more.** \`assist_max_turns\`,
> \`automation_max_turns\` and \`study_max_turns\` were retired in 1.48.0. A turn
> cap is a runaway guard, not a budget, and it was the wrong thing to put in
> front of somebody: set it low and a run stops mid-thought and produces
> nothing parseable, having paid for every token it spent; set it high and it
> never fires. The guards are still there — large, and invisible: 40 turns for
> voice, 200 for an automation task, 40 for a card, 60 for a fix, 24 for the
> brief, the weekly report and a one-off intent, and **none at all** for a
> study session, \`brain ask\` or the chat. And a run that trips one is now
> **landed** rather than truncated: it is resumed with two more turns and told
> to finish with what it has, in the format the task asked for, so a partial
> answer files instead of a thorough one that never did.
>
> What is left to reason about is the **wall clock**, which is the guard that
> actually bounds what a run costs: \`study_timeout_minutes\` for a study
> session and \`generation_timeout_minutes\` for a card.

## Insights

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| \`auto_refresh_hours\` | 0–168 | \`24\` | How often recurring cards regenerate. \`0\` disables. |
| \`history_days\` | 1–30 | \`7\` | How much history each analysis reads. |
| \`history_keep_runs\` | 0–200 | \`40\` | Past runs kept per card. |
| \`history_keep_days\` | 0–365 | \`30\` | Age limit on past runs. |
| \`model\` | string | \`""\` | Override the Claude model. Empty uses the default. |
| \`generation_timeout_minutes\` | 2–30 | \`8\` | Per-generation timeout. |

## House checks and policy

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| \`checks_interval_hours\` | 0–168 | \`6\` | How often the deterministic house checks run. They read Home Assistant and the Supervisor directly and never call Claude, so they cost nothing. \`0\` means never on a timer; \`brain check\` and the tab's button still run them. |
| \`self_healing\` | bool | \`false\` | Let brAIn make up to three repairs a night, inside your quiet hours: start an add-on that was set to run at boot, ping a dead Z-Wave node, reload an integration that failed to set up. Nothing else, never on a protected entity, and never on a finding you have already answered. See **The house acts**. |
| \`protected_entities\` | list | \`[]\` | Entity ids (\`lock.front_door\`) or whole domains (\`alarm_control_panel.*\`) that brAIn may never act on. Enforced at the one place every Home Assistant tool call passes through, so it covers voice, automations, insight runs, the fixer, the overnight healer and anything the panel writes into \`automations.yaml\`; a call aimed at an area or device containing one is refused too, and so is a label or floor target, which cannot be resolved there. A shell command or a file edit does not go through that chokepoint — the terminal, the chat and Fix it are **told** the list instead. Protected entities can always be looked at. |

## Undo and access

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| \`edit_journal_days\` | 0–365 | \`14\` | How long to keep snapshots of files Claude edited. **\`0\` really disables it** — nothing is snapshotted and nothing is indexed, so \`brain undo\` has nothing to restore. (Through 1.47.0 it only disabled the **prune**, which made the one setting that said off the one that made the journal unbounded.) |
| \`access_share\` | bool | \`true\` | Mount \`/share\`. |
| \`access_media\` | bool | \`true\` | Mount \`/media\`. |
| \`access_backup\` | bool | \`true\` | Mount \`/backup\` read-only. |
| \`access_addon_configs\` | bool | \`true\` | Mount other add-ons' config directories. |
| \`access_addons\` | bool | \`true\` | Mount add-on source directories. |
| \`additional_directories\` | list | \`[]\` | Extra paths to expose. |
| \`persistent_apk_packages\` | list | \`[]\` | Alpine packages reinstalled on every start. |
| \`persistent_pip_packages\` | list | \`[]\` | Python packages reinstalled on every start. |
| \`log_level\` | enum | \`info\` | Add-on log verbosity. At \`debug\` the panel logs every HTTP request (polls included) and ttyd its own connection chatter; below that a successful poll is silent and only failures are logged. |
`,
  },
  {
    id: "what-it-costs",
    icon: "💰",
    title: "What it costs",
    body: `
# What it costs

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
`,
  },
  {
    id: "what-it-will-not-do",
    icon: "🚫",
    title: "What it will not do",
    body: `
# What it will not do

An honest list, because a tool that can edit your house should be clear about its
edges.

- **It does not back up your configuration.** Home Assistant's own backups are
  whole-system and restorable; duplicating them inside \`/config\` only made the backups
  bigger. brAIn keeps an edit journal of its own changes instead.
- **It never touches an existing \`/config/.git\`.** If you version your config
  yourself, that's yours.
- **Nothing that runs on a schedule can act on your house.** Scheduled work — cards,
  the morning brief, the weekly report, study sessions, a one-off intent — runs with
  Home Assistant tools that **read only**: states, history, statistics, the logbook,
  the registries, brAIn's own measurements. The list is asserted from both ends, an
  allow list and a deny list, because an unlisted tool would **fail** rather than be
  **forbidden**, and those are not the same guarantee with a real house behind them.
  Two things can act, and both need a press: the Findings **Fix it** button, and
  accepting a proposal. Overnight self-healing is the third and is off by default,
  runs no Claude at all, and does exactly three things.
- **It does not restart Home Assistant by itself**, and a fix never deletes anything
  it didn't create.
- **Overnight self-healing does exactly three things and no more.** No
  power-cycling a device through its plug, no restarting Home Assistant, no
  restarting itself, and no Claude run on that path at all. It is off by
  default, capped at three repairs a night, and never touches a protected entity
  or a finding you have answered.
- **No emergency playbook unlocks a door or disarms an alarm**, whatever the
  emergency. And brAIn never runs a playbook itself — it writes one, you accept
  it, and Home Assistant runs it.
- **Voice is limited to Home Assistant by default.** Widening it to Bash and file
  editing is a setting you turn on deliberately.
- **The registry services are admin-gated**, and destructive sweeps (orphan cleanup)
  are dry-run by default.
- **It is not affiliated with Anthropic or the Open Home Foundation.** It runs the
  official Claude Code CLI under your own account.
`,
  },
  {
    id: "ports",
    icon: "🔌",
    title: "Ports",
    body: `
# Ports

| Port | What | Needed? |
| --- | --- | --- |
| 8099 | The ingress panel. Also reverse-proxies \`/terminal/\`. | Internal; ingress handles it. |
| 7681 | ttyd, direct access. | **Off by default.** Optional, for a kiosk or a bookmarked full-screen terminal. |
| 8098 | The assist worker pool's internal API. | Internal only. |

## About port 7681

Before 1.19.0 this port was published on every install and ttyd ran without
a password, so anyone on your network could open a root shell with \`/config\`
read-write and your signed-in Claude. It is unpublished now, and the
terminal you use in the panel does not need it — the panel proxies ttyd over
loopback, which is what makes Terminal a tab.

If you do want the direct port (a wall tablet, a bookmark), assign it under
the add-on's **Network** settings. It asks for a password either way:

- Username \`brain\`; the password is generated on first start.
- It is printed in the add-on log, and stored at \`/data/terminal-credential\`.
- To rotate it, delete that file and restart the add-on.

Please don't forward this port through your router. It is a shell.
`,
  },
  {
    id: "security",
    icon: "🔒",
    title: "Security",
    body: `
# Security

brAIn runs with real authority over your Home Assistant: \`/config\`
read-write, admin access to the Home Assistant API, and — depending on the
options you enable — \`/share\`, \`/media\` and other add-ons' configuration.
That is the point of it, and it is worth knowing where the edges are.

- **Home Assistant's login is the boundary.** Everything brAIn exposes sits
  behind ingress, which means behind your Home Assistant account. Nothing
  should be reachable without it; if you find something that is, that is a
  vulnerability and [SECURITY.md](https://github.com/bruhautomation/BRUH-HA-Apps/blob/main/SECURITY.md)
  is how to report it privately.
- **AppArmor is on.** The profile denies the container the things a host
  escape needs — mounting, kernel modules, raw sockets, kernel tunables, the
  Docker socket. It deliberately does not restrict what brAIn does **inside**
  the container, because an agent that can only run a fixed list of commands
  is an agent that breaks the first time you ask it something new.
- **Your Claude credential stays out of your backups.** Home Assistant
  backups are unencrypted unless you opt in, and they travel. Restoring a
  backup costs you one sign-in.
- **Claude Code runs as an unprivileged user** (UID 1000), not root.
- **\`protected_entities\` is the line brAIn may not cross, and it is worth
  knowing exactly how far the enforcement reaches.** Put the front door lock,
  the alarm and the garage door on it and **every route through the Home
  Assistant tools refuses** — voice, automations, insight runs, the chat and
  the terminal when they use those tools, the fixer, the overnight healer and
  anything the panel writes into \`automations.yaml\` or \`scenes.yaml\`. It is
  enforced at the one place those calls pass through, not in a prompt: the
  refusal covers the entity, its device and its area, and a label or floor
  target is refused outright because it cannot be resolved there. While the
  list is non-empty, \`fire_event\` is refused wholesale (an event reaches the
  house through whatever automations listen for it, and which ones do cannot
  be checked from there), and so is a \`homeassistant.turn_on\`/\`turn_off\`/
  \`toggle\` that names no target at all, which addresses every entity there is.
  **What it cannot gate is a shell.** The terminal, the chat and **Fix it**
  hold Bash and file editing, and a shell command or a file edit does not go
  through that chokepoint. Those three are **told** the list instead — it is in
  the fixer's own instructions and in the generated \`/config/CLAUDE.md\`, which
  is rewritten after every consolidation pass — and the rule there is Claude
  keeping it rather than a gate enforcing it. If that distinction matters to
  you, leave \`dangerously_skip_permissions\` off, which is the default.
- **\`dangerously_skip_permissions\` does what it says.** Off by default. On,
  Claude stops asking before it edits a file or runs a command in the
  interactive terminal.
- **The panel's rating is 6/6** in the add-on store — the highest the
  Supervisor gives, and it is worth knowing that \`hassio_role: admin\` costs
  two points that ingress and AppArmor pay back. brAIn needs that role
  because \`ha addon\` manages your other add-ons.
`,
  },
  {
    id: "where-things-live",
    icon: "📁",
    title: "Where things live",
    body: `
# Where things live

| Path | What |
| --- | --- |
| \`/config/.brain/memory/memory.md\` | The memory document. Yours to edit. |
| \`/config/.brain/memory/voice.md\` | A ≤2 KB distillate spliced into voice prompts. Derived; don't edit. |
| \`/config/.brain/memory/inbox/\` | Candidate facts awaiting consolidation. |
| \`/config/.brain/findings/inbox/\` | Problems study sessions found, awaiting filing. |
| \`/config/CLAUDE.md\` | The generated description of your installation. |
| \`/data/chat/<session id>.json\` | One chat conversation's scrollback each. Losing one costs a scrollback, never context — Claude Code keeps the conversation itself. (\`/data/chat_transcript.json\` is the single file this used to be, read once on upgrade.) |
| \`/config/custom_components/brain/\` | The Home Assistant integration, deployed at startup. |
| \`/data/findings.json\` | The findings list and its history. |
| \`/data/.brain/edits/\` | The edit journal \`brain undo\` restores from. |
`,
  },
  {
    id: "credits",
    icon: "🙏",
    title: "Credits",
    body: `
# Credits

The web terminal at the heart of this add-on began as
[Claude Terminal](https://github.com/heytcass/home-assistant-addons) by Tom
Cassady — that add-on is what showed Claude Code could live inside Home
Assistant behind ingress at all. BRUH Terminal was built on it, and brAIn is
what BRUH Terminal grew into.

BRUH Power Tools is adapted from [Spook](https://github.com/frenck/spook) by
Franck Nijhof (MIT).
`,
  },
  {
    id: "license",
    icon: "📜",
    title: "License",
    body: `
# License

MIT.
`,
  },
];
