"""What brAIn checks by rule while its looks are held for budget.

The Resident's first look is what turns a reading a little outside its
band into a finding, and the look is a Claude run: when the session
budget is spent or the account's usage limit is reached, `_resident_gate`
holds the batch and nothing looks. That is right for spending and wrong
for a freezer, a water meter or a lock, because "held" read as "nobody
was told" — the decision trail said `gate_hold` seven times about one
freezer probe and the household heard nothing.

So while a batch is held for budget, the signals about food storage,
water and security are checked here, in code and against what the house
already measured, and **nothing here spends a run or takes an action**:
it returns rows for the normal filing path (`triage.gate`, then shown as
nothing having looked, which is true) and nothing else.

* **Which entities.** Read off structure, never names. Security is the
  entity's domain (a lock, an alarm panel) or a door/window/lock class;
  water is a valve or a water/moisture/flow class; food storage is a
  temperature whose own measured usual is cold (`COLD_USUAL_MAX_C`) and
  held tight (`COLD_SPREAD_MAX_C`) — a fridge or a freezer is a regulated
  band, and an outdoor thermometer in winter is cold but not regulated.
* **What trips.** A reading outside its own band (`resident._judged`, the
  bar the look itself is offered readings at) in the harmful direction,
  by a move a person would notice (`checks.baseline.min_move`), AND past a
  unit-aware limit for food storage: a freezer warmer than -15 °C (5 °F),
  a fridge warmer than 5 °C (41 °F) — the same figures the look is given.
  A probe by a freezer's door that always reads warm is inside its band,
  so the band is what keeps this quiet on a healthy house; the limit is
  what keeps it quiet on a band that only moved a little. A lock that
  says it is jammed and an alarm that says it was triggered trip on their
  own state. A leak, smoke or gas detector is the safety lane's and is
  not checked twice.
* **What is said.** One notice per kind of entity per house day, never
  one per held look: that the closer look was skipped and why, and what
  the rule found instead.
"""
from __future__ import annotations

import datetime as dt

COLD, WATER, SECURITY = "cold", "water", "security"
# What a person reads for each kind.
KIND_WORDS = {COLD: "fridge and freezer", WATER: "water",
              SECURITY: "door, lock and alarm"}
KIND_ORDER = (COLD, WATER, SECURITY)

# The producers, as house checks: filed by code (no model's sentence to
# rewrite), muted by "Stop raising these" like any check, and a notice can
# carry `valid_until`, so it retires itself when its day is over.
TRIP_SOURCE = "check:budget.tripped"
NOTICE_SOURCE = "check:budget.skipped"
TRIP_TITLE = "Checked by rule while looks were paused"
NOTICE_TITLE = "Looks paused for budget"

SECURITY_DOMAINS = frozenset({"lock", "alarm_control_panel"})
SECURITY_CLASSES = frozenset({"door", "garage_door", "window", "opening",
                              "lock", "tamper"})
WATER_DOMAINS = frozenset({"valve"})
WATER_CLASSES = frozenset({"moisture", "water", "volume_flow_rate"})
# States that mean it, read off the entity itself.
TRIPPED_STATES = {"lock": frozenset({"jammed"}),
                  "alarm_control_panel": frozenset({"triggered"})}

# A temperature whose usual is at or under this is kept cold on purpose…
COLD_USUAL_MAX_C = 8.0
# …when its band is this tight (a median absolute deviation, °C).
COLD_SPREAD_MAX_C = 2.5
# Under this usual it is a freezer, else a fridge.
FREEZER_USUAL_MAX_C = -5.0
# Past these, food is at risk whatever the band says.
FREEZER_LIMIT_C = -15.0
FRIDGE_LIMIT_C = 5.0


def _domain(entity_id: str) -> str:
    return str(entity_id or "").split(".", 1)[0]


def _celsius(value: float, unit: str) -> float | None:
    import numfmt  # noqa: PLC0415 — panel-local leaf
    from checks.thermal import _to_celsius  # noqa: PLC0415

    which = numfmt.temperature_unit(unit)
    return _to_celsius(float(value), which) if which else None


def _usual(baseline: dict) -> tuple[float, float] | None:
    overall = (baseline or {}).get("overall") or {}
    median, spread = overall.get("median"), overall.get("spread")
    if not isinstance(median, (int, float)) or isinstance(median, bool):
        return None
    return float(median), float(spread or 0.0)


