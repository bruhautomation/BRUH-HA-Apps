# What the development loop has learned

The fixer (`SKILL.md`) reads this before every run, and the weekly retro
adds to it. Each bullet is dated, short, and says what failed and why.
A lesson that every contributor should follow belongs in `CLAUDE.md` as
well.

Last retro: 2026-10-20
Last UX audit: 2026-10-18

## Lessons

- 2026-10-07: Before the loop's first run. The repository's own `CLAUDE.md`
  is the record of every mistake this add-on has already made; most fixes
  are an existing bullet there applied in a new place.
- 2026-10-07: First UX audit. A `display` set on a class beats the `[hidden]` attribute, so an empty hidden container (`.kclean`) drew as a bar in Memory › Knowledge. When a container is toggled with `hidden`, check that its class does not set `display`.
- 2026-10-08: Run 1 took 7.5 hours for 10 batches, and "the tests time
  out" was the Bash tool, not the suite: it kills a command at 120s by
  default, and the serial suite is 6m15s, of which two thirds is sleeping or
  waiting on subprocesses (2m10s CPU). A batch also ran the suite up to four
  times (subagent, run, CI on the PR, CI on main). Now: the subagent runs
  `tests/affected.py --base origin/main --run`, the run runs
  `python3 -m pytest tests -q -n 4 --dist loadfile` (1m41s) with the Bash
  `timeout` raised or in the background, and always `python3 -m pytest`,
  because the bare `pytest` on PATH cannot see the dependencies.
- 2026-10-09: A test that replaces a module function and registers
  `addCleanup` AFTER the replacement restores the fake, not the original,
  and the leak fails an unrelated class later in the same worker
  (`SceneDesignCase`). Register the cleanup with the original first.
- 2026-10-09: `test_bright_addon` and BRUH Print's tests both import a
  top-level `stores` package; on one xdist worker the first loaded wins and
  the other fails. A failure that passes alone is worth checking for this
  before calling it a flake.

- 2026-10-09: Every add-on update makes the house comment "Back again"
  on every faults issue whose row it still holds, all in the same second,
  with "last seen" in the house's local time (UTC−4) at that moment. Before
  calling one a regression, ask what the row reads: a 24-hour journal
  window still holds pre-fix runs, a scorecard's all-time Wrong count never
  falls, and only a live count (like waiting looks) present after the fix is
  evidence. The body is not refreshed, so a live row's new detail is not
  visible from here.

- 2026-10-09: A `[Producer …] ignored N of M times` fault reads the
  all-time scorecard, so it keeps reporting after the rule is fixed. Compare
  the Wrong count with the last `[Scorecard]` issue from before the fix:
  only a Wrong count above what the fixed cause explains is new evidence.
- 2026-10-10: A stray real `/config/.brain/memory` left in the cloud
  container by an earlier run makes `test_task_failures`' memory test fail
  locally on `main` too; check a local-only failure against `main` before
  chasing it. Every add-on update still re-opens every fault issue whose
  row it holds (nine this run, all re-stamps); the house side of that is
  in `brain/panel/devloop/`, a person's file.

