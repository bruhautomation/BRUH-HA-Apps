#!/usr/bin/env python3
"""A Claude run made outside the panel, into the panel's run journal.

The journal (`panel/journal.py`) is where brAIn counts what it asked
Claude: who ran it, how long it took, what it cost and how it ended. Every
panel run records itself through `journal.record`, and two things hang off
that call — the problem reports and the usage tracker's nudge — so a run
that is not journaled is a run nothing counts, nothing reports when it
fails, and nothing tells the usage figure about. The voice pool, the
classic voice listener and the automation listener all run Claude in
processes of their own, and none of them was recorded: the highest-traffic
Claude path in a house was the one the add-on's own diagnostics could not
see.

This is the one route those processes have in. It imports the panel's own
`journal` and `usage_store` rather than writing the row shape down a
second time — a shape written twice is a shape that drifts, and the
reader that matters (`journal.summary`, `journal.is_claude_run`) is the
panel's — and does the two things a panel run gets for free: the row, and
the nudge when a model actually ran.

What it cannot do from here is what only the panel's listeners do — a
problem report, the usage ledger, the scheduler's rate-limit pause — so
every row it writes carries ``extra.shell``, and the panel books each such
row on its scheduler tick through the same listeners an in-process row
meets (`journal.book_shell_rows`, the arrangement `journal.py record`
gives study and the consolidator). The report writer needs the panel's
diagnostics, and a second copy of it here would be the drift this module
exists to avoid; booking the row there is how a failed voice turn files
its report without one.

Never raises, and never fails the run it is accounting for: a journal that
cannot be written is a missing line, which is the state these runs were in
before this existed.

Usable two ways:

  * imported (the pool): ``record_run("voice", "ok", envelope=..., ...)``
  * from a shell (the listeners)::

      python3 brain_run_journal.py record SOURCE OUTCOME \
          [--duration S] [--envelope FILE] [--model M] [--error TEXT] \
          [--run-id ID] [--extra KEY=VALUE ...]

Stdlib only, like the pool that imports it.
"""
from __future__ import annotations

import json
import os
import sys


def _panel_dir() -> str:
    """Where the panel's modules are: the image's /opt/panel, or the repo's."""
    configured = os.environ.get("BRAIN_PANEL_DIR", "")
    if configured:
        return configured
    here = os.path.dirname(os.path.abspath(__file__))
    sibling = os.path.normpath(os.path.join(here, "..", "panel"))
    return sibling if os.path.isdir(sibling) else "/opt/panel"


def _panel_modules():
    """`journal` and `usage_store`, or None when the panel cannot be read.

    Appended to the END of sys.path, so a panel module can never shadow a
    standard-library one in the process that imported this.
    """
    path = _panel_dir()
    if path not in sys.path:
        sys.path.append(path)
    try:
        import journal  # noqa: PLC0415 — the panel's, found at call time
        import usage_store  # noqa: PLC0415
    except Exception:  # noqa: BLE001 — no panel is no journal, never a crash
        return None
    return journal, usage_store


def record_run(source: str, outcome: str, *, duration_s: float | None = None,
               envelope: dict | None = None, model: str = "",
               error: str = "", run_id: str = "",
               extra: dict | None = None) -> dict | None:
    """One journal row for a run, plus the usage nudge if a model ran.

    `envelope` is the CLI's own result object (`--output-format json`, or a
    stream's `result` event) when there is one: the session id, the turns
    and the tokens are read off it the way `engine._journal` reads them,
    so a voice turn and a card cost the same arithmetic. A run with no
    envelope — a voice turn that died, a plain-text one-shot — still
    records its outcome and duration, and carries `run_id` when the caller
    minted one.
    """
    try:
        mods = _panel_modules()
        if mods is None:
            return None
        journal, usage_store = mods
        meta = envelope if isinstance(envelope, dict) else {}
        turns = meta.get("num_turns")
        # `shell` first, so a caller's own keys cannot take its place: it is
        # what makes the panel book this row (`journal.is_shell_row`).
        row_extra = {"shell": True}
        for key, value in (extra or {}).items():
            if key not in row_extra:
                row_extra[key] = value
        row = journal.record(
            source, outcome,
            error=error or "",
            duration_s=duration_s,
            model=model or "",
            tokens=usage_store.tokens_from_meta(meta),
            turns=turns if isinstance(turns, int) and not isinstance(turns, bool)
            else None,
            run_id=str(meta.get("session_id") or run_id or "")[:64],
            extra=row_extra,
        )
        # The panel's usage listener, done here because it cannot hear a
        # row written in another process: the account's figure moves when a
        # run spends tokens and at no other time, so a finished run is the
        # moment to ask — `journal.is_claude_run` decides, off the row.
        if journal.is_claude_run(row):
            usage_store.nudge()
        return row
    except Exception:  # noqa: BLE001 — accounting must not fail the run
        return None


def _cli(argv: list[str]) -> int:
    if len(argv) < 3 or argv[0] != "record":
        print("usage: brain_run_journal.py record SOURCE OUTCOME [options]",
              file=sys.stderr)
        return 2
    source, outcome = argv[1], argv[2]
    opts: dict = {"extra": {}}
    rest = argv[3:]
    while rest:
        flag = rest.pop(0)
        value = rest.pop(0) if rest else ""
        if flag == "--duration":
            try:
                opts["duration_s"] = float(value)
            except ValueError:
                pass  # a duration that will not parse is a row without one
        elif flag == "--envelope":
            try:
                with open(value, encoding="utf-8", errors="replace") as fh:
                    loaded = json.load(fh)
                if isinstance(loaded, dict):
                    opts["envelope"] = loaded
            except (OSError, ValueError):
                pass  # plain-text output, or none: the row is still worth having
        elif flag == "--model":
            opts["model"] = value
        elif flag == "--error":
            opts["error"] = value
        elif flag == "--run-id":
            opts["run_id"] = value
        elif flag == "--extra" and "=" in value:
            key, _, val = value.partition("=")
            opts["extra"][key] = val
    if not opts["extra"]:
        opts.pop("extra")
    record_run(source, outcome, **opts)
    # Always 0: a shell caller runs this after its answer is written, and
    # a journal problem is not the run's problem.
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
