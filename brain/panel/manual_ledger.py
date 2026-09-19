"""What a person did by hand, kept — because *why* is not in the logbook.

This is the fourth and last deliberate exception to `actions.py`
persisting nothing, and like `override_ledger` and `routines` it claims
something narrower than the rule rejected. What that rule rejected was a
second copy of the **timeline**; what is kept here is only the changes a
*person* caused, on the domains where somebody reaching for a control is
a decision rather than a reflex — tens of rows a day, not thousands.

It exists because the one question a house cannot answer about itself is
the interesting one. `actions.py` says a person turned the sprinklers on
at 19:04. `routines.py` says they do that most weekday evenings at about
seven. Neither says **why**, and the why is what everything downstream
wants: an automation written without it fires at seven o'clock for ever
and is wrong the first week it rains.

Four things are worth knowing before changing anything here.

**Voice counts, and `routines.py` is right to exclude it.** A habit
miner builds a time trigger, and a trigger built on "somebody asked
Assist" is a trigger built on a sentence rather than on a time. But a
voice command is the single most informative manual action a house
records, because the person said what they wanted in words — so it is
kept here and `cause` rides with every row. What is *not* kept is
`unattributed`: a wall switch and a device's own integration reach Core
identically, and a question about a press nobody can prove happened is a
question brAIn invented.

**Some questions a house should not ask.** `EXCLUDED` is locks, alarm
panels and the domains that track where people are. *"Why did you unlock
the front door at 02:40"* is a question with a correct answer and no
good reason to be asked by a piece of software, and one badly-judged
question of that shape costs more trust than every well-judged one
earns. It is a refusal rather than a ranking, because a ranking is a
thing that gets tuned.

**An automated move is one timestamp, not a row.** The only question
asked of it is *does something already do this* — if an automation moves
the same entity to the same state, a person doing it too is an override
and `auto.overridden` owns that. The map is kept over **this** module's
domain set rather than read from `routines.py`'s, whose narrower list
would answer "no" for every script and scene: a partial answer to a
question about whether something is explained is worse than no answer,
because it reads as an explanation being absent.

**And nothing here decides anything** — the same split `baselines.py`,
`closures.py`, `routines.py` and `thermal.py` keep. It answers "what did
somebody do by hand, when, how often, and is there a shape to it";
`curiosity.py` decides which of those is worth spending a Claude run on,
and a person decides whether the answer is true.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import time

import habits

log = logging.getLogger("brain.manual")

STORE = os.environ.get("BRAIN_MANUAL_LEDGER", "/data/manual-actions.json")

# The same two months `override_ledger` and `routines` keep, for the same
# reason: long enough for a seasonal shape to appear, short enough that
# something somebody stopped doing in the spring is not asked about in
# the summer.
KEEP_DAYS = 60.0
# A ledger, not a log.
MAX_ROWS = 4000

# Which domains a person touching something is a *decision* on. The order
# is the ranking: with one question a day to spend, the machines whose
# timing carries a reason go before the lamp somebody walked past.
#
# This is the one guess in the file and it is made where being wrong is
# cheap, the trade `chore.waiting` and `measures_something_hot` write
# down: a domain left out costs a question nobody got, and one left in
# costs a run and a line of somebody's attention.
DOMAINS = (
    # Somebody ran a thing they had written down. The most informative
    # manual action in a house after a voice command, because a script
    # has a name that says what it is for.
    "script",
    "scene",
    # Water, heat and the machines with a season in them. "Why at seven"
    # is a real question about every one of these.
    "valve",
    "water_heater",
    "climate",
    "humidifier",
    "vacuum",
    # A switch is a pump, a heater, a dehumidifier, a sprinkler zone or a
    # Christmas tree. It carries no device class to tell them apart,
    # which is exactly why the answer has to be asked for.
    "switch",
    "input_boolean",
    "button",
    "input_button",
    "cover",
    "fan",
    "media_player",
    # Last on purpose. Lights are the highest-volume manual action in
    # nearly every house and the least likely to carry a reason worth
    # keeping, so they are eligible and they never outrank a pump.
    "light",
)
# And the domains where the question itself is the problem. A house that
# asks about these is a house somebody turns off, and being right about
# the pattern would not help: see the header.
EXCLUDED = ("lock", "alarm_control_panel", "person", "device_tracker",
            "binary_sensor", "sensor", "camera")

# The causes worth keeping. `unattributed` is deliberately absent — see
# the header — and so is every automated cause, which lands in the
# `automated` map instead.
CAUSES = ("person", "voice")
AUTOMATED_CAUSES = ("automation", "script", "scene", "brain")
# A state that is not a state. A light going `unavailable` is not a
# decision, and an `unknown` is a reading that is not there.
SKIP_STATES = ("unavailable", "unknown", "")

# What it takes to call a set of presses a shape rather than a
# coincidence. Looser than `routines.py`'s, and deliberately: that module
# is about to build a **time trigger**, which is wrong if it fires at the
# wrong end of an hour, where this is about to ask a **question**, which
# is answerable about "most evenings" as well as about 18:40.
MIN_DAYS = 4
MIN_SHARE = 0.4
MAX_SPREAD_MIN = 90.0
# Still happening. A shape somebody stopped in March goes on looking
# beautiful in a sixty-day ledger; the same gate `override_ledger.pattern`
# carries, for the same reason.
RECENT_DAYS = 12.0

# How far outside its own established shape a press has to fall before it
# is *odd* rather than merely late. Three spreads of the subject's own
# scatter, with a floor under it, because three spreads of a shape that
# never varies is four minutes.
OFF_PATTERN_SPREADS = 3.0
OFF_PATTERN_FLOOR_MIN = 90.0
# And how much shape there has to be before "outside it" means anything.
OFF_PATTERN_MIN_DAYS = 6
# An odd press is news for about as long as somebody remembers doing it.
OFF_PATTERN_RECENT_H = 36.0


def domain_of(entity_id: str) -> str:
    return entity_id.split(".", 1)[0] if "." in entity_id else ""


def eligible_domain(entity_id: str) -> bool:
    """Is this something worth being curious about at all?

    Both halves are asked, and the refusal is asked first: `EXCLUDED` is
    a rule about what may never be asked, and `DOMAINS` is a guess about
    what is worth asking. A domain in neither is simply not kept.
    """
    domain = domain_of(entity_id)
    if domain in EXCLUDED:
        return False
    return domain in DOMAINS


def rank_of(entity_id: str) -> int:
    """Where this domain sits in `DOMAINS`. Lower is more interesting."""
    domain = domain_of(entity_id)
    return DOMAINS.index(domain) if domain in DOMAINS else len(DOMAINS)


def subject_key(entity_id: str, state: str) -> str:
    """The thing a question is about: one entity going to one state.

    Not the press. *"Why do you turn the sprinklers on"* and *"why do you
    turn them off"* are two questions with two answers, and a key that
    collapsed them would ask a model about a set of events with no single
    reason behind it.
    """
    return f"{entity_id}|{state}"


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------

def load(path: str | None = None) -> dict:
    """`{"rows": [...], "automated": {key: last_ts}}`, however it failed.

    Every way of failing reads as *no evidence*, which costs a question
    going unasked for another pass. The alternative — a half-read ledger
    read as a complete one — would ask a model about four rows and call
    them a month.
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
        log.warning("could not write the manual-action ledger: %s", exc)


