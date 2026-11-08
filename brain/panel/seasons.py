"""The turns of the year, each said once in the morning brief (#643).

brAIn promises one sentence, at a waking hour, for the moments a house
turns with the year: the first frost, the first morning the heating ran,
the solstices and equinoxes, and the last cooling run — said in hindsight,
once enough cool days have passed to know it was the last.

**All of it is arithmetic, so code does it.** The solstices and equinoxes
are computed (`turning_points`, Meeus' method, to within minutes); the
frost is the forecast low the occasions read already fetches; heating and
cooling are climate entities' `hvac_action` in the recorder's history. No
model decides that −2 °C is a frost or that a fortnight is long enough, and
the sentence is composed here and sent as written.

**A "first" needs a watch behind it.** A record that began yesterday has
not seen the summer, and "the first frost of the autumn" on the day brAIn
was installed in January would be a guess. So a first is only a first when
brAIn looked on most of the days before it (`LOOKED_MIN` of `QUIET_DAYS`)
and saw none, and only in the half of the year that ends in winter.

**Once, and only once delivered.** Each event has a key per season; it is
`said` when the brief carrying it was sent, never when it was composed,
and an event nobody heard inside its few days stops being offered rather
than arriving a week late.

Stdlib only and pure over what it is handed; the server fetches.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
from pathlib import Path

import atomic_write

FILENAME = "seasons.json"
# Beside the forecast it reads (`occasions.STORE`) unless named.
STORE_ENV = "BRAIN_SEASONS_FILE"

FROST_C = 0.0
# A first needs this many days before it with none, and brAIn looking on
# at least LOOKED_MIN of them.
QUIET_DAYS = 30
LOOKED_MIN = 21
# The last cooling run is said once this many days have passed without
# one, and brAIn looked on most of them.
COOL_DAYS = 21
COOL_LOOKED_MIN = 15
# How long a moment stays worth a sentence after its day.
SAY_WITHIN = {"frost": 1, "heating": 2, "cooling_end": 2, "turn": 1}
# Days of record kept.
KEEP_DAYS = 400
# Climate entities read per pass.
MAX_CLIMATE = 20

NORTH, SOUTH = "north", "south"


def path_for(beside: Path | str | None) -> Path:
    named = os.environ.get(STORE_ENV)
    if named:
        return Path(named)
    return Path(beside).with_name(FILENAME) if beside else Path("/data") / FILENAME


def hemisphere(latitude) -> str:
    try:
        return SOUTH if float(latitude) < 0 else NORTH
    except (TypeError, ValueError):
        return NORTH


def _d(text: str) -> dt.date:
    return dt.date.fromisoformat(str(text)[:10])


def autumn_side(day: dt.date, hemi: str) -> bool:
    """The half of the year that ends in winter: July to December in the
    north, January to June in the south."""
    return (day.month >= 7) if hemi != SOUTH else (day.month <= 6)


# ---------------------------------------------------------------------------
# Solstices and equinoxes
# ---------------------------------------------------------------------------

# Meeus, Astronomical Algorithms, ch. 27: the mean instants for 2000–3000
# and the 24 periodic terms.
_MEAN = (
    (2451623.80984, 365242.37404, 0.05169, -0.00411, -0.00057),
    (2451716.56767, 365241.62603, 0.00325, 0.00888, -0.00030),
    (2451810.21715, 365242.01767, -0.11575, 0.00337, 0.00078),
    (2451900.05952, 365242.74049, -0.06223, -0.00823, 0.00032),
)
_TERMS = (
    (485, 324.96, 1934.136), (203, 337.23, 32964.467), (199, 342.08, 20.186),
    (182, 27.85, 445267.112), (156, 73.14, 45036.886), (136, 171.52, 22518.443),
    (77, 222.54, 65928.934), (74, 296.72, 3034.906), (70, 243.58, 9037.513),
    (58, 119.81, 33718.147), (52, 297.17, 150.678), (50, 21.02, 2281.226),
    (45, 247.54, 29929.562), (44, 325.15, 31555.956), (29, 60.93, 4443.417),
    (18, 155.12, 67555.328), (17, 288.79, 4562.452), (16, 198.04, 62894.029),
    (14, 199.76, 31436.921), (12, 95.39, 14577.848), (12, 287.11, 31931.756),
    (12, 320.81, 34777.259), (9, 227.73, 1222.114), (8, 15.45, 16859.074),
)
# Terrestrial time runs about this far ahead of UTC this century.
_DELTA_T_S = 70.0


def turning_instant(year: int, which: int) -> dt.datetime:
    """The instant (UTC) of the March equinox (0), June solstice (1),
    September equinox (2) or December solstice (3) of `year`."""
    y = (year - 2000) / 1000.0
    a, b, c, d, e = _MEAN[which]
    jde0 = a + b * y + c * y ** 2 + d * y ** 3 + e * y ** 4
    t = (jde0 - 2451545.0) / 36525.0
    w = math.radians(35999.373 * t - 2.47)
    dl = 1 + 0.0334 * math.cos(w) + 0.0007 * math.cos(2 * w)
    s = sum(amp * math.cos(math.radians(ph + sp * t)) for amp, ph, sp in _TERMS)
    jde = jde0 + 0.00001 * s / dl
    unix = (jde - 2440587.5) * 86400.0 - _DELTA_T_S
    return dt.datetime.fromtimestamp(unix, dt.timezone.utc)


# (north name, south name, longest/shortest) per instant.
_TURNS = (
    ("spring equinox", "autumn equinox", None),
    ("summer solstice", "winter solstice", "june"),
    ("autumn equinox", "spring equinox", None),
    ("winter solstice", "summer solstice", "december"),
)


def turning_points(year: int, tz, hemi: str = NORTH) -> list[dict]:
    """The year's four turning points, on the house's own calendar."""
    out = []
    for which, (north, south, solstice) in enumerate(_TURNS):
        when = turning_instant(year, which).astimezone(tz or dt.timezone.utc)
        name = south if hemi == SOUTH else north
        out.append({"key": f"turn:{when.date().isoformat()}", "kind": "turn",
                    "date": when.date().isoformat(), "name": name,
                    "solstice": bool(solstice)})
    return out


def _turn_sentence(point: dict, today: dt.date) -> str:
    day = _d(point["date"])
    lead = "Today is" if day == today else "Yesterday was"
    name = point["name"]
    if point["solstice"]:
        tail = ("the longest day of the year" if name.startswith("summer")
                else "the shortest day of the year")
        return f"{lead} the {name}, {tail}."
    after = ("the days are longer than the nights from here"
             if name.startswith("spring")
             else "the nights are longer than the days from here")
    return f"{lead} the {name}: {after}."


# ---------------------------------------------------------------------------
# What brAIn saw
# ---------------------------------------------------------------------------

def _c(value: float, unit: str) -> float:
    return (value - 32.0) * 5.0 / 9.0 if "f" in str(unit or "").lower() else value


def _fmt(value: float, unit: str) -> str:
    text = f"{value:.1f}".rstrip("0").rstrip(".").replace("-", "−")
    return f"{text} {unit or '°C'}"


def _looked(store: dict, kind: str, dates) -> None:
    seen = set(store.setdefault("looked", {}).setdefault(kind, []))
    seen.update(str(d) for d in dates)
    store["looked"][kind] = sorted(seen)


def note_forecast(store: dict, days: list[dict], today: str) -> None:
    """The forecast days the occasions read built (`occasions.forecast_days`):
    today is a day brAIn looked, and a low at or below freezing today or
    tomorrow is a frost on that day."""
    _looked(store, "frost", [today])
    frosts = store.setdefault("seen", {}).setdefault("frost", {})
    limit = (_d(today) + dt.timedelta(days=1)).isoformat()
    for day in days or []:
        date, low = str(day.get("date") or ""), day.get("low")
        if not date or low is None or date > limit or date < today:
            continue
        unit = day.get("unit") or "°C"
        if _c(float(low), unit) <= FROST_C:
            frosts.setdefault(date, _fmt(float(low), unit))


def climate_days(raw, tz) -> dict[str, set]:
    """`{"heating": dates, "cooling": dates}` from Core's history answer
    (`/history/period`, attributes kept): a local date on which any climate
    entity's `hvac_action` was heating or cooling."""
    out: dict[str, set] = {"heating": set(), "cooling": set()}
    for series in raw or []:
        for point in series or []:
            if not isinstance(point, dict):
                continue
            action = str((point.get("attributes") or {}).get("hvac_action") or "")
            if action not in ("heating", "cooling"):
                continue
            stamp = str(point.get("last_updated") or point.get("last_changed") or "")
            try:
                when = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            except ValueError:
                continue
            if when.tzinfo is None:
                when = when.replace(tzinfo=dt.timezone.utc)
            out[action].add(when.astimezone(tz or dt.timezone.utc).date().isoformat())
    return out


