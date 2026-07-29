# Changelog

All notable changes to **BRain**, newest first. This project adheres to [Semantic Versioning](https://semver.org).

## 1.7.0

### Findings — memory you can act on

Memory tells you what is *true* of your home. A guess asks whether BRain has
something *wrong*. Neither has anywhere to put the third thing: something that
is **broken**.

**Findings** is a new tab, and it is a work list. A battery that died. A sensor
that has read the same value for six days. A device stuck unavailable. An
automation whose trigger entity was renamed, so it can never fire again.
Insight runs and study sessions both file them, and BRain reports a given
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
how you check what BRain changed in your house last week. Successful fixes are
written into memory too, so a later analysis doesn't rediscover a problem BRain
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
**"study…"** and BRain runs a study session instead of drawing a card: it digs
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
has just taught BRain something and wants to see it land. The Memory tab now
has a **⇪ File into memory now** button that runs the same pass immediately —
same script, same safety checks, and it says how much is waiting before you
press it.

### Removed: the removed-cards graveyard

⚙ Settings kept a list of built-in cards you had deleted, offering them back.
That belongs to a version of BRain that shipped nine cards to every house. This
one studies your home and proposes cards *for that home*, so the way to get a
card back is to ask for it again and have BRain build it for the house it now
knows — not to resurrect a generic one. ✕ now means the same thing for every
card: gone.

### The header carries the real wordmark

The bar drew the gable alone beside the word "BRain" set as live text, because
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

BRain's logo is now a **descendant of the BRUH Automation logo rather than a
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

BRain used to ship nine cards (Overview, Energy, Climate, Lighting, Security, Presence,
Media, Device Health, Automations), all enabled from the moment you installed it. They
generated before BRain knew anything about the house, so they said generic things about a
home it had never looked at — and cost tokens doing it, on every schedule, forever.

**A fresh install now has no cards at all.** The first run studies the home — naming,
occupancy, energy, climate, device reliability — and only then proposes cards grounded in
what it actually found, each with a one-line reason citing the evidence. You pick which to
keep. Nothing generates, and the scheduler stays idle, until you do.

**There is no canned fallback.** If the home is too sparse to learn from, BRain says what's
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

- **Logbook events.** Every new fact fires `brain_learned`, so *"BRain learned: the hallway
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
  **BRain** with the neural-mesh mark. A test now strips tags before checking,
  so this class of miss can't come back.
- **Several hints told you to go run a command in "the BRain add-on" — from
  inside BRain.** They were inherited from when Terminal and Insights were
  separate. They now point at the Terminal tab.
- **Retired CLI names in the UI.** `ha-share-login` and `ha-memory` no longer
  exist; the panel referenced both.
- **A new agent defaulted to the name "Claude Agent"** instead of "BRain Agent".

### Branding

- Added `logo.png` / `logo@2x.png` for the home-assistant/brands submission.
  Until that PR merges, Home Assistant has no artwork for the `brain` domain
  and shows the raw domain beside the name — which is why a fresh install
  reads "brain BRain". Nothing in this repo can change that; see
  `brands/README.md`.

## 1.0.1

- **Fixed the panel's login failing with `su-exec: claude: No such file or directory`.**
  The CLI was looked up with the root user's `PATH` and then executed as the
  `claude` user. The binary lives at `/root/.local/bin/claude`, which is on neither
  user's `PATH`, so the lookup fell through to the bare name `claude` and su-exec
  couldn't find it. The panel now prefers the `claude-run` wrapper and otherwise
  resolves an absolute path.
- **BRUH Terminal and BRUH Insights are removed.** BRain replaces both; their test
  suites now cover BRain.
- **Renamed the files that were ours rather than Claude Code's**: `claude_client.py`
  is now `panel/engine.py`, and the session picker and auth helper are
  `brain-menu.sh` and `brain-auth-helper.sh`. `CLAUDE.md`, `CLAUDE_CONFIG_DIR`, the
  `claude` user, and the `claude-run` wrapper keep the name — they *are* Claude
  Code's own file, env var, user, and binary.

## 1.0.0

First release. BRain replaces **BRUH Terminal** and **BRUH Insights**, which are now
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
- The conversation agent appears as **BRain** in Settings → Voice Assistants.
- `assist_learning` is now just **`learning`** — it governs everything BRain learns,
  not only the voice channel.

### The CLI is two commands

Fourteen `ha-*` scripts collapse into two dispatchers, split by what they act on:

- **`brain`** — its own faculties: `brain memory`, `brain learn`, `brain ask`,
  `brain undo`, `brain doctor`
- **`ha`** — Home Assistant operations: `ha log`, `ha reload`, `ha entity`,
  `ha service`, `ha addon`, `ha notify`, `ha share`, `ha check`, `ha context`

`brain help` and `ha help` list everything. If a pre-existing `ha` command is ever
found on `PATH`, BRain installs its own as `hass` instead rather than shadowing it.

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
- Existing `/config/.git` directories are left strictly alone. BRain no longer writes
  to them; delete yours if you don't want it.
- The `git` binary is still installed — it's useful in a terminal.
