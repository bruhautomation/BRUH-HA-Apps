# What the development loop has learned

The fixer (`SKILL.md`) reads this before every run, and the weekly retro
adds to it. Each bullet is dated, short, and says what failed and why.
A lesson that every contributor should follow belongs in the area's note
in `docs/notes/` as well (in `CLAUDE.md` only when it applies to every
change in the repository).

Last retro: 2026-10-27
Last UX audit: 2026-10-18

## Lessons

- 2026-10-07: Before the loop's first run. The repository's own `CLAUDE.md`
  (since 2026-10-27, its notes in `docs/notes/`) is the record of every mistake this add-on has already made; most fixes
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
- 2026-10-24: hassfest wants every component an integration uses in `dependencies`/`after_dependencies`, and `devloop-guard` lets only the version line of `manifest.json` change. Reach an optional component (Z-Wave, energy, Thread) through `power_tools._component`, which imports it only when it is loaded, rather than adding it to the manifest. Hassfest also refuses a URL in `strings.json` and the translations.
- 2026-10-24: `issue_write` with `labels` REPLACES every label on the issue, so a close that sets `devloop:fixed` drops `from-house` and the stream label. Close with REST instead: POST the comment, POST `labels[]=devloop:fixed` to the labels endpoint, then PATCH `state=closed`.
- 2026-10-24: Batches that each add MCP tools conflict on the tool lists and the documented count. Merge both sides of every list, re-add a tool's whole `TOOLS` entry from the other side rather than splicing half a dict, and let `test_documented_counts` give the count. The xdist "node down" hang came back once (cancel, read the log, one re-run passed).

- 2026-10-27: Subagents in parallel worktrees share one git stash and one
  process table. Two batch agents used `git stash` to compare against the old
  code, and one ran `pkill -f pytest`, which can kill another worktree's run.
  Every subagent prompt now says: no stash (a WIP commit instead), and never
  kill processes it did not start.
- 2026-10-27: The installed Chromium moved to
  `/opt/pw-browsers/chromium-1243/chrome-linux64/chrome`; the path in the
  skill's measure recipe is stale. Find it with `ls /opt/pw-browsers` before a
  measure run rather than trusting a remembered path.
- 2026-10-27: With other agents loading the box, the affected suite ran past
  ten minutes and was killed by the background limit. Give a background test
  run `timeout` 2400000 and write it to a file; the suite itself is ~3 minutes
  on a quiet machine.
- 2026-10-27: `test_bambu_copies` raced its own cleanup: the print job was
  still writing when `tearDown` removed the directory. A test that starts a
  background job waits for it to finish (an Event set in a `finally`) before
  it ends.
- 2026-10-27: `test_devloop_screenshot_card` fails locally in a cloud session
  (no browser it can drive); CI runs it. Read it as environmental, never as
  a batch's regression.

- 2026-10-27: An issue filed against an older version is often fixed on `main` already (20 snapshot faults from one Core restart were fixed by 3.8.26): read the CHANGELOG for the issue numbers and the code before dispatching a batch, and close it with the fixing PR.
- 2026-10-27: CodeQL's "module imported more than once" fires on an `import x` inside a function when the module is imported at the top; a subagent added one for a "read per call" comment. Module attribute access is already per call.
- 2026-10-27: In a cloud session the full `chromium-1243` hangs on `--dump-dom`; browser tests need `BRAIN_CHROMIUM=/opt/pw-browsers/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell`.

- 2026-10-28: Merging main into a prepared batch whose branch rewrote the same fix sentences as an earlier merged batch (sre.py, checks/integrations.py) conflicts semantically; hand the merge back to the batch's own subagent with both sides' intent spelled out, then bump the version and add the CHANGELOG entry after it commits. `test_hypothesis_days` failed on every branch once real time passed its fixed day (read at the real clock); tests that file at a fixed time read back at that same clock.
- 2026-10-28: A subagent may find the dashboard tools were never missing and the refusal was wording (Lovelace); read the answer's wording and the prompts before assuming a permission gap.

- 2026-10-29: A subagent's brief that names a file (`islandbar.js`) the issue text mentioned can be wrong: the house's local copy is not in this repository, so say "if it exists" and let the agent report. Two prepared batches that both touch `morph-panel.js` conflict on a scroll listener; merge both intents into one listener rather than choosing a side.
- 2026-10-29: An owner request that asks for a permission (YOLO write access) still has a part that needs none: the additive `/config/.brain/ui/house.css`/`house.js` layer answered "I can't change my own header" without making any program file writable.