def dates_between(start: float, end: float, tz) -> list[str]:
    """Every local date the window [start, end] touches."""
    zone = tz or dt.timezone.utc
    first = dt.datetime.fromtimestamp(start, zone).date()
    last = dt.datetime.fromtimestamp(end, zone).date()
    out = []
    while first <= last:
        out.append(first.isoformat())
        first += dt.timedelta(days=1)
    return out


def note_climate(store: dict, runs: dict[str, set], looked: list[str]) -> None:
    _looked(store, "climate", looked)
    seen = store.setdefault("seen", {})
    for kind in ("heating", "cooling"):
        have = set(seen.get(kind) or [])
        have.update(runs.get(kind) or ())
        seen[kind] = sorted(have)


# ---------------------------------------------------------------------------
# What is worth a sentence
# ---------------------------------------------------------------------------

def _count_in(dates, start: dt.date, end: dt.date) -> int:
    """How many of `dates` fall in [start, end)."""
    a, b = start.isoformat(), end.isoformat()
    return sum(1 for d in dates if a <= d < b)


def _first(seen, looked, day: dt.date, hemi: str) -> bool:
    start = day - dt.timedelta(days=QUIET_DAYS)
    return (autumn_side(day, hemi)
            and _count_in(seen, start, day) == 0
            and _count_in(looked, start, day) >= LOOKED_MIN)


