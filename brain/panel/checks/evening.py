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

from ._util import House, join_names

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

    hits = []
    for eid, entry in entities.items():
        st = house.states.get(eid)
        if not st or not house.enabled(eid):
            continue
        state = str(st.get("state") or "").lower()
        if state not in closures.OPEN_STATES:
            continue
        usual = closures.usual_open(entry, bucket)
        # None is "not watched at this hour", which is not "never open".
        if usual is None or usual > RARE_OPEN:
            continue
        hits.append((usual, eid, entry))

    if not hits or len(hits) > MAX_ROWS:
        return []
    hits.sort()

    names = sorted(house.name(eid) for _u, eid, _e in hits)
    when = (f"around {settles // 60:02d}:{settles % 60:02d}, which is when "
            "this house usually settles"
            if settles is not None else
            f"after {FALLBACK_HOUR}:00")
    return [{
        # One row, not one per door: this is a single thing to do before
        # bed, and four rows to dismiss one at a time is a chore.
        "text": "Something is open that is usually shut at this hour",
        "detail": (join_names(names) + " — open now, and "
                   + ("normally shut at this hour of the week"
                      if len(hits) > 1 else
                      f"open for under {int(RARE_OPEN * 60)} minutes of "
                      "this hour in an ordinary week")
                   + f". Checked {when}."),
        "fix": ("Shut it, or if it is meant to be open press Wrong and "
                "say so — brAIn measures what is normal here rather than "
                "assuming, so it will stop asking once this hour looks "
                "like your ordinary one."),
        "severity": "warning",
        "fixable": False,
        "entity_id": hits[0][1],
    }]


CHECKS = [
    {"id": "evening.left_open",
     "title": "Open at bedtime, and usually shut",
     "needs": ("states", "registry", "closures"), "run": left_open},
]

__all__ = ["CHECKS"]