def kind_of(entity_id: str, device_class: str = "",
            baseline: dict | None = None) -> str:
    """`COLD`, `WATER`, `SECURITY` or "" for one entity."""
    domain = _domain(entity_id)
    klass = str(device_class or "").strip().lower()
    if domain in SECURITY_DOMAINS or (domain == "binary_sensor"
                                      and klass in SECURITY_CLASSES):
        return SECURITY
    if domain in WATER_DOMAINS or klass in WATER_CLASSES:
        return WATER
    if klass not in ("", "temperature") or not isinstance(baseline, dict):
        return ""
    usual = _usual(baseline)
    unit = str(baseline.get("unit") or "")
    if usual is None:
        return ""
    centre = _celsius(usual[0], unit)
    if centre is None or centre > COLD_USUAL_MAX_C:
        return ""
    # A spread is a difference: no offset in the conversion.
    import numfmt  # noqa: PLC0415
    spread_c = usual[1] / 1.8 if numfmt.temperature_unit(unit) == "°F" \
        else usual[1]
    return COLD if spread_c <= COLD_SPREAD_MAX_C else ""


def _reading(entity_id: str, live: dict, signal: dict):
    """The entity's state now (the bus keeps `live` current), else the
    value its signal carried."""
    row = (live or {}).get(entity_id)
    if isinstance(row, dict) and str(row.get("state") or "") not in (
            "", "unknown", "unavailable"):
        return str(row["state"])
    for ev in (signal or {}).get("evidence") or ():
        if isinstance(ev, dict) and ev.get("entity") == f"{entity_id}.value":
            return str(ev.get("value") or "")
    return ""


def _measured_trip(entity_id: str, kind: str, value: float, baseline: dict,
                   bucket: int) -> dict | None:
    """A numeric reading outside its band the harmful way, or None."""
    import resident  # noqa: PLC0415 — the look's own bar, read lazily
    from checks.baseline import min_move  # noqa: PLC0415

    usual = _usual(baseline)
    if usual is None:
        return None
    unit = str(baseline.get("unit") or "")
    judged = resident._judged(value, baseline, bucket)
    drift = baseline.get("trend") or {}
    drifted = bool(drift.get("consistent")) and float(
        drift.get("spreads") or 0.0) >= resident.USUAL_DRIFT_SPREADS
    outside = bool(judged and judged["outside"]) or drifted
    # Warmer for food storage, more for water: the direction that harms.
    if not outside or value <= usual[0] or value - usual[0] < min_move(unit):
        return None
    out = {"value": value, "usual": usual[0], "spread": usual[1],
           "unit": unit, "drifted": drifted and not (
               judged and judged["outside"])}
    if kind == COLD:
        reading_c, usual_c = _celsius(value, unit), _celsius(usual[0], unit)
        if reading_c is None or usual_c is None:
            return None
        limit_c = (FREEZER_LIMIT_C if usual_c <= FREEZER_USUAL_MAX_C
                   else FRIDGE_LIMIT_C)
        if reading_c <= limit_c:
            return None
        out["limit_c"] = limit_c
    return out


def check(pending: list[dict], baselines: dict, names: dict, live: dict,
          bucket: int) -> dict:
    """Every held signal about food storage, water or security, checked.

    ``pending`` is the Resident's held batch; ``baselines`` the baseline
    store's entities; ``names`` `server._NAMES` (``name``, ``class``);
    ``live`` `findings_store.LIVE_STATES`. Returns ``{"seen": {kind:
    [entity ids]}, "trips": [{entity, kind, name, state | measured}],
    "inside": [{entity, kind, name} read and not tripped]}``. Pure: no store, no
    clock, no run.
    """
    seen: dict[str, list[str]] = {}
    trips: list[dict] = []
    inside: list[str] = []
    for sig in pending or ():
        if not isinstance(sig, dict) or sig.get("finding_ts"):
            # A filed row is on the list already, and is shown whether or
            # not a look reaches it (the stale sweep).
            continue
        eid = str(sig.get("subject") or "")
        if "." not in eid:
            continue
        row = (names or {}).get(eid) or {}
        baseline = (baselines or {}).get(eid)
        kind = kind_of(eid, row.get("class") or "", baseline)
        if not kind or eid in seen.get(kind, ()):
            continue
        seen.setdefault(kind, []).append(eid)
        state = _reading(eid, live, sig)
        name = str(row.get("name") or eid)
        tripped = TRIPPED_STATES.get(_domain(eid))
        if tripped is not None:
            if state.lower() in tripped:
                trips.append({"entity": eid, "kind": kind, "name": name,
                              "state": state.lower()})
            elif state:
                inside.append({"entity": eid, "kind": kind, "name": name})
            continue
        try:
            value = float(state)
        except (TypeError, ValueError):
            continue
        if not isinstance(baseline, dict):
            continue
        found = _measured_trip(eid, kind, value, baseline, bucket)
        if found:
            trips.append({"entity": eid, "kind": kind, "name": name,
                          "measured": found})
        else:
            inside.append({"entity": eid, "kind": kind, "name": name})
    return {"seen": seen, "trips": trips, "inside": inside}


