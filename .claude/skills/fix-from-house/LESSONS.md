# What the development loop has learned

The fixer (`SKILL.md`) reads this before every run, and the weekly retro
adds to it. Each bullet is dated, short, and says what failed and why.
A lesson that every contributor should follow belongs in `CLAUDE.md` as
well.

Last retro: 2026-10-07
Last UX audit: 2026-10-09

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

## Loop health

One line per run: date, duration, issues by ending, slowest step.

- 2026-10-08/09: ~10h, 20 issues closed: 16 fixed (PRs #380, #381, #382 and batch 4), 2 already fixed, 1 duplicate, 1 not brAIn; 6 rolling/evidence left open by design. Slowest step: the UI batch subagent (17 min) and waiting on CI.
- 2026-10-09: ~3h this session (resumed run), 10 issues closed, all fixed (PRs #385, #386, #387 and this batch), 2 of them filed by the UX audit and fixed in the same run; 6 rolling/evidence left open by design. Slowest step: the Opus UI batch subagent (16 min); a worktree branch mix-up cost one re-push.
- 2026-10-09 06:00: ~15 min, 6 reopened faults closed with no code change: 3 re-stamps of rows still inside their window or count (#137, #117, #116), 1 duplicate count (#5), 1 not brAIn (#4), 1 handed to a person after three fixes did not clear a live count (#82). UX audit skipped: already done today on this same main. Slowest step: reading the reopen history.
- 2026-10-09 06:30: ~15 min, 1 issue closed with no code change: #146, the frozen-sensor rule's all-time Wrong count, explained by the battery-voltage cause fixed in 2.18.3. UX audit skipped: already done today on this same main. Slowest step: tracing which Wrongs predate the fix.
- 2026-10-09 16:00: ~3h, 9 issues closed as fixed (PRs #395, #396 and batch 5: #149, #152, #154, #155, #163, #164, #166, #167, #168); rolling/evidence left open by design. Slowest step: the Opus UI subagents (~22–25 min) and re-running CI over the screens Chromium start-up flake.
