"""Where the household is, and which speaker in the house can reach them.

A phone is the right place for almost everything brAIn says, and the wrong
place for one kind of thing: a problem that is costing something RIGHT NOW,
in a house with somebody standing in it, at an hour they are up. The
bedroom window open on a freezing evening is a sentence somebody in the
kitchen can act on in the time it takes them to unlock a phone and read
it — if it is said in the kitchen. This module answers the two questions
that sentence needs, from the states Home Assistant already publishes and
nothing else:

* **the roster** — the people Home Assistant tracks (`person.*`), the voice
  satellites and the rooms they are in (`assist_satellite.*`), off the area
  names the last checks pass recorded;
* **where somebody is** — the rooms whose motion, occupancy or presence
  sensors moved in the last few minutes, freshest first.

And it decides, deterministically, whether a finding may be SPOKEN at all.
Four refusals, each a rule in code and never a sentence in a prompt:

**Never to an empty house, and never to a room nobody is in.** No person
home, or no room with a fresh presence reading, is no speaker: a sentence
said to nobody is a sentence nobody heard, and one said in the wrong room
is a stranger's voice in it.

**Never an escalating row.** Those are the phone's ladder, built to be
answered and repeated; a voice that also said them would be a second,
unrepeatable copy of the loudest thing brAIn does. Never below `serious`
or a producer that is not `now`, because a voice in the room is louder than
a phone in a pocket.

**Only house-level words.** What is spoken is the check's own sentence —
a pure function's text about a device — and never a model's, a Resident
claim or anything naming a person: a case about somebody's whereabouts,
read aloud in a kitchen, is the household-surveillance failure the design
page names. A sentence naming any tracked person is not spoken.

**Never inside the quiet hours.** The phone may break them for an urgent
row; a speaker in a sleeping house may not.

What it does NOT do yet is listen. `assist_satellite.start_conversation`
would let the room answer, and an answer has to be tied to the case it was
about by the panel rather than by a model — which needs the satellite and
the caller identified on the voice turn. Until that context reaches the
conversation agent, brAIn announces and the phone carries the buttons.
"""
from __future__ import annotations

import datetime as dt

# How fresh a presence reading has to be for its room to count as one
# somebody is in. Longer, and a room left ten minutes ago is told about a
# window; shorter, and somebody sitting still in it is not there.
PRESENCE_FRESH_S = 10 * 60
PRESENCE_CLASSES = ("motion", "occupancy", "presence")
# The sentence is a lock screen's, said aloud: short.
SPOKEN_CHARS = 200
SPEAKABLE_SEVERITIES = ("serious", "critical")


def _ts(value) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    try:
        text = str(value or "").replace("Z", "+00:00")
        return dt.datetime.fromisoformat(text).timestamp()
    except ValueError:
        return 0.0


def roster(states: list[dict], areas: dict[str, str]) -> dict:
    """`{"people": [...], "satellites": [...]}` off one states read.

    `areas` is `{entity_id: area name}` from the last checks pass — the map
    the feed already reads — so nothing here asks the registry itself.
    """
    people, satellites = [], []
    for s in states or []:
        if not isinstance(s, dict):
            continue
        eid = str(s.get("entity_id") or "")
        attrs = s.get("attributes") if isinstance(s.get("attributes"), dict) else {}
        if eid.startswith("person."):
            people.append({"entity_id": eid,
                           "name": str(attrs.get("friendly_name") or eid),
                           "home": str(s.get("state") or "") == "home"})
        elif eid.startswith("assist_satellite."):
            if str(s.get("state") or "") in ("unavailable", "unknown"):
                continue
            satellites.append({"entity_id": eid,
                               "area": str((areas or {}).get(eid) or ""),
                               "name": str(attrs.get("friendly_name") or eid)})
    return {"people": people, "satellites": satellites}


def occupied_areas(states: list[dict], areas: dict[str, str],
                   now: float) -> list[str]:
    """Rooms with a presence reading inside `PRESENCE_FRESH_S`, freshest
    first. A sensor that is ON now counts whenever it last changed: a room
    with somebody sitting in it reads `on` and has not moved for an hour."""
    seen: dict[str, float] = {}
    for s in states or []:
        if not isinstance(s, dict):
            continue
        eid = str(s.get("entity_id") or "")
        if not eid.startswith("binary_sensor."):
            continue
        attrs = s.get("attributes") if isinstance(s.get("attributes"), dict) else {}
        if attrs.get("device_class") not in PRESENCE_CLASSES:
            continue
        area = str((areas or {}).get(eid) or "")
        if not area:
            continue
        changed = _ts(s.get("last_changed"))
        on = str(s.get("state") or "") == "on"
        if not on and now - changed > PRESENCE_FRESH_S:
            continue
        stamp = now if on else changed
        seen[area] = max(seen.get(area, 0.0), stamp)
    return [a for a, _t in sorted(seen.items(), key=lambda kv: -kv[1])]


def pick_satellite(roster_: dict, occupied: list[str]) -> dict | None:
    """The satellite in the freshest occupied room, or None.

    None when nobody tracked is home — an empty house is told nothing — and
    when no occupied room has a satellite: the phone is the honest answer
    for somebody in a room without one.
    """
    people = roster_.get("people") or []
    if people and not any(p.get("home") for p in people):
        return None
    by_area: dict[str, dict] = {}
    for sat in roster_.get("satellites") or []:
        if sat.get("area"):
            by_area.setdefault(sat["area"].lower(), sat)
    for area in occupied:
        sat = by_area.get(area.lower())
        if sat:
            return sat
    return None


def speakable(row: dict, tier: str, urgency: str) -> bool:
    """Whether this row may be said aloud at all — before any room is chosen."""
    if tier != "notify":
        return False
    if urgency != "now":
        return False
    if str(row.get("severity") or "") not in SPEAKABLE_SEVERITIES:
        return False
    return str(row.get("source") or "").startswith("check:")


def spoken_text(row: dict, roster_: dict) -> str | None:
    """What is said, or None when the row's own words are not house-level.

    The check's sentence and nothing else, with a pointer to the phone for
    the rest — and refused outright when it names a tracked person.
    """
    text = " ".join(str(row.get("text") or "").split())
    if not text:
        return None
    low = text.lower()
    for p in roster_.get("people") or []:
        for word in (p.get("name") or "", (p.get("entity_id") or "")
                     .split(".", 1)[-1].replace("_", " ")):
            word = word.strip().lower()
            if len(word) >= 3 and word in low:
                return None
    said = f"brAIn here. {text.rstrip('.')}. The details are on your phone."
    return said[:SPOKEN_CHARS]


__all__ = ["PRESENCE_FRESH_S", "occupied_areas", "pick_satellite", "roster",
           "speakable", "spoken_text"]
