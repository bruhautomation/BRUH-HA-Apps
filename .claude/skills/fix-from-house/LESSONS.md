# What the development loop has learned

The fixer (`SKILL.md`) reads this before every run, and the weekly retro
adds to it. Each bullet is dated, short, and says what failed and why.
A lesson that every contributor should follow belongs in `CLAUDE.md` as
well.

Last retro: 2026-10-07
Last UX audit: 2026-10-07

## Lessons

- 2026-10-07: Before the loop's first run. The repository's own `CLAUDE.md`
  is the record of every mistake this add-on has already made; most fixes
  are an existing bullet there applied in a new place.
- 2026-10-07: First UX audit. A `display` set on a class beats the `[hidden]` attribute, so an empty hidden container (`.kclean`) drew as a bar in Memory › Knowledge. When a container is toggled with `hidden`, check that its class does not set `display`.
