"""What is open at bedtime that usually is not.

The one thing people most want a house to notice, and the one brAIn could
not say anything about: every other check here reads a state and knows
whether it is wrong, and *a door being open is not wrong*. It is wrong at
half past eleven on a Tuesday in a house that always has it shut then,
and it is nothing at all in a house that leaves it open all summer. The
difference is a measurement, and `panel/closures.py` is where it lives.

Three rules, and each answers "does this fire on a healthy house".

**It only speaks at bedtime.** A door open at four in the afternoon is a
door somebody is using. The window comes from `panel/rhythm.py` — when
this house actually settles, weekdays and weekends apart — and falls back
to a configured hour until there is a measurement, exactly as the morning
brief does.

**It only speaks about an hour it has watched.** `usual_open` returns
`None` for a bucket with no observation behind it, and that is a
different answer from "never open then": an entity added on Tuesday knows
nothing about Sunday, and reporting a fraction of a fraction as a habit
is how a check earns being ignored.

**And past a handful of rows it says nothing at all.** A house being aired
out, or a recorder that was purged, moves every closure at once — and
fifteen rows about open windows is a report about the measurement rather
than about the house, the same cap `base.unusual` carries.
"""
from __future__ import annotations

import logging
import re

from ._util import House, clock, join_names, parse_ts

log = logging.getLogger("brain.checks.evening")

# Open this little of the hour, historically, and having it open now is
# news. Five percent of an hour is three minutes: a door somebody walks
# through every evening clears this comfortably.
RARE_OPEN = 0.05
# How far either side of the measured settle time counts as bedtime.
WINDOW_MIN = 90
# Until this house has been measured. Deliberately late: a check that
# fires at nine in the evening is a check that fires while people are
# still up, and that is the one way this becomes noise.
FALLBACK_HOUR = 23
# More than this and it is the house, not a door.
MAX_ROWS = 4


_CAR_RE = re.compile(r"\b(car|vehicle|truck|suv|van)\b", re.I)


def _car(house: House, eid: str) -> bool:
    return eid.startswith("lock.") and bool(_CAR_RE.search(house.name(eid)))


def _bedtime(now: float) -> tuple[bool, int | None]:
    """Whether it is around this house's bedtime, and what that is.

    The second half is returned so the finding can say *why* it thinks
    now is late — a check whose timing nobody can see is a check people
    argue with.
    """
    try:
        import baselines  # noqa: PLC0415
        import rhythm  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001 — the package stays importable
        log.debug("rhythm unavailable: %s", exc)
        return False, None

    import datetime as dt  # noqa: PLC0415

    tz, _name = baselines.house_timezone()
    local = dt.datetime.fromtimestamp(now, tz)
    minute = local.hour * 60 + local.minute
    settles = rhythm.settle_minute(rhythm.profile(), local)
    target = settles if settles is not None else FALLBACK_HOUR * 60
    # Around it, the short way round the clock: 00:10 is twenty minutes
    # from 23:50, and a bedtime near midnight is the ordinary case.
    away = abs(minute - target) % rhythm.MINUTES_PER_DAY
    near = min(away, rhythm.MINUTES_PER_DAY - away) <= WINDOW_MIN
    return near, (int(settles) if settles is not None else None)


