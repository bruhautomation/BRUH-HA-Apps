"""Every time somebody put back what an automation had just done, kept.

`actions.py` persists nothing on purpose: every question it answers is
about a window, so every function is pure over one fetch and there is no
second thing to keep true. This is the one exception, and it is a
narrower claim than the one that rule rejected.

What that rule rejected was persisting the **timeline** — tens of
thousands of rows a day, a second copy of Home Assistant's own logbook,
and an accumulating store whose only purpose was longer windows.
Overrides are a handful of rows a week, and without them the thing they
are evidence for cannot be said at all: *"you undo this every weekday
morning"* is a sentence about weeks, and one day of logbook can only ever
report a count. An automation somebody puts back once a day, every day,
for a month is the clearest possible signal a house gives — and it never
reaches three in any single day, so nothing saw it.

Two details are load-bearing.

**Passes overlap, so every row arrives several times.** The checks pass
runs every six hours over a twenty-six hour window, so the same override
is offered four or five times, and a ledger that appended what it was
given would report one disagreement as five. The id is the event
(`ts`, entity, automation), not the offering.

**A pattern is about days, not events.** Four overrides in one evening is
one evening; four across four weeks at the same hour is a rule that does
not fit this house. Nothing here reports a pattern that does not span
`MIN_DAYS` distinct days, whatever the count.
"""
from __future__ import annotations

import json
import logging
import os
import time

log = logging.getLogger("brain.overrides")

STORE = os.environ.get("BRAIN_OVERRIDE_LEDGER", "/data/overrides.json")

# Long enough to see a season in a heating rule, short enough that a
# habit somebody changed in the spring stops being quoted at them.
KEEP_DAYS = 60.0
# A ledger, not a log: past this the oldest go.
MAX_ROWS = 2000
# A pattern has to still be happening. The ledger keeps two months so a
# shape has room to appear, but a rule somebody FIXED goes on having a
# beautiful shape in the history — and a finding that cannot clear for
# eight weeks after the problem is gone is the list nobody reads. The
# settled ledger stops it coming back once a person ends it; this is what
# stops it standing there when the overrides simply stopped.
RECENT_DAYS = 7.0

# What it takes to say "you keep doing this" about weeks rather than
# about one evening.
MIN_EVENTS = 4
MIN_DAYS = 3
# How much of the day the overrides have to fall inside before the hour
# is worth naming. Wider than this is not a time of day, it is "whenever".
BAND_HOURS = 4
# And what share of them have to be in it.
BAND_SHARE = 0.75


def _row_id(entry: dict) -> str:
    """The event, not the offering. See the note about overlapping passes."""
    return "{}|{}|{}".format(int(entry.get("ts") or 0),
                             entry.get("entity_id") or "",
                             entry.get("by") or entry.get("by_name") or "")


