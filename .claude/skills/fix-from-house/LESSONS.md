# What the development loop has learned

The fixer (`SKILL.md`) reads this before every run, and the weekly retro
adds to it. Each bullet is dated, short, and says what failed and why.
A lesson that every contributor should follow belongs in `CLAUDE.md` as
well.

Last retro: 2026-10-07
Last UX audit: 2026-10-08

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

## Loop health

One line per run: date, duration, issues by ending, slowest step.
