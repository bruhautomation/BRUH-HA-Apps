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

**Your house already has nerves. Now give it a brAIn.** Claude plus a suite of new tools
hands it the keys. Stop programming your house — let it think.

brAIn runs Claude Code and a suite of tools inside Home Assistant, and builds a permanent
memory of your house.

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

## It runs Home Assistant

Most AI integrations can turn on a light. brAIn administers the installation. It
reaches Home Assistant three ways at once — **39 native tools** for reading and
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
(it makes the change and reports back), **Discuss** (talk it over first, changing
nothing), **Remind me later**, **I fixed it**, **Dismiss**, or **Wrong**.

**Wrong is the one that teaches it.** Press it and you can say *why* in a sentence —
"that sensor always reads on, it isn't stuck" — and that sentence goes into memory and
into what the next analysis knows about your house. It isn't a filter on a wording; it
is a fact brAIn didn't have, and it is what stops the same misreading coming back in
different words next week. The sentence is optional: if it really is just normal here,
press it and say nothing.

The Findings tab is also where brAIn's **guesses** wait — things it believes about your
home and wants a yes or no on. Same list, because both are the same job: a decision only
you can make. **No** asks why too.

I fixed it and Wrong are endings, and ending one **removes it**. The answer goes into
memory as a fact about your home and the wording is remembered, so the same problem is
never raised at you twice — but there is no pile of dismissed cards left behind. A work
list full of things nobody has to look at again is not a work list.

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
  Delete one you don't want with **⋯ → Delete**; ask for it again whenever you like and
  brAIn builds it fresh, for the house it now knows.
- **The ask bar makes cards.** Every question you ask becomes a card. If the answer is
  worth having every week, press **＋ Make recurring** on it and the question becomes a
  scheduled insight. There is no separate "new insight" dialog — asking *is* the way in.
- **The ask bar also learns.** Start a line with **"learn about…"** or **"study…"** and
  brAIn runs a study session instead of drawing a card: it digs through the registry,
  history and long-term statistics for that corner of the house, and what it finds lands
  in **Memory** and **Findings**. It runs for minutes in the background.