def load(path: str | None = None) -> list[dict]:
    try:
        with open(path or STORE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


def save(rows: list[dict], path: str | None = None) -> None:
    import atomic_write  # noqa: PLC0415 — panel-local

    target = path or STORE
    parent = os.path.dirname(target)
    if parent and not os.path.isdir(parent):
        return
    try:
        atomic_write.write_json(target, rows[-MAX_ROWS:])
    except OSError as exc:
        log.warning("could not write the override ledger: %s", exc)


def record(overrides: list[dict], now: float | None = None,
           path: str | None = None) -> int:
    """File what this pass saw. Returns how many were new.

    Only a person undoing an *automation* is kept: a script or a scene is
    something somebody ran on purpose a moment earlier, so putting it
    back is a change of mind rather than evidence about a standing rule.
    """
    now = time.time() if now is None else now
    rows = load(path)
    seen = {_row_id(r) for r in rows}
    added = 0
    for o in overrides or []:
        if o.get("by_cause") != "automation":
            continue
        key = o.get("by") or o.get("by_name") or ""
        if not key or not o.get("ts"):
            continue
        row = {
            "ts": int(o["ts"]),
            "entity_id": o.get("entity_id") or "",
            "by": key,
            "by_name": o.get("by_name") or key,
            "from_state": o.get("from_state") or "",
            "to_state": o.get("to_state") or "",
        }
        if _row_id(row) in seen:
            continue
        seen.add(_row_id(row))
        rows.append(row)
        added += 1
    rows = [r for r in rows
            if (now - (r.get("ts") or 0)) <= KEEP_DAYS * 86400]
    rows.sort(key=lambda r: r.get("ts") or 0)
    save(rows, path)
    return added


# ---------------------------------------------------------------------------
# What the ledger is for
# ---------------------------------------------------------------------------

def _band(hours: list[int]) -> tuple[int, int, float] | None:
    """When of the day these happen, as the tightest hours that hold most.

    Two things this must not do, and the second was found by driving it.

    It **wraps midnight**, because "late evening" is 22:00–01:00 in a
    great many households and a window that could not cross it would
    report the busier half and call that the answer.

    And it reports the hours that are actually **occupied**, not the
    search window that found them. Fifteen overrides all at 08:10 fit
    inside a four-hour window starting at 05:00 just as well as one
    starting at 08:00, and the first version took whichever start it
    tried first: it said *"almost always between 05:00 and 09:00"* about
    something that only ever happens at ten past eight. That is not a
    slightly loose answer — it is a condition somebody would write, which
    would stand the automation down for three hours nothing happens in.
    So the window is only the search, and what comes back is the span
    from the first occupied hour in it to the last.
    """
    if not hours:
        return None
    best = None
    for start in range(24):
        offsets = sorted((h - start) % 24 for h in hours
                         if (h - start) % 24 < BAND_HOURS)
        if not offsets:
            continue
        # More of them is better; a tie goes to the tighter span, which
        # is what stops a window being reported instead of the hours.
        rank = (len(offsets), -(offsets[-1] - offsets[0]))
        if best is None or rank > best[0]:
            best = (rank, start, offsets)
    if best is None:
        return None
    _rank, start, offsets = best
    return ((start + offsets[0]) % 24,
            (start + offsets[-1] + 1) % 24,
            len(offsets) / len(hours))


def pattern(rows: list[dict], tz=None,
            now: float | None = None) -> dict | None:
    """When these overrides happen, when there is a "when".

    Returns None rather than a weak answer: a shape nobody would
    recognise, reported as if it were one, is worse than the count on its
    own — it invites somebody to write a condition around a coincidence.
    """
    import datetime as dt  # noqa: PLC0415

    if len(rows) < MIN_EVENTS:
        return None
    tz = tz or dt.timezone.utc
    now = time.time() if now is None else now
    # Still happening, not merely well-shaped. See RECENT_DAYS.
    last = max((r.get("ts") or 0) for r in rows)
    if (now - last) > RECENT_DAYS * 86400:
        return None
    stamps = [dt.datetime.fromtimestamp(r["ts"], tz) for r in rows
              if r.get("ts")]
    days = {s.date() for s in stamps}
    if len(days) < MIN_DAYS:
        return None

    out = {"events": len(stamps), "days": len(days),
           "first": min(r["ts"] for r in rows),
           "last": max(r["ts"] for r in rows)}

    band = _band([s.hour for s in stamps])
    if band and band[2] >= BAND_SHARE:
        out["from_hour"], out["to_hour"], out["hour_share"] = band

    weekend = sum(1 for s in stamps if s.weekday() >= 5)
    if weekend == 0 and len(days) >= MIN_DAYS:
        out["when_days"] = "weekdays"
    elif weekend == len(stamps) and len(days) >= MIN_DAYS:
        out["when_days"] = "weekends"
    return out


def by_automation(rows: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for r in rows or []:
        key = r.get("by") or ""
        if key:
            grouped.setdefault(key, []).append(r)
    return grouped


__all__ = [
    "BAND_HOURS", "BAND_SHARE", "KEEP_DAYS", "MAX_ROWS", "MIN_DAYS",
    "MIN_EVENTS", "RECENT_DAYS", "STORE", "by_automation", "load", "pattern", "record",
    "save",
]