- 2026-10-12: Never `pkill -f <pattern>` in the same Bash command as anything else: the pattern matches the shell running the command, which kills itself (exit 144) and whatever it was about to start. Three suite runs were lost that way.
- 2026-10-12: The full local suite (`-n 4 --dist loadfile`) hung in this container for 30 minutes with no output, while CI ran it in under two minutes and each batch's `tests/affected.py --run` (2–6k tests) passed in 1–2 minutes. When the local full suite stalls, ship on the affected run and let CI be the gate rather than burning the session.
- 2026-10-12: `test_devloop_screens`' real-browser test failed twice in CI with "Chromium did not start" before any assertion: a cold Chromium start on a loaded runner exceeds the 15 s budget in `screens._launch` (a person's file). The test now warms the browser once, untimed. If it still flakes, the budget itself is a `needs-human` change.
- 2026-10-12: `sec.*` checks file at `info`, and `answers.chip` read every `info` row as a Tidy-up, so security findings were folded away with unused helpers. A severity is not a category; the chip asks the source too now.
- 2026-10-13: Run `devloop_guard.py` AFTER committing: it reads committed changes only, so a guard run on a dirty tree said ok while the commit edited `brain/panel/devloop/upstream.py`, and CI's devloop-guard caught it. Check every path you are about to edit against `needs_human_paths` before editing, not after.
- 2026-10-13: A "Back again" whose last sighting is older than the close is a re-stamp, not a recurrence: `upstream._follow_up` reopened on any version change (#246).
- 2026-10-19: Fixed at the source in brAIn 3.0.9 (a person's change): a not-brain, duplicate or declined report is never reopened or commented on; a fixed one reopens only when its fault went away and came back after the close, or lasted a day on a release first seen after the close; a newer scorecard closes the older; a still-happening report's body is rewritten with the current numbers; Morph rows carry when they last happened. From 3.0.9 on, a "Back again" is evidence: read it, do not re-close it on reflex. A reopen on a house still running 3.0.8 or older is still the old re-stamp.
- 2026-10-19: A `[Producer …] ignored N of M` fault now drops out once nobody has marked the rule Wrong for 14 days (`reports.SCORE_RECENT_S`), so a fixed rule's report goes quiet and the house says "Not seen since" two days later.
- 2026-10-13: A Morph panel serving `/morph_static/0.1.0/` (or any version older than the add-on) is Home Assistant still running the old integration: a restart is pending, not a Morph bug.
- 2026-10-13: Morph reports whose fix is in code that exists only in the house's own copy of a frontend module (#242), or that ask for a new rendering architecture (#243), are a person's design call; close them not_planned with needs-human rather than building the feature in a batch.
- 2026-10-18: Two subagents made a fix pass by changing an existing test (one moved a fixture, one rewrote an assertion) even though the prompt forbade it. Both changes were reverted and those items handed to a person. Before shipping, run `git diff --stat origin/main -- tests/` and read every line changed in a test file that already existed.
- 2026-10-18: `merge_pull_request` with no `commit_message` squashes every commit message on the branch, so the message of a change dropped later in review (the history-cutoff change in #437) landed on main. Always pass `commit_title` and `commit_message`.
- 2026-10-18: CI's Python tests job hung for six hours after an xdist worker died ("node down: Not properly terminated"). The full suite passed locally in two minutes and the one re-run passed. Read a cancelled job's log for "node down" before looking for a code cause.
- 2026-10-18: Reports filed against a version older than the fix are not current. Check the `brAIn` row of the report's table before fixing anything, and close a report that a release since then already fixed as a duplicate of the issue that fixed it.
- 2026-10-20: "run found error, return N, exit…" in a Bambu Studio slice log is the CLI's `flush_and_exit` signing off, not the reason. The reason is the `[error]` lines before it. A fix written to that line could not have been aimed (#328), so read what comes before a sign-off before naming a cause, and say in the PR when the cause is still unproven.
- 2026-10-20: A picture whose `src` is swapped blanks for a frame even when the new URL is already decoded somewhere else. A live feed needs a second element behind it, swapped once it is decoded. A measure that samples an image has to wait for `complete && naturalWidth > 0`, because a lazily loaded one reads as blank.
- 2026-10-20: Two fixes (#327 late ignore, #322 unattributed rhythm) were blocked by existing assertions that pin the old behaviour (test_resident_unjudged.py:63, test_open_row_look_reason.py:60, test_rhythm.py:110). They were handed to a person with the test lines named, not worked around. When the fix the owner wants contradicts a pinned test, the person decides which one is right.
- 2026-10-20: `test_bruh_print_atomic_write`'s race test asserts that the OLD recipe loses a write. Under a loaded `-n 4` run the two threads may not interleave, so it can fail on a branch that never touches BRUH Print. It passes alone; treat it as scheduling, not a regression.

- 2026-10-23: A test that reads or writes under `/data` passes alone and fails beside another that left files there (two `test_usage_tracker` renewal tests). Before reading a local-only failure as a regression, run the file alone; a fix for it isolates the path, never skips the test.
- 2026-10-23: `devloop-guard` refuses a new `skipIf`. A test that depends on an optional library (zoneinfo data) needs a fallback that keeps it running, such as a fixed-offset timezone, not a skip.
- 2026-10-23: CodeQL comments land on a pull request after it merged (import cycles, mixed import styles, a statement with no effect). Check the last merged PR's threads at the start of each batch and fix them in it.
- 2026-10-23: After a squash merge, merging `main` into a follow-up branch conflicts on the branch's own earlier changes. Take the branch's side for those files and confirm `git diff origin/main` shows only the new work.
- 2026-10-23: The house filed two issues under what looked like one fault (#358, #365); worth checking whether its fingerprint splits a fault whose wording moves.

## Loop health

One line per run: date, duration, issues by ending, slowest step.

- 2026-10-08/09: ~10h, 20 issues closed: 16 fixed (PRs #380, #381, #382 and batch 4), 2 already fixed, 1 duplicate, 1 not brAIn; 6 rolling/evidence left open by design. Slowest step: the UI batch subagent (17 min) and waiting on CI.
- 2026-10-09: ~3h this session (resumed run), 10 issues closed, all fixed (PRs #385, #386, #387 and this batch), 2 of them filed by the UX audit and fixed in the same run; 6 rolling/evidence left open by design. Slowest step: the Opus UI batch subagent (16 min); a worktree branch mix-up cost one re-push.
- 2026-10-09 06:00: ~15 min, 6 reopened faults closed with no code change: 3 re-stamps of rows still inside their window or count (#137, #117, #116), 1 duplicate count (#5), 1 not brAIn (#4), 1 handed to a person after three fixes did not clear a live count (#82). UX audit skipped: already done today on this same main. Slowest step: reading the reopen history.
- 2026-10-09 06:30: ~15 min, 1 issue closed with no code change: #146, the frozen-sensor rule's all-time Wrong count, explained by the battery-voltage cause fixed in 2.18.3. UX audit skipped: already done today on this same main. Slowest step: tracing which Wrongs predate the fix.
- 2026-10-09 16:00: ~3h, 9 issues closed as fixed (PRs #395, #396 and batch 5: #149, #152, #154, #155, #163, #164, #166, #167, #168); rolling/evidence left open by design. Slowest step: the Opus UI subagents (~22–25 min) and re-running CI over the screens Chromium start-up flake.
- 2026-10-10 20:30: ~1h, 30 issue closures: 9 fixed (PRs #399, #400, #401), 2 of them filed by the UX audit; 15 re-stamped faults closed as before (10 on the 2.18.15 update, 5 more when 2.18.17 landed mid-run); 2 duplicates, 1 not brAIn, 1 declined, 1 handed to a person (the `get_history` half of #172; its panel half fixed). Slowest step: the Opus writing batch (26 min) and #401's two CI cycles on the screens Chromium start-up failure (passed on re-run; no local repro).
- 2026-10-12 13:30: ~3h, 43 issue closures: 22 fixed in PRs #405, #406, #408, #410 and the last batch (3 filed by the UX audit, 2 the owner's own requests), 16 re-stamped faults closed as before (11, then 5 more after the 2.18.2x updates), 5 handed to a person (#186 healing.py, #196 the MCP server's error log, #210–#212 in the Morph add-on, which the skill does not let the loop touch). Slowest step: the subagents (19–24 min each) and #406's three CI cycles on the screens Chromium start-up and a missing `except` comment.
- 2026-10-13 11:00: ~5h, about 50 issue closures: 14 fixed (PRs #425, #426, #427, #428 and this Morph batch), 2 handed to a person (#242, #243) plus #246 filed for the re-stamp bug and #82/#227 earlier, the rest duplicates, not-brAIn and re-stamped faults re-closed after each update. Retro done. Slowest step: the Opus subagents (9-17 min) and one CI cycle lost to devloop-guard on a person's file.
- 2026-10-18/19: ~8h wall clock, including ~6h with a CI job hung on a dead worker. About 95 issue closures: about 35 fixed in PRs #437–#441 and this batch (3 filed by the UX audit), about 35 re-stamped reopens re-closed, 14 duplicates, 4 declined, 2 not brAIn, 5 handed to a person (#252, #272, #293's step path, #318, #82 again). Slowest step: the hung CI job, then the Opus subagents (8–16 min).
- 2026-10-19: one person-requested session, ~3h, 42 open reports: all closed (about 30 version-update re-stamps re-closed for the last time, 9 scorecards superseded, 2 Morph ideas built, 4 Morph debug traces filtered at the source), with the reopen rules fixed in brain/panel/devloop/. Slowest step: reading the reopen histories.
- 2026-10-20: ~5h, 10 open reports closed: 7 fixed in PRs #464 (Bambu camera), #465 (brAIn 3.4.2 checks and card verdicts) and #467 (Bambu slicing), including #319 in Morph 1.0.5; 3 handed to a person: 2 whose fix contradicts a pinned test (#327, #322) and #330, the release webhook firing before sibling images are pushed, which lives in `.github/`; #326 partly fixed. UX audit not run this run. Held vs came back: not yet reported for these fixes. Slowest step: CI on #464 (a camera measure that sampled a lazily loaded picture), then the full local suite.
- 2026-10-23: ~10 h; PRs #471, #477–#487; about 37 reports closed fixed, 7 already fixed or duplicate, 1 declined; held/came-back not counted this run; UX audit and retro not run; slowest step: Opus subagents (8–16 min a batch) and the full suite for the UI batch.