def left_open(snap: dict, now: float) -> list[dict]:
    """Closures that are open now and are normally shut at this hour."""
    import baselines  # noqa: PLC0415
    import closures  # noqa: PLC0415

    store = snap.get("closures") or {}
    entities = store.get("entities") or {}
    if not entities:
        return []
    near, settles = _bedtime(now)
    if not near:
        return []

    tz, _name = baselines.house_timezone()
    bucket = baselines.hour_of_week(now, tz)
    house = House(snap)
    # A lock's own door sensor that says open while the door's dedicated
    # contact says shut and the lock is locked is the sensor, not the door
    # (#1130): `dev.door_disagree` reports the sensor, once.
    shut_by_contact = closures.outvoted(house.states, _pairs(house))

    hits = []
    for eid, entry in entities.items():
        st = house.states.get(eid)
        if not st or not house.enabled(eid):
            continue
        state = str(st.get("state") or "").lower()
        if state not in closures.OPEN_STATES:
            continue
        if eid in shut_by_contact:
            contact = shut_by_contact[eid]["contact"]
            house.gave_up("evening.left_open", [{"entity_id": eid}],
                          f"{house.label(contact)} on the same door reads "
                          "closed and the lock is locked, so the door is "
                          "shut", kind="explained")
            continue
        usual = closures.usual_open(entry, bucket)
        # None is "not watched at this hour", which is not "never open".
        if usual is None or usual > RARE_OPEN:
            continue
        if not house.should_report(eid, "evening.left_open"):
            continue
        hits.append((usual, eid, entry))

    if len(hits) > MAX_ROWS:
        house.gave_up("evening.left_open", [{"entity_id": h[1]} for h in hits],
                      f"{len(hits)} doors and windows were open at once at "
                      f"bedtime — past {MAX_ROWS} that is a house being aired, "
                      "not doors left open by mistake")
        return []
    if not hits:
        return []
    hits.sort()

    names = sorted(house.name(eid) for _u, eid, _e in hits)
    when = (f"around {settles // 60:02d}:{settles % 60:02d}, which is when "
            "this house usually settles"
            if settles is not None else
            f"after {FALLBACK_HOUR}:00")
    # A lock is unlocked and a car is a car: "open" is a door's word, and a
    # car left unlocked read as a door left open told nobody which it was.
    locks = all(eid.startswith("lock.") for _u, eid, _e in hits)
    cars = locks and all(_car(house, eid) for _u, eid, _e in hits)
    if cars:
        text = "A car is unlocked when it is usually locked at this hour"
    elif locks:
        text = "Something is unlocked that is usually locked at this hour"
    else:
        text = "Something is open that is usually shut at this hour"
    now_word, usual_word = (("unlocked", "locked") if locks
                            else ("open", "shut"))
    return [{
        # One row, not one per door: this is a single thing to do before
        # bed, and four rows to dismiss one at a time is a chore.
        "text": text,
        "detail": (join_names(names) + f" — {now_word} now, and "
                   + (f"normally {usual_word} at this hour of the week"
                      if len(hits) > 1 else
                      f"{now_word} for under {int(RARE_OPEN * 60)} minutes "
                      "of this hour in an ordinary week")
                   + f". Checked {when}."),
        "fix": f"{usual_word.capitalize()} it if it should be {usual_word}.",
        "severity": "warning",
        "fixable": False,
        "entity_id": hits[0][1],
    }]


def _pairs(house: House) -> dict:
    """`closures.door_pairs` over this snapshot's registries."""
    import closures  # noqa: PLC0415

    return closures.door_pairs(house.states, house.entities,
                               list(house.devices.values()))


# How long both sensors have to have held their readings before a
# disagreement is a fault: a lock's sensor reporting a few seconds behind
# the contact is radio, not a fitting.
DISAGREE_SETTLE_S = 15 * 60


def door_disagree(snap: dict, now: float) -> list[dict]:
    """A lock's own door sensor that contradicts the door's contact sensor.

    One row per door, about the lock's sensor, for as long as the two
    disagree: the text names the two sensors and nothing that changes
    while they do, so each pass finds the same row rather than filing a
    new one. What brAIn believes in the meantime is the contact's reading
    while the lock is locked (`closures.outvoted`).
    """
    house = House(snap)
    out = []
    for sensor, pair in sorted(_pairs(house).items()):
        contact, lock = pair["contact"], pair["lock"]
        mine = house.states.get(sensor) or {}
        theirs = house.states.get(contact) or {}
        a = str(mine.get("state") or "").lower()
        b = str(theirs.get("state") or "").lower()
        if {a, b} != {"on", "off"}:
            continue
        changed = [parse_ts(mine.get("last_changed")),
                   parse_ts(theirs.get("last_changed"))]
        if any(t is None or now - t < DISAGREE_SETTLE_S for t in changed):
            continue
        if not house.should_report(sensor, "dev.door_disagree"):
            continue
        since = clock(max(changed))
        lock_word = str((house.states.get(lock) or {}).get("state") or "")
        said_open, said_shut = ((house.label(sensor), house.label(contact))
                                if a == "on" else
                                (house.label(contact), house.label(sensor)))
        believed = (
            "While the lock is locked and the contact sensor reads closed, "
            "brAIn takes the door as shut; whenever the contact sensor reads "
            "open, brAIn takes the door as open."
            if a == "on" else
            "brAIn takes the door as open while the contact sensor says so.")
        out.append({
            "text": (f"{house.label(sensor)} disagrees with "
                     f"{house.label(contact)} about the same door"),
            "detail": (f"Since {since}, {said_open} has read open and "
                       f"{said_shut} closed, with "
                       f"{house.label(lock)} {lock_word or 'in an unknown state'}. "
                       f"{believed}"),
            "fix": ("Check how the lock's door sensor is fitted: most locks "
                    "need it calibrated again after the lock or the door is "
                    "adjusted, in the lock's own app."),
            "severity": "warning",
            "fixable": False,
            "entity_id": sensor,
            "evidence": [{"entity": sensor, "value": a},
                         {"entity": contact, "value": b}],
        })
    return out


CHECKS = [
    {"id": "evening.left_open", "area": "devices",
     "title": "Open at bedtime, and usually shut",
     "needs": ("states", "registry", "closures"), "run": left_open},
    {"id": "dev.door_disagree", "area": "devices",
     "title": "A lock's door sensor contradicts the door's contact sensor",
     "needs": ("states", "registry"), "run": door_disagree},
]

__all__ = ["CHECKS"]