def skipped_because(why: str) -> str:
    """The sentence a row filed here carries where a look's would be."""
    return (f"brAIn's closer look was skipped because {why}, so this was "
            "checked by rule against what the house usually reads instead.")


def trip_text(trip: dict) -> str:
    """The row's title: stable per entity, so a re-report is one row."""
    name = trip["name"]
    if trip.get("state"):
        return f"{name} says {trip['state']}"
    if trip["kind"] == COLD:
        return f"{name} is warmer than it is kept"
    return f"{name} is higher than its usual range"


def titles_for(row: dict) -> set[str]:
    """Every title `trip_text` can give this entity (``entity``, ``kind``,
    ``name``), so a trip that is over can be found by it."""
    states = TRIPPED_STATES.get(_domain(row["entity"]), ())
    if states:
        return {trip_text({**row, "state": s}) for s in states}
    return {trip_text(row)}


def trip_row(trip: dict, why: str) -> dict:
    """A wire-shaped finding for one trip. No action, nothing fixable."""
    import numfmt  # noqa: PLC0415

    name = trip["name"]
    if trip.get("state"):
        said = f"{name} reported {trip['state']}."
    else:
        m = trip["measured"]
        unit = m["unit"]

        def q(v):
            return (numfmt.temperature(v, unit) if trip["kind"] == COLD
                    else numfmt.quantity(v, unit))
        low, high = m["usual"] - 3 * m["spread"], m["usual"] + 3 * m["spread"]
        said = (f"{name} reads {q(m['value'])}; it usually reads "
                f"{q(m['usual'])} (from {q(low)} to {q(high)})")
        if m.get("drifted"):
            said += ", and has been climbing for days"
        if "limit_c" in m:
            said += (", and it is warmer than "
                     f"{numfmt.temperature(m['limit_c'], '°C', whole=True)}, "
                     "past which food is not kept safely")
        said += "."
    return {
        "text": trip_text(trip),
        "detail": f"{said} {skipped_because(why)}",
        "kind": "problem",
        "severity": "warning",
        "fixable": False,
        "entity_id": trip["entity"],
        "source": TRIP_SOURCE,
        "source_title": TRIP_TITLE,
    }


def notice_row(kind: str, seen: list[str], tripped: int, why: str,
               local: dt.datetime) -> dict:
    """The day's one notice for one kind: the look was skipped, and what
    the rule found instead. Valid until the house day is over."""
    import numfmt  # noqa: PLC0415

    words = KIND_WORDS[kind]
    stamp = f"{local:%a} {local.day} {local:%b}"
    n = len(seen)
    readings = numfmt.count(n, "reading", "readings")
    found = ("none was outside it" if not tripped
             else "one was outside it and is on the list" if tripped == 1
             else f"{tripped} were outside it and are on the list")
    midnight = (local + dt.timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    return {
        "text": f"brAIn could not look closely at {words} readings "
                f"({stamp})",
        "detail": (f"Its closer look at {readings} was skipped because "
                   f"{why}. It checked {'it' if n == 1 else 'them'} by rule "
                   f"against what the house usually reads instead, and "
                   f"{found}. It looks closely again once the budget "
                   "allows."),
        "kind": "problem",
        "severity": "info",
        "fixable": False,
        "source": NOTICE_SOURCE,
        "source_title": NOTICE_TITLE,
        "valid_until": int(midnight.timestamp()),
    }


__all__ = [
    "COLD", "KIND_ORDER", "KIND_WORDS", "NOTICE_SOURCE", "SECURITY",
    "TRIP_SOURCE", "WATER", "check", "kind_of", "notice_row",
    "skipped_because", "titles_for", "trip_row", "trip_text",
]
