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

It reaches Home Assistant three ways at once — a **native MCP server** (39 tools) for
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

### It checks the house without spending a token

Not every problem needs a model to find. brAIn runs a set of **house
checks** on a schedule (every `checks_interval_hours`, six by default) and on
**Run checks now** on the Findings tab: they read Home Assistant directly —
the registries, the states, your `automations.yaml`, the traces Home
Assistant keeps, a week of statistics, the dashboards, and the Supervisor's
own view of backups, add-ons and the disk — and file what they find as
ordinary findings under a "check" label, with no Claude run at all.

- **Automations** naming an entity that no longer exists, or calling a service
  that is not registered (the old phone's `notify.mobile_app_*`, with the
  replacement named); whose last run failed; that trigger but never get past
  their condition; that keep being skipped on `mode: single`; that have never
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
  own `last_seen`, because a sleepy sensor is "available" between check-ins
  and availability alone says nothing about it.
- **The registry**: entities still named after their hardware (a name like
  `0x00158d0001abcdef Temperature` is unfindable in a picker and unsayable
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
  day, *measured against how often that rule actually ran* (three undos of
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
attributes) and fires a **`brain_finding` event** for each new one, so an
automation can react the moment brAIn files something. And if you set
`findings_notify_service` in the add-on configuration to one of your
`notify.*` services, new findings at or above `findings_notify_min_severity`
(default `serious`) are pushed straight to it — a dead battery rings your
phone; a naming nitpick waits on the tab. The whole tab is also scriptable as
`brain findings` (list / fix / done / wrong / ack / snooze) from the terminal.

Between `notify_quiet_start` and `notify_quiet_end` (22 to 7 by default, in
your home's own timezone) only the **urgent** ones get through: a device that
has gone offline, an add-on that has stopped, a disk about to fill, a reading
that is impossible. Everything else is **held**, not dropped, and arrives as a
single message when the quiet ends. Urgency is not severity — a `critical`
battery forecast is three weeks away and a `warning` about a boiler that has
stopped answering is now — so it is a property of the check that raised the
row, not of the row's wording. Anything you fixed or dismissed overnight is
dropped from the queue rather than announced: being told at seven about a
problem that went away at four is how these messages stop meaning anything.
Set both to the same value (or leave both empty) to notify at any hour.

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

And everything it has learned is **portable**: `brain memory export` writes one
JSON file carrying the memory document, the findings list, the settled answers
and the facts ledger (the Memory tab's ⬇ Export does the same), and
`brain memory import` folds one back in on another install — ledgers merge with
the local entries winning, and the document itself is only replaced when the
local one is empty or you say `--replace-memory`. Migrating to new hardware no
longer means starting the learning over.

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
  **Chats** by default — everything you started yourself, in the chat or the
  classic terminal, including a finding you opened for discussion — and puts the
  rest behind a chip each, alphabetically:
  *Automation*, *Cards*, *Fixes*, *Memory*, *Study*, *Voice* — with a count, and
  only for the ones your house actually uses. Each row's time is when something
  last *happened in* the conversation — opening one just to look at it doesn't
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
- Findings surface as `sensor.brain_open_findings` and a `brain_finding` event per
  new one — and `findings_notify_service` pushes them to a phone with no automation
  at all.
- The same findings are `todo.brain` in Home Assistant's own **To-do** panel and
  mobile app: one list, two views. Ticking one off is "I've fixed it" and deleting
  one is "not a problem here" — the Findings tab's own two endings, so answering
  from your phone teaches brAIn exactly what pressing the button would have.
- `sensor.brain_health` says whether brAIn itself is working, so an automation can
  tell you the add-on is in trouble rather than you noticing the insights stopped.

### It knows what "unusual" means here

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
  *baseline* has stopped describing your house — a heating season starting,
  a meter replaced — and reporting them all would be reporting the
  measurement rather than the home.

- **It won't report a meter for going up.** A `total_increasing` energy
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

Claude can read it too: ask *"is the utility room damp?"* and it looks up
what damp normally is in your utility room rather than picking a number.

### It knows what is normally open

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
door open in. Not about a door that is *usually* open then. And not at all
when half the house is open at once, because that is you airing the place out
rather than a door left ajar.

Only closures are measured — a motion sensor being on at midnight is not
something anybody wants told about, and including it would bury the row that
matters.

### It knows when your house gets up

Everything scheduled used to happen at a time somebody typed into a box,
which is a timer, not a rhythm — 07:00 is early on a Sunday and late on a
Tuesday in the same home. So brAIn measures it instead: the first thing a
**person** does each day is the house waking up, and the last is it settling.
Not a motion sensor (which fires for a cat and for the heating) and not a
light (an automation does that at dawn) — somebody actually doing something.

It keeps two numbers a day and nothing else, and it will not answer until it
has a fortnight of them. Weekdays and weekends are measured apart, because one
number over both is wrong on all seven days rather than on none — which does
mean the weekend answer takes about five weeks to appear, since a weekend is
two days a week. And a home that stirs anywhere between 05:00 and 11:00 has no
usual time, so it says so rather than reporting the middle of that as one.

### A morning brief, when there is something to say

Turn on **Send a morning brief** and brAIn sends one short message a day to
your notify service, at the hour your home actually starts moving.

The part that matters is when it *doesn't*. The decision to send is made
before Claude is asked anything, out of things already counted: findings filed
since the last brief, brAIn itself not working, an odd night. A quiet morning
costs nothing and sends nothing — "all quiet" every day is the message people
mute, and each one that *is* sent costs a Claude turn, which is why this is
off by default.

What Claude is for is the sentence: under eighty words, one paragraph, no
greeting and no headings, because this is read on a lock screen. It can look
things up to make a reason specific ("the freezer is at -12, usually -18") but
it is not handed your house and it may not invent a number.

Until brAIn has watched for a couple of weeks it uses the fallback hour you
set. If it has been restarted and missed the window it waits for tomorrow
rather than delivering breakfast at lunchtime.

### One report a week

Turn on **Send a weekly report** and brAIn sends one message a week — by
default on a Sunday, at the same hour the brief would go. It is the report
meant for everybody in the house, so the notify service to point it at is
usually `notify.notify`.

It carries four things: what you used against the week before, what was found
and what was answered, what brAIn learned, and **one thing to do this week**.

That last one is chosen *before* Claude sees anything — the worst open
severity, then the one open longest. Asked to pick, a model picks the finding
it can write the best sentence about, which is the one carrying the most
detail rather than the most consequence.

It is not the morning brief with a longer timer. The brief asks *is there
anything*; the report asks *what happened*, and its failure is the opposite
one — a report that lists everything is the pile of unread cards it replaced.
So every section is gathered and capped before Claude runs, and Claude's job
is to say those things rather than to choose them.

A week with nothing in it — nothing found, nothing answered, nothing learned
and no meter to read — sends nothing. And unlike the brief, a report that
missed its hour still goes out later that day: a weekly report on Sunday
afternoon is still that week's, and skipping a week to protect an hour is the
wrong trade.

`brain weekly` prints what this week holds without sending; `brain weekly
send` sends one now — which **moves the week**, so the next scheduled report
is a week from now rather than a week from Sunday.

### What the house used

The energy half needs one thing from you: **Home Assistant's own Energy
configuration**. brAIn reads the grid sources you declared there and nothing
else. It deliberately does not gather up every sensor with a device class of
`energy` — a whole-home clamp, an inverter and every smart plug behind them
all carry that class, so a house with six plugs would report roughly twice
what it used and nothing on screen would say so. No energy configuration
means no energy section, and a sentence saying which.

Cost appears only where the Energy dashboard has a cost *statistic*. If you
gave it a price to multiply instead, Home Assistant makes its own cost sensor
under a name brAIn would have to guess at, and a guessed name quotes somebody
else's number.

Both weeks are seven complete days ending at last midnight — never a partial
today, which would report a 45% fall that is nothing but the clock. If a meter
was reset or replaced mid-week those days are dropped, and with them the
comparison: you get the total it could measure and "no comparison to make"
rather than a plausible-looking drop.

### It knows when the washing finished

Nothing in Home Assistant says a cycle ended. A smart plug reports watts, and
every rule written on one is a number typed into a box — `> 10 W` is a running
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
ten days for it to have run a few times. `GET /api/appliances` shows what was
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

### Answering without opening anything

Two places show brAIn's work list, and both of them can end an item.

**`todo.brain`** is the open findings in Home Assistant's own To-do panel and
mobile app — the same list the Findings tab shows, as items. Completing one is
"I've fixed it"; deleting one is "not a problem here". Both are the tab's own
endings, so the memory line, the settled key and the row leaving the list all
happen exactly as they would have.

You cannot *add* an item. There would be nothing behind it and it would vanish
on the next refresh, and a list that silently deletes what you put on it is
worse than one that does not offer to take it. There are no due dates yet
either: a forecast's date lives in the prose of its detail ("about 9 days
left"), and a date parsed out of a sentence is a guess with a calendar entry
attached to it.

The list needs Home Assistant 2023.11 or newer (the To-do panel's own floor).
On anything older it is simply absent.

**Notifications get buttons** — *I've fixed it*, *Not a problem*, *Later* —
when two things are true: the notify service is the Home Assistant companion
app (`notify.mobile_app_*`), and the message is about exactly one finding.
Every other notifier means something different by the payload the buttons ride
in, or nothing at all, and a guess there is how a working notification stops
arriving; and a digest about three problems could not say which one a button
answered. In both cases the message is the one you were already getting.

Either way the answer reaches the add-on through a small file on
`/config/.brain/`, not over the network — brAIn's panel port is deliberately
not published — so if the add-on is stopped when you tick something off, the
answer waits for it rather than being lost.

### It knows what changed, and what changed it

A state does not carry a cause. Nothing in `light.kitchen` being on says
whether somebody pressed a switch, an automation fired, a voice command
asked, or brAIn did it — and that is the question behind most of what people
ask their house.

The **Activity** tab reads Home Assistant's own logbook and puts a cause on
every row: the automation by name, the script, the scene, the person, the
voice assistant, or brAIn. Tap a row for that entity's own recent history.
Page back a day at a time; filter by cause. It costs nothing — no Claude run,
no stored copy — and it needs the `logbook` integration, which is part of
Home Assistant's default config.

Some rows say **no cause recorded**. That is deliberate: a press on a wall
switch and a push from a device's own integration arrive identically, so
naming either would be a guess, and a timeline that guesses is not evidence.

brAIn's own actions are the one thing it does not have to read out of the
logbook. It calls Home Assistant with the Supervisor's token like every other
add-on, so its changes are indistinguishable there from any integration's —
it writes down what it did instead, in `/config/.brain/actions.jsonl`, and
matches that against the logbook.

Claude can read all of this too: ask *"why did the hall light come on"* in
the chat or the ask bar and it looks up the cause rather than reasoning from
a state.

### It says when it is not working

`sensor.brain_health` is `ok`, `degraded` or `failed`, with the reason and
what to do about it in its attributes. It never goes unavailable — Home
Assistant hides the attributes of an unavailable entity, and this is the
entity you look at when the others have gone — and a verdict that has gone
stale reports *that* rather than serving you its last good answer.

It is a state and a sentence, never a score: one number over a house hides
its worst problem inside an average. A face you have switched off is never
counted as a fault. The same verdict appears at the top of **Diagnostics**
under ⚙ and in `brain doctor`.

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

**⚙ > Diagnostics** is the read-only half of the settings dialog: versions, whether
the Claude sign-in is holding, the last 24 hours of Claude runs counted by how they
ended with the failures behind those counts, and the last house-checks pass —
including **which checks could not run, and why**. That last line is the one worth
reading: a skipped check did not find nothing, it could not look, and it is also the
check that is not allowed to clear a row. **Copy for a bug report** puts the payload
on the clipboard (it falls back to putting the text on screen, selected, when an
ingress iframe is refused the clipboard). It is the same payload behind **Download
diagnostics** on the brAIn integration page, and the one `brain report` bundles.

## The CLI

Two dispatchers, split by what they act on. brAIn's own faculties are under `brain`;
anything that acts on Home Assistant is under `ha`.

```bash
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
| `findings_notify_service` | string | *(empty)* | A `notify.*` service (with or without the prefix) that gets a push when brAIn files a new finding. Empty means no notifications — the Findings tab, the sensor and the `brain_finding` event work either way. |
| `findings_notify_min_severity` | `info` \| `warning` \| `serious` \| `critical` | `serious` | Only findings at or above this severity are pushed. The default means dying batteries and silent sensors ring your phone while naming nitpicks wait on the tab. |
| `notify_quiet_start` | string | `22` | The hour (0–23, your home's timezone) from which only urgent findings ring your phone. Everything else is held and delivered as one message when the quiet ends. |
| `notify_quiet_end` | string | `7` | The hour held findings are delivered. A window that crosses midnight (22 to 7) is the normal case. Set both the same, or both empty, for no quiet hours. |
| `morning_brief` | bool | `false` | One short message a day, at the hour your home actually starts moving, and only when there is something to say. Each one sent costs a Claude turn; a quiet morning costs nothing. Needs `findings_notify_service` set. |
| `morning_brief_hour` | string | `7` | When to send it until brAIn has measured your home's own hour (about a fortnight), or if your days are too irregular for there to be one. |
| `weekly_report` | bool | `false` | One message a week: what the house used against the week before, what was found and answered, what brAIn learned, and the one thing worth doing. Needs `findings_notify_service` set — point it at `notify.notify` and it reaches everybody. |
| `weekly_report_day` | list | `sunday` | Which day it goes out. The hour is `morning_brief_hour`, or your home's own measured hour once brAIn knows it. |

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

### House checks and policy

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `checks_interval_hours` | 0–168 | `6` | How often the deterministic house checks run. They read Home Assistant and the Supervisor directly and never call Claude, so they cost nothing. `0` means never on a timer; `brain check` and the tab's button still run them. |
| `protected_entities` | list | `[]` | Entity ids (`lock.front_door`) or whole domains (`alarm_control_panel.*`) that brAIn may never act on, from any face. Enforced where every action passes through, so it covers the terminal, the chat, Fix it, voice and automations; a call aimed at an area or device containing one is refused too. They can still be looked at. |

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
- **`protected_entities` is the line brAIn may not cross.** Put the front
  door lock, the alarm and the garage door on it and no face of the add-on
  — terminal, chat, Fix it, voice, automations — can act on them, whichever
  service is called and whether the target is the entity, its device or its
  area. It is enforced in the one place every action passes through, not in
  a prompt.
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
