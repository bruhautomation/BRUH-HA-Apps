"""A card's figures that brAIn counts itself, from Home Assistant's history.

An insight card is written by a Claude run, and so were all of its numbers:
when the run failed (an outage, a usage limit) the card had no figures at
all, though "how many times did it defrost this week" and "how many hours
did the backup heater run" are a count and a sum over the recorder's own
rows (#1499). So a card may declare `figures`, beside `live`: which entity,
which state (or attribute value) and whether to count the times it began or
the hours it lasted. brAIn computes them over the last `WINDOW_DAYS` days,
writes them as the card's first tiles, and computes them again whenever a
later run of the card fails, so the numbers stay current and the model's
part is the commentary around them.

Pure: the panel fetches the history (`server._card_figures`) and hands the
rows in.
"""
from __future__ import annotations

import datetime as dt
import math

WINDOW_DAYS = 7
MAX_FIGURES = 4
MAX_LABEL = 40
MEASURES = ("times", "hours")
# A state that is no reading: never the state a figure counts.
_NO_READING = frozenset({"unavailable", "unknown", "", "none"})


def clean(value, is_entity_id) -> list[dict]:
    """A model's `figures` list as specs brAIn will compute, capped.

    `is_entity_id` is `ha_data.is_entity_id`: an id that names nothing
    is dropped, as `live`'s are."""
    out: list[dict] = []
    for item in value if isinstance(value, list) else ():
        if not isinstance(item, dict):
            continue
        eid = str(item.get("entity_id") or "").strip()
        measure = str(item.get("measure") or "").strip().lower()
        label = " ".join(str(item.get("label") or "").split())[:MAX_LABEL]
        if not is_entity_id(eid) or measure not in MEASURES or not label:
            continue
        state = str(item.get("state") or "on").strip()[:40] or "on"
        spec = {"label": label, "entity_id": eid, "state": state,
                "measure": measure}
        attribute = str(item.get("attribute") or "").strip()[:40]
        if attribute:
            spec["attribute"] = attribute
        if spec not in out:
            out.append(spec)
        if len(out) >= MAX_FIGURES:
            break
    return out


def _epoch(value) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    try:
        return dt.datetime.fromisoformat(
            str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def _value(row: dict, attribute: str):
    if attribute:
        return (row.get("attributes") or {}).get(attribute)
    return row.get("state")


def measure(spec: dict, rows, now: float,
            days: int = WINDOW_DAYS) -> float | None:
    """The figure over the window, or None when the history holds no row.

    `rows` is one entity's `/history/period` series (the state in force at
    the window's start first). "times" counts the changes INTO the state
    inside the window; "hours" sums the time spent in it, clipped to the
    window. A no-reading row ends a stretch and starts none.
    """
    start = now - days * 86400
    want = str(spec.get("state") or "on").strip().lower()
    attribute = str(spec.get("attribute") or "")
    points: list[tuple[float, bool]] = []
    last_value = None
    for row in rows or ():
        if not isinstance(row, dict):
            continue
        when = _epoch(row.get("last_changed") or row.get("last_updated"))
        if when is None or when > now:
            continue
        raw = _value(row, attribute)
        if attribute and raw is None and last_value is not None \
                and not row.get("attributes"):
            # A minimal row carries no attributes: it is the last value
            # still in force, not a change.
            raw = last_value
        last_value = raw
        text = str(raw if raw is not None else "").strip().lower()
        points.append((max(when, start), text == want and text not in _NO_READING))
    if not points:
        return None
    points.sort(key=lambda p: p[0])
    times = 0
    seconds = 0.0
    before = False
    for i, (when, match) in enumerate(points):
        if match and not before and when > start:
            times += 1
        if match:
            end = points[i + 1][0] if i + 1 < len(points) else now
            seconds += max(0.0, end - when)
        before = match
    if spec.get("measure") == "times":
        return float(times)
    return seconds / 3600.0


def say(spec: dict, figure: float, days: int = WINDOW_DAYS) -> str:
    """The tile's value, with its window: "12 in 7 days", "3.4 h in 7 days"."""
    window = f"in {days} days"
    if spec.get("measure") == "times":
        return f"{int(figure)} {window}"
    if not math.isfinite(figure):
        return ""
    if figure < 1:
        return f"{round(figure * 60)} min {window}"
    return f"{figure:.1f} h {window}"


def tiles(specs, series: dict, now: float) -> list[dict]:
    """The computed tiles, in the spec's order; a figure with no history is
    left out rather than shown as zero (no rows is not "never")."""
    out = []
    for spec in specs or ():
        figure = measure(spec, (series or {}).get(spec.get("entity_id")), now)
        if figure is None:
            continue
        value = say(spec, figure)
        if value:
            out.append({"label": spec["label"], "value": value,
                        "computed": True})
    return out


def merge(computed: list[dict], highlights, limit: int = 6) -> list[dict]:
    """brAIn's own tiles first, then the run's that are not the same label
    (the run's figure for a label brAIn counted is the model's guess at a
    number brAIn has), then the run's others, capped. Earlier computed
    tiles are replaced, never stacked."""
    labels = {str(t.get("label") or "").strip().lower() for t in computed}
    kept = [h for h in (highlights if isinstance(highlights, list) else ())
            if isinstance(h, dict) and not h.get("computed")
            and str(h.get("label") or "").strip().lower() not in labels]
    return (list(computed) + kept)[:limit]


__all__ = ["MAX_FIGURES", "MEASURES", "WINDOW_DAYS", "clean", "measure",
           "merge", "say", "tiles"]
