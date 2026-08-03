# Changelog

All notable changes to **brAIn**, newest first. This project adheres to [Semantic Versioning](https://semver.org).

## 1.21.0

### Added

- **Undo, in the toast.** Every press that takes something off the Findings
  list — both endings, **Got it**, **Dismiss**, and either answer to a guess —
  now leaves an **Undo** button in the toast for a few seconds. It puts back
  all of it: the card, the suppression that would have stopped brAIn raising
  it again, and the line it queued for your memory document.

  It exists because those presses delete the row, which is what makes the list
  a list, and because "I fixed it" and "Wrong" sit next to each other meaning
  opposite things — so a mis-tap is not hypothetical and there was nothing to
  put back by hand. It is deliberately short-lived: this is "I pressed the
  wrong one", not a history. Once a consolidation has run, the fact is in the
  document and editing the document is the honest answer — press Undo after
  that and it says so rather than pretending.

  **Fix it has no Undo**, because it has already sent Claude at your actual
  house and taking the card back would be a lie about what was undone.
  **Remind me later** has none either: it took nothing away, and it already
  has *Bring it back now*.

- **"I fixed it" takes a note too.** The same box **Wrong** offers, for a
  different reason — nothing is being corrected, so what you type is simply
  more of the fact:

  > Replaced the CR2032 — it's a 3-monthly job on that one.

  "I fixed it" leaves brAIn knowing a problem is over. That sentence leaves it
  knowing your house. Optional, like the other one, and it lands in memory as
  part of the fix rather than as a correction of anything.

### Fixed

- **"9 things waiting" over four cards.** The Memory tab's filing queue
  counted one thing and listed another. The count read the memory inbox —
  every fact any writer has queued for the consolidator. The list read the
  facts ledger, which only holds what *insight runs discovered*, minus
  anything older than the last consolidation. So corrections, confirmed
  guesses, facts you typed in yourself, voice, study sessions and anything
  another add-on left in `/share` were all counted and never shown. Neither
  number was wrong; they were answers to different questions.

  The list is the inbox now — every row is a line the next pass will actually
  read, labelled with where it came from — and the count is the length of it,
  from the same read. **✕** on a row drops it from the queue and asks the
  consolidator for nothing, because a queued fact has never reached the
  document; the old button was asking to strike a line that, more often than
  not, had never been written.

- **Tooltips ran off the left of the screen.** They were anchored to each
  control's right edge and up to 240px wide, so anything sitting in the first
  ~236px lost its text off the side — four of the six buttons under a finding
  on a phone, and still two of them on a desktop, because the list starts at
  the left margin. They are measured and clamped to the window now, and open
  upward when there is no room below.

- **The toast was squeezed into the right-hand half of the screen.** It was
  positioned from the centre, which on a phone left it about 195px to lay out
  in — so its text wrapped to four lines inside a box with the whole width to
  spare. Nobody noticed until the Undo button had to sit beside it.

## 1.20.0

### Changed

- **One list of things waiting on you, and it's Findings.** brAIn asks you two
  kinds of question: *is this broken?* and *have I got this right?* Until now
  the second one was asked in two other places as well — inline under every
  insight card, and in the Memory tab under "Waiting on you" — while the
  badge on Findings counted neither of them. Answering a guess on the card
  left the same guess sitting in Memory looking unanswered, and a Memory tab
  badged with work you didn't have to do is how you learn to stop reading the
  badge next to it, which counts work you do.

  Guesses now sit at the top of the Findings list with the same **✓ Yes** /
  **✕ No** they always had, and the badge counts everything waiting on a
  decision. The Memory tab is what it should have been all along: a queue that
  files itself and a document to read. It has no badge, because nothing on it
  is waiting for you.

### Added

- **"Wrong" replaces "Ignore" on a finding, and it asks why.** The old button
  said what happened to the row. What people actually mean is usually *you've
  misread my house* — the sensor isn't stuck, it's a contact on a cupboard
  nobody opens — and the old button had nowhere to say so. brAIn learned that
  one sentence was unwanted and nothing about the house, so the next run made
  the same mistake in different words.

  Pressing **✕ Wrong** now opens a box for one sentence:

  > That sensor always reads on. It's not stuck.

  That goes two places: into your memory document at the next consolidation,
  and into what every future analysis is told about this home. **It is not
  treated as an instruction.** brAIn is handed what you said and works out
  what follows from it — usually a standing fact about a device or a habit,
  sometimes nothing at all — so you don't have to phrase a correction
  carefully for it to be useful.

  The box is optional: if it really is just normal here, press Send empty and
  it behaves exactly as Ignore did. The same box is offered when you turn down
  a guess, and from the action strip while you're discussing a finding in the
  chat — telling Claude there reaches that one conversation, and the box
  reaches every future one.

## 1.19.7

### Changed

- **The add-on installs from a prebuilt image instead of building on your
  machine.** `config.yaml` now carries an `image:` key pointing at
  `ghcr.io/bruhautomation/{arch}-brain`, which the add-on's CI has been
  publishing for both architectures on every change. Installs and updates
  become a download rather than a container build — on a Raspberry Pi that is
  minutes of SD-card writes replaced by a pull, and one less thing that can
  fail halfway through on a flaky network. Everyone also gets the identical
  image, rather than whatever their machine happened to resolve at build time.

  Nothing about the add-on itself changes, and no action is needed: the next
  update simply arrives the fast way.

## 1.19.6

### Security

- **The srcdoc height message had no origin check, and could not have had a
  useful one.** Every insight card renders in a sandboxed `srcdoc` iframe, and
  those all report their origin as the string `"null"` — so an origin
  comparison cannot tell one card's frame from another's, or from any other
  opaque-origin window that posts at the panel. The handler checks window
  identity against the frame it is addressed to instead, which is the rule the
  keyboard message from the terminal frame already followed.
- **An insight id containing `</script>` would have escaped the snippet it was
  embedded in.** The height-reporting script is built by interpolating the card
  id through `JSON.stringify`, which does not escape `<`. It does now.
- **The terminal handoff file was world-writable.** `/data/terminal-handoff.json`
  was chmod `0o666` so the `claude` user could read and remove it; it is chowned
  to that user and `0o600` now. Removing a file was always governed by the
  directory it sits in, which that user already owns, so the write bit bought
  nothing and granted it to everyone.
- **Path containment is now proved where the path is built.** Insight ids,
  history stamps and card names were already behind anchored allowlists that
  cannot express a separator, so nothing was reachable — but the guarantee lived
  in a regex somewhere up the call stack. `_under()` joins under a base
  directory and refuses anything that did not stay there. `_unmirror_card` was
  the one that had no allowlist at all, and its directory is under
  `/config/www`, which Home Assistant serves.

### Fixed

- **The bundle collector and the memory writer no longer put exception text in
  a response.** A bare `except Exception` was reporting whatever the Home
  Assistant read hit, and an `OSError`'s text is an errno and a path. Both log
  the detail and answer with the sentence the user can act on.
- **A streaming conversation that ended without a result event had an
  unreachable error branch.** The only way out of the request block without an
  exception is past the status check that marks the stream accepted, so the
  fallback to file IPC was always the right answer and the `RuntimeError` beside
  it could never run.

### Changed

- Every deliberately silent exception handler in the add-on now says what is
  lost when the exception is ignored — 60-odd of them, from a failed cache write
  to a client that disconnected mid-stream. They were all intentional; none of
  them said so.

## 1.19.5

### Fixed

- **`dangerously_skip_permissions: false` did nothing in the session picker.**
  `brain-menu.sh` read the flag as
  `PERMS_FLAG="${BRAIN_CLAUDE_PERMS_FLAG:-$PERMS_FLAG}"` with the variable
  initialised to `--dangerously-skip-permissions`. That failed open twice over.
  A missing `/data/.brain_env` meant "skip every prompt", so the safe state
  depended on a file existing — and `:-` cannot tell empty from unset, while
  `run.sh` writes exactly `export BRAIN_CLAUDE_PERMS_FLAG=""` when the option is
  OFF. So the dangerous fallback fired on the *normal* path: every session
  started from the picker ran with permission prompts disabled regardless of
  what the option said.

  Reachable whenever `auto_launch_claude` is off, which is what puts the picker
  in front of you. The default `auto_launch_claude: true` path was never
  affected — it takes the flag straight from `run.sh`.

  The flag now starts empty and is only ever set to what `run.sh` says. A
  security default may only fail closed.

### Changed

- **The chat says when a tool call was refused rather than broken.** Headless
  `-p` cannot prompt, so a call outside the permission set never runs — but it
  came back as a plain red Error, indistinguishable from a crash. It now renders
  amber, labelled "Not permitted", with a line saying nothing is broken, that
  asking again will not help, and that the terminal can approve a call like this
  where the chat cannot.

  The signal is the CLI's own wording, since nothing structured comes back on
  that path, so the match is deliberately narrow. A bare `Permission denied` is
  **not** treated as a refusal — that is what the kernel says when a perfectly
  permitted `Bash` call touches a file it cannot read, and calling an ordinary
  EACCES a policy decision would send people to change a setting that was never
  in the way.

## 1.19.4

### Fixed

- **"The chat works but the terminal asks me to log in, and the usage sensors are
  dead."** One fault with three faces, and 1.19.3 fixed the wrong half of it.

  Two functions resolve the same credential in opposite order. `engine.get_auth`
  (the chat) reads the panel's store first and consults Claude Code's own
  `.credentials.json` last. `brain-auth-env.sh` (the terminal) reads the CLI's
  file *first* — and decided it was usable with a prefix test,
  `startswith("sk-ant-")`, which says a token is shaped like a credential, not
  that it is one.

  So an expired CLI token won everywhere it mattered. The terminal deferred to
  it, exported nothing, and let the CLI prompt for a login while a working panel
  credential sat unread. The usage tracker walked the same order and got a 401.
  Only the chat, with its own inverted order, kept working.

  And it could not clear on its own: `run.sh` restores `.credentials.json` from
  a backup whenever the live file goes missing, so deleting the dead token
  brought it back on the next boot. The original reasoning — "worst case the
  restored token is stale and the user logs in anyway" — was wrong, because the
  CLI's file outranks every other store for the terminal.

  Fixed by checking the expiry rather than the prefix, in all four places that
  ask the question: `brain-auth-env.sh`, the usage tracker, `engine`'s
  "signed in via the CLI" status, and the backup restore, which now discards an
  expired backup instead of resurrecting it. The CLI's own login still wins when
  it is actually live — a `claude /login` done in the terminal is the most recent
  thing the person did there, and an older pasted token should not override it.

- **A refused credential no longer speaks for the ones behind it.** The tracker
  stopped at the first token it found. It now tries each store in turn and falls
  through on a 401, so a stale token in one place cannot mask a working sign-in
  in another. Anything that isn't a 401 stops the search, because that is about
  the request rather than the credential.

- **`ha selftest` names this failure directly.** It reports the CLI credential's
  expiry, and when that has passed it says so and gives the two files to remove —
  including the backup, without which the next restart puts it straight back.

## 1.19.3

### Fixed

- **Every usage-limit sensor was unavailable if you signed in through the
  panel.** The usage tracker looked for a credential in exactly one place —
  Claude Code's own `.credentials.json` — and reported `no_oauth_token` when it
  wasn't there. But brAIn keeps a credential in three places, and the panel is
  the primary sign-in surface: a panel login is stored under `/data/secrets`,
  and `ha login` shares one under `/config/.brain/secrets`. So the terminal, the
  voice listener and the fixer were all authenticated off a login the tracker
  insisted did not exist, and the sensors said "not authenticated" about the one
  thing that wasn't wrong.

  The tracker now resolves a credential the same way everything else in the
  add-on does, in the same order, and runs as root because two of those three
  stores are root-owned `0700` directories — running it as the `claude` user is
  precisely what limited it to the one store it could read.

- **A sign-in that cannot work now says which one it is.** An Anthropic API key
  bills per token and has no subscription window, so there is no utilization to
  report and never will be; that used to arrive as `no_oauth_token`, which reads
  as "sign in again" and sends people to redo a login that worked.

- **Four sensors going unavailable with no stated reason.** A new
  `Usage tracker` diagnostic sensor sits beside them and never goes unavailable,
  because its whole job is to be readable at the moment the others are not. It
  reports `ok`, or what stopped it: `no_oauth_token`,
  `api_key_has_no_usage_limits`, `http_401`, `network_error`, `stale`,
  `not_running`.

- **Stale utilization was reported as live.** A failed poll left the last
  reading in place indefinitely, so a tracker that had stopped kept answering
  with whatever it last saw. Readings now expire after two hours — the same
  window the panel already applied to the same file — and a single failed poll
  no longer blanks four working sensors, because a fresh reading is left alone
  to age out instead of being overwritten with an error.

- **The chat's context pill claimed more tokens than the window it measured
  against.** Two separate mistakes, compounding:

  The token count came from the `result` envelope, whose `usage` is the whole
  turn added up — every model call the CLI made while working, each of which
  re-sends the conversation. A turn that ran ten tools reported roughly ten
  conversations' worth of tokens. It now reads the per-call `usage` on the
  `assistant` event, so a turn reports the same size whether it took one tool
  call or thirty.

  The denominator was a table where every Opus and every Sonnet was 200K. That
  was true when it was written and is now wrong for every model the add-on
  actually runs — Opus and Sonnet went to 1M at 4.6. The window is read from the
  model's version rather than its family name, so Opus and Sonnet from 4.6
  onward are 1M, Haiku is 200K, and a model whose version can't be read reports
  a token count and no percentage rather than a percentage of a guess.

## 1.19.2

### Fixed

- **The integration page reads "brain brAIn" instead of showing a logo.** Home
  Assistant had no artwork for the `brain` domain, so it fell back to printing
  the raw domain beside the name. The artwork existed and had been staged for
  over a year for a submission to home-assistant/brands that could not be made:
  since Home Assistant 2026.3.0 that repository closes any pull request adding a
  new custom integration automatically, before a human sees it.

  What replaced it is a `brand/` folder shipped beside the integration's own
  manifest, which Home Assistant serves itself and prefers over the CDN. brAIn
  now ships one, so the icon and the wide lockup appear on the integration page
  and in the sidebar with nothing to submit and nobody to wait for.

  The logos are 341×256 and 682×512 rather than the 512×384 the add-on store
  gets. The brand spec caps a logo's *shortest* side at 256 — the staged assets
  were 512×384 and would have failed the validator that submission was aiming
  at, so they had never been in spec either.

## 1.19.1

### Added

- **"Back up Home Assistant first" now says so where it matters.** brAIn edits
  your real configuration — automations, dashboards, helpers, entities. It is
  built to be careful, it snapshots every file before it changes it, and
  `brain undo` puts them back. None of that is a backup you can restore from,
  and the gap between "careful" and "recoverable" is the one worth naming out
  loud. The notice sits on the first-run screen, above every phase of it, so
  it is on screen before brAIn is allowed to change anything — and in the
  README and DOCS for anyone deciding whether to install.

  It is styled as a caution rather than an error. Red in this panel means
  "something went wrong just now", and a permanent notice wearing it teaches
  people to read past red.

## 1.19.0

### The terminal port was a shell anyone on your network could open

`ports: 7681/tcp: 7681` published ttyd to the LAN on every install, and ttyd
was started with `--writable` and no `--credential`. Anyone who could reach
your Home Assistant box — a guest on the Wi-Fi, anything on the IoT VLAN, a
compromised device — could open `http://homeassistant.local:7681` and get a
root shell with `/config` read-write and a Claude Code already signed in to
your Anthropic account. No Home Assistant login was involved at any point.
This is the exposure Home Assistant documented in
[GHSA-gh5m-4m97-c95h](https://github.com/home-assistant/core/security/advisories/GHSA-gh5m-4m97-c95h).

Two things changed, and either alone would have been enough:

- **The port is no longer published.** Ingress never needed it — the panel
  reverse-proxies `/terminal/` to ttyd over loopback, which is what makes
  Terminal a tab. If you were using the direct port for a wall tablet,
  assign it again under the add-on's Network settings.
- **ttyd requires a password now, published or not.** `run.sh` generates one
  into `/data/terminal-credential` on first start and the panel presents it
  upstream on every proxied request, so nothing changes for anyone coming in
  through Home Assistant. The password is printed in the add-on log. The
  proxy drops any `Authorization` header the browser sends before adding its
  own, so a cached credential for the ingress origin cannot be replayed at
  ttyd.

`webui:` is gone with it — it pointed at the raw ttyd port, so the button
would now lead somewhere nothing is listening.

### An AppArmor profile

brAIn shipped without one, which cost a point of the Supervisor's security
rating and left the container unsandboxed. brAIn runs an agent that edits
files and runs commands, so a profile enumerating permitted binaries would
break the first time you asked it to do something new. This one constrains
what brAIn can do to the **host** instead: no mounting, no kernel modules,
no raw sockets, no writes to kernel tunables, no Docker socket, and no
ptracing out of the profile. **brAIn now rates 6/6 in the add-on store.**

### The Claude credential no longer rides into your backups

`/data` holds your signed-in Claude Code session, and Home Assistant backups
are unencrypted unless you opt in — then get copied to cloud storage, NAS
shares and support tickets. `backup_exclude` now keeps the OAuth credential,
the terminal password and the chat scrollback out of them. Restoring costs
you one sign-in.

### Added

- **Every option has a name and an explanation in the UI.** `config.yaml`
  documented all 35 of them in comments nobody installing an add-on reads,
  while the configuration page showed `assist_max_turns` with a blank
  description. `translations/en.yaml` moves that writing to where it is read.
- **A watchdog.** The panel is the ingress target and the foreground
  process, so a hung panel was a dead add-on that still read as "started".
  The Supervisor now polls `/api/health` and restarts it.
- `stage`, `boot` and a minimum `homeassistant` version, declared rather
  than inherited from defaults.

## 1.18.3

### Changed

- **The sidebar icon is a brain.** It was `mdi:home-analytics` — a house with a
  chart in it, which describes the Insights tab and none of the other four.
  Home Assistant only takes an MDI name in that slot, so the sidebar can never
  carry the mark itself; what it *can* do is say what the add-on is, and brAIn
  is the mind you gave the house. `mdi:brain` it is.

## 1.18.2

### Changed

- **The icon says which add-on it is.** `icon.png`, the panel favicon and every
  square brAIn shipped were the gable on its own — which is the *family* mark. It
  says BRUH and says nothing about which add-on you are looking at, so brAIn and
  BRUH Minecraft arrived in the same Home Assistant sidebar wearing the same roof.
  Every square now comes from the full lockup: the parent's `BR` ligature, the
  gable that doubles as the `A`, and `AIN` in smooth caps. Gable-only art is gone
  from the repo, and a test keeps it gone.

## 1.18.1

### "brAIn is filing memory now" that never stopped saying it

The Memory tab could sit forever on *brAIn is filing memory now — this runs
daily, and early when the queue builds up*, long after the pass it was
describing had finished and written the document. Pressing **File into memory
now** did nothing visible: no pass started, nothing failed, nothing said so.

The lock. `with_lock` opened its file descriptor and never closed it, so the
lock was held for the life of the *process* rather than the length of the
*pass*. `--once` got away with that for years because exiting releases the
lock for free — but the daemon calls `with_lock` in a loop and outlives every
pass it runs, so its first consolidation held the lock until its next one, a
day later.

Nothing about that broke consolidation, which is why it hid: one consolidator
at a time is still exactly what happened, and the merges kept working. What it
broke was the *reporting*. The lock is also the panel's only honest answer to
"is a pass running right now", so a lock held forever meant a tab permanently
announcing a merge that had finished, and a button that answered every press
with `{"started": false, "running": true}` because it believed a pass was
already in flight. The one case that still worked was a fresh start, before
the daemon's first pass had taken the lock — which is why it looked like the
terminal worked and the panel didn't.

The lock is now released when the pass ends, in the contention path too, and
the probe `flock_usable` writes no longer leaves a second lock-shaped file in
the memory directory.

### A pass says how long it has been going

"This takes a few minutes" answered a question nobody was asking. A pass is
one Claude call that rewrites the whole document, so its length depends on the
document — and what you want while watching it is not a duration but the
difference between slow and stuck. The banner now counts up: *Filing these
into the memory document now… (2m 10s)*, for the daemon's passes as well as
the button's. The elapsed time is measured on the add-on's clock and sent as a
number of seconds, so a phone whose clock is minutes off still reads right.

## 1.18.0

### A full memory document stopped filing anything, forever

Once memory.md reached its size cap, every consolidation refused itself and
nothing was ever filed again. The pass asks Claude for the whole updated
document and rejects an answer over the cap — but the rejection changed
nothing about the next attempt, so the daemon ran the identical prompt every
five minutes, got the identical over-size answer, and refused it again. The
queue kept growing behind it, which meant each attempt was asked to fit
*more* into a document already full: a loop that got further from succeeding
the longer it ran. The only symptom was a Memory tab that never moved.

An overshoot is now measured and fed back — "your last answer was N bytes
over, drop the oldest and lowest-value facts until it fits" — and only a
second overshoot fails the pass. When it does fail, it says the document is
full and names `memory_max_kb`, instead of reporting a byte count nobody can
act on.

### Memory got room to be memory

`memory_max_kb` now defaults to **32 KB**, up from 8. Voice is unaffected —
it reads the 2 KB `voice.md` distillate on every request, and always did, so
the small cap was never buying speed where speed is felt.

The insight bundle was the other half of that mistake: learned memory and the
CLAUDE.md house context shared one 4 KB budget with memory read first, so a
memory document over 4 KB was silently truncated mid-fact *and* a document
that filled the budget starved the house context entirely. Each gets its own
now, sized so a full memory document arrives whole. When the bundle is over
budget the context is trimmed rather than dropped — dropping it threw away
everything brAIn has learned about the home to save a few hundred bytes.

### Background passes can label themselves again

The run-source ledger is written by the panel (as root) and by the
consolidator and study watcher (started as the `claude` user). Root created
it first, so every daemon claim failed with `Permission denied` and ran
unlabelled — defeating the 1.17.0 change that keeps machine conversations out
of your Chats rail and away from `adopt`. It is created claude-owned up
front. The failure also printed a bash error on every pass despite the
library being documented as silent: `>> file 2>/dev/null` silences the
command, not the shell's own "cannot open" message.

### "File into memory now" logs where you were told to look

A button-started pass had its output captured and discarded unless the script
exited non-zero — while the failure it reported told you to go read those
lines in the add-on log. They now stream there as the pass writes them, the
same as the daemon's.

## 1.17.0

### "File into memory now" actually files

The consolidator gave Claude 120 seconds to rewrite the whole memory
document plus the voice distillate. On a document with anything in it that
was a coin flip, and losing it looked identical to a broken login: `timeout`
killed the CLI, the pass logged *"Claude invocation failed (not
authenticated?)"*, the queue stayed exactly where it was, and the daemon did
it again five minutes later, forever. The one line explaining it sent you to
re-do a sign-in that was fine.

A pass now gets 480 seconds — what an insight run gets, for the same reason —
and says what actually went wrong: a timeout says it timed out and names the
setting to raise, and any other failure carries Claude's own last line of
stderr instead of a guess. The Memory tab shows that reason too, where you
come back to look, rather than only in a toast that has already gone.

The button also stops waiting for the pass it starts. A consolidation takes
minutes; the request carrying it timed out long before it did, which is why
pressing the button appeared to do nothing and then said it had failed while
the pass was still running. It now returns straight away, the tab reports
progress off the consolidator's own lock, and pressing it again while a pass
is in flight joins that one instead of racing it.

### The Chats rail is your chats

brAIn runs Claude Code in `/config` for voice, for automation tasks and for
filing memory, and Claude Code files all of it in the same place your own
conversations go. So the rail filled with machine prompts — forty copies of
the consolidator's opening line — with your own chats somewhere underneath.
Worse, switching back from the classic terminal adopted *the most recent
conversation*, which on a busy house was routinely the consolidator's.

Every background run now claims its session before it starts, so each row
says whose it is and a chip row picks between them. **Yours** is the default,
Voice / Automation / Memory / Study are one press away with a count each, and
only faces that have actually run in your house are offered. Switching back
from the terminal only ever picks up a conversation of yours.

### A quieter log, and a terminal that stays put

The panel logged a line per request, and an open panel polls: thousands of
identical `200`s pushing the one line that explained a failure off the top of
the page. Successful polls are now silent, anything that failed is logged as
a warning, and `log_level: debug` turns every request back on. ttyd's own
notice-level chatter goes the same way.

Most of that chatter was a real bug: nothing pinged the browser half of the
terminal's websocket, so on an idle terminal no bytes crossed it and the
proxy in front — ingress, or Nabu Casa remote — closed it as idle after a
minute or two. ttyd killed the session's process, the client reconnected, and
it repeated for as long as the tab was open. Both halves are pinged now, so a
terminal left open stays connected.

## 1.16.0

### Your conversations, in a rail

On a screen wide enough for it (1100px and up), the chat tab grows a column
of its own listing every conversation in `/config` — whichever face made it —
with **＋** to start a new one and the current one marked rather than hidden.
Picking one resumes it, exactly as the ⋯ menu already did.

Below that width nothing changes: 248px of conversations is most of a phone,
so the rail isn't rendered and **⋯ → Conversations** is still the way in.
Nothing is reachable only from a screen you don't have.

### Which model, and how full

Under the composer, quietly: the model that is actually answering, and how
much of the context window the conversation is occupying — `42k / 200k
context · 21%`, turning amber past 80%.

The token figure is the CLI's own report of what it sent on the last turn,
and what it sent *is* the conversation so far, so it is a measurement rather
than an estimate. Cache reads count, because a cached prompt still occupies
the window; it is only cheaper. A model we have no published window for
reports its token count and no percentage, because a percentage of a guessed
denominator is worse than none.

### A new chat does not lose the old one

"Start a new chat? This one is cleared and Claude forgets its context" was
overstating it. Claude Code keeps the conversation, it stays in the list, and
you can reopen it — so the prompt now says what is actually true.

### Dismiss, next to Ignore

A finding can now be cleared off the list **without** teaching brAIn
anything. **Ignore** settles it: a line into memory, and the analyst is told
never to raise it again. **Dismiss** just deletes the row, so the next
analysis is free to find it again — which is what `forget` in the store has
always done, and it had no button.

The tooltips are shorter too. Ignore's ran to two clauses and a caveat about
wording, next to five other buttons nobody was going to stop and read.

### Fixed

- **The last line of an answer is no longer flush against the composer.**
  Scrolled fully down, the chat log left 8px, which reads as the message
  being cut off rather than as the end of it.
- **The iPhone home indicator no longer overlaps the chat.** The safe-area
  inset was on the composer, which stopped being the bottom-most element when
  the model line was added below it. It is on the container now, which is
  always last whether that line is showing or not.

## 1.15.0

### The full-screen terminal left the bar cut in half

Going full-screen and coming back gave you a sliver of a top bar — and it
stayed a sliver on every other tab, until a reload.

`.topbar`'s height *is* `--bar-h`, and the panel writes `--bar-h` from the
bar it just measured. That is stable at rest and wrong exactly once: the
immersive terminal sets it to `0`, so on the way back out the bar is visible
again but pinned to zero height by the panel's own inline value. It renders
clipped, the next measurement reads the clipped height, and that becomes the
new truth. Measured on a desktop viewport, the 56px bar came back as **1px**.

Measuring now clears the override first, so the bar is always measured
against the stylesheet's value for the current layout rather than against the
previous measurement — and a zero is never written, because the CSS class
already says zero and an inline one would outlive the class that justified
it.

### The findings buttons say what they do, in fewer words

*"Not a problem here"* became **Ignore**, and *"I've fixed it"* became
**I fixed it**. A row of four decisions is read at a glance or not at all,
and the sentences were being skipped. What each ending *teaches* brAIn is
still there, in the tooltip, which is where an explanation belongs. Ignore
also gets a glyph — every other button on the row had one, so the one
without read as the odd one out rather than as the quiet one.

### Answered is gone, because memory is the record

Settling a finding writes a plain fact into `memory.md` and deletes the row.
The **Answered** filter then listed those answers again, which put a pile of
dismissed cards next to a work list that is supposed to empty — and invited
you to treat it as the record when memory already is. It and **Everything**
are both gone; two chips remain, the work and what is waiting.

The settled ledger itself is untouched and still doing its job: it is the
dedup index that stops the analyst re-raising next week what you answered
today. It is simply not a view any more.

### Also

- **The counts we advertise are now tested** (`tests/test_documented_counts.py`).
  "36 native tools" and "65 registry-management services" are derived from
  `TOOL_IMPLEMENTATIONS` and the `PowerTool(...)` registrations, and every
  present-tense claim in the repo is checked against them. They had gone
  stale twice; the site said 56 for six releases after nine more shipped.
- **The docs screenshots are reproducible** (`tests/manual/demo_panel.py`).
  It boots the real panel against a seeded demo home with Claude stubbed
  out, so the pictures on bruhautomation.com stay the actual product.

## 1.14.1

### The guide opens with what brAIn is for

The Docs tab opened by describing what brAIn is made of. It now opens the
way the READMEs and bruhautomation.com do — *your house already has nerves,
now give it a brAIn* — followed by what it actually does: sees the whole
system and can change any of it, keeps a memory you can open and edit,
reachable as a conversation agent or a chat interface or native Claude Code,
and callable from your own automations so the house can ask for help before
you notice anything is wrong.

Five surfaces describe this add-on — two READMEs, `DOCS.md`, the Docs tab and
the website — and they had drifted apart. They now open with the same words.

Text only. No behaviour, no options, nothing to reconfigure.

## 1.14.0

### Switching to chat brought a fraction of the conversation

The measurement, on a real transcript: 1844 replay events, of which 1701
were tool calls and their results — **92%**. The window that carries a
conversation across is 400 events, and it was filled newest-first, so it
carried **3 of the 17 things the person had said** and 24 of 126 replies.

Switching faces showed you the last few minutes of tool chatter and almost
none of the conversation, which is exactly what "not all the messages come
over" looks like, because they hadn't.

The budget is now spent on the conversation first — every word either party
said, then the most recent tool calls with whatever is left. On that same
transcript it now carries **17 of 17 and 128 of 128**. A call and its result
are also kept or dropped together: half a pair renders as a spinner that
never stops, or as nothing at all while still costing a slot.

### The insight card gave its title away to its buttons

The card head was one row: icon, category, title, and **six** icon buttons.
The buttons don't shrink, so on a phone they took about 250px of a 390px
card and left the words 120px — which the category (which wraps) spent on
three lines while the title (which truncates) was cut to "Upstair…".
Backwards: the eyebrow is the part you can afford to lose.

- The title gets the row, and wraps to two lines instead of truncating.
- The category is one line, and it is the one that gives way.
- **⤢ Expand** stays on the card, because it is the only button that acts on
  what is on screen rather than on the card's definition. Regenerate, Edit,
  Give feedback, Add to dashboard and Delete moved into **⋯**, where each of
  them has its name and a line saying what it does — which a row of six
  unlabelled glyphs never had room for.

Measured across seven widths by `tests/manual/measure-cardhead.mjs`, which
fails on a truncated title, a category that wraps, an overflowing head, or
any target under 40px.

### Space back above the first card

- **Tag filters were four rows.** Sixteen chips wrapping is most of a phone
  screen spent on a filter, before the first card. They are one row that
  scrolls now, with **✦ All** pinned to the left so clearing a filter is
  always one press.
- **The ask hint was a four-line paragraph** teaching three features. It is
  one line naming the second verb; asking is what the placeholder already
  invites, and "＋ Make recurring" is a button on the card it applies to.
- **The top bar's ⟳ is gone.** It was an unlabelled circular arrow that read
  like a page reload and in fact queued a Claude run for **every card you
  have** — minutes of work and a real bite out of the usage the pill beside
  it was reporting. Cards run on their own schedule, and **⋯ → Regenerate**
  does one on demand.

### The docs tab could be zoomed and left that way

Not the docs — the search box. iOS Safari zooms the whole page in when you
focus a text control whose font is under 16px, and does **not** zoom back
out when you leave it; inside an ingress iframe that strands the panel at
some arbitrary scale with the bar off screen. The docs search box was
14.4px. So were most of the dialog inputs; the chat composer was 16px
because somebody had already hit this once and fixed it in one place.

Text controls are now 16px on touch devices, asked for once rather than per
control, so anything added later is covered by having been added. Pointer
devices keep the density they were designed at. Long paths in inline code
also wrap now instead of pushing the column sideways.

### The guide describes the buttons that exist

It still taught six icons on a card and a Refresh all in the bar.

## 1.13.0

### Findings end, instead of piling up

"I did it" beside "Not a problem" looked like two ways to make a card go
away, and both of them left it lying there under a filter forever. That is
two problems in one: you couldn't tell which button to press, and pressing
either one didn't actually finish anything.

A finding now **ends**, and ending it deletes the row. Every ending does the
same three things:

* the answer goes into `memory.md` as a plain fact about your home
* the wording is remembered, so the same problem is never reported at you
  twice
* the card is gone

The two buttons say what each one *teaches brAIn*, which is the only
difference that ever mattered:

* **✓ I've fixed it** — it was a real problem and it's sorted now
* **Not a problem here** — it was never a problem; this is normal in this
  house

An automated fix is the third ending, and it works differently on purpose:
the card **stays** and turns green with what brAIn changed and which files
it touched. It altered something in your house, and news you haven't read is
not settled. **✓ Got it** clears it once you have — no second memory line,
because the fix already wrote one when it made the change.

The **Dismissed** and **Fixed** filters are gone. In their place, **Answered**
is one line per ending — what it was, which answer you gave, when — with
**Let brAIn raise it again** if you change your mind. That press stops the
suppression and nothing more: nothing comes back on its own, the next
analysis is simply free to find it, and if it has genuinely stopped
happening, nothing does.

Dismissals you made before this release are folded into the same record at
startup, so nothing you had already waved off comes back.

### The terminal switch carries the conversation

Switching between Chat and Classic changed the renderer and left the
conversation behind, which made two faces of one Claude Code feel like two
rooms. Going one way there was a separate **Continue in the terminal**
button that did carry it — so the switch and the button did different things
and neither of them was obviously the one that moved you.

Now the switch is the only control, and it carries either direction:

* **To Classic** — the chat releases its session and the terminal opens
  already inside that conversation.
* **Back to Chat** — it picks up whatever the terminal was last doing,
  transcript and all.

That second half needs explaining, because the terminal's Claude is not ours
and has no API to ask. What it does leave behind is its transcript, which
Claude Code writes as it goes — so the most recently written conversation in
`/config` *is* what the terminal was last on, and that is what gets resumed.

One honest limit: only one Claude Code process can own a conversation at a
time, so this is a hand-off, not a mirror. The face you leave lets go and the
face you arrive in takes over with the full history. Your shell in the
terminal is never killed to make that happen — it is your shell — and
switching is refused mid-answer rather than throwing away an answer being
written.

### Three fixes for things that only show up on a phone

* **The floating buttons could vanish for good.** Raising the software
  keyboard hid them — including ⤢, the way back out of a folded bar — and
  they only returned when something happened to notice the keyboard had
  gone. On iOS, that something frequently never fired, and the terminal was
  left with no visible controls at all. They are never hidden now: the
  escape hatch may not be behind the state it escapes from.
* **The slash palette stopped filling in.** Typing past the end of the
  filtered list left the highlight pointing at a row that no longer existed,
  and Enter/Tab silently did nothing from then on. The highlight is clamped
  at the moment it's used.
* **Two scrollbars in one pane.** The page scrolled behind the terminal, and
  the memory editor scrolled inside its own already-scrolling box. The
  terminal tab locks the page behind it, and the editor is one scroller.

## 1.12.1

### Memory was never being consolidated at all

This is the actual reason memory stopped updating, and it is embarrassing.

The consolidator takes a lock so two passes can't rewrite `memory.md` at
once. It took it with `flock -w 600` — and `-w` is **util-linux's** flag.
This add-on runs on Alpine, whose `flock` is BusyBox's, and BusyBox accepts
only `-sxun`. Handed an option it doesn't know, BusyBox prints usage and
exits **1** — which is the exact status `flock` uses for *"the lock is
held"*.

So every consolidation pass, from the daily daemon and from **File into
memory now** alike, failed to take a lock that nobody held, decided another
pass must be running, and did nothing. For weeks. The inbox grew, the
document went stale, and the only trace was one line in the add-on log.

The guards added in 1.11.2 were real, but they sat behind a gate that never
opened.

Now: only the portable flags are used. Waiting is `flock -n` polled, and
whether flock can be used at all is **probed with the same flag the real
call uses** — so "flock works here" means the exact thing we're about to do
works here. If it genuinely can't lock, the pass runs anyway and says so,
because refusing forever is the worse failure. Real contention is still
reported as contention.

Any facts that piled up while this was broken are consolidated on the next
pass — nothing was lost, it was queued.

### ...and a wedged consolidator is now visible

The reason this hid for weeks is that nothing on any screen said anything:
the queue just sat there looking like a queue. The Memory tab now says so
when facts have been waiting appreciably longer than the daily pass — with
what to try, and where to look if that doesn't clear it.

It deliberately doesn't detect *this* bug. It detects the symptom every
cause of it shares: facts waiting, and no pass landing.

## 1.12.0

### The two terminals are now one terminal with two faces

Chat and Classic already ran the same Claude Code. What they did not do was
let you move a conversation between them, which made them two places rather
than two views.

**⟲ lists every conversation** in the project directory — started in the
chat, started in the terminal, it makes no difference — with its opening
line and when it was last touched. Pick one and it **replays into the chat
pane** and carries on. Not a blank box with a promise that Claude remembers:
the actual conversation, because Claude Code stores it in the same message
shapes it streams, so it renders through the same code as a live turn.

**Continue in the terminal** now opens the terminal *inside* the
conversation rather than handing you a command to paste. The chat releases
its session, leaves a handoff for the terminal's launcher, and — if the
terminal is already attached — opens it in a new tmux window there and then.
A terminal that has never been opened still comes up in the right
conversation, because the handoff is a file its launcher reads rather than
keystrokes typed at whatever happens to be in front. It expires after ten
minutes, so a restart tomorrow does not silently reopen today's chat.

### Less in the way

Two pieces of clutter that arrived with the features above.

**The chat had five buttons floating over your output.** Five translucent
squares stacked on top of the text you came to read is exactly what this
view exists to get away from. There are two now: **⤢**, which keeps its own
place because it is also the way back from a folded bar, and **⋯**, which
holds New chat, Conversations, Session details and the switch to the classic
terminal. Things you do occasionally, and decide about once.

**The top bar stopped saying the same thing twice.** "Usage budget reached"
was a chip sitting immediately beside a usage pill already reporting the
very number it was about — and on a phone the pair wrapped the bar onto a
third row to do it. The pill carries that state itself: its dot goes
warning-coloured, and pressing it says plainly that automatic insights are
paused, what the budget is, and when the window rolls over.

What is left beside the pill is the one thing a press can undo: **Auto
insights off**. In the ordinary case the bar is back to two rows on a phone
— status and actions, then the tabs.

### Findings you can argue with, and put off

A finding had three answers: fix it, I did it, or never mention this again.
Two things were missing, and both are things people actually want to say.

**💬 Discuss** hands the finding to the chat with everything it knows about
it — the detail, the suggested fix, the entity, the severity — and asks
Claude to look into it and say plainly whether it really is a problem *here*.
The prompt tells it explicitly not to change anything: "explain this to me"
and "go change my house" are different consents, and **Fix it** is still the
only button that gives the second.

So that button travels with the conversation. While you are discussing a
finding, a strip above the composer names it and keeps **Fix it**, **I did
it**, **Later** and **Not a problem** one press away — because agreeing to a
fix at the end of a conversation about it should not mean going back to the
other tab to find the card again. It survives a reload, since a conversation
is not over because the page reloaded.

**⏰ Remind me later** takes a finding off the list for an hour, until
tomorrow, next week or next month. It is deliberately *not* a status change:
dismissing is permanent and is fed back into every future analysis so the
same non-problem is never raised again, and using that for "not right now"
would quietly throw away a real problem you meant to come back to. The
finding stays exactly as open as it was — it just stops asking. It sits
under a **Later** filter while it waits, with the date it returns and a
"bring it back now", because something you cannot find has not come back.

*Also fixed on the way past:* any control other than a top-bar chip that
tried to open a popover had it closed again by the same press, because the
dismiss-on-outside-click listener only recognised the chips as legitimate
openers.

### The palette knows about `brain` and `ha`

Type **/** and you get Claude Code's commands. Type **brain** or **ha** and
you now get brAIn's own — `brain memory add`, `ha reload`, all of them, with
the same descriptions and argument hints the dispatchers print.

The list is parsed from `brain help` and `ha help` rather than written down
here, so a subcommand added to a dispatcher appears in the palette without
anything in the panel being touched. It gets out of the way once you start
typing arguments.

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
