"""Everything the three ledgers know about one entity, in one answer.

`routines`, `override_ledger` and `manual_ledger` each delegate their
grading to `habits`, so the join over all three — *"what do I do with
this light, and what keeps undoing it"* — cannot live in `habits` too: a
module the ledgers import may not import the ledgers back, and doing so
closed an import ring CodeQL reported on the release that introduced it.
This is that join, and it is a join rather than a fourth store: nothing
here is written down, every number comes out of the module that owns it,
and the floors are the producers' own, read at call time rather than
restated. `/api/habits/{entity_id}` and the `habits` MCP tool read it.
"""
from __future__ import annotations

import datetime as dt
import time

import habits
import manual_ledger
import override_ledger
import routines


def habit_of(entity_id: str, *, routine_rows=(), override_rows=(),
             manual_rows=(), tz=None, now: float | None = None,
             automated: dict | None = None) -> dict:
    """Everything the three ledgers know about one entity, in one answer.

    The three were built for three producers and read by three surfaces,
    so *"what do I do with this light, and what keeps undoing it"* — one
    question a person actually has — could only be answered by opening
    three tabs and joining them by eye. This is that join, and it is a
    join rather than a fourth store: nothing here is written down, every
    number comes out of the module that owns it, and the floors are the
    producers' own, read at call time rather than restated.

    A shape is looked for per **state**, because turning something on and
    turning it off are two habits with two times, and the strongest is
    the one reported. The overrides are graded with the override ledger's
    floors and the odd presses with the manual ledger's, for the same
    reason: this is the caller of three producers, not a fourth.
    """
    tz = tz or dt.timezone.utc
    now = time.time() if now is None else now
    entity_id = str(entity_id or "")

    floors = {"min_days": routines.MIN_DAYS, "min_share": routines.MIN_SHARE,
              "max_spread_min": routines.MAX_SPREAD_MIN,
              "recent_days": routines.RECENT_DAYS}
    by_state: dict[str, list[dict]] = {}
    for row in routine_rows or []:
        if str(row.get("entity_id") or "") != entity_id or not row.get("ts"):
            continue
        by_state.setdefault(str(row.get("state") or ""), []).append(row)

    best: tuple | None = None
    name = ""
    for state, group in sorted(by_state.items()):
        name = name or str(group[-1].get("name") or "")
        found = habits.best_shape([float(r["ts"]) for r in group], tz, now, **floors)
        if not found:
            continue
        rank = (found["days"], found["share"])
        if best is None or rank > best[0]:
            best = (rank, state, found)
    state = best[1] if best else ""
    shape = best[2] if best else None

    overrides = []
    mine = [r for r in override_rows or []
            if str(r.get("entity_id") or "") == entity_id and r.get("ts")]
    for key, group in sorted(override_ledger.by_automation(mine).items()):
        if len(group) < override_ledger.MIN_EVENTS:
            continue
        found = habits.grade([float(r["ts"]) for r in group], tz, now,
                      min_days=override_ledger.MIN_DAYS,
                      recent_days=override_ledger.RECENT_DAYS,
                      band_hours=override_ledger.BAND_HOURS,
                      band_share=override_ledger.BAND_SHARE)
        if not found or not found["still_happening"]:
            continue
        overrides.append({"automation": key,
                          "name": group[-1].get("by_name") or key,
                          "events": found["stamps"], "days": found["days"],
                          "band": found["band"], "last": int(found["last"])})

    odd = manual_ledger.off_pattern(
        {"rows": [r for r in manual_rows or []
                  if str(r.get("entity_id") or "") == entity_id],
         "automated": {}}, tz, now)

    # Something already does this. The override rows are the other half
    # of the same question and are consulted too: a rule a person keeps
    # undoing is, by construction, a rule that runs.
    tally = automated or {}
    does_it = bool(mine) or any(
        str(key).split("|", 1)[0] == entity_id
        and (now - float(stamp or 0.0)) <= routines.RECENT_DAYS * habits.DAY_S
        for key, stamp in tally.items())

    name = name or (odd[0].get("name") if odd else "") or entity_id
    return {
        "entity_id": entity_id,
        "name": name,
        "state": state,
        "habit": shape,
        "overrides": overrides,
        "odd": odd,
        "automated": does_it,
        "sentence": habits.sentence_for(name, state, shape, overrides, does_it),
    }


__all__ = ["habit_of"]
