# What the development loop has learned

<!-- Rendered from lessons.json by scripts/lessons.py. Do not edit:
     change lessons.json, then run `python3 scripts/lessons.py render --write`. -->

Last retro: 2026-11-03
Last UX audit: 2026-10-30

The fixer reads this index at the start of every run. Each line is one
lesson: its id, how it is held (a guard rule, a test, a hook, or only
`prose`), and the rule. The evidence behind each is in `lessons.json`.
The run record and the loop's health are `runs.jsonl` in the reports
repository (`scripts/runs_record.py render`), not this file.

## Lessons

- `2026-10-07-display-beats-hidden` (prose): A `display` set on a class beats the `[hidden]` attribute: when a container is toggled with `hidden`, check its class does not set `display`.
- `2026-10-07-notes-are-the-record` (prose): Most fixes are an existing bullet in `docs/notes/` applied in a new place: search the notes for the area before writing a fix.
- `2026-10-08-test-timeouts` (prose): Subagents run `tests/affected.py --base origin/main --run`; the run runs the full suite once with `-n 4 --dist loadfile` and a raised Bash timeout; always `python3 -m pytest`.
- `2026-10-09-addcleanup-order` (prose): Register `addCleanup` with the original BEFORE replacing a module function, or the cleanup restores the fake and leaks into a later class.
- `2026-10-09-producer-ignored-reads-all-time` (prose): A `[Producer …] ignored N of M` fault drops out once nobody marked the rule Wrong for 14 days (`reports.SCORE_RECENT_S`); only a Wrong count above what the fixed cause explains is new evidence.
- `2026-10-09-stores-package-collision` (prose): A failure that passes alone may be two add-ons' top-level `stores` packages colliding on one xdist worker; check `sys.path` before calling it a flake.
- `2026-10-10-local-only-failure` (prose): Check a local-only failure against `main` (and run the file alone) before chasing it: stray files under `/config/.brain` or `/data` from an earlier test break later ones.
- `2026-10-12-chromium-cold-start` (prose): `test_devloop_screens`' real-browser test warms Chromium once, untimed; a cold start on a loaded runner exceeds `screens._launch`'s 15 s budget.
- `2026-10-12-local-suite-stall` (prose): When the local full suite stalls with no output, ship on the batch's affected run and let CI be the gate.
- `2026-10-12-pkill-kills-the-shell` (prose): Never `pkill -f <pattern>` in the same Bash command as anything else, and never kill a process you did not start.
- `2026-10-12-severity-is-not-category` (prose): A severity is not a category: a chip that sorts rows asks the source too, never the severity alone.
- `2026-10-13-guard-after-commit` (prose): Run `devloop_guard.py` after committing: it reads committed changes only, so a dirty tree reads as ok.
- `2026-10-13-morph-old-static` (prose): A Morph panel serving `/morph_static/<older version>/` is Home Assistant still running the old integration: a restart is pending, not a Morph bug.
- `2026-10-18-node-down` (test:tests/test_ci_timeouts.py): A hung or cancelled CI job is read from its log for 'node down' or a runner shutdown and re-run once before looking for a code cause.
- `2026-10-18-older-release-reports` (prose): Read the release a report was filed against (the block's `release`) before fixing: a report a later release already fixed is closed as a duplicate of the fixing issue.
- `2026-10-18-squash-commit-message` (prose): Always pass `commit_title` and `commit_message` to `merge_pull_request`: without them the squash message carries every commit, including dropped ones.
- `2026-10-18-tests-changed-to-pass` (guard:test-modified): Never make a fix pass by changing an existing test; when a pinned assertion contradicts the fix, open a `devloop-test/<slug>` PR for the independent reviewer (SKILL.md 0.3).
- `2026-10-20-live-image-swap` (prose): A live picture needs a second element swapped in once decoded; a measure that samples an image waits for `complete && naturalWidth > 0`.
- `2026-10-20-race-test-scheduling` (test:tests/test_bruh_print_atomic_write.py): `test_bruh_print_atomic_write`'s race test can fail under a loaded `-n 4` run on a branch that never touches BRUH Print; it is scheduling, not a regression.
- `2026-10-20-read-before-the-signoff` (prose): Read the lines before a log's sign-off before naming a cause, and say in the PR when the cause is still unproven.
- `2026-10-23-codeql-after-merge` (prose): CodeQL comments land after a PR merged: check the last merged PR's threads at the start of each batch, and grep new tests for import styles CodeQL flags.
- `2026-10-23-fingerprint-split` (prose): Check whether one fault filed as two issues is a fingerprint split by moving wording, and say so to the house half.
- `2026-10-23-merge-after-squash` (prose): After a squash merge, merging `main` into a follow-up branch conflicts on its own earlier changes: take the branch's side and confirm `git diff origin/main` shows only new work.
- `2026-10-23-no-new-skip` (guard:skip): A test that depends on optional data (zoneinfo) gets a fallback that keeps it running, never a new skip: the guard refuses `skipIf`.
- `2026-10-24-labels-replace` (prose): `issue_write` with `labels` REPLACES every label: close by POSTing the comment, POSTing the label, then PATCHing `state=closed`.
- `2026-10-24-manifest-dependencies` (guard:version-only): Reach an optional HA component through `power_tools._component` rather than adding it to `manifest.json`: the guard lets only the version line change, and hassfest refuses a URL in strings.
- `2026-10-24-tool-list-conflicts` (test:tests/test_documented_counts.py): Batches that add MCP tools conflict on the lists and the documented count: merge both sides, re-add a whole `TOOLS` entry, and let `test_documented_counts` give the count.
- `2026-10-27-background-timeout` (prose): Give a background test run `timeout` 2400000 and write its output to a file when other agents load the box.
- `2026-10-27-environmental-browser-tests` (prose): `test_devloop_screenshot_card` fails in a cloud session with no drivable browser; CI runs it. Never read it as a batch's regression.
- `2026-10-27-find-chromium` (prose): Find Chromium with `ls /opt/pw-browsers` rather than a remembered path; in a cloud session browser tests need `BRAIN_CHROMIUM` set to the headless shell.
- `2026-10-27-wait-for-background-jobs` (prose): A test that starts a background job waits for it (an Event set in a `finally`) before tearDown removes its directory.
- `2026-10-27-worktree-hygiene` (prose): Subagents in parallel worktrees never `git stash` (a WIP commit instead) and never kill processes they did not start.
- `2026-10-28-fixed-clock-tests` (prose): A test that files at a fixed time reads back at that same clock, never the real one.
- `2026-10-28-read-the-refusal` (prose): Before assuming a permission gap, read the refusal's wording and the prompts: the tool may never have been missing.
- `2026-10-28-semantic-merge` (prose): Two prepared batches that rewrote the same sentences or the same listener merge both intents (the batch's own subagent does it), then bump and add the CHANGELOG entry.
- `2026-10-29-additive-layer` (prose): An owner request that asks for a permission usually has a part that needs none; the additive `/config/.brain/ui/house.css`/`house.js` layer answered 'I can't change my own header'.
- `2026-10-29-brief-names-files-if-they-exist` (prose): A subagent's brief says 'if it exists' for a file named only in an issue: the house's own copy is not in this repository.
- `2026-10-30-look-series` (prose): A series of owner `look` reports on one control is one spec read latest-first.
- `2026-10-30-refusal-regex-negatives` (prose): Read every new refusal regex against everyday sentences and give it a negative test list.
- `2026-11-03-agent-load` (prose): With many fixer agents at once, each runs only its own new tests plus ruff and the guard; CI is the full-suite gate.
- `2026-11-03-dependabot-majors` (prose): A Dependabot major bump can ride a devloop PR after it is tested (a local build; `npm update <pkg> --package-lock-only` within the parent's range), with the add-on's version bump.
- `2026-11-03-overload-flakes` (prose): A subprocess test that fails with an empty prompt only under load (`test_ask_face_parity`) is re-run once and its log read before looking for a code cause.
- `2026-11-03-two-addon-pr` (prose): A PR that touches two add-ons bumps both versions and keeps both CHANGELOG sections when the next batch conflicts.
- `2026-11-03-version-is-many-places` (prose): Run `.github/scripts/check-changelog-version.sh <add-on>` and grep the old version across the add-on before pushing a bump: GardenRX and BRUH Print pin it in several files.
- `2026-11-04-hassfest-service-text` (prose): Write service help text without angle brackets or colons, and parse services.yaml with yaml.safe_load before pushing.
- `2026-11-04-reload-restores-globals` (prose): A test that reloads a module must put back what other modules set on it; a failure that comes and goes by xdist worker is an ordering bug to find, not a re-run.
- `2026-11-04-sibling-service-first` (prose): A batch that needs a sibling add-on's new service is split: the add-on's half ships first as its own PR and version, then brAIn's half, which treats the service as optional for an older add-on.
- `2026-11-04-three-subagents-max` (prose): Run at most three subagents at a time on a 4-CPU container; read a local failure that also fails on main against main and let CI be the gate.

3 retired lesson(s) are kept in `lessons.json`.