- **Tags are yours.** Each card carries a few \`#tags\` — the chips above the cards filter
  by them, so \`#batteries\` surfaces every card that found a battery problem, whatever
  category it came from. The row scrolls sideways; **✦ All** stays pinned at the left, so
  clearing a filter is always one press. Press ✎ on a card's tag row to drop a bad tag or
  add your own. Your edits survive regeneration; new tags a later run discovers still
  appear.

### A card's buttons

Two on the card, and the rest behind **⋯**. Six glyphs in a row was most of the width of
a card on a phone, and the title was what got squeezed out to make room for them.

- **⤢ Expand** — the only one on the card itself, because it is the only one that acts on
  what is on screen rather than on the card's definition.
- **⋯ → Regenerate** — run this card again now.
- **⋯ → Edit** — name, icon, prompt and schedule. Fixed daily times ("07:00, 19:00") use
  far fewer tokens than a short interval.
- **⋯ → Give feedback** — tell Claude what to do differently next time ("ignore the guest
  room sensor", "show costs in dollars"). It sticks, for every future run.
- **⋯ → Add to dashboard** — YAML for a Webpage card, so an insight lives on your own
  Home Assistant dashboard.
- **⋯ → Delete** — the card and its history.

There is no "refresh everything" button. It used to sit in the top bar, where it was a
circular arrow that read like a page reload and in fact queued a Claude run for every
card you had — minutes of work and a real bite out of the usage the pill beside it was
reporting. Cards run on their own schedule, and **⋯ → Regenerate** does one on demand.

## Findings

Things brAIn thinks are **broken**, and what it did about them. See **Findings** in this
guide. A number on the tab means something is waiting on your decision.

The same list is \`todo.brain\` in Home Assistant's own **To-do** panel and mobile app
(needs core 2023.11+). Ticking one off is *I've fixed it*; deleting one is *not a
problem here* — the two endings on this tab, so answering there teaches brAIn exactly
what pressing the button would have. You cannot add an item: there would be nothing
behind it, and it would vanish on the next refresh.

A notification about **one** finding, sent to the companion app
(\`notify.mobile_app_*\`), arrives with those endings as buttons. Any other notifier
means something different by the payload they ride in — or nothing at all — and a
digest about three problems could not say which one a button answered, so both get
the message they always did. Answers reach the add-on through a file on
\`/config/.brain\` rather than over the network, so one given while the add-on is
stopped waits for it instead of being lost.

## When the washing finished

Nothing in Home Assistant says a cycle ended, so brAIn measures each machine
overnight from ten days of its own five-minute history — looking for the
**shape** an appliance has: hours near a floor, punctuated by runs well above
it. A sensor without that shape (a router, a fridge) gets no profile rather
than a guessed threshold, and you need a power sensor on the appliance plus
about ten days of it running.

The waiting is the part that matters. A dishwasher's dry phase draws almost
nothing for twenty minutes, so "done the moment the power drops" would say
done three times a cycle. That quiet phase is measured too: the gaps between
draws fall into two groups — lulls inside a cycle, idles between them — and
the jump between the groups is the machine's own answer.

The **chore** is narrower than the measurement: a washing machine, a tumble
dryer or a dishwasher that has finished and is still full, matched on the
sensor's name. A deliberate guess in the cheap direction — not recognising
your machine costs a missing reminder, recognising the wrong one means being
told to go and empty your television. brAIn **cannot see that you emptied
it** (an empty machine and a full one draw the same power), so the chore ends
the way any finding does: tick it off, press the notification button, or press
it here. It clears itself if the machine runs again.

## How your house holds its heat

Pre-heating so a room is warm *when you get up*, telling a window open from a
cold day, warning that pipes will freeze by morning — each is the same two
numbers about a room, and a threshold that is right in one house is wrong in
the next. So brAIn measures them, per room, overnight, from a month of hourly
history: **how fast the room falls towards outside** (its reciprocal is the
number people have an intuition for — *this room holds its heat for about
eight hours*) and **how fast anything puts the heat back**.

You need one outdoor temperature sensor and at least one indoor one in an
area. With no outdoor reference there is no model at all, and ⚙ Diagnostics
says so: every number here is a *difference* from outside. The measurement is
taken **at night** on purpose — a south-facing room warms with the heating
off, and a fit that includes an afternoon reports a room that gains heat as it
gets colder outside.

Two findings come out of it. **A room that never reaches what it is set to**:
nothing errors, the thermostat calls and the room sits two degrees short all
winter. brAIn only says so when the arithmetic *and* the evidence agree — the
room must never once have been seen at the temperature it is asked for — 
because a thermostat that switches off at its setpoint never lets a room show
what it could have done. And **a room that empties much faster than the rest
of the house**: a draught, a loft hatch, an open flue. That one needs four
measured rooms before it will compare one against the others, and says nothing
at all if half the house fires at once, because that is the measurement rather
than a room.

Neither is ever urgent, so quiet hours can hold both.

## When the heating is late, and when something is open

The same two numbers answer three more questions.

**Your heating starts too late.** A schedule set to a fixed hour warms the
bedroom to its setpoint at 07:40 in a house that is up at 07:00 — every
weekday, with nothing recording a fault, because the automation ran and the
room did get warm. brAIn needs three of its own measurements to agree before
saying so: when this house *actually* gets up, what the room reads at that
hour of an ordinary week, and how long the climb takes. Then it names the time
the heating would have to start. Weekday mornings only, and never until the
wake time is measured — a preheat time pinned to a typed-in 07:00 is a guess
wearing a number.

**A window is open.** A room falling more than twice as fast as its own
insulation allows is losing heat by a route the walls do not have. Only
sayable because the model exists: the same half-degree in ten minutes is a
draught in one room and an ordinary evening in another.

**The pipes are at risk.** When does this room reach 5 °C — where water in an
outside wall starts to be at risk, well before the room's thermometer reads
freezing. Only for a room already *falling*, because nothing in Home Assistant
says the heating is off, so the fall is the evidence.

The last two read five-minute history: an hourly average cannot see a window
opened forty minutes ago, because it is still inside the hour that has not
finished. Both break quiet hours. The preheat one does not — a schedule that
starts late will start late again tomorrow.

## Where a proposal comes from

The first thing brAIn proposes is **what you already do by hand** — somebody
turning the hall lamp on at about twenty to seven every weekday. No check can
report that: the light works, the switch works, nobody has complained.

So the checks pass keeps the changes a **person** caused, and only those. An
automation moving a light says nothing about a habit, and a wall switch reaches
Home Assistant with no record of who pressed it — brAIn calls that
*unattributed* rather than guessing.

Five things have to hold before anything is offered, and each answers "would
this fire on a house with no habit in it": **six separate days** (twelve
presses on one Monday is one Monday); **a share of the days it could have
happened on**, weekdays and weekends counted apart, because six times in a
fortnight is a habit and six times in two months is a coincidence; **a time
rather than a stretch of evening**, averaged around the clock so a bedtime
either side of midnight is not reported as noon; **it has to still be
happening**; and **nothing must already do it**, because a second rule moving
the same thing is two rules that will disagree.

What it writes is a plain time trigger with a weekday condition when the habit
has one — never a condition it did not measure. A pass offers at most three.

## Proposals, and the trial before them

The **Proposals** tab is the only list here that is not about something being
wrong. It has its own tab rather than a row on Findings, because a list of
things you might want beside a list of things that are broken makes both worse.

**Nothing brAIn writes is enabled without a trial.** Press *Try it for a week*
and the automation runs in **shadow** — it watches live events and logs what it
*would* have done, calling nothing. At the end: *it would have fired six times;
on five of those you did the same thing by hand.*

Every proposal shows its evidence and a **replay** — what the automation would
have done over the last month of your own history, answered in seconds. A
suggestion from nowhere deserves a no.

**Saying no teaches more than saying nothing.** The reason box is optional, but
*"the hall light stays on because my partner works nights"* is a fact brAIn did
not have. A declined proposal is remembered by the **change** it described, not
the sentence — so rewording it will not get it offered again.

Replay covers \`time\`, \`state\`, \`numeric_state\` and \`template\` triggers. Anything
else is refused in as many words, and refused **whole** — never replayed for
just the part that can be read, because a plausible wrong number is worse than
no number.

## What counts as unusual

brAIn measures your house overnight: for every numeric sensor, what it normally
reads **at this hour of this day of the week**, and how much it normally varies,
from a month of Home Assistant's own statistics. No Claude run, nothing spent.

That is what lets a finding say *"4.2 times its normal variation for a Tuesday
morning"* instead of *"that looks high"*. Claude reads the same numbers when you
ask it something like "is the utility room damp?".

It is deliberately quiet in five cases: a sensor that never moves gets no
baseline (there is nothing to measure oddness against), an hour of the week it
has only seen twice is an anecdote rather than a normal, an *impossible* reading
is the device check's to report, an energy total is *supposed* to be higher than
it has ever been, and more than a handful of odd readings at once means the
baseline has stopped describing your house rather than that your house
has changed.

### The slow ones

A freezer 6°C warmer than it was a month ago has never once been outside its
usual range — the range is built from the same weeks the drift happened in, and
moved along with it. It reads about 2 times its normal variation, against a bar
of 6. Nothing above can see it, however far it goes.

So brAIn also fits a line through the month and tells you when a reading has
been **walking one way for weeks**, with the same discipline: something that
turned around mid-month is not a drift, a step change is not weeks of drifting,
and a move smaller than the noise it sits in is not a move. When five
thermometers drift together that is the weather rather than a device, so the
whole class stands down — what you get is the one room doing something the
others are not.

## What is normally open

A door being open is not wrong — it is wrong at half past eleven in a home that
always has it shut then, and nothing at all in one that leaves it open all
summer. brAIn measures which house yours is: for every door, window, lock and
cover, how much of each hour of the week it is normally open, from a month of
your own history. Time-weighted, so a door open ten minutes and one open ten
hours are not the same thing.

Then **at your own bedtime** it files one finding if something is open that
usually is not — one row, not one per door, because it is a single thing to do
before bed. It is deliberately quiet in the afternoon, about an hour it has
never watched, about a door that is usually open then, and when half the house
is open at once (that is airing out, not a door left ajar).

## When your house gets up

Everything scheduled used to happen at a time somebody typed in, which is a
timer rather than a rhythm. brAIn measures it instead: the first thing a
**person** does each day is your house waking up, the last is it settling. Not
a motion sensor (it fires for a cat and for the heating) and not a light (an
automation does that at dawn) — somebody actually doing something.

Two numbers a day, nothing else, and no answer until there is a fortnight of
them. Weekdays and weekends are measured apart, so the weekend answer takes
about five weeks to appear. A home that stirs anywhere between 05:00 and 11:00
has no usual time and is told so, rather than handed the middle of that.

## When it rings your phone

\`findings_notify_service\` pushes new findings straight to a \`notify.*\` service.
Between **quiet hours** (\`notify_quiet_start\` to \`notify_quiet_end\`, 22 to 7 by
default, in your home's own timezone) only the urgent ones get through — a
device gone offline, an add-on that has stopped, a disk about to fill, an
impossible reading.

Urgency is not severity. A \`critical\` battery forecast is three weeks away; a
\`warning\` about a boiler that has stopped answering is now. So it is a property
of the check that raised the row, not of how the row is worded.

**Send a morning brief** is the other half: one short message a day, at the
hour your home actually starts moving. The part that matters is when it does
not send — that decision is made before Claude is asked anything, out of
things already counted (findings since the last one, brAIn itself not working,
an odd night). A quiet morning costs nothing and sends nothing, because "all
quiet" every day is the message people mute and each one that *is* sent costs
a Claude turn.

**Send a weekly report** is one message a week — by default on a Sunday, at the
same hour. What the house used against the week before, what was found and
answered, what brAIn learned, and **one thing to do this week**. That last one
is picked before Claude sees anything (worst open severity, then longest open):
asked to choose, a model picks the finding it can write the best sentence about
rather than the one that matters. A week with nothing in it sends nothing — and
unlike the brief, one that missed its hour still goes out later that day,
because a report on Sunday afternoon is still that week's.

The energy half reads **Home Assistant's own Energy configuration** and nothing
else. Summing every sensor with a device class of \`energy\` would count a
whole-home clamp, an inverter and every plug behind them, so a house with six
plugs would report about twice what it used with nothing on screen to say so.
No energy configuration means no energy section. Cost appears only where the
Energy dashboard has a cost *statistic*, never from a price brAIn would have to
guess a sensor name for.

Everything else is **held rather than dropped**, and arrives as one message when
the quiet ends. Anything you fixed or dismissed overnight is dropped from that
queue rather than announced — being told at seven about a problem that went away
at four is how these messages stop meaning anything. Set both hours the same, or
both empty, to notify at any hour.

## Activity

**What changed in your house, and what changed it.** Every state change with the thing
that caused it beside it: an automation (by name), a script, a scene, a person, a voice
command, or brAIn. Tap any row for that entity's own recent history.

Read straight from Home Assistant's logbook every time you open the tab — no Claude run,
nothing spent. It needs the \`logbook\` integration, which is part of the default config;
if it has been removed from \`configuration.yaml\`, this tab says so rather than showing
you an empty house.

Some rows say **no cause recorded**, and that is the honest answer rather than a gap. A
press on a wall switch and a push from a device's own integration arrive in Home
Assistant identically, so anything that named one of them would be guessing — and a
timeline that guesses is not something you can use as evidence.

Above the list, when there are any: **the times somebody put back what an automation had
just done**. That is the clearest signal a house gives about a rule being wrong for it,
and it is invisible everywhere else — the automation ran, nothing errored, and the light
is off.

Two shapes of that become a finding. **Three in a day, measured against how often that
rule actually ran** — three undos of something that ran three hundred times is you having
an unusual Tuesday, and only the share can tell that from a rule nobody wants. And **the
slow one**: putting the same thing back once a day for weeks, which never reaches three
on any single day. Only overrides are kept for that (a handful of rows a week, not a copy
of the logbook), because *"you undo this every weekday morning"* is a sentence about weeks
and one day of history can only ever produce a count.

When there is a pattern in **when**, the finding names it, because that is the condition
the automation is missing — *"almost always between 08:00 and 09:00 and only on
weekdays"*. When there isn't one it says nothing, rather than reading a shape into a
coincidence somebody would then write a condition around.

And **two automations undoing each other** is its own finding. Both ran, neither failed,
and the light ends up in whichever state the later trigger left it — so the result differs
from day to day depending on the order two triggers happened to fire in. No trace shows
it, because nothing went wrong in either run.

## Terminal

Full Claude Code in the browser, with native Home Assistant access — read states, call
services, check history, edit YAML, reload config.

It's the same terminal the add-on runs, served through this panel, so there's no second
sidebar entry and no second login.

**It has two faces**, and the button in the corner switches between them (so does
⚙ Settings). Both run the same Claude Code, on the same login, in the same \`/config\`,
with the same permissions — the difference is entirely how you see it.

**The switch carries the conversation.** Going to Classic releases the chat's session
and opens the terminal already inside it. Coming back picks up whatever the terminal was
last doing, transcript and all. You do not have to finish a thought in the face you
started it in — swap mid-answer and carry on typing.

One honest limit: only one Claude Code process can own a conversation at a time, so this
is a hand-off, not a mirror. The face you leave lets go; the face you arrive in takes
over with the full history. The terminal's own shell is never killed to make that happen
— it is your shell — so if you had one running, it is still sitting there where you left
it.

**Chat** is the default. Claude Code's output rendered as a conversation: text that
reflows to your screen, code blocks that scroll inside their own box, tool calls folded
into one line each (tap for the arguments and the result), reasoning streamed live into
a "Thinking" line as it happens, and a real text box so dictation and autocorrect
behave. While Claude works, a status line under the newest content says what it is doing
— thinking, writing, which tool is running — and how long the turn has been at it, the
same way the native CLI does. **⏹** stops an answer in progress and **＋** starts a new
chat. It survives a reload, a locked phone, and the add-on restarting.

**When Claude needs a permission you haven't granted, it asks.** A call outside the
pre-approved set used to fail silently in the chat — headless Claude Code cannot put a
prompt on a TTY — and the answer got written around the gap. Now the same question the
classic terminal would ask arrives as a card in the conversation: what tool, aimed at
what, **Allow once** or **Don't allow**. The turn waits for your answer (ten minutes,
then it declines on your behalf and says so), a declined call shows amber as "not
permitted" rather than red as an error, and everything already allowed in
\`/config/.claude/settings.local.json\` still runs without asking.

**When Claude has a question, you get the question — not a permission slip.** Claude
Code sometimes asks multiple-choice questions mid-task (which zone did you mean, which
approach do you prefer). Those used to arrive as "may I use AskUserQuestion?", and
allowing it sent back an empty answer sheet that broke the turn. The chat now renders
the questions themselves: tap an option, pick several where it allows it, or type your
own answer — and **Don't answer** tells Claude to use its best judgement instead of
asking again.

**One thing the chat can't do: appear in the Claude app on your phone.** The app's
"connected" sessions ride Remote Control, which only supports interactive sessions —
the chat drives Claude Code headlessly, and there is no flag that changes that (it's a
Claude Code limitation, not a setting). The conversation itself is not stuck, though:
switch to Classic and the same conversation moves into a real terminal session, which
can register with the app like any other.

**Type / for Claude Code's commands, or \`brain\` / \`ha\` for brAIn's own.** The palette
lists what *your* install actually has — including anything you put in
\`/config/.claude/commands\`, and every subcommand the two dispatchers print. Neither
list is written down in the panel, so neither can go stale. ↑/↓ to move, Enter or Tab
to pick. A few Claude Code commands are REPL-only (\`/help\` among them) and say so
rather than failing.

**⋯ holds the rest.** *New chat*; *Conversations* — every conversation in \`/config\`,
started here or in the classic terminal, and picking one replays it into the pane and
carries on; *Session details* — the model, the project directory, how you are being
billed, and this conversation's id (copy it to resume from an SSH session or another
machine); and the switch between the two faces.

Both faces stand in the same directory, which is what lets each see the other's
conversations at all: Claude Code files them per working directory.

**On a wide screen the conversations get a rail.** From about 1100px the chat grows a
column down the left listing every conversation, with **＋** for a new one and the one
you are in marked rather than hidden. It is the same list the menu opens and the same
resume — below that width it isn't drawn, because 248px of conversations is most of a
phone, and **⋯ → Conversations** is still there.

**The rail shows yours, and says who ran the rest.** brAIn drives the same Claude Code
from \`/config\` for voice, for automation tasks and for filing memory, so those land in
the same store your own chats do — and a house that uses them ends up with a column of
machine prompts. Each row carries who started it, and the chips above the list choose:
**Yours** to begin with, then **Voice**, **Automation**, **Memory** or **Study** with a
count each. Only faces that have actually run in your house are offered, nothing is
hidden, and opening a machine's run is a perfectly good way to see what voice really
did with "turn off the kitchen lights". Switching back from the classic terminal only
ever picks up a conversation of yours.

**Starting a new chat does not lose the old one.** Claude Code keeps it and it stays in
the list. What a new chat costs is that the next thing you say belongs to a separate
conversation, not that anything was forgotten.

**Deleting takes one press, or one pass.** The **✕** on a row deletes that conversation,
with an Undo in the toast for a few minutes. To clear several at once, press the
checklist icon above the list (in the rail or in **⋯ → Conversations**): rows grow
checkboxes, **Select all** takes everything but the chat you are in, and **Delete**
removes the lot with a single Undo that puts them all back. The open conversation is
never deleted — start a new chat first if you really mean it.

**Under the box: which model is answering, and how full the conversation is** — say
\`42k / 1000k context · 4%\`, going amber past 80%. The number is the CLI's own report of
what it sent on the last model call, and what it sent *is* the conversation so far, so it
is measured rather than estimated. Cached parts count: a cached prompt still takes up the
window, it is only cheaper to send. The window is the model's own published one, so it
changes with the model you are on — Opus and Sonnet are 1M from 4.6 onward, Haiku is 200k.

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
Nothing on this tab is waiting on you — the queue files itself, and the document is
there to read. Anything that needs an answer is on **Findings**.

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
| **Findings** | What is *broken* in this home? | Fixed, or corrected |

A finding is a work list item. A dead battery. A sensor that hasn't changed value in six
days. A device stuck unavailable. An automation whose trigger entity was renamed, so it
can never fire again. Something is wrong and somebody has to do something about it.

Findings come from insight runs and from study sessions — the same passes that fill
memory — and from the **house checks**, which cost nothing. brAIn only reports a problem
**once**: the same finding in different words is recognised and dropped.

## House checks

Not every problem needs a model to find. On a schedule (every
\`checks_interval_hours\`, six by default) and on **Run checks now**, brAIn reads Home
Assistant directly — registries, states, your automations, the traces Home Assistant
keeps, a week of statistics, the dashboards, and the Supervisor's own view of backups,
add-ons and the disk — and files what it finds under a *check* label, with no Claude run:

- an automation naming an entity that no longer exists, or calling a service that is
  not registered (your old phone's notify service, with the replacement named)
- an automation whose last run failed, whose condition never passes, that keeps being
  skipped on \`mode: single\`, that has never fired, or was switched off and forgotten
- a device unavailable for more than a day; a battery low, or *gone quiet*; an
  impossible reading; a sensor frozen on one value for a week
- an automation that is switched on, errors at nothing, and can never fire again,
  because the entity in its trigger has been unavailable for days
- a Z-Wave node the controller has marked dead, or a Zigbee device that has stopped
  checking in — a sleepy sensor reads as \`available\` between check-ins, so silence is
  the honest question and not availability
- an entity still named after its hardware, a device in no area, a helper nothing uses,
  a device row with no entities behind it
- nothing backed up in a week; an add-on erroring, or set to start on boot and stopped;
  a disk nearly full; a recorder database that has outgrown its headroom
- a dashboard showing entities that no longer exist
- a battery **running down**, from the slope of its last sixty days — a finding with a
  date on it

A check's finding clears itself when the check stops finding it — the device came back,
the battery was changed — and it is simply removed, so it can come back if the problem
does. What *you* end stays ended.

## How right it's been

Every ending here is a label. **I did it** and **Got it** say the report was right;
**Wrong** says it was not. Once a producer — a check, a card, a study topic — has a few
endings, a line under the filters says how right it has been. That is the number that
decides whether this tab is trusted, and it is the number that gets a check with a bad
threshold fixed.

## Guesses are on this list too

The first two rows of that table stay different kinds of knowledge, but answering them
is the same job — a decision only the person who lives here can make — so they are on
one list. A guess sits at the top of **Needs you** with **✓ Yes** and **✕ No**:

> The garage fridge is meant to run 24/7

**Yes** files it as a plain fact in memory. **No** offers you the same box Wrong does,
and the same thing is true of it: "no" retires one guess, and *"no, that's the beer
fridge and it's meant to cycle all night"* retires every guess built on the same
misreading. Never more than three are open at a time, and they expire after 14 days.

They used to be answerable in two other places as well — under each insight card and in
the Memory tab — with a badge that counted neither. Answering in one left the others
showing an open question. One list, one badge, and when it says nothing is waiting,
nothing is.

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

### The two endings

They are easy to confuse until you say what each one *teaches brAIn*, which is the only
difference that matters:

**✓ I fixed it** — it was a real problem and it is sorted now. For anything with hands
in it: replacing a battery, re-pairing a device. brAIn marks findings like these **needs
you** rather than offering to fix them, because inventing a software substitute for a
dead battery is worse than saying so.

It offers the same box, for a different reason: nothing is being corrected here, so what
you type is simply more of the fact.

> Replaced the CR2032 — it's a 3-monthly job on that one.

"I fixed it" leaves brAIn knowing a problem is over. That sentence leaves it knowing your
house. Optional, like the other one.

**✕ Wrong** — brAIn has misread something, or it is simply normal in this house. If the
garage freezer is *supposed* to sit at -30°C, one press ends that conversation for good:
the answer is fed back into every future analysis, so brAIn stops raising it rather than
raising it again next week for you to dismiss again.

**Say why, if there is a why.** Pressing it opens a box for one sentence:

> That sensor always reads on. It's not stuck.

That sentence is worth more than the press. Without it, brAIn learns that one wording was
unwanted, and reports the same misunderstanding again in different words. With it, it
learns something about your house — and that goes two places: into your memory document
at the next consolidation, and into what every future analysis is told about this home.

It is not a rule brAIn obeys literally. It is handed over as *what you said*, and brAIn
works out what follows from it — usually a standing fact about a device or a habit,
sometimes nothing at all. That is on purpose: you shouldn't have to phrase a correction
carefully for it to be useful.

The box is optional. If it is just normal here and there is nothing to explain, press
Send with it empty.

Both endings do the same three things. The answer goes into memory as a plain fact about
your home, the wording is remembered so the same problem is never reported at you twice,
and **the card is deleted**. There is no pile of dismissed cards to scroll past — a list
of things nobody has to look at again is not a work list.

### Undo

Because the card is deleted, and because the two endings sit next to each other meaning
opposite things. Every press that takes something off the list — both endings, **Got it**,
**Dismiss**, and either answer to a guess — leaves an **Undo** in the toast for a few
seconds. It puts back all of it: the card, the suppression that would have stopped brAIn
raising it again, and the line it queued for your memory document.

It is deliberately only that long. This is "I pressed the wrong one", not a history: once
a consolidation has run, the fact is in the document and the way to change it is to edit
the document. If you press Undo after that, it says so rather than pretending.

**Fix it has no Undo**, because it starts a Claude run against your actual house and
taking the card back would be a lie about what was undone. **Remind me later** has none
either — it took nothing away, and it already has *Bring it back now*.

### Dismiss, which is neither

**⌫ Dismiss** clears the row and teaches brAIn nothing. No memory line, no suppression —
so the next analysis is free to find the same thing again, and probably will if it is
still there.

That is the difference from Wrong, and it is why both exist. Wrong is a judgement about
the problem: *you've misread this*, or *this is normal here*. Dismiss is a judgement
about the list: *not now, and I don't want to promise anything*. Use it when you're
clearing the board rather than answering it.

**💬 Discuss** opens it as a conversation in the Terminal tab, with everything brAIn
knows about it already in the question: the detail, the fix it had in mind, the entity,
the severity. It is asked to look into the thing and say plainly whether it really is a
problem *in your house* — and told not to change anything, because "explain this to me"
and "go change my house" are different permissions.

The decisions come with you. While you are discussing a finding, a strip above the
message box keeps **Fix it**, **I fixed it**, **Later** and **Wrong**
one press away, so agreeing to the fix at the end of the conversation doesn't mean
coming back here to find the card again. Wrong asks for its reason there too — telling
Claude in the chat reaches *this* conversation, and the box reaches every future one.

**⏰ Remind me later** is the answer for "yes, but not now" — an hour, tomorrow, next
week, next month. It is not a decision and it does not settle anything: the finding
stays exactly as open as it was and simply stops asking. Use it instead of dismissing
something you actually intend to deal with, because dismissing is permanent. While it
waits it sits under the **Later** filter, showing when it comes back, with a button to
bring it back sooner.

## After a fix

When brAIn fixes something itself, the card **stays on the list** and turns green with
what it changed and which files it touched. That is deliberate: it altered something in
your house, and news you haven't read is not settled. **✓ Got it** clears it once you
have. What it changed is already in memory by then, so the press only means "I've seen
this".

The **Answered** filter is the record of everything you have ended — one line each,
saying whether you dealt with it or told brAIn it was never a problem. It is not an
archive of cards; the cards are gone. If you change your mind, **Let brAIn raise it
again** stops suppressing that one. Nothing comes back on its own — the next analysis is
simply free to find it, and if it has genuinely stopped happening, nothing does.
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
| Findings | what you said when you pressed **Wrong** or **I fixed it** |
| Guesses | the ones you confirmed, and your reason for the ones you didn't |
| \`brain memory add\` | what you type in the terminal |

One writer means the terminal, the panel, and voice can all feed the same memory without
fighting over the file.

**Waiting to be filed** is that queue, and every row in it is a line the next pass will
read — whoever put it there. It used to list only what insight runs had discovered while
counting everything, which is why it could say "9 things waiting" above four cards. **✕**
on a row drops it before it is filed; nothing is asked of the consolidator, because a
queued fact has never reached the document. A line that *is* in the document is edited out
of the document, in the markdown editor beside the queue.

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

## Guesses live on Findings

brAIn proposes things it believes and asks you to confirm — *"the garage fridge is meant
to run 24/7"* — and a confirmed one becomes a line in the document beside this queue.
But answering is a **decision**, and decisions are all in one place: the **Findings**
tab. See that section for what Yes and No do.

Nothing on this tab is waiting on you. The queue below files itself on a timer, and the
document is here to read and edit.

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
brain check                        # the house checks, now — no Claude run
brain doctor                       # end-to-end diagnostic
brain doctor --json                # the same verdict as one JSON object
brain report                       # redacted diagnostics bundle for a bug report
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
- **\`sensor.brain_open_findings\`** — how many findings are waiting on you, with the
  severity split and the texts as attributes.
- **A \`brain_finding\` event per new finding**, for automations and the logbook — and
  the \`findings_notify_service\` add-on option pushes new findings to a phone with no
  automation at all.

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
- **\`sensor.brain_open_findings\`** — how many findings are waiting on you, with the
  severity split and the texts as attributes.
- **A \`brain_finding\` event per new finding**, for automations and the logbook — and
  the \`findings_notify_service\` add-on option pushes new findings to a phone with no
  automation at all.

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
**Press it** for when each one resets and what the session went on — there is no hover
version, because a phone is where that pill is most often the only thing worth reading.
Nothing is budgeted against the weekly number — it is
there because a session that looks fine tells you nothing about a week that doesn't.

Both figures come from your Anthropic account when you signed in with a subscription.
When brAIn can't read them, the pill shows **\`~19%\`** with a warning dot instead: a
tilde means the number is an *estimate* of brAIn's own spending against a rough plan
allowance, not your account's real usage, and the weekly window isn't shown at all.
Press the pill and it names the reason — most often an API key (which bills per token
and has no usage window), a sign-in that has expired, or Anthropic rate-limiting the
usage endpoint itself, which is nothing to do with your account's quota and clears on
its own. The \`sensor.brain_usage_tracker\` diagnostic entity carries the same status
for automations.

## What a card costs, and where to see it

A card is not a chat message. Generating one posts a snapshot of your home to Claude and
gets a whole rendered visualization back, so **a single card is typically 25k–45k
tokens** — a few percent of a Pro session each, and several cards in a row is a real
bite out of a 5-hour window.

## How a card gets its data

There are two ways, and ⚙ **Settings → How a card gets its data** picks between them.

**Search** (the default) gives Claude a *map* of your home — how many entities of each
kind exist, which areas they're in, a few anchors like people and thermostats — plus
read-only Home Assistant tools. It then looks up what the card actually needs: search by
room or by name, read the few entities that matter, pull their history. A question about
the hallway costs the hallway. It is also the only mode that can afford **history on a
question you type**, which the one-shot path never could.

**Snapshot** posts the whole slimmed home in a single turn with no tools at all. It's
predictable and it's the automatic fallback — if a search run fails or runs out of turns,
brAIn falls back to the snapshot so a card always appears. That fallback is logged, so a
run that keeps taking it is worth reading the log about.

Neither mode can change anything in your house. Insight runs get **reading tools only** —
no service calls, no controls, no shell. The one place brAIn changes things is the
Findings tab's **Fix it** button, which you press.

Why not a middle option, where Claude is handed a list of every entity and picks from it?
Measured: the list costs about as much as the data does, because every entity id has to
be in it. Searching by name skips that entirely.

Under Snapshot, **an asked question is the expensive kind**: a category card sends that
category's slice of the home, while a question sends *every* entity (up to 500) plus
device context, because the question could be about anything. That is why, in Snapshot
mode, three answers can cost what a dozen category refreshes do.

Three places now say so, and they say the same number:

- **While it runs** — the card's spinner line reads \`500 entities · ~33k tokens sent\`,
  so the size is visible before the answer is.
- **After it runs** — the card's footer shows \`41.2k tokens\` beside the stopwatch.
  Hover it for the input/output split. Seconds and tokens are different readings: a fast
  card over the whole home outspends a slow one over eight thermostats.
- **Across the window** — press the usage pill. Under the two windows is *What brAIn
  spent, this session*, itemized per card. When the percentage is your account's live
  figure it covers everything on your subscription — terminal, chat and voice included —
  and the list underneath is only brAIn's own generation runs.

The add-on log carries the same numbers, one line per run:
\`custom-1785807758 cost 41.3k tokens (33.2k in + 8.1k out; 0 read from cache, free)\`.

Biggest levers, in order:

1. **Leave "How a card gets its data" on Search.** It is the single biggest one, and it is
   the default.
2. **Fixed daily times** on a card ("07:00, 19:00") instead of an interval.
3. **Disable cards you don't read.** Each card's **⋯ → Edit** dialog has an Enabled
   switch.
4. **A smaller model.** Settings → Claude model. Smaller models cost far fewer tokens;
   the bigger ones dig deeper.
5. **Fewer history days.** Settings → History analyzed.

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
smoke-tests the CLI. \`brain doctor --json\` gives the same verdict as one JSON object.

## What brAIn has been doing

**⚙ > Diagnostics** is the read-only half of the settings dialog: versions, whether the
Claude sign-in is holding, the last 24 hours of Claude runs counted by how they ended,
the failures behind those counts, and the last pass of the house checks — including
**which checks could not run, and why**. That last line is the one worth reading. A
check that was skipped did not find nothing; it could not look, and it is also the check
that is not allowed to clear a row, so "12 ran, 3 skipped" and "15 ran" are very
different reports of a quiet house.

**Copy for a bug report** puts the whole payload on the clipboard. If your browser
refuses the panel the clipboard — an ingress iframe sometimes does, and there is no way
to ask in advance — the text appears on screen already selected, ready for Ctrl/Cmd+C.

## Reporting a bug

\`\`\`bash
brain report
\`\`\`

That writes one redacted archive under \`/share/brain/reports/\`: the self-test's verdict,
the panel's diagnostics (versions, options, the last day of the run journal — every
Claude run and how it ended, the findings and memory stores' shapes, the last house
checks pass), and the tail of the add-on log. Anything credential-shaped is replaced
before it is written; prompts and replies are never in it. Read it, then attach it to
the issue. The same bundle is behind **Download diagnostics** on the brAIn integration
page in Home Assistant.

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

Don't fight it in the prompt — use **⋯ → Give feedback** on the card. That's remembered and
applied to every future run of that card.

If it's wrong about a *fact* rather than a presentation choice, fix it in **Memory**.
Delete the wrong line and brAIn is asked to drop it from the document too.

## It keeps flagging something that's fine

Press **✕ Wrong** on the finding and say why in the box:

> That sensor always reads on. It's not stuck.

That reaches both your memory document and every future analysis, which is what stops
the same misreading coming back in different words. Telling it in Memory works too, and
so does answering the guess it's already showing you on **Findings**.

## Claude's login expired

Open the Terminal tab and run \`claude\` once. Background tasks, voice, and insights pick
the fresh login up automatically.
`,
  },
];
