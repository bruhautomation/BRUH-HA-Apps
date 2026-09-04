"""What you do by hand, often enough and near enough the same time.

Everything brAIn could say about a house was about something being
*wrong*. A habit is not wrong — somebody walks over and turns the lamp on
at about twenty to seven every weekday, and no check can report that,
because there is nothing to report: the light works, the switch works,
nobody has complained. It is nonetheless the single most useful thing a
house knows about itself, and the only reason it was unsayable is that
nothing was keeping the evidence.

So this is the second deliberate exception to `actions.py` persisting
nothing, and it claims exactly what `override_ledger` claims and no more.
What that rule rejected was the **timeline** — a second copy of the
logbook, tens of thousands of rows a day. What is kept here is only the
changes a *person* caused, which on a real house is tens a day, not
thousands: an automation moving a light is not evidence about a habit,
and a wall switch reaches Core with no context at all and is
`unattributed`, which is a guess this refuses to make.

Five floors, and every one of them answers "would this fire on a house
with no habit in it".

**A count is not evidence without a denominator**, the lesson
`auto.overridden` shipped without. Four times in two months at about six
is a coincidence; four times in five days is a habit. So a routine is a
**share of the days it could have happened on**, and the days it could
have happened on are counted in the same shape the routine claims — a
weekday routine is graded against weekdays.

**A median of scattered times is a confident answer over data that holds
none.** `rhythm.py` had this first and the arithmetic is its, imported
rather than copied: the median is **circular**, because half past
midnight and half past eleven are forty minutes apart and a straight
median of them is noon — the opposite side of the day — and a spread
wider than `MAX_SPREAD_MIN` is not a time, it is "sometime in the
evening".

**A habit has to still be happening.** The ledger keeps two months so a
shape has room to appear, and somebody who moved house in March goes on
having a beautiful March in it. `RECENT_DAYS` gates on the last one.

**Something already doing it is a reason not to offer it.** A second
automation moving the same entity to the same state is not a helpful
duplicate, it is `auto.conflict` written on purpose — so every key an
automation has moved recently is kept too, as one timestamp per key
rather than as rows, and a key it has touched stands down. That is a
boolean's worth of storage for the one question it answers.

**And a proposal nobody asked for costs attention**, so `MAX_ROUTINES`
caps what one pass may offer however many it found. The strongest go
first, and the rest are still in the ledger next time.

Nothing here decides anything — the same split `baselines.py`,
`closures.py` and `thermal.py` keep. It answers "what do you do, when,
and how reliably"; `proposals.py` decides what that is worth offering,
and a person decides whether it is true.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import time

import rhythm

log = logging.getLogger("brain.routines")

STORE = os.environ.get("BRAIN_ROUTINE_LEDGER", "/data/routines.json")

# Long enough for a habit to show, short enough that one somebody
# stopped in the spring is not quoted back at them in the summer. The
# same window `override_ledger` keeps, for the same reason.
KEEP_DAYS = 60.0
# A ledger, not a log.
MAX_ROWS = 6000
# Still happening, not merely well-shaped.
RECENT_DAYS = 10.0

# What it takes to say "you always do this".
MIN_DAYS = 6
MIN_SHARE = 0.6
# Wider than this is not a time of day. `rhythm` uses 90 minutes for a
# whole household waking up; a person reaching for one lamp is tighter
# than that, and a trigger built on a looser number fires at the wrong
# end of an hour.
MAX_SPREAD_MIN = 45.0
# A pass offers a handful. More than this at once is not a house full of
# habits, it is a list nobody reads.
MAX_ROUTINES = 3

# Which domains a time trigger can sensibly act on. This is the one
# guess in the file and it is made where being wrong is cheap: a missed
# habit costs nothing, and a proposal to run somebody's vacuum at 06:40
# because they once did is how the whole tab gets closed.
DOMAINS = ("light", "switch", "fan", "cover", "climate", "media_player",
           "input_boolean", "scene", "humidifier")
# And which states. A light going to `unavailable` is not a habit, and
# an `unknown` is a reading that is not there.
SKIP_STATES = ("unavailable", "unknown", "")


def _key(entity_id: str, state: str) -> str:
    return f"{entity_id}|{state}"


def domain_of(entity_id: str) -> str:
    return entity_id.split(".", 1)[0] if "." in entity_id else ""


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------

def load(path: str | None = None) -> dict:
    """`{"rows": [...], "automated": {key: last_ts}}`, however it failed.

    Every way of failing reads as *no evidence*, which costs a habit
    going unnoticed for another pass. The alternative — a half-read
    ledger read as a complete one — would propose a routine off four
    rows and call it a month.
    """
    try:
        with open(path or STORE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {"rows": [], "automated": {}}
    if not isinstance(data, dict):
        return {"rows": [], "automated": {}}
    rows = data.get("rows")
    automated = data.get("automated")
    return {
        "rows": [r for r in rows if isinstance(r, dict)]
        if isinstance(rows, list) else [],
        "automated": {str(k): float(v) for k, v in automated.items()
                      if isinstance(v, (int, float))}
        if isinstance(automated, dict) else {},
    }


def save(payload: dict, path: str | None = None) -> None:
    import atomic_write  # noqa: PLC0415 — panel-local

    target = path or STORE
    parent = os.path.dirname(target)
    if parent and not os.path.isdir(parent):
        return
    try:
        atomic_write.write_json(target, {
            "rows": (payload.get("rows") or [])[-MAX_ROWS:],
            "automated": payload.get("automated") or {},
        })
    except OSError as exc:
        log.warning("could not write the routine ledger: %s", exc)


def _row_id(row: dict) -> str:
    """The change, not the offering.

    Checks passes overlap — every six hours over a twenty-six hour
    window — so the same press arrives four or five times, and a ledger
    that appended what it was given would report one habit as five.
    """
    return "{}|{}|{}".format(int(row.get("ts") or 0),
                             row.get("entity_id") or "",
                             row.get("state") or "")


def record(actions: list[dict], now: float | None = None,
           path: str | None = None) -> int:
    """File what this pass saw. Returns how many person-moves were new.

    An automated move is not stored as a row: it is one timestamp per
    key, because the only question asked of it is "does something
    already do this", and keeping the rows would be the timeline this
    module exists to not keep.
    """
    now = time.time() if now is None else now
    payload = load(path)
    rows = payload["rows"]
    automated = payload["automated"]
    seen = {_row_id(r) for r in rows}
    added = 0
    for a in actions or []:
        entity_id = str(a.get("entity_id") or "")
        state = str(a.get("state") or "")
        ts = a.get("ts")
        if not entity_id or not ts or state in SKIP_STATES:
            continue
        if domain_of(entity_id) not in DOMAINS:
            continue
        cause = a.get("cause")
        if cause in ("automation", "script", "scene", "brain"):
            key = _key(entity_id, state)
            automated[key] = max(float(ts), automated.get(key, 0.0))
            continue
        if cause != "person":
            # A wall switch and a device's own integration reach Core
            # identically; naming either is a guess, and a habit built
            # on one is a habit brAIn invented.
            continue
        row = {"ts": int(ts), "entity_id": entity_id, "state": state,
               "name": str(a.get("name") or entity_id)}
        if _row_id(row) in seen:
            continue
        seen.add(_row_id(row))
        rows.append(row)
        added += 1

    cutoff = now - KEEP_DAYS * 86400
    rows = [r for r in rows if (r.get("ts") or 0) >= cutoff]
    rows.sort(key=lambda r: r.get("ts") or 0)
    automated = {k: v for k, v in automated.items() if v >= cutoff}
    save({"rows": rows, "automated": automated}, path)
    return added


# ---------------------------------------------------------------------------
# What the ledger is for
# ---------------------------------------------------------------------------

def _in_shape(stamp, shape: str) -> bool:
    weekend = stamp.weekday() >= 5
    return (shape == "every day"
            or (shape == "weekdays" and not weekend)
            or (shape == "weekends" and weekend))


def _eligible_days(shape: str, first: float, last: float, tz) -> int:
    """How many days this routine COULD have happened on.

    The denominator, and it is counted in the routine's own shape: a
    weekday habit graded against every day of the window would report
    five days in seven as 71% and refuse a habit that never misses.
    """
    start = dt.datetime.fromtimestamp(first, tz).date()
    end = dt.datetime.fromtimestamp(last, tz).date()
    n = 0
    day = start
    while day <= end:
        weekend = day.weekday() >= 5
        if (shape == "every day"
                or (shape == "weekdays" and not weekend)
                or (shape == "weekends" and weekend)):
            n += 1
        day += dt.timedelta(days=1)
    return n


def _grade(stamps: list, shape: str, tz) -> dict | None:
    """Does this set of presses hold up as a habit of this shape?

    Everything a routine has to clear, in one place, so a shape cannot
    be adopted on one set of floors and reported against another.
    """
    kept = [s for s in stamps if _in_shape(s, shape)]
    if not kept:
        return None
    days = {s.date() for s in kept}
    if len(days) < MIN_DAYS:
        return None

    minutes = [s.hour * 60 + s.minute for s in kept]
    centre = rhythm.circular_median(minutes)
    if centre is None:
        return None
    spread = rhythm.circular_spread(minutes, centre)
    if spread > MAX_SPREAD_MIN:
        return None

    first = min(s.timestamp() for s in kept)
    last = max(s.timestamp() for s in kept)
    eligible = _eligible_days(shape, first, last, tz)
    if eligible <= 0:
        return None
    share = len(days) / eligible
    if share < MIN_SHARE:
        return None

    return {"when_days": shape, "minute": round(centre),
            "at": rhythm.clock(centre), "spread_min": round(spread, 1),
            "days": len(days), "eligible_days": eligible,
            "share": round(share, 3), "events": len(kept),
            "first": int(first), "last": int(last)}


def _best_shape(stamps: list, tz) -> dict | None:
    """`every day` only when BOTH halves of the week hold up on their own.

    A habit on ten weekdays and one Sunday clears the whole-window share
    comfortably — ten days out of fourteen — and calling it `every day`
    builds a trigger that fires on two mornings it was never wanted on.
    So the broad claim has to be earned twice, once on each half, and
    what a not-quite-daily habit falls back to is the narrower true
    statement rather than the wider convenient one.

    The cost is worth naming: a genuinely daily habit reads as
    `weekdays` for its first three weeks, because six weekend days take
    that long to accrue. That is the same floor `rhythm` pays for
    measuring weekends apart, and it is the cheaper mistake — a routine
    that misses two days a week is a smaller wrong than one that fires
    on two mornings somebody is asleep.
    """
    week = _grade(stamps, "weekdays", tz)
    end = _grade(stamps, "weekends", tz)
    if week and end:
        # Both halves hold up on their own — at the SAME time. A habit at
        # 07:00 on weekdays and 10:00 at weekends is two clean shapes,
        # and the merged set does not refuse it: the spread is a median
        # deviation, so fifteen weekday presses hide six weekend ones
        # completely and `every day at 07:00` comes out with a spread of
        # zero. That is the trigger this function exists to refuse — a
        # daily 07:00 in a house that sleeps until ten on Sundays — so
        # the halves have to agree on the hour before the union is asked,
        # and a refusal either way falls back to the narrower true claim.
        apart = rhythm.circular_spread([end["minute"]], week["minute"])
        if apart <= MAX_SPREAD_MIN:
            daily = _grade(stamps, "every day", tz)
            if daily:
                return daily
        return week if week["days"] >= end["days"] else end
    return week or end


def mine(payload: dict | None = None, tz=None, now: float | None = None,
         path: str | None = None) -> list[dict]:
    """Every habit the ledger can prove, strongest first and capped.

    Pure over what it is handed: nothing here fetches, writes or
    decides.
    """
    payload = load(path) if payload is None else payload
    tz = tz or dt.timezone.utc
    now = time.time() if now is None else now
    rows = payload.get("rows") or []
    automated = payload.get("automated") or {}

    groups: dict[str, list[dict]] = {}
    for r in rows:
        entity_id = str(r.get("entity_id") or "")
        state = str(r.get("state") or "")
        if not entity_id or not state or not r.get("ts"):
            continue
        groups.setdefault(_key(entity_id, state), []).append(r)

    found = []
    for key, group in groups.items():
        # Something already does this. See the docstring: a second rule
        # moving the same entity to the same state is a conflict on
        # purpose, and this is the one question the automated tally
        # exists to answer.
        if (now - automated.get(key, 0.0)) <= RECENT_DAYS * 86400:
            continue
        last_seen = max(r["ts"] for r in group)
        if (now - last_seen) > RECENT_DAYS * 86400:
            continue
        stamps = [dt.datetime.fromtimestamp(r["ts"], tz) for r in group]
        graded = _best_shape(stamps, tz)
        if not graded:
            continue

        entity_id, state = key.split("|", 1)
        found.append({
            "entity_id": entity_id,
            "state": state,
            "name": group[-1].get("name") or entity_id,
            **graded,
        })

    # Days first, then how reliably: a habit on twenty days beats one on
    # eight however tidy the eight were. Sorted before capping, so a
    # pass takes the same ones every time rather than a set that changes
    # with dictionary order.
    found.sort(key=lambda r: (-r["days"], -r["share"], r["entity_id"]))
    return found[:MAX_ROUTINES]


# ---------------------------------------------------------------------------
# What a routine looks like as something you could turn on
# ---------------------------------------------------------------------------

_SERVICE = {
    "on": "turn_on", "off": "turn_off",
    "open": "open_cover", "closed": "close_cover",
    "playing": "media_play", "paused": "media_pause",
}

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri"]
WEEKENDS = ["sat", "sun"]


def service_for(entity_id: str, state: str) -> str | None:
    """The call that produces this state, or `None` when there isn't one.

    Deliberately a short table rather than a rule. A `climate` entity's
    state is its hvac mode and `scene` has no off — a routine whose
    action cannot be named is not proposed, because a proposal whose
    automation does not run is worse than no proposal.
    """
    domain = domain_of(entity_id)
    verb = _SERVICE.get(state)
    if not verb:
        return None
    if domain == "cover" and state in ("open", "closed"):
        return f"cover.{verb}"
    if domain == "media_player" and state in ("playing", "paused"):
        return f"media_player.{verb}"
    if state in ("on", "off") and domain in (
            "light", "switch", "fan", "input_boolean", "humidifier"):
        return f"{domain}.{verb}"
    return None


# A measured median lands on a minute; a habit does not. Rounding to
# five does two things at once: it reads like a time somebody would have
# chosen, and it stops a median that wandered by a minute from producing
# a config `proposals.key_for` hashes differently — which would offer
# again, at 18:41, the change that was declined at 18:40.
TRIGGER_GRAIN_MIN = 5


def trigger_minute(routine: dict) -> int:
    raw = int(routine.get("minute") or 0) % 1440
    return (int(round(raw / TRIGGER_GRAIN_MIN)) * TRIGGER_GRAIN_MIN) % 1440


def to_config(routine: dict) -> dict | None:
    """The automation, in Home Assistant's own words.

    A time trigger, because that is what the evidence supports: the
    ledger knows *when* and does not know what else was true, and a
    trigger inventing a condition it never measured would be brAIn
    guessing in the one place a person cannot check.
    """
    service = service_for(routine.get("entity_id") or "",
                          routine.get("state") or "")
    if not service:
        return None
    minute = trigger_minute(routine)
    # No `alias`. `proposals.key_for` hashes the config, so anything in
    # it that can move without the change moving re-offers a proposal
    # somebody has already declined — and a title carries both the
    # entity's name, which a rename moves, and the time, which the
    # median moves by a minute. What is left is the change itself.
    config = {
        "trigger": [{"platform": "time",
                     "at": f"{minute // 60:02d}:{minute % 60:02d}:00"}],
        "action": [{"service": service,
                    "target": {"entity_id": routine["entity_id"]}}],
        "mode": "single",
    }
    shape = routine.get("when_days")
    if shape == "weekdays":
        config["condition"] = [{"condition": "time", "weekday": WEEKDAYS}]
    elif shape == "weekends":
        config["condition"] = [{"condition": "time", "weekday": WEEKENDS}]
    return config


def title_for(routine: dict) -> str:
    verb = {"on": "on", "off": "off"}.get(routine.get("state") or "")
    name = routine.get("name") or routine.get("entity_id") or "something"
    when = {"weekdays": "on weekdays",
            "weekends": "at weekends"}.get(routine.get("when_days") or "",
                                           "every day")
    action = f"Turn {name} {verb}" if verb else \
        f"Set {name} to {routine.get('state')}"
    minute = trigger_minute(routine)
    return "{} at {:02d}:{:02d} {}".format(
        action, minute // 60, minute % 60, when)


def why_for(routine: dict) -> str:
    """The evidence, as the numbers rather than as a claim about them."""
    shape = {"weekdays": "weekday", "weekends": "weekend"}.get(
        routine.get("when_days") or "", "")
    unit = f"{shape} days" if shape else "days"
    return (
        "You have done this yourself on {days} of the last {eligible} {unit}, "
        "at {at} give or take {spread} minutes. Nothing in Home Assistant "
        "does it for you.".format(
            days=routine.get("days"), eligible=routine.get("eligible_days"),
            unit=unit, at=routine.get("at"),
            spread=int(round(float(routine.get("spread_min") or 0))))
    )


def as_proposal(routine: dict) -> dict | None:
    """A routine as `proposals.add` takes one, or `None` if it cannot be."""
    config = to_config(routine)
    if not config:
        return None
    return {
        "kind": "automation",
        "title": title_for(routine),
        "why": why_for(routine),
        "source": "routine",
        "config": config,
    }


__all__ = [
    "DOMAINS", "KEEP_DAYS", "MAX_ROUTINES", "MAX_ROWS", "MAX_SPREAD_MIN",
    "MIN_DAYS", "MIN_SHARE", "RECENT_DAYS", "STORE", "as_proposal",
    "domain_of", "load", "mine", "record", "save", "service_for", "title_for",
    "to_config", "trigger_minute", "why_for",
]