def _row_id(row: dict) -> str:
    """The event, not the offering.

    Checks passes overlap — every six hours over a twenty-six hour
    window — so the same press arrives four or five times, and a ledger
    that appended what it was given would report one evening as five.
    `override_ledger` and `routines` both key this way for the same
    reason.
    """
    return "{}|{}|{}".format(int(row.get("ts") or 0),
                             row.get("entity_id") or "",
                             row.get("state") or "")


def record(actions: list[dict], now: float | None = None,
           path: str | None = None) -> int:
    """File what this pass saw. Returns how many person-moves were new."""
    now = time.time() if now is None else now
    payload = load(path)
    rows = payload["rows"]
    automated = payload["automated"]
    seen = {_row_id(r) for r in rows}
    added = 0
    for action in actions or []:
        entity_id = str(action.get("entity_id") or "")
        state = str(action.get("state") or "")
        ts = action.get("ts")
        if not entity_id or not ts or state in SKIP_STATES:
            continue
        if not eligible_domain(entity_id):
            continue
        cause = action.get("cause")
        if cause in AUTOMATED_CAUSES:
            key = subject_key(entity_id, state)
            automated[key] = max(float(ts), automated.get(key, 0.0))
            continue
        if cause not in CAUSES:
            continue
        row = {"ts": int(ts), "entity_id": entity_id, "state": state,
               "name": str(action.get("name") or entity_id),
               "cause": cause}
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

