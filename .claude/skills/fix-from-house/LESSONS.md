# What the development loop has learned

The fixer (`SKILL.md`) reads this before every run, and the weekly retro
adds to it. Each bullet is dated, short, and says what failed and why.
A lesson that every contributor should follow belongs in `CLAUDE.md` as
well.

Last retro: 2026-10-13
Last UX audit: 2026-10-13

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
- 2026-10-13: A "Back again" whose last sighting is older than the close is a re-stamp, not a recurrence: `upstream._follow_up` reopens on any version change. Filed as #246 (needs a person; the patch is in its body). Until it lands, re-close such issues with the same reason they had.
- 2026-10-13: A Morph panel serving `/morph_static/0.1.0/` (or any version older than the add-on) is Home Assistant still running the old integration: a restart is pending, not a Morph bug.
- 2026-10-13: Morph reports whose fix is in code that exists only in the house's own copy of a frontend module (#242), or that ask for a new rendering architecture (#243), are a person's design call; close them not_planned with needs-human rather than building the feature in a batch.

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
