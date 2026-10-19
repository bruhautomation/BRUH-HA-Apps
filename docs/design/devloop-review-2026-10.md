# The development loop, reviewed: what closes it and what is still open

*October 2026. A review of brAIn's and Morph's learning and error-reporting
machinery against the question "can the loop run without a person in it,
and would we know if it stopped working". Read with
[`devloop.md`](devloop.md) (the design) and
[`brain/DEVLOOP.md`](../../brain/DEVLOOP.md) (what a user sees).*

## The shape of the loop today

```
 house ──faults/wrongs/scorecard/look/screens/morph──► private repo ──► routine
   ▲                                                                       │
   │  verdict labels, "Fixed in brAIn x.y.z" ◄─────────────────────────────┘
   │                                                                       │
   └── auto-update ◄── merged PR ◄── CI + devloop-guard ◄── batched fix ◄──┘
   │
   └── "Not seen since" / "Back again" / "Still happening" ──► routine (next run)
```

Eleven streams on the house, a cloud routine that drains every open issue
to a closed one, a guard that holds what a model is not trusted to keep,
and three follow-up sentences that let a fix be judged on the house it
came from. That is already most of a closed loop, and the recent work
(3.0.9: follow-ups only when something is new) fixed the loudest failure,
which was every update reopening every issue.

## What was open, and what this change closes

Each of these was a seam where the loop relied on silence or on prose
where it needed a fact. Ranked by how much of the loop ran through it.

### 1. The fix version never came home (closed)

The routine writes `Fixed in brAIn x.y.z` and the house read nothing off
it. Two consequences, both measured against the shipped code:

- A fault still seen on a release **older** than the fix reopened the
  issue a day after any unrelated update (`persisted` keyed on "a release
  first seen after the close", not on the fix's release). A house running
  3.0.9 with a fix in 3.0.10 reopened it on 3.0.9.
- A house with auto-update off, or one update behind, was read as a house
  where every fix held. Silence was success.

Now: the version is read off the closing comment once, compared with the
release the house runs, and a fixed report on an older release says
nothing. Installed and gone, the house says **Held**. Not installed, the
wait is counted in ⚙ and on the scorecard body the routine reads every run.
The routine is told, in the skill, that this comment's opening is parsed.

### 2. The owner's own request was never verified (closed)

A `look` report is the owner's words. It has no fingerprint that stops, so
after "Fixed in" nobody — not the house, not the routine, not the owner —
ever learned whether the person got what they asked for. `Done when:` was
the bar and nothing held the fix to it where it mattered.

Now: once the fix's release is installed, one question on Today. Yes posts
a confirmation; No posts the owner's words and reopens. Asked once per
fix, only for `look` and `unmet` (a quiz about a model's own gap would be
noise), settled under its own kind so no scorecard counts it, no memory
line. The skill treats *Not fixed on brAIn x.y.z* as the strongest evidence
it has.

### 3. A fault issue carried a sentence and no evidence (closed)

`Run (card): ended crash` plus 400 characters of detail. The fixer had to
find the traceback by guessing which run, which day, which file. Problem
files on the house had the log tail the whole time, redacted, and the loop
never attached them.

Now: the journal rows behind a run fault (when, which job, the error's own
words) and the trouble lines of the add-on log ride the issue body,
redacted and aliased, and the body is rewritten on *Still happening* so
the excerpt is current.

### 4. The panel's own crashes were invisible (closed)

An unhandled exception in a route was aiohttp's 500 and its logger's
traceback. No journal row, so no fault row, no problem file, no issue. The
one failure class the panel could not report was its own. Now a middleware
journals it (route pattern, exception, deepest panel frame), spaced per
route and type, and every other surface picks it up by the doors they
already have.

### 5. The Resident's judgement reached the cloud through nothing (closed)

`outcomes.py` grades every first look and investigation against what the
household did next, nightly, deterministically, and writes judgement facts
the Resident reads. The scorecard stream grades the *checks*; nothing
graded the *model's* calls where a developer could see it. The `outcomes`
stream files one keyed issue per lopsided scope with the look's reasons and
the typed notes, and clears when a confirmed case ends the pattern. Off by
default, because it quotes what a person typed.

### 6. Morph's service faults stayed in the log (closed)

Morph's ledger held what the panel reported (a card that threw, an overlap)
and the service's four `except` blocks logged and moved on. A request loop
failing every poll never reached brAIn's `morph` stream. `note_exception`
files each with its frame and traceback.

### 7. "Failing test first" was prose (closed)

The skill says it; two subagents in one run ignored it and changed tests
instead (LESSONS.md, 2026-10-18). The guard now fails a `devloop/` PR that
changes code with nothing under `tests/`. Copy, layout and docs are exempt.

### 8. The cloud half's health was unobservable from the house (closed)

If the routine stopped running, the house saw open issues and nothing
else. `cloud_last_seen` (the newest close among read-back verdicts) rides
`/api/devloop` and ⚙'s line.

## What is still open

In the order I would do them.

1. **Regression detection is prose.** The skill tells the routine to
   revert on "a drop of 20 points in a producer's share right". Nothing
   computes it: the scorecard is all-time, settled entries carry no
   release, and a release-over-release comparison needs the house to
   record which release each ending was given on. One field on the settled
   entry (`version`) and a per-release tally on the scorecard body would
   make the revert rule a number the routine reads rather than two issues
   it compares by eye. The `outcomes` stream has the same gap one level
   down: a look's verdicts carry `run_id` but not the release.

2. **The corpus never sees a real house.** Checks are graded on two frozen
   fixture houses. A Wrong from a real house arrives as a sentence, and
   the fixer rebuilds a fixture from the sentence. An opt-in export of the
   *aliased checks snapshot* (states and registries, ids and names
   through the same alias map, numbers intact) as a corpus entry would
   let the routine replay the rule against the house that marked it
   wrong. The privacy cost is real and is the reason it stays a separate
   switch; `screens` already crosses a bigger line.

3. **The routine's run record is a sentence in LESSONS.md.** "~8h wall
   clock, about 95 closures" is written by a model each run. A JSON line
   per run (duration, closures by verdict, held vs came-back, PRs, the
   slowest step) in the lock issue's closing comment would let the house
   show the other end's health as numbers, and let "fixes that held /
   fixes that came back" be a score rather than a feeling. The skill now
   asks for the pair in prose; the structured form is the next step.

4. **Lessons are applied by being read.** CLAUDE.md and LESSONS.md are the
   loop's memory, and they work because the routine reads them at the
   start of every run. Some lessons are enforceable and should move to
   the guard or to CI as they recur: "always pass `commit_title` on a
   squash merge" cannot be, but "a test file that already existed was
   changed" can (a guard rule on modified lines in existing test files,
   distinct from the deleted/skipped rules it has).

5. **The owner's question could carry a picture.** For a `devloop:ux`
   report, the question "is it fixed?" would be answered faster with the
   house's own Screens capture of that pane from the new release beside
   it. The pieces exist (`screens.py`, the capture names); it is a join.

6. **Morph's learning loop is per house, and that is right**, but its
   `code_reports` (gaps the pass noticed in Morph's own code) still need a
   press to leave. Once the verdict channel shows Morph suggestions are
   mostly accepted, that press could become review-mode-only, the way
   brAIn's own streams are.

## What was deliberately not done

- **No second judge on the house.** The verify question is asked, not
  inferred: a model deciding "this looks fixed" on the owner's behalf is
  the error the loop exists to catch.
- **No reach through the guard.** None of this touches
  `needs_human_paths` from a `devloop/` branch; it was done by a person
  and lands through an ordinary PR, which is what the guard exists to
  distinguish.
- **No new option.** Everything here is a panel setting or a stream switch
  under the existing master switch.