def by_subject(rows: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for row in rows or []:
        entity_id = str(row.get("entity_id") or "")
        state = str(row.get("state") or "")
        if not entity_id or not state or not row.get("ts"):
            continue
        grouped.setdefault(subject_key(entity_id, state), []).append(row)
    for group in grouped.values():
        group.sort(key=lambda r: r.get("ts") or 0)
    return grouped


def shape(rows: list[dict], tz=None, now: float | None = None) -> dict | None:
    """When one subject's presses happen, when there is a "when".

    `None` rather than a weak answer, the rule `override_ledger.pattern`
    and `routines._grade` both keep: a set of times nobody would
    recognise as a pattern, reported as if it were one, invites a
    question built around a coincidence — and a question is the one
    thing here that costs somebody's attention whether or not it was
    worth asking.

    The median is **circular** and the arithmetic is `rhythm.py`'s,
    imported rather than copied: presses either side of midnight have a
    straight median of noon, which is not a small error but the opposite
    side of the day.
    """
    tz = tz or dt.timezone.utc
    now = time.time() if now is None else now
    if not rows:
        return None
    # One grading, this ledger's floors: looser than `routines` on
    # purpose (a question is answerable about "most evenings"), and the
    # share is over the SPAN the presses cover rather than a claimed
    # shape's eligible days, because no claim is being made — the label
    # is observed and rendered as "any day" when the week is mixed.
    found = habits.grade([r["ts"] for r in rows if r.get("ts")], tz, now,
                         min_days=MIN_DAYS, max_spread_min=MAX_SPREAD_MIN,
                         recent_days=RECENT_DAYS)
    if not found or not found["still_happening"]:
        return None
    first, last = found["first"], found["last"]
    span_days = max(1, int((last - first) // 86400) + 1)
    share = found["days"] / span_days
    if share < MIN_SHARE:
        return None
    when_days = ("any day" if found["shape"] == habits.EVERY_DAY
                 else found["shape"])

    return {
        "events": found["stamps"],
        "days": found["days"],
        "span_days": span_days,
        "share": round(share, 3),
        "minute": round(found["median_minute"]),
        "at": found["at"],
        "spread_min": found["spread_min"],
        "when_days": when_days,
        "first": int(first),
        "last": int(last),
        "cause": "voice" if all(r.get("cause") == "voice" for r in rows)
                 else "person",
    }


def _describe(rows: list[dict]) -> dict:
    last = rows[-1]
    return {
        "entity_id": last.get("entity_id") or "",
        "state": last.get("state") or "",
        "name": last.get("name") or last.get("entity_id") or "",
    }


def recurring(payload: dict | None = None, tz=None,
              now: float | None = None,
              path: str | None = None) -> list[dict]:
    """Every subject with a shape brAIn has no explanation for.

    The sprinkler case, and the one the request that produced this module
    named: *somebody runs this at about this time, most days, and nothing
    anywhere says why*. Sorted so that with one question to spend it is
    asked about the strongest shape on the most interesting domain, and
    so that the ordering is **total** — an arbitrary pick among ties
    would ask about a different subject on every pass and settle none of
    them.
    """
    payload = load(path) if payload is None else payload
    automated = payload.get("automated") or {}
    out: list[dict] = []
    for key, rows in by_subject(payload.get("rows") or []).items():
        if key in automated:
            # Something already does this, so a person doing it too is a
            # disagreement rather than a mystery, and `auto.overridden`
            # is the finding that reports it.
            continue
        found = shape(rows, tz, now)
        if not found:
            continue
        out.append({"kind": "recurring", "subject": key,
                    **_describe(rows), **found})
    out.sort(key=lambda s: (rank_of(s["entity_id"]), -s["days"],
                            -s["share"], s["subject"]))
    return out


def off_pattern(payload: dict | None = None, tz=None,
                now: float | None = None,
                path: str | None = None) -> list[dict]:
    """Presses that fall well outside their own subject's established shape.

    The other half, and the one no measurement brAIn had could see: the
    heating turned up at two in the morning by somebody who never does
    that. It is deliberately asked only of a subject that **already has**
    a shape — a first-ever press on a new device would otherwise be the
    oddest thing in the house every time something was installed, which
    is how a feature like this fires on a healthy house.

    The distance is measured the short way round, because 23:50 is twenty
    minutes from 00:10 and a straight subtraction makes it the oddest
    press ever recorded.
    """
    payload = load(path) if payload is None else payload
    tz = tz or dt.timezone.utc
    now = time.time() if now is None else now
    out: list[dict] = []
    for key, rows in by_subject(payload.get("rows") or []).items():
        if len(rows) < 2:
            continue
        recent = [r for r in rows
                  if (now - (r.get("ts") or 0)) <= OFF_PATTERN_RECENT_H * 3600]
        if not recent:
            continue
        # The shape is measured over everything EXCEPT the presses being
        # judged. A press included in its own baseline drags the centre
        # toward itself, which is how the oddest thing in the house comes
        # out ordinary. Split by row id rather than by dict equality: two
        # rows that happened to carry the same values would exclude each
        # other, and `in` over a list is a scan per row.
        judged = {_row_id(r) for r in recent}
        history = [r for r in rows if _row_id(r) not in judged]
        found = shape(history, tz, now)
        if not found or found["days"] < OFF_PATTERN_MIN_DAYS:
            continue
        # `habits.odd_press` is the one arithmetic — the distance the
        # short way round, the allowance off the subject's own spread —
        # handed the shape already graded so every press in this burst is
        # judged against the same history.
        judged_shape = {"days": found["days"], "spread_min": found["spread_min"],
                        "median_minute": found["minute"], "at": found["at"]}
        for row in recent:
            odd = habits.odd_press(row["ts"], [], tz, shape=judged_shape,
                                   spreads=OFF_PATTERN_SPREADS,
                                   floor_min=OFF_PATTERN_FLOOR_MIN,
                                   min_days=OFF_PATTERN_MIN_DAYS)
            if not odd:
                continue
            out.append({
                "kind": "off_pattern", "subject": key,
                **_describe([row]),
                "ts": int(row["ts"]),
                "at": odd["at"],
                "cause": row.get("cause") or "person",
                "usually_at": odd["usually_at"],
                "usually_spread_min": odd["usually_spread_min"],
                "away_min": odd["away_min"],
                "allowance_min": odd["allowance_min"],
                "days": found["days"],
                "events": found["events"],
                "when_days": found["when_days"],
            })
    out.sort(key=lambda s: (-s["away_min"], rank_of(s["entity_id"]),
                            s["subject"]))
    return out


def candidates(payload: dict | None = None, tz=None,
               now: float | None = None,
               path: str | None = None) -> list[dict]:
    """Everything worth being curious about, in one list.

    The odd presses first: *"why did you do that last night"* is a
    question somebody can still answer, where *"why do you do that most
    evenings"* is true next week as well. `curiosity.py` takes the
    budget and the settling from here.
    """
    payload = load(path) if payload is None else payload
    return (off_pattern(payload, tz, now)
            + recurring(payload, tz, now))


def progress(payload: dict | None = None, now: float | None = None,
             path: str | None = None) -> dict:
    """One question about this store, in `house.py`'s shape.

    A floor's cost is silence, and silence is indistinguishable from
    broken: on a fresh install there is nothing to be curious about for a
    week, and nothing anywhere would say so.
    """
    payload = load(path) if payload is None else payload
    rows = payload.get("rows") or []
    now = time.time() if now is None else now
    if not rows:
        return {"state": "collecting", "have": 0, "need": MIN_DAYS,
                "unit": "days of manual actions", "reason": "",
                "ready_at": None,
                "note": "nobody has been seen using a control by hand yet"}
    days = len({dt.datetime.fromtimestamp(r["ts"], dt.timezone.utc).date()
                for r in rows if r.get("ts")})
    if days < MIN_DAYS:
        return {"state": "collecting", "have": days, "need": MIN_DAYS,
                "unit": "days of manual actions", "reason": "",
                "ready_at": int(now + (MIN_DAYS - days) * 86400),
                "note": f"{days} of {MIN_DAYS} days seen"}
    return {"state": "ready", "have": days, "need": MIN_DAYS,
            "unit": "days of manual actions", "reason": "",
            "ready_at": None,
            "note": f"{len(rows)} manual actions over {days} days"}


__all__ = [
    "AUTOMATED_CAUSES", "CAUSES", "DOMAINS", "EXCLUDED", "KEEP_DAYS",
    "MAX_ROWS", "MAX_SPREAD_MIN", "MIN_DAYS", "MIN_SHARE",
    "OFF_PATTERN_FLOOR_MIN", "OFF_PATTERN_MIN_DAYS",
    "OFF_PATTERN_RECENT_H", "OFF_PATTERN_SPREADS", "RECENT_DAYS", "STORE",
    "by_subject", "candidates", "domain_of", "eligible_domain", "load",
    "off_pattern", "progress", "rank_of", "record", "recurring", "save",
    "shape", "subject_key",
]
