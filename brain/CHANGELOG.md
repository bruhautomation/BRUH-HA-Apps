# Changelog

All notable changes to **brAIn**, newest first. This project adheres to [Semantic Versioning](https://semver.org).

## 1.43.0

**1.42.0's last two steps did nothing.** It shipped the proposal lifecycle —
`proposed → trialling → accepted | declined` — and the two that make it mean
anything were unimplemented. "Try it for a week" set a status and an end date,
and nothing ever looked at the week: `proposals.trial_due` and
`proposals.record_trial` had no caller outside their own tests. Accept recorded
a status, wrote a memory line and deleted the row, and **the automation was
never created**. A feature that does nothing is indistinguishable from one that
is broken, and both of these read from the tab as the second.

### Added

- **`panel/trials.py` — a trial is a replay of the week you lived through,
  graded against what you actually did.** There is no live-event subscription
  behind this and there does not need to be: `shadow.replay` already says when
  the automation would have fired over a window the recorder holds, and
  `panel/routines.py`'s ledger already says what a *person* did in it. So the
  whole trial is arithmetic over two things that exist, and nothing here
  fetches, writes or decides — the split `baselines.py`, `closures.py` and
  `thermal.py` keep.

  It is re-run on **every checks pass** rather than once at the end. A replay
  costs one history fetch, so *"three days in: it would have fired three times
  and you did the same twice"* is free, where a report that only exists on the
  seventh day is a week of a card saying nothing. When the week is up the row
  stays `trialling` with its result attached: ending a trial is a person's
  press, which is exactly what `record_trial` already refused to do for itself.

  **Three verdicts, and the third is the one worth having.** *Agreed* is a
  press to the same state within `AGREE_WINDOW_S` of the firing. *Disagreed* is
  nothing happening, which is weak evidence either way and says so by its name.
  *Contradicted* is the person putting the entity to the **opposite** state in
  that window — they would have undone it, and folding that into "disagreed"
  reports a change somebody actively did not want as merely unproven, which is
  `auto.overridden`'s argument one layer earlier. Each firing lands in exactly
  one bucket, decided by the **nearest** press, so a verdict cannot depend on
  the order the ledger happens to be in.

  **A refusal is carried, never zeroed.** *"It would never have fired"* and
  *"brAIn cannot replay this"* are different answers and only one of them is
  about the automation. The same holds for an action this cannot read as one
  entity going to one state — `routines.service_for` is the authority on that,
  so the reader cannot drift from the producer that wrote the config.

- **`panel/automation_writer.py` — a yes becomes an automation, and it can be
  taken back.** This is the first code in the add-on that changes `/config`
  **without a Claude run and without somebody pressing Fix it**, so it is the
  narrowest thing that can do the job.

  **Snapshot first, append never rewrite.** The snapshot goes into the same
  edit journal `scripts/brain-edit-snapshot.py` writes, in the same line shape,
  so `brain undo` reverts this exactly as it reverts a Claude edit — there is
  no second undo mechanism to keep true, and `tests/test_automation_writer.py`
  drives the real shell script rather than asserting a shape it might not read.
  The append is *text*: `automations.yaml` is somebody's file, with their
  ordering, their comments and their quoting, and a writer that re-serialised
  the whole list would hand back a diff nobody asked for on every accept. The
  test asserts the prefix of the file is **byte-identical**, not merely that it
  still parses.

  **Four refusals, each a sentence rather than a guess.** A **protected
  entity** is asked about here because `protected_entities` is enforced at the
  MCP server's `call_service` and a YAML file the panel writes is not one of
  its callers — same patterns, same wildcards; an **area or device target** is
  refused outright while the list is non-empty, because resolving one needs
  registries this has none of and a protected entity reached through its area
  is the bypass. A house with no `automation: !include automations.yaml` keeps
  its automations somewhere this cannot find, and appending to a file Core does
  not read is a change that silently does nothing — the refusal **names the
  line it looked for** rather than guessing at another file. A file that is not
  a list of automations is somebody's config in a shape this does not
  understand. And a duplicate `id` is a config Core refuses to load, where a
  duplicate `alias` is a house where nobody can tell the two apart.

  The `alias` is added at write time rather than in `routines.to_config`, which
  deliberately carries none: that config is what `proposals.key_for` hashes,
  and a title holds the entity's name and the time, either of which can move
  without the change moving.

- **Accept writes it, reloads, verifies, and only then settles.** Three claims,
  and they were being reported as one. *The file was written* is the writer.
  *Home Assistant read it* is `automation.reload`. *The automation exists* is a
  state in Core — and only the third is what somebody pressing Accept meant. A
  `mode:` Core does not recognise, a trigger a custom integration owns and has
  not loaded, a read-only `/config`: each of those leaves a file on disk and a
  reload that returns 200 and no automation. The same distinction BRight draws
  between a `play_media` call being accepted and a speaker making a sound.

  Any of the three failing puts the file back, reloads again and returns a
  **409 with the sentence**. A yes that could not be honoured is not a yes that
  was recorded: the proposal is exactly where it was, with no memory line and
  no settled key.

  **Undo reverses all three effects or says which one it could not** — the
  file, the reload, and the row (`proposals.reopen`, keyed on the original
  `ts`, refusing over an occupied one and dropping the settled key as
  `unsettle` does), plus the queued memory line. A trial that was running when
  it was accepted comes back as a *proposal* rather than as a trial whose week
  has since passed, because "try it for a week" is a promise about the next
  seven days. And an undo that claimed success while the automation was still
  running would be worse than one that reported the failure, so `undone` is all
  three or none.

  The settled entry carries the `automation_id` and `entity_id`, because
  "accepted" and "accepted, and here is what it became" are different claims
  and only the second can be checked against the house six months later. The
  change is announced as **its own message** rather than as a finding — nothing
  is wrong, there is no severity and no button on it that could end anything —
  and it is sent rather than held, which is the one sender here with somebody
  awake by construction. `journal.OUTCOMES` gains `applied`.

- **`ha_data.call_core_service` and `ha_data.entity_exists`.**
  `ha_data.call_service` is `brain.*`-only by construction — it hardcodes the
  domain, which is what stops a caller turning a request for brAIn's own
  service into a request for anybody's. The general one has exactly one caller,
  and both halves of its path are checked against the shape a service name can
  have, because pasting a name off the wire into a URL is what made
  `history_params` a partial SSRF. `entity_exists` reads a 404 as *the answer*
  and anything else as an error: "Core did not answer" and "Core says it is not
  there" are different claims.

- **`/api/diagnostics` reports trials apart from results.** "3 trialling, 0
  with a result" is the exact shape of the failure this release fixes, and it
  is unreadable from a single count.

### Panel

- **A trial that reports nothing is a trial nobody can tell is running, and
  that is what the card showed for a release.** The Proposals tab now says
  where a trial has got to and what the week has found, in words somebody
  would use: *"Day 3 of 7 · would have fired 6 times · you did the same on 4
  · nothing happened on 1 · you did the opposite on 1"*. Every number comes
  off `trial_result` — `firings` is capped at 50 where the counts are not, so
  adding the list up in the browser would be a second answer that goes wrong
  in exactly the week busy enough to matter. The three states a trial can be
  in are three different sentences, because they are three different answers:
  graded; **not graded yet**, for a row that started trialling since the last
  checks pass, where zeros would read as *"it would never have fired"*; and
  **refused**, carried whole, which is about brAIn rather than about the
  automation — and that card keeps its buttons, since a trial that could not
  be graded is still a person's decision and the replay evidence is still on
  it. Past `trial_ends_at` the line becomes *"Trial over:"*, the row stays on
  the list (ending one is a press) and Accept becomes the primary action. The
  "re-graded every few hours" sentence appears once for the list rather than
  once per card, because three open trials would otherwise carry it three
  times and it would be read on none of them.

- **A yes that Home Assistant would not honour is read on the card, not in a
  toast.** The 409 carries a sentence and the whole list with the row still on
  it, so the panel re-renders from the payload and puts the refusal *where the
  buttons were* — the arrangement the decline reason box already uses, for the
  same reason: what you are reading about has to stay on screen while you read
  it. Dismiss brings the buttons back. A yes that landed takes the row away
  and says *"Added ‹name› to your automations"* with **Undo** on the same
  toast every finding ending uses; undoing reverses the file, the reload and
  the row, and when it cannot, the toast says which half failed in the
  server's own words — an "undone" over an automation still running would be
  worse than the failure it hid. Undo is a 44px target on touch: it takes back
  a change to somebody's house and the offer expires with the toast.

- **`tests/manual/measure-proposals.mjs` drives all of it** against the real
  renderer behind a stubbed fetch, with a proposal in each trial state. It
  fails on a missing progress line, on the store's vocabulary reaching the
  card (`contradicted` is nobody's word), on an ungraded trial rendering
  zeros, on a refused accept that does not leave its sentence on the card, on
  an accepted one that stays on the list or offers no Undo, and on anything
  under the touch floor at 390, 430, 768 and 1200px.

### Fixed

- **"Nothing brAIn writes is ever enabled without a trial" was not true, and the
  docs said it in four places.** The panel has always offered Accept on a
  `proposed` row and `decide` takes any open status, so a person could skip
  the week — which is right: it is their house and their yes, and a
  mandatory trial would be the same paternalism as a required reason box.
  What must never happen is enabling *on its own*, and every doc now says
  exactly that and what skipping the trial costs (the evidence). The store's
  own docstring also still described the 1.42.0 trial that never ran —
  "evaluating against live events… within three minutes" — and now describes
  the one that does.

- **A protected entity is dropped at the producer as well as at the writer.**
  `routines.mine` now takes the patterns (read by the caller — the miner stays
  pure) and skips a habit on an entity `automation_writer.apply` would refuse.
  The writer has to refuse one, being the last gate before `/config`, but a
  card offering something brAIn will not do is a wasted no.

## 1.42.0

The capability map's **shadow runner**, and the fifth kind of knowledge it
exists to serve. Everything ranked above the forecasts on that map stands on
one thing brAIn could not do: try a change without committing the house to it.

### Added

- **`panel/shadow.py` — what an automation would have done.** Takes an
  automation, evaluates its triggers and conditions against the **recorded
  past**, and reports when it would have fired and what it would have done. It
  calls no service and touches nothing. *"Over the last 30 days this would have
  fired 26 times; on 4 a condition would have blocked it."*

  **The scope is four trigger kinds and the refusal is the feature.** `time`,
  `state`, `numeric_state` and `template` are what the recorder can
  reconstruct. Anything else is refused **whole**, naming the kind — never
  trimmed to the replayable subset, because reporting "this would have fired
  twice" about an automation whose webhook fires forty times a day is a
  confident wrong number that reads exactly like a right one, and it is the
  number somebody would decide on.

  A template is replayed only when every entity it names is in the timeline,
  and only a named set of Home Assistant's own helpers is allowed. Rendering
  against a half-built world gives a blank; a blank reads as `unknown`, which
  reads as `false`, which is a confident *no*.

  The details that decide whether a number is right: `for:` is a promise about
  a stretch, answered from the **next** sample rather than this one;
  `numeric_state` is a **crossing**, never a level; a template fires on the
  **edge**, not on every moment it stays true; and an area or device target is
  recorded and deliberately **not** resolved, because expanding one needs the
  registry as it was at the time.

- **`panel/proposals.py` — what could be better.** The fifth kind of knowledge,
  with its own store and its own tab: a list of things you might want sitting
  beside a list of things that are broken makes both worse. The lifecycle is
  `proposed → trialling → accepted | declined`, and **nothing brAIn writes is
  ever enabled without a trial**.

  Its decisions are refusals: the key is the **change** and not the sentence,
  so a miner that rewords its explanation is still offering what you declined;
  a declined key is remembered forever while the row is prunable; past
  `MAX_OPEN` the tab **refuses** a new proposal rather than pushing an
  unanswered one out; `record_trial` does not end the trial, because a store
  that ended one by writing its own result would be deciding the thing it is
  reporting on; and a decline **with** a reason is a fact about the house while
  one without is a preference about a suggestion, which memory has no use for.

- **`panel/routines.py` — what you already do by hand, and the offer it earns.**
  A store with a surface and nothing filling it is a feature that does nothing,
  which is indistinguishable from a broken one, so the first producer ships
  with it. The checks pass keeps the changes a **person** caused — the second
  deliberate exception to `actions.py` persisting nothing, and the same
  narrower claim `override_ledger` makes: tens of rows a day, not the timeline.
  An automated move is kept as **one timestamp per key**, because the only
  question asked of it is *does something already do this*.

  Five floors, each asserted in `tests/test_routines.py` against the case it
  must NOT fire on before the case it must find. **Six separate days**, not six
  presses — twelve presses on one Monday is one Monday. **A share of the days
  it could have happened on**, which is the denominator `auto.overridden`
  shipped without: six times in a fortnight is a habit and six times in two
  months is a coincidence, and a count reports both identically. **A time
  rather than a stretch of evening**, on `rhythm.py`'s own circular arithmetic,
  because a straight median of times either side of midnight is noon. **It has
  to still be happening.** And **nothing may already do it**, or the proposal
  is `auto.conflict` written on purpose.

  `every day` has to be earned **twice**, once on each half of the week: a
  habit on ten weekdays and one Sunday clears the whole-window share
  comfortably, and calling it daily builds a trigger that fires on two mornings
  nobody wanted it. The cost is that a genuinely daily habit reads as
  `weekdays` for three weeks, which is the cheaper mistake and is asserted
  rather than described.

  What it writes is a plain time trigger and a weekday condition when the habit
  has one — never a condition it did not measure. The config carries **no
  `alias`**, because `proposals.key_for` hashes it and a title carries both the
  entity's name, which a rename moves, and the time, which the median moves by
  a minute: either would re-offer at 18:41 what was declined at 18:40. The
  trigger time is rounded to five minutes for the same reason, and because it
  then reads like a time somebody would have chosen.

- **The API**: `GET /api/proposals`, `POST /api/proposal/{ts}/trial`,
  `POST /api/proposal/{ts}/{accept,decline}` and `POST /api/replay`. A decline's
  note goes through the same `_submit_memory` path a finding's "Wrong" uses, so
  an answer teaches the same thing whichever list it was given on. A replay
  refusal is a **422 with the reason in words**, because "it would never have
  fired" and "brAIn cannot replay this" are different answers.

  Both doors — the Replay button and the habit miner offering a proposal — go
  through one `_replay_config`, because "how often would this have fired" asked
  two ways is two answers waiting to disagree.

- **`/api/diagnostics` carries the miner and the store.** A tab with nothing on
  it reads the same whether the miner found no habit or the ledger has been
  empty since March, and "I could not look" versus "there was nothing" is the
  distinction every check in this add-on carries. The empty state names the
  floor rather than leaving somebody to wonder whether it is broken.

  **The replay does not use `ha_data.get_history`.** That helper downsamples
  numeric series into hourly buckets, drops `unavailable`/`unknown` and caps how
  many changes it keeps — correct for handing a model a summary, fatal here. A
  replay counts **edges**, and an hourly bucket has already thrown away the
  moment a sensor crossed its threshold.

### Fixed

- **The image did not ship Jinja, and only a comment said it did.** The
  template branch of the replay carried `# pragma: no cover — the image ships
  jinja2` and `brain/Dockerfile` installed no such package, so **every
  template trigger refused on every real install** while three tests passed on
  machines that happened to have Jinja from somewhere else. A comment cannot
  fail — the same shape as a grep for a line standing in for a test of what
  the line does. `py3-jinja2` is in the image, `jinja2` is in the test
  requirements, and `test_the_image_ships_what_a_template_needs` fails if
  either goes; a second test renders a template through `shadow`'s own path
  rather than asking whether `jinja2` imports.

- **`_num` guards on `math.isfinite`, not on the `f != f` NaN idiom.** CodeQL
  reads that idiom as a comparison of identical values and it was right to ask
  — and the wider guard it named catches the case the idiom missed:
  `float("inf")` parses happily and satisfies `above:` for ever, so a sensor
  reporting it would fire the trigger and then hold it against every later
  crossing. A state that is not a *finite* number is not a number a replay can
  answer with.

- **The history query was built by pasting entity ids into a URL, in three
  places.** `ha_data.get_history`, `closures.fetch_history` and
  `shadow.fetch_history` each wrote `?filter_entity_id={','.join(ids)}` — and
  `_rest_get`'s own docstring already said not to, and said why: *"nothing a
  caller passes can steer the request into being a different request… equally
  how an ordinary entity id with an odd character in it would silently corrupt
  the call."* All three were written past it.

  On the replay path the ids come out of an automation config that arrived in
  an HTTP body, so an id carrying `&` is a **second parameter** rather than a
  value — a partial SSRF (`py/partial-ssrf`), and CodeQL was right to call it
  critical. Off that path the ids come from the registry and the same
  character corrupts the call quietly instead, which is the failure nobody
  would ever have traced.

  One `history_params` builds it now, out of ids checked against
  `ENTITY_ID_RE`, handed to aiohttp as `params` so it does the encoding; a bad
  id is **dropped, not escaped**, because an id that is not an id names
  nothing and would spend a request asking Core about a made-up string. The
  shapes are asserted against a real aiohttp server rather than against a
  string the test wrote — the valueless flags Core wants are exactly the
  detail a hand-written expectation gets wrong the same way the code does —
  and a grep-level test fails a fourth copy, the way `atomic_write`'s does.

- **The template allow-list moved onto the render path.** `render_template`
  renders a Jinja string that arrived in an HTTP body, and the allow-list that
  makes that safe ran only in `check_replayable` — an earlier and separate
  pass, so the sandbox was reached safely only while every caller remembered
  to validate first. That is the same shape as asking `protected_entities`
  anywhere but the chokepoint. It validates for itself now; validating twice
  on the replay path costs one regex sweep of a short string.

- **The sandbox renders with `autoescape=True`.** Its output never reaches a
  browser and cannot change the verdict — the result is compared against a
  fixed set of words — so the safe setting is free, and the day somebody puts
  that output on a page is the day the missing escape matters.

- **The seventh tab moved the top bar's breakpoint, and broke its touch floor
  at 320px.** A tab is ~90px of row, so the single-row shape stopped fitting
  the two trouble states (1302px paused, 1328px on a failed login): the band
  moves from 1240 to **1340**, taken from what `measure-topbar.mjs` reports
  rather than guessed. And seven 44px tabs plus their gaps need 320px exactly,
  leaving nothing for the bar's own padding — every tab came out 42px on the
  narrowest phone. The strip **wraps** now, with `min-width` on the tab making
  the fit binary, so the row gives way at whatever width stops holding it and
  the labels and the targets both survive; only 320px pays for it, and the
  panel remeasures `--bar-h` to match.

### Tests

- `tests/test_shadow.py` (41), `tests/test_proposals.py` (30) and
  `tests/test_routines.py` (30), with every guard verified by **mutation** —
  break it, watch the test fail, restore it. That caught one test whose name
  claimed something it did not measure: the numeric-crossing fixture never had
  two consecutive samples above the bar, so "fires on the crossing" and "fires
  on the level" gave the same answer.

- `tests/manual/measure-proposals.mjs` joins the `layout` job, and
  `test_no_width_gets_a_row_of_bare_glyphs` now names its tabs instead of
  counting them — a count says nothing about whether the tab added last kept
  its label.

## 1.41.1

### Fixed

- `thermal.RECENT_BUCKET_S`, a constant assigned and read nowhere, removed —
  CodeQL's finding on the 1.41.0 pull request, and a correct one. The number
  was written as documentation of the five-minute bucket, but the resolution
  is already stated in prose one line above it and expressed as
  `"period": "5minute"` in the query three lines below, so it recorded a fact
  nothing needed it for.

  It is the same query `TestNoLoggerNothingLogsThrough` is a narrow slice of,
  so the obvious move was to widen that guard — measured, and it does not
  hold. File-local it reports 163, nearly all of them `const.py` names that
  exist precisely to be imported somewhere else; repo-wide it reports 11, and
  three of those are `CONFIG_SCHEMA`, which Home Assistant reads off an
  integration module *by name* at setup, so nothing here refers to it and
  deleting it would break all three integrations. A rule with exceptions no
  test can tell from real dead code is a rule that needs a hand-maintained
  allow-list, and that is a guard that rots. The reasoning is recorded in
  `tests/test_code_scanning.py`'s docstring instead.

## 1.41.0

### Added

The rest of the capability map's **#11**. 1.40.0 measured how each room holds
its heat; this is what the measurement is *for* — three findings, each
answering a question no single state in Home Assistant can.

- **`climate.preheat` — the heating starts too late.** A schedule set to a
  fixed hour warms the bedroom to its setpoint at 07:40 in a house that is up
  at 07:00, every weekday, and nothing anywhere records a fault: the
  automation ran, the thermostat called, the room got warm. Three of brAIn's
  own measurements have to agree before it will say so — `rhythm` for when
  this house actually gets up, `baselines` for what the room reads at that
  hour of an ordinary week, and the thermal model for how long the climb takes
  — and then it names the time the call would have to come.

  It reports **weekday mornings only**, because that is where a schedule
  exists and where `rhythm` has the days behind it (a weekend accrues two days
  a week and takes about five weeks to measure). And it says nothing at all
  until the wake time is measured rather than guessed: a preheat time pinned
  to a typed-in 07:00 is a guess wearing a number. **The proof that the
  heating *does* arrive is required**, not optional — a room still short two
  hours later is `climate.underheated`'s finding, and "start earlier" is
  advice that cannot work on one.

- **`climate.window` — a room losing heat faster than it can.** More than
  twice what its own `k` allows is a route the walls do not have. This check
  is only *sayable* because the model exists: the same half-degree in ten
  minutes is a draught in one room and an ordinary evening in another, and no
  fixed threshold can tell them apart. The room's allowance is read where the
  fall **started** rather than where it ended — a room's allowed loss shrinks
  as it cools, so the end sets a lower bar, and the start is the reading that
  gives the model the benefit of the doubt.

- **`climate.freeze` — the pipes.** From the current reading and the current
  outdoor temperature, when this room reaches 5 °C: where water in an outside
  wall starts to be at risk, well before the room's own thermometer reads
  freezing. It only reports a room that is **already falling**, rather than
  assuming nothing heats it — `coast` describes an unheated room and no state
  anywhere says the heating is off, so the fall is the evidence.

- **`thermal.recent`** is the live half of the snapshot key, the way
  `appliances` already does it: the nightly store says how a room behaves, and
  the checks pass fetches what it is doing now — the modelled rooms and their
  outdoor reference, over four hours. **Five-minute statistics, not hourly**,
  because an hourly mean cannot see a window opened forty minutes ago: it is
  still inside the hour that has not closed. One fetch, two checks.

- `climate.freeze` and `climate.window` ride at **`now`** urgency and may
  break quiet hours — a freeze warning at 3am is exactly when it is wanted,
  and an open window costs money for as long as it stays open. `climate.preheat`
  stays `whenever`: a schedule that starts late will start late again tomorrow.

- Both live checks **stand down for the room the other claims**, freeze first.
  A room freezing because a window is open is one problem, and the sentence
  that names the freezing is the one worth waking somebody for — the same
  arrangement `climate.underheated` and `climate.heat_loss` already keep.

### Tests

- 26 more cases in `tests/test_thermal.py` (83 total), and each new guard is
  verified against the failure it exists for rather than only against the fix:
  dropping freeze's "already falling" evidence makes it forecast a heated
  room; dropping preheat's "it does get there later" proof makes it advise an
  earlier start on a room that never arrives; removing `recent_fall`'s span
  floor turns a thermometer's own 0.1 step into a rate; and reading the window
  allowance at the end of the fall instead of the start reports a room the
  model can account for.
- The clean fixture in `tests/test_house_checks.py` gained live readings — a
  cold evening with every room easing down well inside what its insulation
  allows — so both live checks run their whole loop over four rooms and are
  asserted silent, rather than silent for want of data.

## 1.40.0

### Added

- **A thermal model of the house** (`panel/thermal.py`), roadmap item **#11**'s
  larger half. Every climate capability people actually want — start the
  heating so the bedroom is warm *when we get up*, tell me a window is open
  rather than that it is cold, warn me the pipes will freeze by morning, say
  what a 17°C setback would cost — is the same two numbers about a room, and
  brAIn held neither. Without them each of those is a threshold somebody
  guesses at, and a threshold that is right in one house is wrong in the next:
  a stone cottage and a new flat lose heat an order of magnitude apart, and so
  do two rooms of one house.

  The two numbers are Newton's. **`k`**, the loss coefficient, is how fast a
  room falls towards outside; its reciprocal is the time constant, which is
  the number people have an intuition for ("this room holds its heat for about
  eight hours"). **`h`**, the gain, is how fast anything puts the heat back.
  Both are measured per room, nightly, from a month of hourly statistics,
  against one outdoor reference — and the reference brAIn chose is recorded in
  the payload, because every `k` in the house is measured against that one
  choice and a reference nobody can check is a reference nobody can correct.

  Five rules keep it honest, and each answers a way it would otherwise be
  confidently wrong:

  - **The sun is the confounder, and night is the gate.** A south-facing room
    warms with the heating off, so a fit that includes an afternoon reports a
    room that gains heat as it gets colder outside. `k` is measured only in
    the deep-night hours — the same shape of gate as the `state_class` one on
    `baselines.trend`: a measurement that would be wrong in every house
    belongs in the build, not in the check that reads it.
  - **A fit is not a measurement until it is graded.** A month whose outdoor
    temperature barely moved has no leverage — every point sits at the same x
    and the line through them is whatever the noise says, which looks exactly
    like a real answer. The delta has to span something, the fit is graded
    against the scatter about its own line, and a slope that does not clear
    that scatter is no slope.
  - **A number outside physics is not a room.** A time constant of twenty
    minutes is a thermometer in a draught and one of a fortnight is a
    thermometer inside a wall; both are reported unmeasured rather than
    measured badly.
  - **Indoors and outdoors have to agree about what a degree is.** `k` is
    unit-free only while both halves of the difference are in the same
    degrees, so a Fahrenheit reference against a Celsius room is a loss rate
    wrong by 1.8 with nothing downstream able to tell. That room gets no
    model.
  - **A freezer carries `device_class: temperature` too**, and so does a hot
    water tank. A room is a reading that spends the month inside a band people
    live in.

  And, as with `baselines.py` and `closures.py`, **nothing here decides
  anything**. It answers how fast a room loses heat, how fast it can gain, and
  what those imply for a given night; whether any of that is worth telling
  somebody is the check's.

- **Two findings that read it** (`panel/checks/thermal.py`). Both are
  invisible from any single state, which is why nothing could report them
  before.

  - **`climate.underheated`** — a room asked for a temperature it never
    reaches. Nothing errors: the thermostat calls, the valve opens, the boiler
    runs, and the room sits two degrees under its setpoint all winter. It
    requires the arithmetic **and** the evidence — the room must never once
    have been seen at the temperature it is asked for, over a month of hours —
    because a thermostat that switches off at its setpoint never lets a room
    show what it could have done, so a well-heated room's measured ceiling
    understates it and a check reading the ceiling alone would fire on the
    healthiest houses first. It also stands down entirely when the month held
    no cold night, rather than extrapolating a January answer out of an
    August.
  - **`climate.heat_loss`** — a room that empties much faster than the rest of
    the house. It needs four measured rooms before one can be unusual against
    the others, and the room has to be fast in absolute terms as well as
    relatively, because twice the loss rate of a very well insulated house is
    still a good room. Past two rows it says nothing, because a cold snap or a
    purged recorder moves every room at once.

  The two share `underheated_rooms`, so a draughty room that also never
  reaches its setpoint is one card with one fix rather than two — the same
  arrangement `dev.unavailable` and `dev.zwave_dead` keep.

- Both ride at `whenever` urgency (`check:climate.` in
  `notify_router.PRODUCER_URGENCY`): a room that has been two degrees short all
  winter is not two degrees shorter at three in the morning, so quiet hours may
  hold them.

- `⚙ Diagnostics` and `/api/diagnostics` carry the store's summary, including
  the one field that is not a count: with no outdoor sensor there is no model
  at all, and that is a **sentence** rather than a zero. "No climate findings"
  and "no room could be measured against anything" look identical from every
  other surface, and only one of them is a house that is fine.

### Tests

- `tests/test_thermal.py` (57 cases) builds rooms whose physics is *known* and
  checks the number that comes back is the one that went in — 0.10 per hour
  recovered as 0.10, a 1.5°C/h gain as 1.5 — rather than asserting that a
  number came back. The night gate, the evidence half of `climate.underheated`
  and the shared standing-down are each verified against the failure they
  exist for: removing the gate moves the recovered loss rate off the physics,
  and removing the evidence makes the check fire on a room that has been at
  its setpoint all month.
- The clean fixture in `tests/test_house_checks.py` gained a four-room thermal
  store and a thermostat, so both checks are asserted silent on a healthy
  house before they are asserted to find a planted one.

## 1.39.0

### Added

- **Appliance state tracking** (`panel/appliances.py`), the measurement the
  roadmap's chore engine stands on and the last third of **#7**. Nothing in
  Home Assistant says a wash finished, and every rule anybody writes on top
  of a smart plug is a wattage typed into a box: `> 10 W` is a running
  dishwasher in one house and a phone charger in the next. So the numbers are
  measured, per machine, from its own ten days of five-minute statistics —
  the argument `baselines.py` makes about the word "unusual", applied to a
  distribution that is a different shape. A power reading is not a band with
  a middle and a spread; it is **bimodal**, and a sensor that does not have
  that shape (a router, a standing draw) gets **no profile** rather than a
  guessed threshold.

  Five rules, four of them about being confidently wrong:

  - **The floor is a low percentile, never the minimum.** One zero during a
    power cut would otherwise set the idle level for good.
  - **"Below the threshold" is not "finished".** A dishwasher's dry phase
    draws almost nothing for twenty minutes, so a machine that reports done
    the moment the draw drops reports done three times a cycle. The wait is
    measured too: the gaps between draws are *themselves* bimodal — lulls of
    minutes inside a cycle, idles of hours between them — and **the widest
    jump in that sorted list is the appliance saying how long its own quiet
    phases last**.
  - **A blip is not a cycle.** Every compressor, kettle and inrush clears a
    threshold for a moment.
  - **"Unloaded" cannot be seen from power at all**, and this does not
    pretend otherwise: an emptied machine and a full one draw exactly the
    same watts. Three states are measured — `idle`, `running`, `finished` —
    and the fourth is a person saying so, which is what 1.38's To-do list and
    notification buttons are for.
  - **And nothing here decides anything**, the same split the baselines keep.

  It rides the nightly baseline pass: one `/states` fetch, three measurements
  of the same house. `GET /api/appliances` is where somebody checks whether
  their washing machine was measured at all, and ⚙ Diagnostics carries how
  many machines have a shape against how many are chores — nine profiled
  sensors and no chores means nothing here is *named* like a machine somebody
  has to empty.

- **`chore.waiting`** — the washing that finished and is still in the
  machine. It is the first check whose question no state answers, and it
  carries three floors of its own. **Only what a person has to empty**: the
  measurement is universal, the chore is narrowed by NAME to a washer, a
  dryer and a dishwasher — the one guess here, made in the direction where
  being wrong is cheap, because a missed chore costs nothing and a
  notification telling somebody to go and empty their television is how the
  whole feature gets turned off. **It waits** `QUIET_MIN` on top of the
  machine's own measured settle time, because a cycle that ended four minutes
  ago is somebody standing at the machine. And **it stops asking** past
  `STALE_HOURS`: yesterday's washing is a fact about the week, not something
  to do. Its notification urgency is `whenever` — a chore arrives in the
  evening by construction and an emptied dishwasher at eight in the morning
  is the same dishwasher, so quiet hours have to be able to hold it.

## 1.38.0

### Added

- **brAIn's work list, in Home Assistant's own To-do app** (`todo.brain`).
  The Findings tab is behind ingress, so a critical finding was a panel
  somebody had to open; `sensor.brain_open_findings` answered *how much* and
  nothing answered *what* anywhere a person already looks. **One list, two
  views** — not a copy: every item is derived from the mirror the add-on
  already publishes, nothing about a finding is stored on the Home Assistant
  side, and the item's uid is the finding's own id.

  Three decisions, each of them a refusal:

  - **Adding an item is not offered.** An item created there would have
    nothing behind it and would vanish on the next poll, and a list that
    silently deletes what you put on it is worse than one that does not
    offer to take it — so `CREATE_TODO_ITEM` is absent and the app hides the
    button.
  - **Completing is "I've fixed it" and deleting is "not a problem here".**
    The tab's own two endings and no new vocabulary; each writes the memory
    line it always did.
  - **No due dates yet, deliberately.** A forecast's date lives in the prose
    of its `detail` ("about 9 days left"), and a date parsed out of a
    sentence is a guess with a calendar entry attached to it. The forecast
    checks have to carry a real one first.

  The platform is looked up rather than named (`getattr(Platform, "TODO")`):
  `todo` arrived in core 2023.11 and this integration's floor is 2023.6, so
  on an older core the list is simply absent — a missing platform is a
  missing entity, where naming one the core has never heard of fails the
  whole entry.

- **Findings on a phone arrive with buttons** — *I've fixed it*, *Not a
  problem*, *Later* — and pressing one ends the finding without opening
  anything. Two gates, and both of them are about not breaking something
  that works:

  - **Only the companion app.** Every other notifier takes `data` and means
    something different by it or nothing at all, and a payload built on a
    guess is how a working notification stops arriving. The gate is the one
    signal that is not a guess: a `mobile_app_*` service. A notify *group*
    containing mobile apps is deliberately not detected — it cannot be, from
    a name.
  - **Only a message about exactly one finding.** A digest is several
    problems in one notification and a button on it would have to guess
    which, so a held batch arrives as it always did.

- **One route back into the store, for both** (`panel/finding_requests.py` +
  `custom_components/brain/requests.py`). The panel owns the findings store
  and Home Assistant cannot reach it — 8099 is `null` in `ports:` on purpose
  and stays that way — so what crosses the gap is a **request**, not a
  write: a small JSON file on the shared volume, picked up within seconds
  and applied **through the same code the tab's own buttons use**
  (`_end_finding`, extracted for exactly this). A second implementation
  would be the same answer teaching brAIn two different things depending on
  where it was given.

  Four rules, and every one of them is about the two sides being a few
  seconds apart rather than about anything going wrong. **A request naming a
  finding that is gone is an ordinary race**, not an error and not a reason
  to retry or resurrect. **Applying twice is harmless** — settling an
  already-settled finding changes nothing — which is why the delete being
  able to fail needs no ledger of applied ids. **Every field is data from
  another process**: the id is an int or the request is dropped, the verb is
  one of a closed set, the note is capped. And **the queue is bounded**, so
  an add-on that was off for a week does not spend its first minute on a
  directory nothing drained.

- ⚙ **Diagnostics** carries what has come in from outside the panel and what
  is stuck: "nothing has been ticked this week" and "the loop died on
  Tuesday holding four answers" look identical from every other surface.

### Changed

- The findings mirror now carries `detail` and `fix`, cut harder than the
  store keeps them (240 characters each). A to-do item's description is read
  on a phone before deciding whether to get up, and it wants the evidence
  and the suggested fix — but fifty rows of the store's full 600 would be
  60 KB of mirror for two paragraphs nobody scrolls to the end of.

## 1.37.0

### Added

- **The weekly report** (`panel/weekly.py`), the last piece of the roadmap's
  #10. One message a week: what the house used against the week before, what
  was found and answered, what brAIn learned, and the one thing worth doing
  this week. Off by default (`weekly_report`), on the day you choose
  (`weekly_report_day`, Sundays), to whatever notify service the findings
  already use — so pointing that at `notify.notify` is what makes it the
  report that goes to everyone.

  **It is not the morning brief with a longer timer**, and building it as one
  is how weekly reports end up unread. The brief asks *is there anything* and
  its whole design is a refusal; a report asks *what happened*, and its
  failure mode is the opposite one — a report that lists everything is the
  dozen unread cards with the covers off. So every section is gathered
  deterministically and **capped** before any model runs, and the model's job
  is to say four things rather than to choose which four.

  **"One thing to do this week" is chosen before the model, not by it.** Asked
  to pick, a model picks the row it can write the best sentence about, which
  is the one carrying the most detail rather than the most consequence. It is
  the worst open severity, then the longest open, and the prompt says which
  one it is writing about.

  **"Still open" is not "filed".** A finding raised and settled inside the same
  week has left the store, so nothing can count what was filed without
  counting it twice or not at all — the number is named for what it actually
  is rather than dressed up as the one nobody can compute.

  **The day is the gate and the hour is only a preference.** Unlike the brief,
  whose window shuts 45 minutes after the house gets up because a brief at
  lunchtime is not a morning brief, a weekly report delivered on Sunday
  afternoon is still that week's — so the window only ever opens, and
  skipping a week to protect an hour is the trade this deliberately does not
  make.

- **What the house used, week over week** (`panel/energy.py`). The arithmetic
  is the easy half; **which meters** is the half that produces a number nobody
  can tell is wrong. Summing "every sensor with `device_class: energy`"
  double-counts by construction — a whole-home clamp, the inverter and every
  smart plug behind them all carry that class — so a house with six plugs
  would report roughly twice what it used, silently. The set is **Home
  Assistant's own** (`energy/get_prefs`, the grid sources somebody actually
  declared), and a house with no energy configuration gets a sentence saying
  so rather than a plausible group picked here.

  Three more rules, each against a total that looks right: **cost only where a
  cost statistic exists** (a price to multiply means HA made its own sensor
  under an id we would have to guess, and a guessed id quotes somebody else's
  number); **both windows are seven complete local days**, ending at midnight
  and never at `now`, because half of today against seven full days is a 45%
  fall that is nothing but the clock; and **a negative day is a meter reset**,
  dropped rather than added, which shortens the window and stands the
  comparison down instead of reporting a plausible fall. Where the recorder
  can answer consumption itself (`types: ["change"]`) it is asked; the
  cumulative `sum` is the fallback, and deriving from it is why the fetch
  reaches one day further back than the report does.

- **`brain weekly`** — the week's numbers and the last report sent, and
  `brain weekly send` to write one now. `GET /api/weekly` and
  `POST /api/weekly/run` are the same answers for the panel. Sending by hand
  **moves the week** rather than adding to it: two reports about overlapping
  weeks make the numbers in both meaningless.

### Fixed

- **A restart is not a new morning, and it was** (`panel/schedule_store.py`).
  Both scheduled messages are guarded by a "once a day" / "once a week" stamp
  and both kept it in memory only, so restarting the add-on set it back to
  zero and the next time the window came round the message went out again — a
  second brief on the same morning, and (had it existed) a second weekly
  report about the same week. Restarting is the first thing anybody does
  after changing an option, which makes that the ordinary case rather than
  the unlucky one. Both stamps now live in `/data/schedule.json`, and every
  way of failing to read one reads as "never sent": a lost stamp costs one
  duplicate message, where a stamp wrongly read as *sent* would silence a
  real report.

### Added

- ⚙ **Diagnostics** carries the report's own state — whether it is on, which
  day, when it last went, and what the last gather held. A report that has
  never sent because no week was worth reporting reads, from outside, exactly
  like one whose loop died in March.

## 1.36.0

### Added

- **What is normally open here** (`panel/closures.py`). `baselines.py` answers
  "is this reading unusual" and cannot answer it for a door, because it
  measures medians and spreads over numbers and a door has neither. So the
  one thing people most want a house to notice at bedtime — *is anything open,
  unlocked or ajar that usually is not* — had no measurement behind it at all,
  and any rule for it would have been a threshold somebody guessed.

  What a binary entity has instead of a median is **how much of the time it is
  open**: for each hour of the week, the seconds it spent open over the
  seconds it was observed. A back door open at 23:40 is news in a house that
  has it shut then on 49 nights out of 50, and is nothing in one where it
  stands open all summer.

  Four things keep it bounded and honest. **Only closures** — doors, windows,
  locks, covers and garages, by device class and domain; a hall motion sensor
  being on at midnight is not something anybody wants told about, and
  including it would bury the row that matters. **Time-weighted, never
  sampled**: a door open for ten minutes and one open for ten hours look
  identical to a sampler that catches each once. **A bucket has to have been
  watched** — below an hour of observation it says nothing rather than
  reporting a fraction of a fraction, and `usual_open` returns `None` for it,
  which is a different answer from "never open then". **And it decides
  nothing**, the same split `baselines.py` keeps.

  The interval walk is the part that had to be right: a door shut on Friday
  and opened on Monday is *one* interval across sixty buckets, so it walks the
  hour boundaries rather than charging the whole span to the hour it started
  in — which is how a rarely-changing entity would otherwise report almost
  every hour as unwatched. It advances even across a daylight-saving boundary,
  where a clock that does not move is an infinite loop.

- **`evening.left_open` — open at bedtime, and usually shut.** Every other
  check reads a state and knows whether it is wrong; a door being open is not
  wrong, and this is the first check whose entire answer is a measurement of
  this particular house.

  It only speaks at bedtime, and bedtime comes from `panel/rhythm.py` — when
  this house actually settles, weekdays and weekends apart — falling back to a
  late hour until there is a measurement, exactly as the morning brief does.
  It only speaks about an hour it has watched. And past a handful of rows it
  says nothing, because a house being aired out moves every closure at once.

  Four open doors are **one row**, not four: this is a single thing to do
  before bed, and four rows to dismiss one at a time is a chore.

- **A bedtime pass.** The scheduled checks run every `checks_interval_hours`
  from whenever the add-on started, so on most houses they would simply never
  be awake in the evening window — the check would have been unreachable. The
  panel now runs one pass around the measured settle time, using the same
  `brief.due` window logic rather than a second copy of "is this the moment".

  Its notification urgency is `now`, and that is load-bearing: this check
  fires *inside* quiet hours by construction, since bedtime is when the quiet
  window opens. Anything else holds it until morning, which is the one
  delivery that makes the check pointless.

## 1.35.0

### Added

- **The house's own clock** (`panel/rhythm.py`). Everything brAIn does on a
  schedule happens at a time somebody typed into a box, which is the
  definition of a timer rather than a rhythm: 07:00 is early on a Sunday and
  late on a Tuesday in the same house, and somebody who keeps correcting when
  a message arrives stops reading it.

  The house already answered this and nothing was asking. The action miner
  files every change under a cause, and the first one caused by a **person**
  is the house waking up — not a motion sensor (which fires for a cat and for
  the heating), not a light (an automation does that at dawn), but somebody
  actually doing something. Two numbers a day, kept; not a timeline.

  Four floors, and they are the ones the baselines and the override ledger
  already carry. A fortnight of days before it says anything. **Weekdays and
  weekends measured apart**, because one number over both is wrong on all
  seven days rather than on none — the cost being that a weekend answer takes
  about five weeks to exist, which looks like a bug from outside and is the
  floor doing its job. A spread wider than an hour and a half means there is
  no usual time, and saying so beats a confident number over data that holds
  none.

  **And the median is circular.** Settle times sit either side of midnight,
  and four of them inside forty minutes of it have a straight median of
  **12:00** — not a small error, the opposite side of the day. Everything
  here is measured around the clock, and the test asserts that failure
  against the arithmetic that produces it rather than describing it.

- **A morning brief** (`panel/brief.py`, `morning_brief`, off by default).
  One short message a day, at the hour this house actually starts moving.

  **The decision to send is made before any model is asked.** "All quiet"
  every morning is the message people mute, and it costs a Claude turn — the
  most expensive thing the add-on does — to produce. `worth_saying` is
  deterministic and reads what is already counted: findings filed since the
  last brief, a health verdict that is not `ok`, a night with an unusual
  share of changes nothing can attribute. An empty answer costs nothing at
  all and sends nothing.

  What the model is for is the sentence: under eighty words, one paragraph,
  no greeting and no markdown, because this is read on a lock screen. It gets
  the reasons and read-only tools to make them specific, and it is not handed
  the house. A reply too short to be a brief is not sent, because sending
  that is worse than the silence it replaced.

  The window opens at the measured wake (or the fallback hour until there is
  a measurement) and closes 45 minutes later, so a panel restarted at 09:00
  does not deliver breakfast at lunchtime; the send is stamped *before* the
  run, because a pass that takes three minutes must not let the next tick
  start a second one.

### Changed

- ⚙ Diagnostics reports what the rhythm has measured and what the brief last
  did with it. A rhythm that never gathered enough days looks exactly like
  one that did and chose 07:00, and the difference has to be readable from
  outside.

## 1.34.0

### Fixed

- **`auto.overridden` counted overrides with no denominator, and reported two
  opposite things identically.** Three undos of a rule that ran three times is
  a rule that does not fit this house; three undos of one that ran three
  hundred times is somebody having an unusual Tuesday. The check could not
  tell them apart, which is the shape of finding people learn to ignore.
  `actions.automation_moves` counts what each automation actually did over the
  same window off the same mined list, the check fires on a *share* once there
  are enough runs for a share to mean anything, and the detail says "3 of the
  4 times it acted" rather than "3 times". Below that floor the count stands
  alone, because 3 of 3 is 100% and says nothing the count did not.

### Added

- **The slow override — the one that never reaches three in a day.** Somebody
  putting the same thing back once a day for a month is the clearest signal a
  house gives about a rule not fitting it, and a check that only ever looks at
  today is structurally unable to see it. `panel/override_ledger.py` keeps
  overrides — and only overrides — so that the sentence *"you undo this every
  weekday morning"* can be said at all.

  This is a deliberate exception to `actions.py` persisting nothing, and a
  narrower claim than the rule that made: what that rejected was keeping the
  **timeline**, tens of thousands of rows a day and a second copy of Home
  Assistant's own logbook. Overrides are a handful of rows a week.

  And a pattern has to still be **happening**, not merely be well shaped.
  The ledger keeps two months so a shape has room to appear, but a rule
  somebody fixed goes on having a beautiful shape in that history — and a
  finding that cannot clear for eight weeks after the problem is gone is
  the list nobody reads. Nothing is reported unless the last override was
  within the last week.

  Two more details are load-bearing. Passes overlap — every six hours over a
  twenty-six hour window — so the same override is offered four or five times
  and a ledger that appended what it was given would report one disagreement
  as five; the id is the **event**, not the offering. And a pattern is about
  **days**: four overrides in one evening is one evening, and nothing here
  reports a shape that does not span several distinct days, whatever the count.

- **When you override it is the condition the automation is missing**, so the
  finding names it: *"almost always between 08:00 and 09:00 and only on
  weekdays"*. The hours reported are the ones that are **occupied**, not the
  window that found them — the first cut searched four-hour windows and took
  whichever start it tried first, so fifteen overrides all at 08:10 came back
  as "between 05:00 and 09:00", which is not a slightly loose answer but a
  condition somebody would write that stands the automation down for three
  hours nothing happens in. A day that has no shape gets no sentence, rather
  than a coincidence dressed as a pattern.

- **`auto.conflict` — two automations undoing each other.** Named as a separate
  finding when the override rules were written, and deferred then. Both ran,
  neither errored, and the entity is in whichever state the later trigger left
  it — so which one "wins" depends on the order two triggers happened to fire
  in, which is not something anybody designed, and the result is different from
  one day to the next. No check that reads Core can see it and no trace shows
  it, because nothing went wrong in either run.

  `find_conflicts` carries the same three rules as `find_overrides` for the
  same reasons (inside the window, the state has to actually differ, one move
  is undone once) plus a fourth that is new: **an automation cannot conflict
  with itself**, or a rule that sets a light on and then off inside one run
  reports itself as its own opponent. A pair is keyed unordered, or A-undoes-B
  and B-undoes-A count as two disagreements between the same two rules and each
  half sits under the floor.

## 1.33.0

### Added

- **The drift the band cannot see** (`baselines.trend`, `forecast.decline`).
  The failure with no bad reading in it: a freezer 6°C warmer than it was a
  month ago has never once been outside its usual range, because the range is
  built from the same weeks the drift happened in and moved along with it.
  Measured on a real-shaped month, that freezer reads **2.3 spreads** to
  `base.unusual` — which needs six — and **16** to the trend. It is not that
  the band is badly tuned; it is structurally incapable of seeing a drift,
  however far the drift goes, and nobody notices until something spoils.

  So a line is fitted through the month, to what is left once the week's own
  pattern is taken out (each hourly mean minus the median for its hour of the
  week — subtracting a constant per bucket removes the daily and weekly shape
  without touching a slope). The noise it is measured against is the spread
  *about that line*, which is the one estimate a drift cannot inflate.

  Four floors answer "does this fire on a healthy house". A window that
  **turned around in the middle** is not a drift and a step change is not
  weeks of drifting — both halves have to agree on a direction. A move
  smaller than the noise it sits in is not a move, and one too small to act
  on is not either. **Five thermometers drifting together is the weather
  rather than a device**, so the whole device class stands down and what is
  left is the one room doing something the others are not. And past a
  handful of rows it says nothing at all, the same rule `base.unusual`
  caps itself with.

- **Quiet hours, and urgency as its own axis** (`panel/notify_router.py`).
  Before this there was a sender and no router: five callers each handed new
  findings straight to one notify service, and the whole policy was a service
  name and a severity floor. So `sys.disk_low` at 03:40 was a phone lighting
  up a bedroom about something that would still be true at breakfast, and the
  second time that happens the notification is gone for good.

  Between `notify_quiet_start` and `notify_quiet_end` (22 to 7 by default, in
  the house's own timezone) only urgent findings get through. **Urgency is
  not severity**: a `critical` battery forecast is three weeks out and a
  `warning` about a boiler that has stopped answering is now, so it is
  declared per **producer** — a line of code — rather than per row, whose
  wording a model or an f-string would change out from under it.

  **A quiet hour is a hold, not a silence.** Held rows queue on disk and leave
  together as one message when the quiet ends; dropping them would mean a
  notifier silently deciding some problems were not worth mentioning. Anything
  settled or cleared while it waited is dropped from the queue rather than
  announced — being told at seven about a problem that went away at four is
  how these messages stop meaning anything — and a findings store that cannot
  be read sends everything, because not knowing whether a problem is over is
  not evidence that it is.

### Fixed

- **`base.unusual` was quiet on energy meters by accident rather than on
  purpose.** A `total_increasing` total is higher than it has ever been every
  hour of its life — that is what the class means — so "far outside its usual
  range" is a statement about arithmetic. What kept it quiet was that the
  band's own spread widens along with the ramp, which is not a guarantee: a
  meter that resets has no such protection. Both baseline checks now require
  `state_class: measurement`, and the trend is never even computed for a
  total, since a trend nothing should read is a trend nothing should store.
- **A reading far outside its band on a sensor that has been drifting for a
  month is now reported once, as the drift.** The two checks share
  `baselines.trend` and one eligibility question, so they cannot disagree
  about it — the same rule `dev.unavailable` and `dev.zwave_dead` follow for
  a dead Z-Wave node.

### Changed

- One least-squares fit, in `baselines.least_squares`. `checks/forecasts.py`
  had its own copy for the battery runway; two implementations of "the slope
  of these points" is two answers to a question that has one, and nothing
  would ever have noticed them disagreeing.
- The ⚙ Diagnostics section reports what the router is holding and for which
  window. A hold queue nobody can see is a queue that silently swallows, and
  "quiet hours are working" has to be tellable from "the flush loop died
  holding four findings since Tuesday".

## 1.32.0

### Added

- **The baseline engine: what is normal for this house** (`panel/baselines.py`).
  "Unusual" is the word behind most of what people want a smart home to
  notice — water running at night, a freezer drifting, a boiler on for twice
  as long as it usually is — and until there is a number behind it, every
  rule that uses it is a threshold somebody guessed. brAIn now measures, for
  every numeric sensor, what it normally reads at **this hour of this day of
  the week** and how far it normally strays, from a month of the house's own
  long-term statistics. It runs overnight, costs no Claude turn, and decides
  nothing by itself.

  Five rules keep it honest. **The bucket is an hour of the week in the
  house's own timezone** — a weekday 7am is not a Sunday 7am, and UTC would
  smear every household's morning across two buckets and move it twice a
  year; a timezone that cannot be read falls back to UTC and says so.
  **Spread is a median absolute deviation, not a standard deviation** —
  one meter that spiked when the oven came on would otherwise set a band
  nothing can ever fall outside. **A reading that never moves has no
  spread**, and dividing by it makes every change infinite, so there is a
  floor under the spread and an entity whose whole history is one value is
  reported as having no useful baseline rather than an exquisitely
  sensitive one. **A bucket with too few samples says nothing** — an hour
  seen twice is an anecdote. And **nothing here decides anything**: it
  answers "how far outside its own normal is this, in units of its own
  spread", and the checks and the model decide what is worth saying.

- **`base.unusual`** — a reading well outside what this house normally does
  at this hour. Six spreads (a MAD runs about two thirds of a standard
  deviation, so the bar is higher than the number looks), nine when the
  answer had to come from the entity's whole history rather than this hour,
  and never for a move too small for a person to notice. It stands down for
  a reading `dev.implausible` already claims — a thermometer at 99°C is
  impossible before it is unusual, and two checks on one sensor under two
  different fixes is how a list stops being read; they share the question so
  they cannot disagree about it. And it says nothing at all when it would
  say too much: more than a handful of rows means the *baseline* has stopped
  describing the house (a heating season starting, a meter replaced), and
  reporting fifty rows would be reporting the measurement rather than the
  home.

- **`base.stale`** — the measurement itself has stopped being taken. Not a
  fact about the house but about brAIn, and it belongs on the list because
  every baseline check silently says nothing while it is true, which is
  indistinguishable from a house with nothing odd in it.

- **`get_baseline`** MCP tool, read-only and on the analyst's allow-list.
  It is what turns "that looks high" into "4.2 times its normal variation
  for a Tuesday morning" — without it a model asked whether a reading is odd
  has to invent a threshold, and it invents the same one for a freezer and a
  water meter. `GET /api/baselines` and `POST /api/baselines/run` are the
  same answer for the panel and for a person who does not want to wait until
  tonight.

### Changed

- The settings dialog's Diagnostics section and the `brain report` bundle
  both carry whether the house has been measured, how many sensors, and when
  — numbers only, never a month of hourly medians for four hundred sensors.

## 1.31.0

### Added

- **The action miner: who or what changed something** (`panel/actions.py`).
  A state carries no cause — nothing in `light.kitchen` being on says
  whether a person pressed a switch, an automation fired, a voice command
  asked, or brAIn did it, and that is the question behind most of what
  people actually ask their house. The miner reads Home Assistant's own
  logbook, walks each event's context chain, and files every state change
  under a cause. **Proximate and root cause are different and both are
  recorded**: an automation somebody started by hand carries a context
  entity *and* a context user, and reporting only the user turns every
  automation into "you did this" while reporting only the automation loses
  the one fact that explains an unexpected run. **A change with no context
  is `unattributed` in as many words** — a wall switch and a device's own
  integration reach Home Assistant identically, so naming either is a
  guess, and a timeline that guesses is not evidence.

- **brAIn's own actions are recorded rather than inferred.** The MCP server
  calls Home Assistant with the Supervisor's token exactly like every other
  add-on, so a change brAIn made is indistinguishable in the logbook from
  one any integration made. It now appends every service call it makes to a
  ledger (`/config/.brain/actions.jsonl`, trimmed, never rotated) and the
  miner joins against it.

- **The Activity tab.** A day of the house with a cause on every row, the
  hour headings down the side, a filter per cause, and paging back a day at
  a time. Tap any row for that entity's own recent history. The times
  somebody put back what an automation had just done are called out above
  the list rather than left to be spotted in it, because they are evidence
  rather than history. Read straight from the logbook on every visit: no
  Claude run, nothing spent, and nothing cached — a timeline showing the
  house as it was when you last looked is the one thing a timeline may not
  do.

- **`auto.overridden`** — an automation a person has undone three times in
  a day. The automation ran, nothing errored, and the light is off, so it
  is invisible to every other check; it is also the clearest signal a house
  gives about a rule being wrong for it. Agreement is not a fight (a person
  pressing "on" after a rule turned it on), an unrelated decision hours
  later is not an override, and one automation move is undone once however
  many times somebody nudges the dimmer.

- **`explain_change` and `get_activity` MCP tools**, both read-only and on
  the analyst's allow-list, so a card or a chat answering "why did the hall
  light come on" reads the cause instead of guessing from a state. They
  call the panel's own API over loopback rather than re-implementing
  attribution — the same reasoning that sends `brain findings` through the
  API instead of the store files.

- **`sensor.brain_health`** — whether brAIn itself is working, as
  `ok` / `degraded` / `failed`, with the reason and the thing to do about
  it in its attributes. It never goes unavailable: Home Assistant hides the
  attributes of an unavailable entity, and this is the entity somebody
  looks at precisely when the others have gone. A stale verdict fails
  rather than being served as a healthy one, because a reading nothing can
  correct is what took the usage sensors dark. The verdict is derived once,
  in the panel, so the sensor, the settings dialog's Diagnostics section,
  `brain doctor` and `brain report` cannot disagree about it. It is a state
  and a sentence, never a score — one number over a house hides its worst
  problem inside an average — and a switched-off face is never a fault.

### Changed

- `brain doctor` reports the health verdict alongside its own walk of the
  plumbing: a doctor run at 9am cannot see the listener that died at 3am,
  and the verdict can.
- The top-bar measure counted five tab labels by number, which says nothing
  about whether a sixth kept its name; it counts the tabs in the markup now.
  The panel's band test scanned to the end of the stylesheet, so it was
  really testing where the last `@media` in the file sat.

## 1.30.0

### Added

- **Ten more house checks, and the three questions the first set could not
  ask.** 1.29's checks read Home Assistant; these read the registry, the
  radios and the machine underneath. **Registry housekeeping** —
  `reg.hardware_name` finds entities still wearing the serial number their
  integration gave them (an IEEE address, a UUID, a bare hex run; a name
  like `0x00158d0001abcdef Temperature` is unfindable in a picker and
  unsayable to Assist); `reg.no_area` finds devices in no room, which are
  invisible to "turn off the kitchen" and to every area card;
  `reg.unused_helper` finds helpers no automation, script, scene or
  dashboard refers to; `reg.orphan_device` finds device rows with nothing
  behind them. **The radios** — `dev.zwave_dead` reads the Z-Wave node
  status sensor the controller publishes, and `dev.zha_unseen` reads ZHA's
  own `last_seen`, because a sleepy Zigbee sensor is `available` between
  check-ins and availability alone says nothing about it. **The machine** —
  `sys.backup_stale` (nothing backed up, or nothing in a week),
  `sys.addon_down` (an add-on in an error state, or set to start on boot
  and stopped), `sys.disk_space` and `sys.recorder_size`. And
  `auto.trigger_unavailable`, which is the failure with no symptom at all:
  the automation is switched on, nothing errors, no trace is written, and
  it can never fire again because the entity in its trigger has been
  unavailable for days.

- **A Diagnostics section under ⚙.** The run journal has counted every
  Claude run since 1.29 and nothing read it back — it existed only inside a
  bug report somebody else had to ask for. The settings dialog now renders
  `/api/diagnostics`: versions, the sign-in verdict, 24 hours of runs by
  outcome with the recent failures spelled out, and the last house-checks
  pass — including **which checks could not run and why**, since a skipped
  check is not a quiet one and is also the one that may not clear a row.
  "Copy for a bug report" copies the payload, with a fallback that puts the
  text on screen and selected when an ingress iframe is refused the
  clipboard.

- **The bug report template asks for `brain report`.** One field, naming
  where the bundle lands and what is in it — and saying out loud that it
  carries no prompts, no replies and no entity states.

### Changed

- **The house snapshot carries the Supervisor and the recorder.** Backups,
  add-ons, `/host/info` and Core's version, gathered rather than awaited in
  turn; each add-on row is folded together with its own `/info`, because
  the list endpoint does not say whether an add-on was *meant* to be
  running and `boot: manual` is somebody's decision rather than a fault. An
  add-on whose `/info` did not answer keeps no `boot` at all, which reads
  as "I could not look" and files nothing. Plus one `stat` of the recorder
  database and the `purge_keep_days` in `configuration.yaml` — an
  `!include`d recorder block reads as unset, not as a number this made up,
  and a database that is not a file under `/config` (Postgres, MariaDB)
  takes the whole key unavailable rather than reporting as small.

- **A dead Z-Wave node is reported once.** `dev.unavailable` skips a device
  whose node status reads `dead`, because `dev.zwave_dead` has the mesh fix
  on it — re-interview, or remove the failed node — and the same box under
  two different fixes is how a list stops being read.

## 1.29.0

### Added

- **House checks: findings that cost nothing.** Every finding used to come
  out of a Claude run — the analyst sweeping a category on a schedule, or a
  study session — and both are told an empty list is the honest answer, so
  most of those runs spent tens of thousands of tokens to report nothing,
  while the problems that are *deterministically* visible were found only
  when a model happened to look in the right place. `panel/checks/` is a
  set of pure functions over one snapshot of the house (states, registries,
  services, `automations.yaml` and friends, the traces Home Assistant keeps
  in `.storage`, a week of long-term statistics, the dashboards) that file
  findings without calling Claude: automations naming entities that do not
  exist, or calling services that are not registered (the old phone's
  `notify.mobile_app_*`, with the replacement named); automations whose
  last run errored, whose condition never passes, or that keep dropping
  triggers on `mode: single`; automations that have never fired or were
  switched off and forgotten; duplicates; a missing blueprint; devices
  unavailable for more than a day, grouped per device so a dead hub is one
  row; batteries low, or *silent* — a dead device stops reporting its own
  battery, which a threshold never sees; impossible readings; sensors
  frozen on one value for a week; entities left behind by a removed
  integration; dashboards showing entities that no longer exist. They run
  two minutes after startup and every `checks_interval_hours` (default 6;
  0 for never on a timer), on **Run checks now** on the Findings tab, and
  as `brain check`. What they find lands under a "check" label and rides
  into the analyst's prompt block with everything else, so Claude's job on
  the automations card becomes judgement rather than discovery.
- **The first forecast.** `forecast.battery` fits a line through sixty days
  of a battery's statistics and files "… battery is running down" with the
  days left in the detail, three weeks out — a finding with a date on it,
  rather than a threshold that fires the day before it dies.
- **A finding a check no longer reports leaves the list on its own.** A
  device that came back, a battery that was changed, an automation fixed
  by hand: the row is removed, not settled — no memory line, no ledger
  entry — so it can come back if the problem does. Only checks that
  actually *ran* may clear anything: a check whose data could not be
  fetched said nothing, and nothing is not "the problem went away". And
  because a check's finding text is stable on purpose (the store dedupes
  by it), the number that changes lives in the detail and is refreshed in
  place, so a forecast filed a week ago says "about 2 days" today.
- **A producer scorecard.** Every ending on the Findings tab is a label —
  "I did it" and "Got it" say the report was right, "Wrong" says it was
  not — and nothing added them up, because the settled ledger recorded the
  ending and not who raised it. It records the producer now, and a line
  under the filters says how right each one has been ("Device check 11 of
  12 confirmed"), once it has enough endings to mean something. The same
  numbers ride the diagnostics bundle, which is how a check with a bad
  floor gets found across installs rather than argued about.
- **A run journal.** One line per Claude run of any kind — insight, asked
  question, fix, auth check, chat turn — and per checks pass, with who ran
  it, how long it took, what it cost, and how it ended in a fixed
  vocabulary (`ok`, `timeout`, `max_turns`, `unparseable`, `auth`,
  `denied`, `no_cli`, `crash`, `fallback`, `error`). Fallbacks are
  outcomes too, because a fallback nobody counts is a fallback read as the
  real thing. Prompts and replies are never written; error text is
  scrubbed of anything credential-shaped before it lands.
- **Diagnostics, three ways.** `GET /api/diagnostics` is versions, options,
  the journal's last day, the stores' shapes, the last checks pass, the
  daemon roll-call and the auth verdict — no prompts, no entity states.
  The panel mirrors it to `/config/.brain/diagnostics.json` hourly and
  after every checks pass, and the integration now ships a
  `diagnostics.py`, so the standard **Download diagnostics** button on the
  brAIn integration page produces something. `brain report` writes the
  same payload beside `brain doctor --json`, the add-on log tail and the
  versions as one redacted archive under `/share/brain/reports/`, for a
  bug report that arrives with evidence rather than prose.
- **`brain doctor --json`.** The same self-test as one JSON object, so
  `brain report`, the panel and anything else can read a verdict rather
  than scrape a transcript.
- **`protected_entities`.** A list of entity ids or `domain.*` patterns
  brAIn may never act on, from any face — the terminal, the chat, Fix it,
  voice and automations. Enforced in the MCP server's one chokepoint, so
  it covers every `control_*` tool and every direct service call; a
  protected entity can still be looked at. An area or device target is
  resolved through the registry, and a call aimed at an area or device
  that *contains* a protected entity is refused; labels and floors cannot
  be resolved and are refused outright while the list is non-empty.
- **Two design pages** under `docs/design/`: the checks-and-self-tests
  plan this release is the first tier of, and a capability map for what
  comes after.

## 1.28.10

### Fixed

- **A code-scanning sweep, in the two places it found something real.** The
  `Retry-After` parser's "not the delay-seconds form" branch and BRight's
  "no such show version" branch were both silent `pass`es — the query is
  "an `except` that does nothing and has no comment", and in a codebase
  whose comments carry the reasoning the missing comment *is* the finding.
  Each now says what is being ignored and why falling through is the
  answer. Two message strings that sat in a list or a tuple as implicit
  concatenations — the shape that reads as a missing comma — are explicit
  concatenations now. No behaviour changes.

## 1.28.9

### Fixed

- **`brain doctor` warned about a consolidator lock that nothing was
  holding.** The check stat-ed the mtime of
  `/config/.brain/memory/.consolidate.lock` and warned past 15 minutes — but
  that file is an advisory flock target, not a lock-by-existence marker. The
  consolidator takes it with `exec 9>` and releases it with `exec 9>&-`,
  which drops the flock and leaves the file on disk permanently, so its
  mtime records when the last pass *started* and its presence means nothing
  at all. Any home that had not consolidated in the last quarter of an hour
  tripped it, which is nearly every run of the report. The remedy it named
  could not work either: the file lives under `/config` and survives a
  restart, so restarting the add-on left the same warning behind — over a
  memory system that was working the whole time (the panel has always asked
  the right question, so "File into memory now" was never actually
  blocked). The check now probes the flock the way the panel does — shared
  and non-blocking, so asking can never be something a real pass blocks on
  — and it distinguishes a flock that cannot be taken in this image from
  one somebody is holding, which is the confusion that once stopped memory
  updating at all. A warning from it is now worth acting on: an flock dies
  with the process holding it, so a lock still held past any plausible pass
  is a live process genuinely stuck, and restarting really is the remedy.

### Added

- **`brain doctor` reports when a pass last landed, and warns when the queue
  is the thing that is stuck.** The consolidator runs daily, so facts that
  have sat in the inbox for more than 26 hours with nothing filing them are
  a consolidator that is not working — which is the failure the lock warning
  was pretending to look for, asked of the queue rather than of a file
  nobody deletes.

## 1.28.8

### Fixed

- **A passing Claude auth check was never re-earned.** The verification ran
  at panel startup, after a credential was saved, and after the guided
  sign-in — and never again. So a credential that died mid-week was
  reported by nothing: the panel went on serving the startup verdict, the
  auth chip stayed hidden because a working login is not news, and the
  first real symptom was voice, automations and the consolidator failing
  off one credential store while the terminal carried on working off
  another. The verdict now ages out after six hours and is re-earned the
  next time somebody looks at the panel — lazily, off the status the panel
  already polls, because the check is a real Claude turn and an unattended
  timer would spend account tokens forever on a question nobody asked. A
  *failed* verdict ages out too, so fixing a login in the terminal no
  longer needs an add-on restart for the panel to notice.
  The re-check is silent: "Verifying Claude…" answers what a person just
  did, so a six-hourly re-verification leaves the standing verdict on
  screen rather than flashing a chip into the top bar — and shifting its
  layout — while you are reading a card.
- **Two pollers could start two verifications for one question.** The
  in-flight guard read a state its own task had not set yet —
  `asyncio.create_task` only schedules, so nothing inside the coroutine
  runs until the loop yields. It is a flag set synchronously now, in the
  same breath as the check that reads it.
- **The panel wrote `saved_at` in a format the contract does not describe.**
  Both credential files document `"saved_at": <epoch int>`, and
  `ha-share-login` writes an int and greps for one; the panel's own store
  wrote an ISO string. Latent, because each reader happens to read the file
  it wrote — but one documented shape covering two formats is a trap for
  the next one. The shell half has asserted this since it was written; the
  panel half now does too, which is why it drifted.

## 1.28.7

### Fixed

- **The usage sensors sent the wrong one of Claude Code's two User-Agents,
  so the 429 wall 1.28.x was meant to end never ended.** The usage endpoint
  sorts callers into rate-limit buckets by User-Agent, and only Claude
  Code's own gets a bucket that answers a poll. The previous fix read that
  right and then read the bundle wrong: it found `getUserAgent()` —
  `claude-cli/<version> (external, cli)` — which is what the CLI's
  *Messages-API* client sends, while the helper that actually fetches
  utilization sends `claude-code/<version>`. A genuine Claude Code UA sent
  to an endpoint that never sees it is still a stranger, so every poll went
  on landing in the hostile bucket: 429s within hours, an hours-long
  backoff, and four sensors ageing out into unavailable over and over with
  the fix already installed. brAIn now sends `claude-code/<installed
  version>`, and the tests assert it is neither of the two UAs that have
  shipped and failed.
- **A failing tracker looked like a working one showing 0%.** With no
  account numbers the panel falls back to estimating from brAIn's own
  insight runs — which on a home that mostly uses the terminal and the chat
  is 0% that never moves, with the weekly figure simply absent. Nothing on
  screen said the number had changed meaning, and the only note about it
  told you to sign in with your Claude subscription, which is useless
  advice for somebody already signed in. The estimate now reads `~0%` with
  a warning dot, and the popover names the tracker's own reason — a rate
  limit on the endpoint (not your account's usage), an API key that has no
  usage window, an expired credential, a tracker that has not reported yet
  — along with when brAIn will try again.
- **A usage reading with no timestamp could never go stale.** The freshness
  check was skipped whenever `updated_at` was missing rather than treating
  its absence as "this is not a reading", so such a file would have been
  served as current indefinitely.

## 1.28.6

### Fixed

- **The terminal proxy dropped the client's `Authorization` header only if
  it was spelled one of two ways.** ttyd takes a generated Basic credential
  — its port is reachable from the LAN if anyone publishes it — and the
  panel holds that credential and presents it upstream so an ingress user
  never meets a prompt. Whatever the client sent was supposed to be dropped
  first, so a browser holding a credential for the ingress origin could not
  present it to ttyd instead. The drop was two case-sensitive `pop`s over a
  dict keyed by the case the client actually sent, and HTTP considers every
  spelling of a header name identical: `AUTHORIZATION: Basic …` survived
  both and went upstream *beside* the real credential, leaving ttyd to pick
  between them. It is filtered by the same lower-cased pass the hop-by-hop
  headers already got.
- **A terminal websocket that broke mid-frame closed silently.** The two
  pumps race under `asyncio.wait(FIRST_COMPLETED)`, and an exception inside
  a task never reaches `asyncio.wait` — so the proxy's own handler never saw
  it, the log carried no reason for the drop, and Python printed a bare
  "Task exception was never retrieved" traceback into the add-on log at some
  later collection, attributed to nothing. The losing pump was cancelled but
  never awaited, so it was still inside a send when the upstream socket
  closed under it. Both are `_settle` now, which waits the cancellations
  out and reads every task's outcome — the losing pump's own parting
  error must not become the one reported, when the winner's is the
  reason for the shutdown — so the reason lands on the proxy's own
  warning line.

## 1.28.5

### Fixed

- **`brain.disable_device` no longer dies on a device that is its own
  via_device.** The service walks `via_device_id` up to the hub a device
  hangs off, so disabling the last live child disables the lonely parent
  too — and it walked it by recursion. Nothing in Home Assistant makes that
  chain acyclic (`via_device_id` is whatever id an integration reported),
  and `alexa_media` reports every device as its OWN via_device: the walk
  had no end, and the service raised `RecursionError` on each Echo, Wyze
  and Ecobee device it was given, after writing some of the disables. Both
  walks (`disable_device` and `enable_device`) are iterative and carry a
  seen-set now, so a self-reference and a longer A → B → A loop both end
  where they would repeat rather than at the interpreter's stack limit.
  Nothing is lost by stopping there: every device on the cycle has been
  visited by the time it closes.

## 1.28.4

### Changed

- **The Conversations dialog's intro is one line.** The paragraph had grown
  to five sentences and took more of the dialog than the list it was
  introducing. The chips explain themselves on press and the full story
  lives in Docs; the project directory it used to display is still in
  Session details.

## 1.28.3

### Changed

- **"Your chats" is just "Chats".** Under a rail already headed CHATS, the
  possessive answered a question nobody asked; the chip's own tooltip still
  says whose they are (conversations you started — in this chat or the
  classic terminal, including a finding opened for discussion).
- **A finding discussion is titled "Discussing: <the finding>".** A
  conversation's title is its first message, and the discuss prompt used to
  open with the same sentence every time — so a rail of three discussions
  was three copies of "I want to talk about something you flagged…" with
  the finding buried mid-message. The prompt now leads with the finding
  itself, in the rail and in the chat bubble alike.

## 1.28.2

### Fixed

- **"Your chats" is actually yours now.** Two of the worker pool's Claude
  runs never claimed their session ids: the reflection pass that extracts
  facts from voice conversations ("From this smart-home voice conversation,
  extract 0-3 durable facts …") and the one-shot fallback that answers a
  voice request when a stream worker errors ("(Local time: …"). An
  unclaimed id is what "yours" means, so both piled into **Your chats** —
  a person's own conversations buried by the very plumbing meant to sort
  them. Both claim minted ids before running now (reflections under
  *Memory*, fallback turns under *Voice*, with the usual retry for a CLI
  that predates `--session-id`), and a one-time startup pass labels the
  existing backlog by matching brAIn's own shipped prompt openers — your
  list is honest immediately, not in a fortnight when the CLI prunes the
  old files. Genuine chats are never touched: the backfill matches our
  prompts verbatim, nothing a person would type.

## 1.28.1

### Added

- **Card and Fix runs are in the conversation list now, read-only.** Every
  insight run — scheduled or a question you asked — and every Fix-it run is
  a Claude conversation, and until now it was invisible: the engine runs
  them from the add-on's own home directory, so Claude Code filed their
  transcripts where the list never looked. They get chips of their own
  (*Cards*, *Fixes*), and picking one opens a reader showing exactly what
  brAIn sent to Claude about your house, every tool call the run made, and
  what came back. Read-only on purpose: those turns ran under the analyst's
  read-only scoping (or the fixer's), and continuing one under the chat's
  permissions would change the conversation's rules mid-thread. Engine runs
  claim their session ids in the run-sources ledger like every other
  background caller — before the run, so a run that crashes still leaves a
  labelled transcript — and the auth self-check's unclaimed probe is not
  listed at all.

### Fixed

- **Jumping between conversations can no longer land your messages in the
  wrong one.** Two quick picks in the Chats rail raced each other: the
  second pick killed the first one's still-starting process, and depending
  on the interleaving the chat either quietly opened a fresh, invisible
  session or stayed on the *first* conversation while the pane showed the
  second — so everything typed went into a conversation nobody was looking
  at. Switches are serialized now (the last click wins, whole), and
  switching mid-answer is refused with "stop it first" instead of silently
  killing the answer — the same refusal the face switch and the model
  picker already made.
- **Browsing old conversations no longer shuffles the list.** Claude Code
  touches a session file the moment it is resumed, before a word is
  exchanged — and the panel resumes a conversation just to show it. Ordered
  by file time, merely looking at an old conversation shoved it to the top
  stamped "just now". A row's place and age now come from the newest
  timestamped entry in the transcript itself: opening one to look at it
  changes nothing.
- **The conversation you're in is listed again — marked, not hidden.** The
  server excluded the open conversation from the list while the panel
  carried the code to mark it "where you are", so the row you had just
  opened vanished from the rail, which read as the conversation being
  lost. It now shows in both the rail and the ⋯ dialog, highlighted, not
  clickable, and without a delete ✕ (the server refuses that delete
  anyway).

### Changed

- **The chats filter says what it means.** "Yours" is now **Your chats** —
  the conversations you started yourself, in the chat or the classic
  terminal — and the machine chips follow alphabetically: *Automation*,
  *Cards*, *Fixes*, *Memory*, *Study*, *Voice*.

## 1.28.0

### Fixed

- **The usage sensors update every 5 minutes again, and the 429 walls are
  gone with the User-Agent that caused them.** Anthropic's usage endpoint
  sorts callers into rate-limit buckets by User-Agent: the UA Claude Code
  itself sends gets the bucket the whole statusline-tool ecosystem polls
  sustainably, and everything else gets the one that answers 429 after a
  few hours and keeps answering it. The tracker introduced itself as
  `brain/1.0`, which is what every "usage cap nobody hit" actually was —
  and what the 30-minute poll was (wrongly) slowed down to accommodate.
  It now sends the installed CLI's own UA (`claude-cli/<version>
  (external, cli)`, probed from `claude --version`, verified against the
  CLI bundle's `getUserAgent()`), and the poll returns to every 5 minutes,
  so the session percentage tracks within a percent or two of live instead
  of up to half an hour behind. The hour-scale 429 backoff stays as the
  safety net — in the right bucket a 429 is rare enough to mean something.

## 1.27.1

### Fixed

- **`brain memory inbox` and `brain memory clear` are in `brain help` now.**
  Both subcommands existed and were documented on the docs site, but the
  dispatcher's usage text never listed them — and the chat palette is
  parsed from what `brain help` prints, so they could never appear in it.
  `clear` is listed with the `--confirm` it requires.
- **`test_documented_counts.py` names the docs site's real paths.** Its
  failure message pointed at five `src/content/docs/` files that moved to
  `apps/` when the site repo was reorganised.

## 1.27.0

### Added

- **Findings can reach you now.** A critical finding discovered by the 3am
  scheduler used to be completely silent until somebody opened the panel —
  the store lives in the add-on's `/data`, which Home Assistant cannot
  see. The add-on now publishes a mirror of the findings list to
  `/config/.brain/findings_state.json` on every change, and the
  integration builds three things on it: an **Open findings** sensor
  (state = the open count; severity split and the texts as attributes, so
  an automation can put what is actually broken on a lock screen), a
  **`brain_finding` event** per newly-filed finding for automations and
  the logbook, and an optional **push notification** — set
  `findings_notify_service` to any `notify.*` service and
  `findings_notify_min_severity` to the severity that is allowed to ring
  your phone (default `serious`). The store dedupes across every status
  and the settled ledger, so the same problem can never ring twice.

- **`brain findings` — the Findings tab, scriptable.** `list`, `fix`,
  `done`, `wrong`, `ack` and `snooze`, all through the panel's own API, so
  a CLI ending writes the same memory line, settled-ledger key and undo
  token the tab's buttons do. The chat's command palette picks the new
  subcommands up automatically.

- **`brain memory export` / `import` — the learned home, portable.** One
  JSON file carrying the memory document, the findings work list, the
  settled answers and the facts ledger (also downloadable from the Memory
  tab's ⬇ Export button, `GET /api/memory/export`). Import is a
  migration, not a sync: ledgers merge with existing entries winning, the
  memory document replaces only an effectively-empty one unless you pass
  `--replace-memory`, and importing the same file twice changes nothing
  the second time.

- **The scheduler reports itself.** Every category now carries `next_due`
  in `/api/status`, rendered on the card foot ("next in 4 h") so "why did
  my cards stop updating" has an answer on the card instead of one log
  line printed once; `/api/status` also carries the active auto-refresh
  gate (paused / budget reached / not signed in), and the countdown hides
  while a gate holds rather than promising a run that will not come.

- **`/api/health` calls the roll.** The watchdog's liveness endpoint now
  also reports which background daemons are actually running (worker
  pool, listeners, usage tracker, memory consolidator, study watcher,
  ttyd) plus when the last consolidation pass landed — informational
  only, so a dead sibling can never fail liveness and restart-loop the
  add-on. `brain doctor` reads it and compares against its own view.

- **Energy insights lean on Home Assistant's long-term statistics.** The
  analyst is now told explicitly that `get_statistics` reaches back months
  (day/week/month buckets, surviving recorder purges) and is the tool for
  "compared to last week/month" — and the energy category asks for a
  period-over-period anchor instead of extrapolating a month from a few
  days. brAIn deliberately keeps no statistics store of its own: Home
  Assistant already has the sums, so it looks them up.

### Fixed

- **Picking a chat model updates the label under the composer
  immediately.** The label is the only confirmation a pick landed, but the
  event that refreshes it (`init` → `info`) does not arrive until the next
  message — a restarted `--resume` process says nothing until spoken to —
  so the picker looked like it did nothing. The response now carries the
  server-made label (same parser as the info event) and the meta line
  updates on the spot.

- **The four Playwright layout measures now run in CI** (the `layout`
  job) instead of by documented human habit — the two bar shapes, the
  44px target floor, the never-truncated card title, the painted chat
  meta line and the on-screen tooltips are enforced on every PR.

- The facts ledger no longer ships a `remove_fact` function: nothing may
  be deleted from that ledger (deleting is how the analyst re-announces
  what you have already seen), and the one function that could sat there
  called by nothing.

## 1.26.0

### Fixed

- **Usage sensors that went unavailable during a 429 wall now say why —
  and a restart no longer makes the wall worse.** The tracker's rate-limit
  backoff (1/2/4 hours) is deliberately longer than the two-hour window
  after which a reading is too old to trust, so during any streak of 429s
  the four usage sensors *will* go unavailable — that part is by design.
  What was broken: the reason was only written down on the poll *after*
  the reading went stale, which on a four-hour backoff rung is hours
  later. In between, the `Usage tracker` diagnostic sensor said `stale`
  and nothing else — "unavailable for reasons I do not understand". A
  failed poll now records what failed and when it will ask again right
  beside the reading it deliberately left showing, so the moment the
  sensors blank, the diagnostic names the cause (`http_429`, with the
  explanation that this is the endpoint's limit, not your account's
  usage) and `next_attempt_at` says when it retries. And the backoff now
  survives restarts: it lived only in memory, so restarting the add-on —
  the first thing anyone does when sensors go dark — polled the endpoint
  immediately and restarted the ladder from its first rung, retrying
  straight back into the daily meter that caused the outage.

- **A restricted voice assistant could sidestep its service restrictions.**
  Deny-listing `cover.open_cover` did not stop
  `homeassistant.turn_on {"entity_id": "cover.garage_door"}` — Home
  Assistant's meta-services forward to the target entity's own domain, and
  the deny check only matched the spelled name. Meta-calls are now checked
  against their targets and refuse anything touching a restricted domain
  (or targets the check cannot resolve, like whole areas). `fire_event` —
  which can trigger any automation, including one that does exactly what
  the deny-list forbids — is now refused entirely on restricted channels.
  And the one-click deny options now include `brain.*`, so a restricted
  agent can be kept away from the 65 registry-admin power tools
  (including `brain.create_user`, which can mint an admin login).

- **"Voice thinking limit" and "Voice tool access" did nothing in fast
  mode — which is the default.** The worker pool never saw either option:
  it read its environment directly and the values were only written to the
  file the classic listeners re-source. Voice always ran at 5 turns
  (config ships 8) whatever the slider said. Same class of bug as 1.25.2's
  listener fix, in the one consumer that release didn't cover.

- **Voice conversations no longer lose their memory to the pre-warmed
  worker.** A follow-up turn whose worker had been reaped could be handed
  the fresh spare process — which knows nothing — and the stored session
  id was then overwritten, severing the conversation's context for good.
  The spare now only serves conversations that genuinely start from
  nothing; anything with history resumes it, as always promised.

- **Deleting a chat conversation could destroy it while the toast still
  offered Undo.** The trash judged expiry by file modification time, which
  the move into the trash preserves — and a conversation's mtime is its
  last-activity time, routinely older than the 30-minute grace period. A
  just-deleted conversation could arrive "already expired" and be
  unlinked by the very next delete, before Undo was ever pressed. Trash
  entries are now stamped at deletion time, and restore puts the original
  timestamp back so the row keeps its place in the rail.

- **`brain_learned` logbook events now actually fire.** The watcher that
  turns newly-learned facts into logbook entries (documented since it
  shipped, automatable) was never started. Automations triggering on
  `brain_learned` now work.

- **`ha context` always failed.** The dispatcher ran delegated scripts
  with `bash`, which ignores their `with-contenv bashio` shebang — so the
  one delegated script that logs through bashio died with "command not
  found" on its first line, every time. Both dispatchers now exec the
  script itself so its shebang runs it.

- **Automation task notifications never arrived.** The listener posted to
  `notify.persistent_notification` with an `entity_id` key the notify
  schema rejects, so a task with `notify: true` produced a silent 400 —
  no push, no persistent notification, nothing in the log. The requested
  `notify_entity` now picks the notify service, as documented.

- **A failed study session no longer silently doubles its own cost.** The
  study runner misread every failure's exit code as success-shaped, so a
  session stopped by its own timeout triggered a full second session, and
  every failure — auth, rate limit, crash — reported the same unhelpful
  message with stderr thrown away. Failures now report the real reason
  (timeouts by name, anything else with the CLI's own last line), and
  only an old CLI rejecting the session label earns a retry.

- Smaller fixes: two panel writers can no longer silently lose a findings
  update to each other (the store is now locked across read-modify-write);
  the run-sources prune no longer hands the ledger to root and break the
  consolidator's claims until the next restart; the MCP watchdog no longer
  rewrites arbitrary JSON files (chat transcripts included) that merely
  mention `/api/mcp`; notebook edits are now snapshotted before Claude
  changes them so `brain undo` covers them; a malformed terminal handoff
  no longer kills the terminal session at open; a malformed JSON body to
  the findings endpoints gets ignored instead of a 500; a chat stream that
  falls behind now reconnects to a fresh snapshot instead of idling
  forever; `brain.study` is unregistered with the rest when the last
  config entry is removed; a multi-agent install can turn conversation off
  on the entry that still owns the sensors; `memory_max_kb`'s fallback
  agrees with the shipped default.

## 1.25.2

### Fixed

- **"Automation thinking limit" and "Voice thinking limit" did nothing.**
  Whatever you set them to, automation tasks ran at 10 turns and voice ran
  at 5 — the values the add-on falls back on when it can't read your
  settings at all. The settings were saved correctly and written where the
  listeners could find them; the listeners just read the number a moment
  before that file was loaded, so they kept the fallback and never looked
  again. The only visible sign was the `MaxTurns:` line in the automation
  log, which reported the number actually used, not the one you chose.

  This is why an agentic task — anything that searches the web, reads
  several entities, then writes something — would stop early and answer
  with whatever it had. Ten turns is tight for that kind of work, and
  `automation_max_turns` now genuinely ships at 30.

  Study sessions (`/learn` run from the terminal rather than on a
  schedule) had the same fault, so `study_max_turns` and
  `study_timeout_minutes` were ignored on that path.

- **The fallbacks disagreed with the documented defaults.** If the add-on
  ever can't read its saved environment, the listeners now fall back to
  the same numbers `config.yaml` ships (30 and 8) rather than to older,
  lower ones — one answer per setting instead of a second one that only
  appears when nothing is watching.

## 1.25.1

### Fixed

- **The model picker looked like it did nothing.** Choosing a model —
  under the chat box, in ⋯ → Model, or in ⚙ Settings — always did change
  the model that answered you. What it didn't change was the name printed
  under the composer, which is the only place you can see which model is
  running. The panel worked that name out with a pattern that dropped the
  minor version, so Haiku 4.5 read as "Claude Haiku 4" and Sonnet 4.6 as
  "Claude Sonnet 4": any two models of one family printed the same thing,
  and swapping between them left the screen unchanged. (An older id like
  `claude-3-5-sonnet` fared worse — it read the date stamp as the version
  and reported "Claude Sonnet 2".) Names now come from the add-on itself,
  off the model Claude Code reports it resolved.

- **The context percentage kept the old model's window after a switch.**
  Your conversation carries across a model change, so the token count is
  still right — but the window it's measured against belongs to the model.
  Switching to Haiku left the pill dividing by Sonnet's 1M and reporting
  4% of a window it was 21% into, until some later reply happened to
  correct it. It's recalculated the moment the new session starts.

- **The picker's "Default" row named the wrong model.** It read the global
  model once, when the Terminal tab opened. Change that model in ⚙ from
  the same tab and the row — the highlighted one, whenever the chat has no
  override of its own — went on naming the model you had just replaced.

- **The model popover jumped to the corner of the screen** if the window
  resized while it was open from ⋯ → Model. It closes instead.

## 1.25.0

### Added

- **When Claude has a question, the chat shows the question.** Claude Code
  sometimes asks multiple-choice questions mid-task (`AskUserQuestion` —
  which zone did you mean, which approach do you prefer). Those arrived as
  a generic "may I use AskUserQuestion?" permission card, and allowing it
  sent the tool an empty answer sheet that broke the turn. The chat now
  renders the questions themselves — tap an option, pick several where the
  question allows it, or type your own answer — and the answers ride back
  on the CLI's own wire (`updatedInput.answers`, the same contract its
  interactive picker uses). **Don't answer** tells Claude to use its best
  judgement, and renders amber, not as a crash.

- **Unknown control requests are answered, never dropped.** A
  `control_request` is a question the CLI is waiting on; one from a
  feature this panel has never heard of used to disappear into silence,
  which from the chat looked like Claude thinking forever. Anything the
  panel does not implement now gets an error response back so the CLI can
  fail that one feature and carry on with the turn.

- **Delete several conversations in one pass.** A checklist button above
  the chats list — in the rail and in ⋯ → Conversations — turns on
  selection mode: checkboxes per row, **Select all**, and one **Delete**
  with a single Undo that puts the whole batch back. The open conversation
  is skipped and reported rather than failing the batch, and a batch is
  capped at what the trash can restore.

- **The self-test covers the parts that failed quietly.** `brain doctor`
  now also checks: the panel and chat API are answering (with the chat's
  error text when a session failed to spawn), the terminal's password gate
  is actually on (an unauthenticated 200 on :7681 is a FAIL, not a
  curiosity), the Claude CLI itself runs, the usage tracker / memory
  consolidator / study watcher daemons are alive, the run-sources ledger
  is claude-owned (root-owned means background runs get filed as yours,
  silently), a crashed consolidation pass still holding the lock, disk
  space on /data and /config, and how stale the usage reading is.

### Fixed

- **The generated `/config/CLAUDE.md` stopped promising git backups.** It
  still told Claude "YAML edits are auto-backed up via git (if
  auto_backup is enabled)" — a feature removed releases ago — so Claude
  repeated it to people as if it were true. It now teaches what actually
  exists: edits are snapshotted before Claude makes them, and `brain
  undo` reviews and reverts them. (Regenerates on restart, or run
  `ha context`.)

- **The self-test's "tracker polls every ~2 min" hint** predated the
  30-minute poll and sent people waiting on a cadence that no longer
  exists.

## 1.24.0

### Added

- **The chat asks for permission instead of failing silently.** Headless
  Claude Code cannot put a prompt on a TTY, so a tool call outside the
  pre-approved set never ran and the answer was written around the gap —
  the main reason chat answers came up short of the terminal's. The same
  question now arrives as a card in the conversation (what tool, aimed at
  what, **Allow once** / **Don't allow**), carried over the CLI's own
  control channel — the wire the Agent SDK rides. Everything already
  allowed in `settings.local.json` still runs without asking; an
  unanswered card declines itself after ten minutes and says so; a CLI too
  old for the channel just gets the old behavior back.

- **Thinking streams live.** The chat only rendered reasoning when the
  message closed, so a long think was minutes of dots followed by the
  reasoning delivered after its conclusion. Thinking deltas now stream
  into the "Thinking" line as they happen, exactly like answer text.

- **A status line for the whole turn.** The three dots vanished on the
  first token, leaving a tool-heavy minute looking hung. The line now
  stays for the turn and says what Claude is doing — thinking, writing,
  which tool is running, waiting for your approval — with elapsed
  seconds, like the native CLI's bottom line.

- **The docs say why chat sessions don't show in the Claude app.** The
  app's "connected" sessions ride Remote Control, which only supports
  interactive sessions — a Claude Code limitation, not a setting. The
  session popover and the guide now say so, and point at the face switch,
  which moves the same conversation into a terminal session that can
  register.

### Fixed

- **The chat's model picker could apply nothing.** "Is a restart needed"
  was answered by comparing a pick against the panel's *intent*, which is
  refreshed from settings on every request — so after a ⚙ edit the picker
  said "already that model" about a live session still running the old
  one, and a long-lived session never respawns on its own. Every model
  question is now asked of the model the process was actually spawned
  with; a change made anywhere lands on the next message at the latest,
  and `--model` stays on the argv across `--resume`, because a resumed
  session otherwise keeps the model it remembers.

- **Hitting the session turn limit no longer dead-ends the conversation.**
  The cap guards against runaway loops but spans the process, and the old
  answer — "start a new chat to carry on" — charged the person's
  conversation for it. The next message now restarts the CLI with
  `--resume`: the counter resets, the conversation carries on.

- **A session error with a stderr tail could crash the refusal.** The
  message went into an HTTP reason line, which cannot carry newlines, so
  "the session died" surfaced as a 500 about carriage returns.

## 1.23.0

### Added

- **The chat picks its own model.** Press the model name under the composer
  — or ⋯ → Model before a first message has put it there — and choose from
  the same list ⚙ Settings offers. The choice is the chat's own
  (`chat_model`): it never touches the global model option, so the insight
  runs and the listeners keep costing what the Configuration tab says.
  Applying it restarts the CLI with `--resume`, so the conversation carries
  straight across.

- **Conversations can be deleted.** Every row in the Chats rail and the
  Conversations dialog grows a ✕, and the toast grows an Undo — the file is
  moved into a short-lived trash rather than unlinked, so a mis-tap puts
  back exactly what was taken. The conversation that is open is refused
  ("start a new chat first"), and nothing ever edits the CLI's own files:
  deleting a whole conversation is the one mutation, and it is a move.

### Fixed

- **Opening an old conversation could leave a chat that errored on every
  message.** Claude Code prunes old sessions from its store; resuming one
  it no longer holds spawned a CLI that died silently, and the kept resume
  id respawned the same failure forever — which surfaced as "sometimes old
  conversations won't open". The spawn is watched until the CLI says its
  first word now: a resume the CLI refuses drops the id, says so in the
  transcript (the replayed history stays on screen), and opens a fresh
  session, and the panel tells you the context is gone rather than letting
  the next answer reveal it. A fresh session that dies on startup reports
  the CLI's own stderr instead of a shrug.

- **The model and context line under the chat was clipped — at every width,
  and worst on a wide screen.** The Terminal view cancels the page padding
  with negative margins, and a leftover negative *bottom* margin shortened
  the page wrapper, whose `overflow: hidden` then swallowed the bottom
  ~20px of the view: exactly where "Claude Sonnet 5 · 132k / 1000k context"
  lives. A second 6px came from scoping those margins to the top bar's
  breakpoint instead of the one the padding actually changes at. Both are
  fixed, and `tests/manual/measure-chatmeta.mjs` now measures the line with
  `elementFromPoint` — painted, not merely positioned — so it cannot
  quietly go under again.

## 1.22.3

### Fixed

- **The usage sensors worked all night and died by mid-morning.** 1.22.2 cut
  the requests per poll from six to one and slowed the poll from two minutes
  to five, and the sensors still hit a wall of 429s every day — recovering
  at roughly the same hour each night.

  That nightly recovery is the tell. A burst limit clears in minutes; a
  limit that comes back at a fixed hour is a **daily allowance**. And the
  arithmetic matches exactly: nine working hours at a two-minute poll is
  about 270 requests, which is the reported window almost to the minute. The
  previous fix stopped brAIn from *sustaining* a rate limit, which was real,
  but against a per-day cap the only lever is how many requests a day costs.

  The poll is now every **30 minutes** — 48 requests a day instead of 288,
  or the ~4,300 the six-per-poll version could reach. What that costs is
  resolution nobody can see: the five-hour window moves about 1% every three
  minutes at a hard sprint, so a half-hourly reading is never more than a
  percent or two behind, and a sensor slightly behind all day beats one that
  is exact until 10am and unavailable after it.

  The 429 backoff moved from 15/30/60 minutes to **1/2/4 hours** to match.
  Every step must now exceed the poll interval, which is a rule with a test
  behind it: lengthening the poll and leaving the backoff alone would have
  meant a *failing* tracker asking more often than a working one — the exact
  behaviour a daily cap punishes hardest.

## 1.22.2

### Fixed

- **The usage sensors reported a rate limit brAIn had caused itself.** They
  went unavailable with `http_429`, which reads as "you have used up your
  quota" and was nothing of the sort — the *usage endpoint* was refusing to
  answer, with plenty of quota to spare.

  brAIn was asking it six times per poll. The tracker tries each credential
  store in turn, so a token the server refuses gives way to the next one
  rather than speaking for a sign-in that would have worked. But it offered
  a credential per *path*, and the paths are the same file: the add-on
  exports `CLAUDE_CONFIG_DIR` as `/data/home/.claude`, which makes the first
  two identical strings, and symlinks the other two together. One sign-in,
  four identical requests with no pause between them, then two more from the
  panel and `ha login` stores usually holding that same token — every two
  minutes, all day.

  That endpoint is undocumented and limited far harder than anything else
  brAIn touches, and a token hammered on it starts answering 429 and keeps
  answering 429 long after the window that supposedly caused it. Claude Code
  itself only ever calls it when you open its `/usage` screen, never on a
  timer.

  A credential is now offered once however many paths lead to it, so an
  ordinary poll is one request. A 429 is treated as the one failure that
  retrying makes worse: it waits 15 minutes, then 30, then an hour, instead
  of poking the endpoint every five minutes forever and keeping it tripped.
  The endpoint sends `Retry-After: 0` while still refusing, so that header
  can only ever make brAIn wait *longer*, never sooner. The poll itself
  settles at five minutes.

  A rate limit never blanks numbers that are still good — it says nothing
  about your sign-in, so the last reading ages out normally. And the
  **Usage tracker** sensor now carries a `detail` explaining that `http_429`
  is the endpoint's limit and not your account's, because the code on its
  own is read as the thing it isn't.

## 1.22.1

### Fixed

- **Two things saving at once could lose one of them.** Every store in the
  panel wrote its file the same way — write `findings.tmp`, then rename it
  over `findings.json`. That is safe against a *reader*, and exactly wrong
  against a second *writer*: the scratch name is derived from the target, so
  every writer picks the same one. Two writers both create `findings.tmp`,
  the first rename moves it, and the second finds its own file gone. One
  raises, and **the other's write is silently lost** — its bytes went into a
  file the winner had already renamed away.

  It was reachable: pressing **Fix it** writes the findings store from the
  web request while an insight run writes the same store from the
  background worker. Those genuinely overlap, and the loser was whichever
  got there first. The same pattern was in all seventeen places the panel
  saves a file — settings, memory, findings, hypotheses, usage, tags,
  prompts, the chat transcript, insight cards and their history.

  Saving now uses a scratch name nobody else can pick, so concurrent saves
  cannot collide. Two details came along with it, both of which the old code
  got for free and a naive fix would have broken: the file keeps the
  **permissions** it had (several are written by the add-on as root and read
  by the `claude` user, so quietly narrowing them would break the terminal
  and the listeners), and it keeps its **owner** where the add-on is allowed
  to give it away — the old rename silently took `/data/run-sources.jsonl`
  away from the `claude` user every time it pruned.

  Files are also flushed to disk before the rename now, so a power cut
  during a save can no longer leave a file that exists and is empty.

## 1.22.0

### Added

- **Every card now says what it cost.** Generating an insight is the most
  expensive thing brAIn does — a snapshot of your home goes to Claude and a
  whole rendered visualization comes back, typically 25k–45k tokens a card —
  and until now the only evidence of that was the usage pill moving, with
  nothing on screen saying which card moved it. The numbers were already
  coming back from every run and were only ever used to add to a total.

  They are now readable in four places, all reporting the same figure:

  - **While it runs**, the card's spinner line reads `500 entities · ~33k
    tokens sent`, so the size of a run is visible before its answer is.
  - **After it runs**, the card's footer shows `41.2k tokens` beside the
    stopwatch, with the input/output split behind a hover. Seconds and tokens
    are different readings — a fast card over the whole home outspends a slow
    one over eight thermostats.
  - **Across the window**, the usage pill's popover itemizes *What brAIn
    spent, this session*, per card, biggest first.
  - **In the add-on log**, one line per run: `custom-1785807758 cost 41.3k
    tokens (33.2k in + 8.1k out; 0 read from cache, free)`, plus the prompt's
    size as it goes out.

  The itemization is scoped and says so: these are brAIn's own generation,
  fix and setup runs. When the percentage above it is your account's live
  figure it covers your whole subscription — terminal, chat and voice
  included — and a breakdown read as exhaustive is how you conclude a
  terminal session is free.

- **A card now fetches what it needs instead of being handed the house.**
  ⚙ Settings → **How a card gets its data**, and Search is the new default.

  Claude gets a *map* of your home — how many entities of each kind exist,
  which areas they're in, a few anchors like people and thermostats — plus
  **read-only** Home Assistant tools, and it goes and looks up what the card
  actually needs: search by room or by name, read the few entities that
  matter, pull their history. A question about the hallway costs the
  hallway. Measured on a real run: a 1,449-character prompt where the old
  path sent about 100,000.

  It is also the only mode that can afford **history on a question you
  type**. The one-shot path never could — there was no budget left after
  five hundred entities — so typed questions have always been answered from
  a single instant with no trend behind it.

  **Snapshot** is the old behaviour, kept as a setting *and* as the
  automatic fallback: if a search run fails or runs out of turns, brAIn
  falls back to the full snapshot so a card always appears. The fallback is
  logged rather than silent, because a run that keeps taking it is worth
  knowing about.

  **Insight runs can only read.** The analyst's tools are an explicit
  allow-list of the reading half of the Home Assistant MCP server, and every
  acting tool is explicitly denied as well — belt and braces, because
  `--allowedTools` governs what runs without a prompt and a headless run
  cannot be prompted, so an un-listed tool merely *fails* rather than being
  forbidden. Those are not the same guarantee with a real house on the other
  side. `tests/test_security.py` checks the deny list against the MCP
  server's own tool list, so adding an acting tool and forgetting this fails
  in CI rather than in somebody's home. The one path that changes anything
  is still the Findings tab's **Fix it** button, which a person presses.

### Changed

- **A card's data snapshot got 29% smaller, and lost nothing.** A question
  sends every entity in the home, so a character on one row is 500 characters
  on the prompt — and three fields were paying for something nobody read:

  - `lc` is now **minutes since it last changed**, not a 19-character ISO
    timestamp. Staleness is the only thing last_changed was ever read for, and
    the model had to diff the timestamp against `meta.now` to get there.
    Minutes rather than hours because "6 minutes ago" and "an hour ago" are
    different facts and cost the same to say.
  - `n` is **dropped when it is just the entity_id prettified**, which is what
    Home Assistant names an entity by default — a second copy of a string
    already on the row. A renamed entity still carries the name.
  - an **unavailable entity keeps only its id, state and area**. Its unit and
    device class describe a reading that isn't there.

  Measured on a 500-entity home: 72,943 → 52,086 characters, roughly 5k fewer
  input tokens on every card and every question.

- **The docs now say what a card costs**, and which kind is expensive. A
  category card sends that category's slice of the home; a question typed
  into the ask bar sends *every* entity plus device context, because the
  question could be about anything — which is why a few asked questions can
  cost what a dozen scheduled refreshes do. Settings & cost lists it as the
  first lever, above the scheduling ones.

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