def _add(store: dict, event: dict) -> None:
    events = store.setdefault("events", [])
    if any(e.get("key") == event["key"] for e in events):
        return
    events.append(event)


def detect(store: dict, today: str, hemi: str = NORTH) -> list[dict]:
    """New events as of `today`, added to the store and returned. Each key
    is per year, so a season has one of each, ever."""
    before = {e.get("key") for e in store.get("events") or []}
    seen = store.get("seen") or {}
    looked = store.get("looked") or {}
    now = _d(today)
    frosts = seen.get("frost") or {}
    for date in sorted(frosts):
        day = _d(date)
        if _first(list(frosts), looked.get("frost") or [], day, hemi):
            _add(store, {"key": f"frost:{day.year}", "kind": "frost",
                         "date": date, "low": frosts[date]})
    heats = seen.get("heating") or []
    for date in heats:
        day = _d(date)
        if day <= now and _first(heats, looked.get("climate") or [], day, hemi):
            _add(store, {"key": f"heating:{day.year}", "kind": "heating",
                         "date": date})
    cools = [d for d in seen.get("cooling") or [] if d <= today]
    if cools and autumn_side(now, hemi):
        last = _d(cools[-1])
        gap = (now - last).days
        if gap >= COOL_DAYS and _count_in(
                looked.get("climate") or [], last + dt.timedelta(days=1),
                now + dt.timedelta(days=1)) >= COOL_LOOKED_MIN:
            _add(store, {"key": f"cooling_end:{now.year}",
                         "kind": "cooling_end", "date": today,
                         "last": cools[-1], "days": gap})
    return [e for e in store.get("events") or [] if e.get("key") not in before]


def _when(day: dt.date, today: dt.date) -> str:
    delta = (day - today).days
    if delta == 0:
        return "today"
    if delta == 1:
        return "tomorrow"
    if delta == -1:
        return "yesterday"
    return f"on {day:%A} {day.day} {day:%B}"


def sentence(event: dict, today: str) -> str:
    """The one sentence for an event, as `today` reads it."""
    now = _d(today)
    day = _d(event["date"])
    kind = event.get("kind")
    if kind == "frost":
        if day >= now:
            return (f"The first frost of the autumn is forecast for "
                    f"{_when(day, now)}, with a low of {event.get('low')}.")
        return (f"The first frost of the autumn came {_when(day, now)}, "
                f"with a low of {event.get('low')}.")
    if kind == "heating":
        when = "this morning" if day == now else _when(day, now)
        return f"The heating came on for the first time this autumn {when}."
    if kind == "cooling_end":
        last = _d(event["last"])
        return (f"The cooling last ran {_when(last, now)}, and the house has "
                f"not needed it for {event.get('days')} days, so that looks "
                "like the last cooling run of the year.")
    return ""


def due_lines(store: dict, today: str, tz, hemi: str = NORTH) -> list[tuple[str, str]]:
    """`(key, sentence)` for every moment worth saying this morning and not
    said yet."""
    now = _d(today)
    said = store.get("said") or {}
    out: list[tuple[str, str]] = []
    for point in (turning_points(now.year, tz, hemi)
                  + turning_points(now.year - 1, tz, hemi)):
        day = _d(point["date"])
        if point["key"] in said or not 0 <= (now - day).days <= SAY_WITHIN["turn"]:
            continue
        out.append((point["key"], _turn_sentence(point, now)))
    for event in store.get("events") or []:
        key = event.get("key")
        if key in said:
            continue
        day = _d(event["date"])
        lag = (now - day).days
        lead = 1 if event.get("kind") == "frost" else 0
        if -lead <= lag <= SAY_WITHIN.get(event.get("kind"), 1):
            text = sentence(event, today)
            if text:
                out.append((key, text))
    return out


def mark_said(store: dict, keys, at: float) -> None:
    said = store.setdefault("said", {})
    for key in keys:
        said.setdefault(str(key), int(at))


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------

def load(path: Path | str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(store: dict, path: Path | str, today: str) -> None:
    """Pruned to `KEEP_DAYS`: a season's record, not a diary."""
    cutoff = (_d(today) - dt.timedelta(days=KEEP_DAYS)).isoformat()
    looked = store.get("looked") or {}
    for kind in list(looked):
        looked[kind] = [d for d in looked[kind] if d >= cutoff]
    seen = store.get("seen") or {}
    for kind in ("heating", "cooling"):
        if kind in seen:
            seen[kind] = [d for d in seen[kind] if d >= cutoff]
    if "frost" in seen:
        seen["frost"] = {d: v for d, v in seen["frost"].items() if d >= cutoff}
    store["events"] = [e for e in store.get("events") or []
                       if str(e.get("date") or "") >= cutoff]
    atomic_write.write_json(Path(path), store)


__all__ = [
    "climate_days", "dates_between", "detect", "due_lines", "hemisphere",
    "load", "mark_said", "note_climate", "note_forecast", "path_for", "save",
    "sentence", "turning_instant", "turning_points",
]