## Loop health

One line per run: date, duration, issues by ending, slowest step.

- 2026-10-13 11:00: ~5h, about 50 issue closures: 14 fixed (PRs #425, #426, #427, #428 and this Morph batch), 2 handed to a person (#242, #243) plus #246 filed for the re-stamp bug and #82/#227 earlier, the rest duplicates, not-brAIn and re-stamped faults re-closed after each update. Retro done. Slowest step: the Opus subagents (9-17 min) and one CI cycle lost to devloop-guard on a person's file.
- 2026-10-18/19: ~8h wall clock, including ~6h with a CI job hung on a dead worker. About 95 issue closures: about 35 fixed in PRs #437–#441 and this batch (3 filed by the UX audit), about 35 re-stamped reopens re-closed, 14 duplicates, 4 declined, 2 not brAIn, 5 handed to a person (#252, #272, #293's step path, #318, #82 again). Slowest step: the hung CI job, then the Opus subagents (8–16 min).
- 2026-10-19: one person-requested session, ~3h, 42 open reports: all closed (about 30 version-update re-stamps re-closed for the last time, 9 scorecards superseded, 2 Morph ideas built, 4 Morph debug traces filtered at the source), with the reopen rules fixed in brain/panel/devloop/. Slowest step: reading the reopen histories.
- 2026-10-20: ~5h, 10 open reports closed: 7 fixed in PRs #464 (Bambu camera), #465 (brAIn 3.4.2 checks and card verdicts) and #467 (Bambu slicing), including #319 in Morph 1.0.5; 3 handed to a person: 2 whose fix contradicts a pinned test (#327, #322) and #330, the release webhook firing before sibling images are pushed, which lives in `.github/`; #326 partly fixed. UX audit not run this run. Held vs came back: not yet reported for these fixes. Slowest step: CI on #464 (a camera measure that sampled a lazily loaded picture), then the full local suite.
- 2026-10-23: ~10 h; PRs #471, #477–#487; about 37 reports closed fixed, 7 already fixed or duplicate, 1 declined; held/came-back not counted this run; UX audit and retro not run; slowest step: Opus subagents (8–16 min a batch) and the full suite for the UI batch.
- 2026-10-24: ~7.5 h; PRs #489–#500; 44 reports closed, all fixed (brAIn 3.8.9–3.8.17, Morph 1.1.2, GardenRX 0.1.3, BRUH Task Manager 0.1.2), none declined, duplicate or handed to a person; rolling #405 and #369 left open; held/came-back not counted this run; UX audit not run; slowest step: a CI Python job hung on a dead xdist worker (40 min), then the Opus subagents (20–50 min a batch).
- 2026-10-26/27: ~14h, 42 issues fixed in PRs #505–#511 and #515 plus the owner's Bambu requests (#509 and this batch); #369 and #424 left open by design. Held/came-back not counted this run (no Held comments read). Slowest step: batch subagents (20–30 min each) and two lost background test runs.
- 2026-10-27 (evening): ~5h, 38 reports closed: 28 fixed (21 already fixed in 3.8.26; PRs #521, #522, #523, #524 and this Morph batch), 1 not brAIn (#487), 1 declined (#494). Held/came-back not counted. UX audit not run (last 2026-10-18). Slowest step: the findings subagent (~35 min, two rounds) and CI (~8 min a PR).
- 2026-10-28: ~1.5 h of wall clock after the batches started, 23 issues closed: 15 fixed in PRs #526–#529 (brAIn 4.0.6–4.0.9; owner requests #511, #519, #510, #512, #513), 4 declined with plans (#514–#517: self-edit and YOLO write scopes need a new option and permission), 2 duplicates (#237, #518), 2 declined wrongs reports (#500, #501); #512 partly (no unattended reload). Held/came-back not counted. UX audit not run (last 2026-10-18). Slowest step: the largest subagents (30–45 min) and one semantic merge conflict between prepared batches.
- 2026-10-29: ~4 h, 9 reports closed: 8 fixed in PRs #531, #532, #534 (brAIn 4.0.10–4.0.12; owner requests #522–#529), none declined or duplicate; #528 fixed as an additive house layer, not writable /opt/panel. Held/came-back not counted. UX audit not run (last 2026-10-18, now 11 days). Slowest step: the phone-header subagent (~55 min) and the full Morph measure (~5 min).
