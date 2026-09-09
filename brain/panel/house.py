"""What brAIn has measured about this house, and what it is still waiting for.

Seven measurements sit behind nearly everything this add-on says — when
the house gets up, what a reading normally is, how fast a room loses
heat, how often a door is open, what each machine's own power looks like,
what somebody does by hand often enough to be a habit, and what the
electricity did last week. Every one of them has a floor underneath it,
and every floor exists for the same reason: a confident answer over data
that holds none is worse than no answer at all.

The cost of that honesty is that a fresh install is *silent*, and silence
is indistinguishable from broken. A house eight days old has no wake
time, no habit, no trend and no weekly comparison, and nothing anywhere
said so — the tabs simply had nothing on them. So each store answers one
question about itself, in one shape:

    have / need, in a named unit, with a state and one sentence.

Three rules keep this from becoming a second copy of the measurements.

**A store's floor lives in the store.** `progress()` is a method on the
module that owns the constant, reading its own `MIN_DAYS`, `MIN_SAMPLES`,
`MIN_BUCKETS` — never a number restated here. A second copy of a floor is
a floor that drifts, and the drift is invisible until the day the two
disagree about whether a house is ready.

**"I could not look" is not "there is nothing here."** A store whose
build was refused, and a house with no outdoor thermometer at all, are
both `unavailable` and both carry the *store's own* sentence saying which
— never `collecting`, which promises an answer that is not coming.

**`ready_at` is arithmetic and it lives here.** The rate at which a unit
accrues is the store's (a weekday arrives five times in seven; a bucket
takes an hour of watching; a nightly pass is a day), so each store hands
its own rate over and this does the one division. One implementation, so
two tabs cannot disagree about when a house will be ready.

The contract, which the panel builds against exactly:

    GET /api/knowledge/house -> {"generated_at": int, "stores": {...},
                                 "brief": {...}, "weekly": {...}}

    store keys exactly: rhythm, baselines, thermal, closures, appliances,
    habits, energy

    each store: {"state": "not_started"|"collecting"|"ready"|
                          "unavailable"|"stale",
                 "have": n, "need": n, "unit": str, "reason": str,
                 "ready_at": int|null, "summary": str,
                 "updated_at": int|null, "detail": {...}}

    units: rhythm `days` (need MIN_DAYS), baselines `entities` (have =
    entities with >=1 bucket, need 1, detail {measured, with_buckets,
    flat, trends}), thermal `rooms` (need 1, detail {outdoor, rooms,
    coldest}), closures `hours` (have = max watched buckets over
    entities, need MIN_BUCKETS, detail {entities}), appliances `machines`
    (need 1, detail {profiled, chore_capable}), habits `days` (have =
    distinct days in the routines ledger, need MIN_DAYS, detail
    {presses, would_propose, overrides}), energy `days` (need energy.py's
    own MIN_DAYS, detail = week()).

    `summary` is ONE human sentence true in that state. `ready_at` is the
    estimated epoch at which `need` is met at the current rate; null when
    ready or unavailable.

    brief  = {enabled, last_sent, text, reasons, error, fallback_hour,
              wake_measured}
    weekly = {enabled, last_sent, text, error, day}
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger("brain.house")

# The five states a measurement can be in. `unavailable` and `stale` are
# both "no usable answer" and they are deliberately different words: one
# is a house that cannot supply this, the other is a measurement that has
# stopped, and only the second is something to go and fix.
NOT_STARTED = "not_started"
COLLECTING = "collecting"
READY = "ready"
UNAVAILABLE = "unavailable"
STALE = "stale"
STATES = (NOT_STARTED, COLLECTING, READY, UNAVAILABLE, STALE)

# The order the panel renders them in, and the only spelling of the seven
# names anything here uses.
STORES = ("rhythm", "baselines", "thermal", "closures", "appliances",
          "habits", "energy")

# What the energy figures cost: a statistics query over every meter in
# the house, twice. Nobody's electricity moves inside an hour, and the
# aggregate is polled by a tab.
ENERGY_TTL_S = 3600.0
_ENERGY_CACHE: dict = {"at": 0.0, "week": None}


def eta(have: int, need: int, per_unit_s: float,
        now: float | None = None) -> int | None:
    """When `need` is met at the rate this unit accrues, or None.

    `None` is "there is nothing left to wait for" — which covers a store
    that is ready and one whose unit does not accrue on its own — and
    every caller reads it as "do not show a date". The rate is the
    store's own, because only the store knows whether its unit is a
    nightly pass, an hour of watching or a weekday.
    """
    now = time.time() if now is None else now
    try:
        missing = max(0, int(need) - int(have))
        rate = float(per_unit_s or 0.0)
    except (TypeError, ValueError):
        return None
    if missing <= 0 or rate <= 0:
        return None
    return int(now + missing * rate)


def progress(*, unit: str, need: int, have: int, state: str,
             reason: str = "", summary: str = "",
             updated_at: int | None = None, detail: dict | None = None,
             per_unit_s: float = 0.0, now: float | None = None) -> dict:
    """One store's answer, in the shape every store answers in.

    Every `progress()` in the panel ends here, so the shape is written
    down once: a tab that can render one store can render all seven, and
    a store that grows a key grows it for everybody.
    """
    if state not in STATES:  # pragma: no cover — a typo in a caller
        raise ValueError(f"{state!r} is not one of {STATES}")
    return {
        "state": state,
        "have": int(have),
        "need": int(need),
        "unit": unit,
        "reason": reason,
        # A house that cannot supply this at all is not waiting for it,
        # and a date beside "no outdoor thermometer" is a promise nothing
        # is going to keep.
        "ready_at": None if state == UNAVAILABLE
        else eta(have, need, per_unit_s, now),
        "summary": summary,
        "updated_at": int(updated_at) if updated_at else None,
        "detail": detail or {},
    }


def days_ago(when: float | None, now: float | None = None) -> str:
    """`3 days ago`, `yesterday`, `today` — for a sentence, not a clock."""
    if not when:
        return "never"
    now = time.time() if now is None else now
    days = int(max(0.0, (now - float(when))) // 86400)
    return {0: "today", 1: "yesterday"}.get(days, f"{days} days ago")


def plural(n: int, one: str, many: str | None = None) -> str:
    """`1 day` / `4 days`, so a sentence does not read like a template."""
    return f"{n} {one}" if n == 1 else f"{n} {many or one + 's'}"


# ---------------------------------------------------------------------------
# The energy figures, which are the one measurement with no store
# ---------------------------------------------------------------------------

async def energy_week(session, now: float | None = None,
                      ttl: float = ENERGY_TTL_S) -> dict:
    """Last week against the week before, cached for an hour.

    `energy.week` is two statistics queries over every meter the house
    has configured, and this is read by a tab that polls. Nobody's
    electricity moves inside an hour, so the cache costs nothing true.

    A failure is returned in `week`'s own shape — `available: false` and
    a reason in words — rather than raised, because "the recorder did not
    answer" is a state this reports, not an error that should take the
    whole aggregate down with it.
    """
    import energy  # noqa: PLC0415 — panel-local, as everywhere here

    now = time.time() if now is None else now
    cached = _ENERGY_CACHE.get("week")
    if cached is not None and (now - float(_ENERGY_CACHE.get("at") or 0)) < ttl:
        return cached
    try:
        answer = await energy.week(session, now)
    except Exception as exc:  # noqa: BLE001 — one section, not the payload
        log.info("energy figures unavailable: %s", exc)
        return {"available": False,
                "reason": f"the energy figures could not be read: {exc}"[:200]}
    if not isinstance(answer, dict):
        return {"available": False,
                "reason": "the energy figures could not be read"}
    _ENERGY_CACHE["at"] = now
    _ENERGY_CACHE["week"] = answer
    return answer


def forget_energy() -> None:
    """Drop the cached figures. For a test, and for a manual refresh."""
    _ENERGY_CACHE["at"] = 0.0
    _ENERGY_CACHE["week"] = None


# ---------------------------------------------------------------------------
# The aggregate
# ---------------------------------------------------------------------------

def snapshot(now: float | None = None, week: dict | None = None,
             brief: dict | None = None, weekly: dict | None = None) -> dict:
    """Every measurement's own answer about itself, in one payload.

    Pure over the stores and over what it is handed: `week` is fetched by
    the caller (it is the one section that needs a session), and the two
    scheduled-message blocks are the server's, because they are about
    what brAIn *said* rather than about what it has measured.

    A store that raises is reported `unavailable` naming the exception
    rather than taking the payload with it: six measurements and a
    sentence about the seventh is a screen somebody can read, and a 500
    is not.
    """
    import appliances  # noqa: PLC0415
    import baselines  # noqa: PLC0415
    import closures  # noqa: PLC0415
    import energy  # noqa: PLC0415
    import rhythm  # noqa: PLC0415
    import routines  # noqa: PLC0415
    import thermal  # noqa: PLC0415

    now = time.time() if now is None else now
    calls = {
        "rhythm": lambda: rhythm.progress(now=now),
        "baselines": lambda: baselines.progress(now=now),
        "thermal": lambda: thermal.progress(now=now),
        "closures": lambda: closures.progress(now=now),
        "appliances": lambda: appliances.progress(now=now),
        "habits": lambda: routines.progress(now=now),
        "energy": lambda: energy.progress(week, now=now),
    }
    stores = {}
    for name in STORES:
        try:
            stores[name] = calls[name]()
        except Exception as exc:  # noqa: BLE001 — see the docstring
            log.warning("%s could not report its progress: %s", name, exc)
            stores[name] = progress(
                unit="", need=1, have=0, state=UNAVAILABLE,
                reason=str(exc)[:200],
                summary=f"brAIn could not read what it knows about {name}.",
                now=now)
    return {
        "generated_at": int(now),
        "stores": stores,
        "brief": brief or {},
        "weekly": weekly or {},
    }


__all__ = [
    "COLLECTING", "ENERGY_TTL_S", "NOT_STARTED", "READY", "STALE", "STATES",
    "STORES", "UNAVAILABLE", "days_ago", "energy_week", "eta", "forget_energy",
    "plural", "progress", "snapshot",
]
