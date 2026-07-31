# Changelog

All notable changes to **brAIn**, newest first. This project adheres to [Semantic Versioning](https://semver.org).

## 1.11.2

### Home memory cannot be erased by a consolidation any more

**This is the important one.** The consolidator asks Claude for the whole
updated `memory.md` and then checks the answer before writing it: not empty,
still has its `##` headings, still under the size cap. A document that came
back as *nothing but those headings* passed every one of those checks — it
is not empty, it has headings, and it is very much under the cap. So a pass
where the model rewrote instead of merging could replace a year of learned
facts with the blank template, and nothing would object.

Two guards now stand in front of that write:

- **Coming back with no content at all, over a document that had some, is
  refused outright** — at any size. There is no document small enough for
  that to be a real merge.
- **Losing most of the content in one pass is refused** while the document
  is comfortably under its cap. Consolidation adds: it merges the inbox in
  and dedupes, and it only sheds lines when the document is near the cap,
  which is the one case the guard steps aside for.

Either way the document is left exactly as it was and the inbox stays
pending, so the next pass tries again. A stale memory is recoverable; a
wiped one is not.

**And a failed write no longer eats the facts.** The script runs without
`set -e`, so if writing `memory.md` failed — a full disk, a permission
problem — execution fell straight through to the step that archives the
inbox. The document would be unchanged and the queue emptied: the one
combination where nothing anywhere says something went wrong. The write is
checked now, and a failure leaves both alone.

### The Memory tab says when it is filing

Consolidation runs daily, and early once the queue passes 20 facts. None of
that reached the panel — only passes started with the **File into memory
now** button did — so the queue could empty while you were looking at it
with nothing on screen accounting for where the facts went.

The tab now shows a running pass whoever started it, with a spinner and a
line saying whether it is yours or the schedule's. It reads the lock the
consolidator already takes, with a shared lock, so asking the question can
never be something a real pass waits on.

## 1.11.1

### The terminal now stands where the chat does

Claude Code files every conversation under
`~/.claude/projects/<the working directory>/`, and `claude --resume` only
lists the ones belonging to the directory you are standing in. The panel's
chat terminal runs in `/config`; the tmux session inherited whatever
directory the add-on's init happened to give it. When those differ, the two
faces of the same tab keep their conversations where the other one cannot
see them — which is why a chat conversation could not be resumed from the
terminal.

Every session the terminal starts is now pinned to `/config` explicitly. The
same directory is what makes `/config/CLAUDE.md` load and what makes
`/config/.claude/settings.local.json` the project settings the whole add-on
is documented as running under, so inheriting it by luck was never a good
idea either.

The chat's **ⓘ** button now shows the session id, the model, the project
directory and how you are being billed — with **Copy the command** and
**Continue in the terminal**. The second one releases the session first,
because while the panel holds a conversation open the terminal is being
asked to resume something still in use.

### No more price tag on a subscription

Every answer ended with something like `$0.012`. That figure is what those
tokens would have cost had you bought them from the API — on a Pro or Max
plan it is not a charge, and printing it after every message is a number
that looks like money and isn't.

The CLI tells us which case it is (`apiKeySource`), so the figure now
appears only when an API key is genuinely being billed per token. On a
subscription you get the duration and the turn count, which are the parts
that mean something.

### Slash commands

Claude Code advertises its own command list over the stream, and runs a
command when it arrives as an ordinary message. So the chat terminal now
has them: type **/** and the palette lists what *your* install actually has
— including anything in `/config/.claude/commands` — with descriptions and
argument hints. ↑/↓ to move, Enter or Tab to pick.

The list is never hardcoded, so a command you add appears without brAIn
being told about it. A few commands are REPL-only (`/help` among them) and
say so politely rather than failing.

## 1.11.0

### The terminal stops being a window inside a window

A terminal is a grid of fixed-width cells. On a phone that grid is about 40
columns wide, and a grid cannot reflow — so sentences broke mid-word, a
single tool call spent twenty lines saying what one line could say, and the
whole thing sat inside ttyd inside tmux inside an iframe.

The Terminal tab now has **two faces**, and a button on the tab switches
between them (⚙ Settings has the same control). Both run the same Claude
Code, on the same login, in the same `/config`, under the same permissions —
the difference is entirely how you see it.

**Chat** is the new default. Claude Code's own `stream-json` output rendered
as ordinary DOM:

- **Text reflows** to the screen it is on, because it is text and not a grid.
- **Code blocks keep their grid** — inside their own horizontal scroller, so
  a 200-column log line never makes the page slide sideways.
- **Tool calls fold into one line each** — `Read /config/automations.yaml`
  with a dot that goes green or red. Open one for the arguments and the full
  result; a failed one opens itself, because it is the reason the next thing
  Claude says will look strange.
- **Reasoning folds away** behind a "Thinking" line.
- **The composer is a real text box**, so dictation, autocorrect and
  selection behave — there is no hidden xterm helper element to fight with,
  and no iOS diff-fix needed because there is nothing to fix.
- **⏹ stops an answer** and **＋ starts a new chat**. Stopping asks the CLI
  politely first and kills it if it does not answer; either way the
  conversation survives, because Claude Code is what persisted it.
- The transcript survives a reload, a locked phone, and an add-on restart.

**Classic** is the terminal exactly as it was — ttyd over tmux — and is the
right answer for anything that draws its own screen: a TUI, `htop`, an
installer, or running shell commands yourself.

Nothing about what Claude may do changed. The chat session runs in `/config`
under the same `settings.local.json` permissions as the Assist listener, the
Automation listener and the Findings fixer, so there is still one answer to
"what may Claude do here" rather than two.

## 1.10.0

### The bar is one size now

Between roughly 960 and 1240 pixels the top bar had a third shape: one row,
tab labels deleted, tabs shrunk to bare glyphs. That is the width a laptop
with the Home Assistant sidebar open actually renders at — so the
compromise was the shape most people saw, and widening the window made the
tabs *grow*, which reads as a bug whatever the intent.

Gone. There are two shapes and no third: one labelled row at 1240px and up,
and the two-row bar below it, with all five tabs still named. The tabs stop
growing at 168px and centre themselves, so five equal shares of a wide
window isn't five oversized targets with a small glyph adrift in each.

### Every control in the bar does its own job

Three of them opened Settings, so a bar that reported three different things
answered all of them with the same dialog.

- **The usage pill opens its own numbers.** Press it and you get both
  windows with when each one resets, and what the budget actually gates.
  It's a press rather than a hover because the reset times used to live in a
  tooltip — a fact that exists and cannot be read on a phone, which is where
  that pill is most often the only thing worth reading.
- **"Auto insights off" is now the switch.** One press turns them back on
  and the chip goes away, because the thing it was reporting is no longer
  true. A usage budget that has been reached isn't a switch, so that one
  explains itself instead — what you've spent, what the budget is, and when
  the window rolls over.
- **⚙ is the one route to Settings.**

### The terminal gets the screen back on a phone

With the keyboard up, the terminal was getting about a third of the display:
Home Assistant's header, then brAIn's two rows, then the tab strip, then the
keys.

The bar now folds away while you're typing and comes back when you dismiss
the keyboard — the ttyd frame is the only thing in the stack that can see an
iOS keyboard from inside an iframe, and it already had to work that out for
its own toolbar, so it reports it rather than the panel guessing a second
time, worse. **⤢** over the terminal folds the bar away for good, and the
same button brings it back.

tmux also drops its status line below 90 columns. One row out of about
twenty, spent on the session name and the date.

### The documentation says what brAIn actually is

Rewritten around the whole capability rather than around three components:
brAIn administers Home Assistant — every entity, device, area, floor, label,
dashboard, helper, automation and add-on — and the docs now say so, with the
36 native tools, the 65 registry services and the shell all in one page. A
new **What brAIn can do** section opens the in-panel guide.

References to the two add-ons brAIn replaced are gone from the
documentation. They meant nothing to anyone arriving now.

## 1.9.0

### A top bar you can actually hit

The bar was a fixed 48px row at every width, and it stayed one row by deleting
text until it fit — tab labels first, then the words inside the status chips.
On a phone that left five unlabelled glyphs and a bare amber dot, with the only
explanation in a hover, on the one device that cannot hover.

It now has two shapes. On a desktop it is a single 56px row. On a phone the
tabs move to a full-width strip of their own with **each name under its icon**,
and every target — tab, button, status pill — is at least 44px. Nothing hides
its words to fit any more; what gives way is the row.

The measurement script behind it (`tests/manual/measure-topbar.mjs`) now fails
on a target under 44px as well as on an overflow, across all three bar states.

### The usage pill says which number is which

It read `19% · 100%`: two percentages, a dot between them, and nothing saying
that the first is your 5-hour session and the second is your week. It now reads
**Session 19% · Week 100%**, labelled in the bar itself.

The **amber dot beside it is gone** — that was the "auto insights off" /
"budget reached" chip with its words hidden, which is a warning that declines
to say what is wrong. It keeps its words at every width now.

Hovering the pill gives you **the reset times, and nothing else**. It used to
also recite both percentages you can already see, the budget threshold, and
"tap for settings" — four facts in a tooltip, three of them already on screen.

### The Memory tab stops repeating itself

**Already in memory — 23 discoveries** is gone. Once a discovery is filed it is
part of the memory document on the right, and that is where you read it, edit
it, or take it out. Listing it a second time underneath the queue meant a
drained queue never looked drained. Nothing was deleted: the dedup ledger still
holds every announced fact, so brAIn still can't tell you the same thing twice.

The instructions came down with it. Four explanatory paragraphs introduced
lists that were shorter than the paragraphs; what is left is two headings, two
lists and a button. The long version is still in the **Docs** tab.

### Power Tools: nothing is create-only any more

Nine new admin services, closing every gap where you could create something and
then never change or remove it:

- **`rename_label`** and **`update_label`** — a label was create-only. Its
  colour, the thing a label is mostly for, could not be changed after the fact.
- **`delete_device`** — devices could be renamed and disabled but never
  removed. `dry_run` previews the entities that go with it, and names the
  config entries that would recreate it, so a delete that won't stick is
  visible before you make it rather than after.
- **`delete_orphaned_devices`** — the device counterpart of the entity
  cleanup, dry-run by default, for devices whose integration is gone.
- **`delete_integration`** — removing a config entry, with its devices and
  entities. Disable was reversible and there was no delete at all.
- **`set_area_icon`**, **`update_floor`** — an area's icon and a floor's
  icon, level and aliases could be set at creation and never afterwards.
- **`rename_person`** — for the same reason as all the others.

`update_*` services write only the fields you actually name, so changing a
label's colour doesn't blank its description. That is now a test, along with
the rule these services came from: every registry object brAIn can create, it
can also rename and delete.

## 1.8.0

### It's brAIn

The name is spelled **brAIn** everywhere now — add-on, panel, integration,
sensors, CLI help, docs. The wordmark never needed changing: the gable already
doubles as the `A`, and the `A` and the `I` were already the one part drawn in
the accent colour. The letters were saying it before the text was.

The conversation agent, the system health sensor and the usage sensors read
"brAIn" in Home Assistant now. **Entity IDs are unchanged**, so nothing in your
automations, scripts or dashboards breaks.

### "File into memory now" actually empties the list

Pressing it filed the queue and then showed you the same list, unchanged, with
the same "2 things waiting" underneath. Two separate faults:

- **Filed discoveries never left the list.** The list was reading the dedup
  ledger — the record of what has already been announced, which by design
  keeps entries forever. It is now split: **Waiting to be filed** is only what
  is genuinely still queued, and everything already folded into the document
  moves into a collapsed *Already in memory* group below it. The ✕ still works
  in both, because it is the one-click way to make brAIn forget something.
  Nothing was deleted from the ledger, so the analyst still can't re-announce
  a fact you have seen.
- **A pass that filed nothing reported success.** The consolidator exits 0 in
  cases where it deliberately keeps the facts, and being skipped because
  another pass held the lock exited 0 too. The count is now read either side of
  the pass and the response says what actually moved — "the queue didn't move"
  and "another consolidation is already running" are now things the panel can
  tell you, instead of "Filed 2 things" over an unchanged list.

### One usage pill, both windows

The top bar's usage pill showed the 5-hour session and its reset time. It now
shows the **session and the week** — `19% session · 64% week` — because the
seven-day limit is the one that actually ends your week on a Claude plan. The
reset times moved into the hover, where a value that changes once per window
belongs; the numbers, which change all day, stay in the bar. The ⚙ dialog
states the week too.

### The "Claude · subscription" pill is gone

A green pill labelling a state that never changes, sitting in a bar where
space is the scarce thing. The auth chip now appears **only when there is
something to say** — verifying, failed, or not connected — which paid for the
second usage number twice over.

On a 320px screen the bar had been overflowing whenever the login failed;
nothing reported it, because the fit was only ever measured with a healthy
login. `tests/manual/measure-topbar.mjs` now measures three bar states at
every width, and the breakpoints moved to what it reports — five bands now
rather than four. Below 450px the weekly number steps aside, and below 410px
so does the whole pill if a trouble chip needs the room: a login that isn't
working outranks a reading you can check afterwards.

## 1.7.0

### Findings — memory you can act on

Memory tells you what is *true* of your home. A guess asks whether brAIn has
something *wrong*. Neither has anywhere to put the third thing: something that
is **broken**.

**Findings** is a new tab, and it is a work list. A battery that died. A sensor
that has read the same value for six days. A device stuck unavailable. An
automation whose trigger entity was renamed, so it can never fire again.
Insight runs and study sessions both file them, and brAIn reports a given
problem exactly **once** — the same problem in different words is recognised
and dropped.

Every finding has two ways out and no third:

- **✦ Fix it** sends Claude to make the change in your actual Home Assistant.
  It confirms the problem is still real, finds the cause rather than the
  symptom, makes the smallest change that resolves it, verifies the change
  took, and reports back with a list of exactly what it touched. It is bounded
  hard: one finding per run, never deletes anything it didn't create, never
  restarts Home Assistant, never touches secrets, and **nothing runs until you
  press it**. Anything it notices along the way becomes its own finding rather
  than an edit you didn't ask for.
- **Not a problem** dismisses it permanently, and the dismissal is fed back
  into every future analysis. If the garage freezer is *supposed* to sit at
  -30°C, one press ends that conversation for good instead of dismissing the
  same alert every week.

Anything needing hands — a battery, a re-pairing — is marked **needs you**
rather than offered a fix, because inventing a software substitute for a dead
battery is worse than saying so. **✓ I did it** closes those.

Fixed and dismissed findings don't vanish; the filter at the top of the tab is
how you check what brAIn changed in your house last week. Successful fixes are
written into memory too, so a later analysis doesn't rediscover a problem brAIn
resolved itself.

Under the hood the generation contract split in two: what a run *learned* about
the home (durable facts → memory) is now separate from what it *found* wrong
(→ this tab). They were one field, which is why nothing was ever actionable.

### The ask bar does both jobs, so the ＋ button is gone

Asking a question already made a card, and any card can become a recurring
insight with **＋ Make recurring**. A separate "New insight" dialog was a
second, harder path to somewhere you had already been taken — so it's gone from
the header.

The bar now has a second verb. Start a line with **"learn about…"** or
**"study…"** and brAIn runs a study session instead of drawing a card: it digs
through the registry, history and long-term statistics for that corner of the
house, and what it finds lands in Memory and Findings. That was previously
reachable only from the terminal, which meant nobody ran one. The placeholder
and the line under the bar teach both, because the bar is the only place either
is discoverable.

### Tags are yours to edit

Every card carries a few `#tags`, and the chips at the top of the dashboard
filter by them — `#batteries` surfaces every card that found a battery problem,
whatever category it came from. Which was useful right up until a run invented
a bad one, at which point your only option was to hope the next run didn't
repeat it.

Press ✎ on a card's tag row to drop a tag or add your own. What's stored is a
**diff, not a list**: your removals stick across regeneration, but a genuinely
new tag a later run discovers still appears. Storing the final list would have
frozen the card's tags forever.

### File into memory now

The consolidator runs daily, and early once more than 20 things are waiting.
That's the right cadence for a background job and the wrong one for someone who
has just taught brAIn something and wants to see it land. The Memory tab now
has a **⇪ File into memory now** button that runs the same pass immediately —
same script, same safety checks, and it says how much is waiting before you
press it.

### Removed: the removed-cards graveyard

⚙ Settings kept a list of built-in cards you had deleted, offering them back.
That belongs to a version of brAIn that shipped nine cards to every house. This
one studies your home and proposes cards *for that home*, so the way to get a
card back is to ask for it again and have brAIn build it for the house it now
knows — not to resurrect a generic one. ✕ now means the same thing for every
card: gone.

### The header carries the real wordmark

The bar drew the gable alone beside the word "brAIn" set as live text, because
the full lockup has a 132px minimum width and the bar has room for about 52px.
It now draws the actual wordmark — `BR`, the gable that *is* the `A`, `IN` —
as one piece of art, in three brand roles so a single file works in both
themes: the `B`, `R` and `N` follow the theme's ink, the roof stays azure, and
the `AI` and the signal motif always match each other.

A fifth tab and a second tab badge cost real width, so every breakpoint in the
bar moved outward and a fourth was added. The bar still holds one 48px row with
no overflow at every width from 320 to 1440 — verified by rendering it, not by
guessing.

## 1.6.0

### A new mark

brAIn's logo is now a **descendant of the BRUH Automation logo rather than a
cousin of it**. The `BR` ligature, the gable and the signal motif are lifted
unmodified from the parent mark; only the `A`, `I` and `N` are newly drawn, on
the parent's own ratios. The gable *is* the `A`.

The old mark was a neural mesh — a generic AI-brain glyph that could have
belonged to any product. It was also never really chosen: two directions
(mesh and a literal brain profile) sat in `branding/icons/` waiting for a
decision, and the mesh won by being first in the list.

What changed where:

- **The panel's top bar** draws the gable instead of the mesh. The full
  wordmark has a 132px minimum width and the bar has room for about 52px, so
  it uses the gable alone beside the word as live text — which is exactly the
  case the brand kit reserves it for.
- **The favicon** is the 512px app tile.
- **The add-on store icon and logo**, and the four
  home-assistant/brands assets, are re-rendered from the new SVGs.
- **The sidebar icon** is `mdi:home-analytics`. It was `mdi:head-snowflake`,
  picked to rhyme with a mesh that no longer exists. Home Assistant only takes
  MDI names here, so it can rhyme with the mark but never *be* it.
- **The wide lockups are 4:3, not 640×200.** The new mark is 496×342 — near
  enough square that the old banner shape either stranded it in empty plate or
  cropped it.

Every PNG in the repo is now generated by `branding/render.mjs` from the SVGs,
so the two can't drift. The retired mesh and solid-brain sources are deleted,
along with the BRUH Terminal and BRUH Insights icons and the never-submitted
`bruh_claude` brand assets — all art for things that no longer exist.

Nothing about behaviour changes.

## 1.5.1

### Fixed: the header wrapped onto a second row on a phone

The bar is meant to be one 48px row. On a phone it was two: the auth and usage
chips fell below it, outside the bar's own box, with the settings button
stranded next to them.

Two causes, both invisible on a desktop.

- **A rule left over from the old two-bar chrome still said `flex-wrap: wrap`.**
  It was written when wrapping was the intended behaviour ("the usage chips flow
  to a second row instead of clipping") and survived the 1.4.0 redesign that made
  the bar a fixed height. A fixed-height flex container doesn't grow to fit a
  second line — it just spills. The same dead rule also referenced `.brand`, a
  class the 1.4.0 markup no longer has.
- **One breakpoint could never have worked.** The full bar needs **995px**; the
  cut to icon-only tabs was at 780px, which left the 781–1023px band — tablets,
  and any half-width desktop window — overflowing by up to 212px, and still left
  775px of chip text on a 390px phone.

**The bar now sheds text in three measured steps**, each starting before the
previous layout runs out of room: the chip sentences go below 1024px (they cost
287px, more than all four tab labels), tab labels and the wordmark below 780px,
and a little more padding below 400px. Verified by rendering the bar at 24
widths from 320px to 1440px: one row, 48px, no overflow at every one.

What survives to the narrowest screen is what changes: all four tabs, the
coloured status dot, and the usage percentage. What goes is what doesn't —
"Claude · subscription", "used · resets 8:00 AM", and a wordmark that duplicates
the panel title Home Assistant already draws directly above it. Every collapsed
chip keeps its full sentence in `title` and `aria-label`.

Nothing in the bar may shrink any more, either. A shrinking chip compresses its
own text and reads as a rendering glitch rather than as "too narrow" — it fails
silently, and invisibly to a test.

## 1.5.0

### No default cards — it learns your home first

brAIn used to ship nine cards (Overview, Energy, Climate, Lighting, Security, Presence,
Media, Device Health, Automations), all enabled from the moment you installed it. They
generated before brAIn knew anything about the house, so they said generic things about a
home it had never looked at — and cost tokens doing it, on every schedule, forever.

**A fresh install now has no cards at all.** The first run studies the home — naming,
occupancy, energy, climate, device reliability — and only then proposes cards grounded in
what it actually found, each with a one-line reason citing the evidence. You pick which to
keep. Nothing generates, and the scheduler stays idle, until you do.

**There is no canned fallback.** If the home is too sparse to learn from, brAIn says what's
missing and stops. Generic cards about a house it can't read would be noise on every run,
and would teach you to ignore the dashboard.

The flow is resumable — close the panel mid-study and come back — and re-running it never
re-studies a topic it already covered, because a study session is expensive.

## 1.4.1

### Fixed

- **Answering a guess from an insight card never settled it.** When hypotheses replaced
  open questions in 1.3.0, the Memory tab was updated but the card renderer and its
  endpoints were not. Cards still showed a free-text "Answer" box — asking for an essay
  where the answer is yes or no — and the handler wrote to the old question ledger instead
  of the queue. The card looked answered while the guess stayed **open in Memory until it
  expired a fortnight later**. Cards now show the same two-tap ✓/✗, and settle the queue
  by resolving the claim's text (a card carries the text, not the id).
- **Removed the "Answered questions" section from Memory.** It belonged to the model this
  release replaced, rendered `Q: … A: …` — exactly the format removed from memory — and
  nothing populated it any more.

## 1.4.0

### Fixed: confirming a guess settled the wrong one

Clicking ✓ on the second or third pending guess settled the **first** one. Hypotheses used
the current epoch second as their id, and a study session proposes several claims inside
the same second — so they collided, and settling matched whichever came first in the file.
Ids are now unique per entry. (`knowledge_store` had guarded against exactly this; the
hypothesis queue didn't inherit it.)

### A single, compact bar

The chrome was two stacked bars plus a row of labelled buttons — roughly 110px of fixed
furniture above every view, which on the **terminal**, where each pixel is a line of
output, cost real content. It is now **one 48px bar** carrying the mark, the tabs, status
and actions.

- **Monochrome line icons**, inline SVG inheriting `currentColor`, so they follow tab state
  rather than competing with it. Azure is the only colour in the chrome and it marks only
  what is active.
- Toolbar actions are **icon-only** — the labels were noise beside four tabs.
- On narrow screens the tab labels drop and the icons stay, so all four still fit.
- **The Memory tab shows a count** when guesses are waiting. A guess nobody sees is a guess
  that expires unanswered.

## 1.3.0

### Guesses instead of questions

Insight runs no longer ask open-ended questions. They state what they **believe**, phrased
for a yes/no: *"The garage fridge is meant to run 24/7 — right?"* Two taps in the Memory
tab settle it. **Yes** files it as a plain memory line; **No** records a dead end that is
never revisited.

The cap is enforced in code, not just asked for in the prompt — a model that ignores the
budget still cannot grow the queue. Three open at once, 14-day expiry, and a claim already
proposed is never proposed again in any wording.

### Learning you can see from outside the panel

- **Logbook events.** Every new fact fires `brain_learned`, so *"brAIn learned: the hallway
  sensor drops offline around 2am"* appears in your home's timeline next to lights and doors.
- **`sensor.brain_facts_learned`** and **`sensor.brain_last_learned`**.
- **`binary_sensor.brain_waiting_on_you`** — on when a guess needs an answer, with the text
  in `pending`. This exists to be automated: a guess sitting in a panel nobody has open
  expires unanswered, but pushed to a phone it costs one tap.

### Studying on demand

- **`brain.study`** service — with a topic, or without one to study whatever has gone
  stalest. Returns immediately; results arrive in memory, not in a response.
- **`/learn`** and **`/memory`** slash commands in the terminal, where you can watch a
  session work and correct it mid-flight.

### Turn limits were too tight, and failed badly

A turn cap does not degrade — it **truncates**. A run that hits one stops mid-thought and
produces nothing parseable, so the tokens are spent and the result is lost. That made a
tight cap the most expensive setting in the add-on.

- **Study sessions**: 14 turns → **60**, timeout 10 → **30 minutes**, and
  `study_max_turns: 0` now removes the cap entirely.
- **`brain ask`**: 8 → **30** turns.
- **Automation tasks**: 10 → **30** turns. Nobody is waiting on those.
- **Voice**: 5 → **8**. Deliberately still modest — latency *is* the product for voice, and
  the cached area map means most commands take one or two turns anyway.
- Hitting the limit is now reported as hitting the limit, rather than as unparseable
  output — blaming the model for a limit we imposed sends you looking in the wrong place.
- Study prompts now tell the model to land its result if it senses it is running short, so
  a long session degrades to partial instead of losing everything.

## 1.2.0

### A Docs tab

- **A built-in guide**, next to Memory: getting started, the three tabs, how memory
  works, the command line, undo, voice, cost control, and troubleshooting. Searchable,
  with the matched term highlighted in the page. The nav, the search index, and the body
  all come from one source, so navigation can't drift out of sync with the content.
- **Removed the Memory button from the header** — it duplicated the tab.

### Fixed

- **`brain doctor` reported the Assist worker pool as failing when it was healthy.**
  The probe was pinned to port 8099, which the panel took over when the two add-ons
  merged; the panel answered — with a 404 — so the check failed against a perfectly
  working pool. It now reads the port the pool publishes instead of assuming one.
- **`brain doctor` smoke-tested CLI names that no longer exist** (`ha-entity`,
  `ha-addon`, `ha-service`, `ha-yaml-check`), producing five warnings for tools that
  were fine. It now exercises the `ha` dispatcher.
- **The generated `/config/CLAUDE.md` still documented the retired hyphenated commands,
  including `ha-backup`, which no longer exists at all.** That file is how Claude learns
  its own tooling, so a stale entry is a command it will actually try to run. Rewritten
  for the two dispatchers, and a test now fails if a retired name reappears.

## 1.1.1

- **Signing in once is now enough.** Signing in through the panel still left the
  terminal asking for a login. Credential sharing was built when Terminal and
  Insights were separate add-ons and only ran one way: the terminal's
  `ha login` published a credential the panel read. Merged into one add-on the
  panel became the primary sign-in surface, so the arrow has to point both ways.
  A single resolver now hands whatever credential exists to the CLI — used by
  both the `claude-run` wrapper and interactive shells.

  If the CLI already holds its own OAuth login it is left strictly alone: it
  refreshes that credential itself, and injecting a token over the top would
  break the refresh.

## 1.1.0

### The panel is finally one product

- **Three tabs: Insights, Terminal, Memory.** The terminal is the same ttyd
  the add-on already ran, reverse-proxied through the panel, so it is a tab
  rather than a second sidebar entry. The frame only connects when you first
  open the tab — no shell session is started for someone who never does.
- **Memory is a tab, not a dialog.** The same pane, promoted out of the modal
  it was hidden in.

### Fixed

- **The panel still said "BRUH Insights" in its header, and drew the Insights
  bar-chart glyph.** The wordmark is split across HTML tags
  (`BRUH <span>Insights</span>`), so the rename never matched it. It now reads
  **brAIn** with the neural-mesh mark. A test now strips tags before checking,
  so this class of miss can't come back.
- **Several hints told you to go run a command in "the brAIn add-on" — from
  inside brAIn.** They were inherited from when Terminal and Insights were
  separate. They now point at the Terminal tab.
- **Retired CLI names in the UI.** `ha-share-login` and `ha-memory` no longer
  exist; the panel referenced both.
- **A new agent defaulted to the name "Claude Agent"** instead of "brAIn Agent".

### Branding

- Added `logo.png` / `logo@2x.png` for the home-assistant/brands submission.
  Until that PR merges, Home Assistant has no artwork for the `brain` domain
  and shows the raw domain beside the name — which is why a fresh install
  reads "brain brAIn". Nothing in this repo can change that; see
  `brands/README.md`.

## 1.0.1

- **Fixed the panel's login failing with `su-exec: claude: No such file or directory`.**
  The CLI was looked up with the root user's `PATH` and then executed as the
  `claude` user. The binary lives at `/root/.local/bin/claude`, which is on neither
  user's `PATH`, so the lookup fell through to the bare name `claude` and su-exec
  couldn't find it. The panel now prefers the `claude-run` wrapper and otherwise
  resolves an absolute path.
- **BRUH Terminal and BRUH Insights are removed.** brAIn replaces both; their test
  suites now cover brAIn.
- **Renamed the files that were ours rather than Claude Code's**: `claude_client.py`
  is now `panel/engine.py`, and the session picker and auth helper are
  `brain-menu.sh` and `brain-auth-helper.sh`. `CLAUDE.md`, `CLAUDE_CONFIG_DIR`, the
  `claude` user, and the `claude-run` wrapper keep the name — they *are* Claude
  Code's own file, env var, user, and binary.

## 1.0.0

First release. brAIn replaces **BRUH Terminal** and **BRUH Insights**, which are now
deprecated. It is a clean install — there is no migration from either add-on.

### One add-on, one brain

- **The terminal and the insights dashboard now share a process.** They were two
  containers, which meant authenticating Claude twice, two Claude clients, two settings
  stores, and two writers racing on one memory file. Now it's one of each.
- **One ingress panel** serves everything. The panel owns port 8099 and
  reverse-proxies `/terminal/` through to ttyd (HTTP + WebSocket), so the terminal is a
  tab rather than a second sidebar entry. Port 7681 is still published for direct
  access. `enable_terminal` / `enable_insights` turn either face off.
- **The assist worker pool moved to port 8098**, since 8099 now belongs to the panel.
  Nothing hardcodes it — the integration reads the port from the endpoint file the pool
  publishes.

### Renamed

- Integration domain is **`brain`**: services are `brain.send_prompt`,
  `brain.run_task`, and the rest, including all 56 Power Tools.
- Shared state moved from `/config/.bruh_claude/` to **`/config/.brain/`**.
- Environment variables use the `BRAIN_` prefix.
- The conversation agent appears as **brAIn** in Settings → Voice Assistants.
- `assist_learning` is now just **`learning`** — it governs everything brAIn learns,
  not only the voice channel.

### The CLI is two commands

Fourteen `ha-*` scripts collapse into two dispatchers, split by what they act on:

- **`brain`** — its own faculties: `brain memory`, `brain learn`, `brain ask`,
  `brain undo`, `brain doctor`
- **`ha`** — Home Assistant operations: `ha log`, `ha reload`, `ha entity`,
  `ha service`, `ha addon`, `ha notify`, `ha share`, `ha check`, `ha context`

`brain help` and `ha help` list everything. If a pre-existing `ha` command is ever
found on `PATH`, brAIn installs its own as `hass` instead rather than shadowing it.

### Git auto-backup is gone, replaced by something narrower

- **Removed** `auto_backup`, `backup_interval_minutes`, the 30-minute commit watcher,
  and the `.gitignore` management that came with them. Versioning the whole of
  `/config` inside `/config` duplicated what a real Home Assistant backup already does,
  and the repo it grew was then swept into those backups.
- **Added an edit journal instead.** A `PreToolUse` hook snapshots a file's prior
  contents before Claude writes to it, and **`brain undo`** lists those edits in plain
  English and restores one. It records only what Claude touched, lives under `/data`
  so it never pollutes the config directory, and prunes on `edit_journal_days`
  (default 14).
- Existing `/config/.git` directories are left strictly alone. brAIn no longer writes
  to them; delete yours if you don't want it.
- The `git` binary is still installed — it's useful in a terminal.
