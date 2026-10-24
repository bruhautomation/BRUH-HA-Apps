"""The garden's season, as facts brAIn remembers without being told.

GardenRX holds every pick, and its integration publishes the season's totals
on one sensor: the state is the season's weight and ``by_crop`` carries each
crop's weight, picks, value and last pick. Nothing put that into brAIn's
memory, so "how have the tomatoes done this year" was a question the chat
answered by going to look, and a card about the garden started from nothing.

So each checks pass reads that sensor out of the states it already fetched —
no request of its own — and keeps ONE fact per crop (`facts_store.
replace_keyed`): the figure moves with every pick, so a fact per pass would
be a pile of old totals, each still true when it was said. Every fact
expires a few days on, so a garden whose integration went away does not go
on being described as it was in August.

"I could not look" and "nothing was picked" are different answers: no
sensor, an unavailable one or one with no ``by_crop`` list leaves the facts
as they are; a list that is empty (a new season) clears them.
"""
from __future__ import annotations

import math
import time

import facts_store

SOURCE = "gardenrx"
KIND_ATTR = "gardenrx"
HARVEST_KIND = "harvest"
PREDICATE = "garden:"
EXPIRES_DAYS = 4
MAX_CROPS = 60
NAME_MAX = 60
_NO_READING = frozenset({"unavailable", "unknown", ""})


def harvest_sensor(states: dict) -> tuple[str, dict] | None:
    """The harvest sensor's entity id and attributes, or None."""
    for eid, row in sorted((states or {}).items()):
        if not isinstance(row, dict):
            continue
        attrs = row.get("attributes") or {}
        if isinstance(attrs, dict) and attrs.get(KIND_ATTR) == HARVEST_KIND:
            if str(row.get("state") or "").lower() in _NO_READING:
                return None
            return eid, attrs
    return None


def _number(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _amount(value: float) -> str:
    return f"{value:,.1f}".rstrip("0").rstrip(".") if value % 1 else f"{value:,.0f}"


def _crop_name(value) -> str:
    return " ".join(str(value or "").split())[:NAME_MAX]


def crop_fact(crop: dict, year, subject: str, now: float) -> dict | None:
    """One crop's season, as the fact the store keeps. None for a row that
    names no crop."""
    name = _crop_name(crop.get("crop"))
    if not name:
        return None
    lb = _number(crop.get("lb")) or 0.0
    count = _number(crop.get("count")) or 0.0
    picks = int(_number(crop.get("picks")) or 0)
    value = _number(crop.get("value")) or 0.0
    parts = []
    if lb > 0:
        parts.append(f"{_amount(lb)} lb")
    if count > 0:
        parts.append(f"{_amount(count)} counted")
    if not parts:
        parts.append("nothing weighed")
    what = " and ".join(parts)
    season = f"this season ({year})" if year else "this season"
    text = (f"Garden harvest {season}, {name}: {what} over {picks} "
            f"pick{'s' if picks != 1 else ''}")
    if value > 0:
        text += f", worth {value:,.2f}"
    last = str(crop.get("last_at") or "")[:10]
    if last:
        text += f", last picked {last}"
    text += " (from GardenRX)."
    return {"text": text, "predicate": PREDICATE + name.lower(),
            "subject": subject,
            "expires": facts_store._day(now + EXPIRES_DAYS * 86400)}


def facts_from_states(states: dict, now: float | None = None) -> list[dict] | None:
    """Every crop's fact from this pass's states, or None when the garden
    could not be read (no sensor, no reading, no crop list)."""
    now = time.time() if now is None else float(now)
    found = harvest_sensor(states)
    if found is None:
        return None
    eid, attrs = found
    by_crop = attrs.get("by_crop")
    if not isinstance(by_crop, list):
        return None
    out: list[dict] = []
    seen: set[str] = set()
    for crop in by_crop[:MAX_CROPS]:
        if not isinstance(crop, dict):
            continue
        fact = crop_fact(crop, attrs.get("year"), eid, now)
        if fact and fact["predicate"] not in seen:
            seen.add(fact["predicate"])
            out.append(fact)
    return out


def sync(states: dict, now: float | None = None) -> int | None:
    """File this pass's garden facts. None when the garden could not be
    read (nothing touched); otherwise how many crops are now remembered."""
    facts = facts_from_states(states, now)
    if facts is None:
        return None
    return facts_store.replace_keyed(SOURCE, facts, ts=now)


__all__ = ["facts_from_states", "harvest_sensor", "sync"]
