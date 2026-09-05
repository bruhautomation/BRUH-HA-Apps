"""Shadow mode — a new check earns its place before anybody sees it.

The bar for a house check is that a check which fires on a healthy house
is worse than no check, because it is the one the person learns to ignore
first. Every rule in `checks/` carries a floor or a window for that
reason, and every one is asserted silent on the clean fixture. What none
of that can answer is whether the floor is right *in somebody else's
house* — and the way that question has been answered so far is by
shipping the check and reading the Wrong presses.

So a new check runs first in shadow: it files here instead of to the
findings store, nothing renders it, and for a fortnight its rows are
compared with what was actually filed over the same window. It moves to
the visible list when its precision on the corpus and its agreement in
shadow both clear the bar — which is a code change a person makes reading
those two numbers, deliberately. There is **no automatic promotion**: a
producer that promoted itself on a threshold would be a threshold nobody
can see deciding what a house is told.

**A separate store, not a status.** This is the whole design, and the
alternative was tried on paper first. A `shadow` status would touch every
`LIVE_STATUSES` / `UNSETTLED_STATUSES` / `CLEARABLE` site in
`findings_store` — and, far worse, `add_many` dedupes by normalised text
across *every* status and the settled ledger, so a shadow row would
**suppress a real report** of the same problem. A check being trialled
must not be able to silence the analyst. A separate file cannot.

Four rules follow from that.

**It is never read by anything that shows a person something.** Not the
tab payload, not the badge, not the analyst's prompt block, not the
notify router, not the To-do mirror. `tests/test_shadow_findings.py`
asserts each of those separately, because "it is not rendered" is five
claims and a test of one is a test of one.

**Agreement is the number, not precision.** Nothing here has an ending on
it — nobody can press Wrong on a row they cannot see — so what can be
counted is whether something *else* reported the same thing: a matching
normalised key in the visible store or the settled ledger means the
analyst, or another check, found it too. That is weaker than a person's
ending and it says so by its name.

**Days observed rides with the count.** Fourteen rows over one day is one
evening; fourteen over nine days is a pattern. Same argument as
`override_ledger.MIN_DAYS`, and a count with no window is the shape of
number that gets read as whichever the reader expected.

**A shadow row clears exactly as a real one does.** Same rule, from one
place: `findings_store.resolve_clear` is pure over a list and both stores
call it, so a check being trialled cannot have a different lifecycle from
the one it is being compared against.

Stdlib only.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import atomic_write
import findings_store

# No module logger. Nothing here is worth a line of its own: what a pass
# filed is counted in `run_checks`' summary and rendered in ⚙, and a
# logger nothing logs through is another module's boilerplate.
SHADOW_FILE = Path(os.environ.get("BRAIN_FINDINGS_SHADOW",
                                  "/data/findings-shadow.json"))

# Bigger than the visible list's headroom for one check, smaller than an
# archive: this is a sample of what a trialled rule would have said.
MAX_ROWS = 300
# A shadow row older than this has answered its question. The window the
# design page names is two weeks; this keeps double that, so a fortnight's
# comparison still has its whole fortnight in it on the day it is read.
KEEP_DAYS = 30

_LOCK = threading.RLock()


def _load() -> list[dict]:
    try:
        data = json.loads(SHADOW_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = data.get("findings") if isinstance(data, dict) else None
    return [f for f in items if isinstance(f, dict)] if isinstance(items, list) \
        else []


def _write(items: list[dict]) -> None:
    """No mirror, deliberately.

    `findings_store._write` republishes the shared-volume file every time,
    because that is how Home Assistant sees a finding. A shadow row must
    not be seen, so this writes one file and nothing else — and there is
    no code path from here to the integration, the sensor or the To-do
    list to keep true.
    """
    atomic_write.write_json(SHADOW_FILE, {"findings": items[-MAX_ROWS:]})


def add_many(objs: list[dict], now: float | None = None) -> list[dict]:
    """File rows a shadow check reported. Returns the ones that were new.

    Deduped against **this** store only. Not against the visible list and
    not against the settled ledger: a shadow check reporting something the
    analyst already filed is exactly the agreement being measured, and
    dropping it would make every agreement invisible and the count zero.
    """
    now = time.time() if now is None else now
    with _LOCK:
        items = _load()
        seen = {findings_store.normalize(f.get("text", "")) for f in items}
        used = {int(f.get("ts") or 0) for f in items}
        created: list[dict] = []
        for obj in objs:
            entry = findings_store.coerce(obj)
            if entry is None:
                continue
            key = findings_store.normalize(entry["text"])
            if key in seen:
                continue
            ts = int(now)
            while ts in used:
                ts += 1
            entry["ts"] = ts
            used.add(ts)
            seen.add(key)
            items.append(entry)
            created.append(dict(entry))
        if created:
            _write(items)
        return created


def clear_resolved(sources: set[str], keep_keys: set[str]) -> list[dict]:
    """Drop rows a shadow check that RAN no longer reports.

    `findings_store.resolve_clear`'s rule, applied to this file — the same
    function, not a copy of it. A check whose snapshot key was missing is
    not in ``sources`` here for the same reason it is not there: "I could
    not look" and "it went away" are different claims and only the second
    may delete a row.
    """
    with _LOCK:
        kept, gone = findings_store.resolve_clear(_load(), sources, keep_keys)
        if gone:
            _write(kept)
        return gone


def prune(now: float | None = None, keep_days: int = KEEP_DAYS) -> int:
    """Drop rows past the window. Returns how many went."""
    now = time.time() if now is None else now
    cutoff = now - keep_days * 86400
    with _LOCK:
        items = _load()
        kept = [f for f in items if int(f.get("ts") or 0) >= cutoff]
        if len(kept) != len(items):
            _write(kept)
        return len(items) - len(kept)


def listing() -> list[dict]:
    """Every shadow row, newest first. Read by diagnostics and by nothing
    a person looks at."""
    rows = sorted(_load(), key=lambda f: int(f.get("ts") or 0), reverse=True)
    return [dict(f) for f in rows]


def compare(known_keys: set[str], now: float | None = None) -> dict:
    """Per shadow check: how much it said, how much of it was corroborated.

    ``known_keys`` is every normalised key the visible world holds — the
    findings list *and* the settled ledger, because a problem somebody has
    already answered is still a problem that was really there, and leaving
    the ledger out would make a check look worse the better the house is
    kept.

    Returns ``{check_id: {rows, agreed, days, first, last}}``. ``days`` is
    inclusive of both ends, so a single row reads as one day rather than
    as zero — a count over no time at all is the number that gets read as
    whatever the reader expected.
    """
    now = time.time() if now is None else now
    out: dict[str, dict] = {}
    for row in _load():
        source = str(row.get("source") or "")
        if not source.startswith("check:"):
            continue
        check_id = source.split(":", 1)[1]
        got = out.setdefault(check_id, {
            "rows": 0, "agreed": 0, "first": 0, "last": 0})
        got["rows"] += 1
        if findings_store.normalize(row.get("text", "")) in known_keys:
            got["agreed"] += 1
        ts = int(row.get("ts") or 0)
        got["first"] = min(got["first"] or ts, ts)
        got["last"] = max(got["last"], ts)
    for got in out.values():
        span = max(0, now - got["first"]) if got["first"] else 0
        got["days"] = int(span // 86400) + 1
    return out


def known_keys() -> set[str]:
    """Everything the visible world holds, as normalised keys.

    Both halves, for the reason `add_many` and `is_known` consult both:
    settling deletes the row, so the list alone would forget every problem
    somebody has already dealt with and score a shadow check as inventing
    them.
    """
    keys = {findings_store.normalize(f.get("text", ""))
            for f in findings_store.list_all()}
    keys |= {str(e.get("key") or "")
             for e in findings_store.settled_listing()}
    keys.discard("")
    return keys


def diagnostics(now: float | None = None) -> dict:
    """What ⚙ → Diagnostics and `brain report` carry.

    ``checks`` is the ids currently in shadow — named even when they have
    filed nothing, because "this check is being trialled and has found
    nothing" and "no check is being trialled" are different answers and
    only one of them is a rule that may be ready.
    """
    import checks  # noqa: PLC0415 — deferred; checks imports the collector

    try:
        rows = compare(known_keys(), now)
    except Exception as exc:  # noqa: BLE001 — a diagnostics payload must
        # not fail on one reader, and this one reads two stores.
        return {"error": str(exc)[:120], "checks": sorted(checks.SHADOW)}
    return {
        "checks": sorted(checks.SHADOW),
        "keep_days": KEEP_DAYS,
        "by_check": {cid: rows.get(cid, {"rows": 0, "agreed": 0, "days": 0})
                     for cid in sorted(set(checks.SHADOW) | set(rows))},
        "total": sum(r["rows"] for r in rows.values()),
    }
