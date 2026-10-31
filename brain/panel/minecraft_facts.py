"""What Vesper learned in the game, as facts brAIn remembers.

BRUH Minecraft's Vesper keeps a record per person (`.bruh-world/vesper/
people.json`): what a child chose on the choice pads, what a grown-up asked
for in chat, the places each keeps going back to, how much they play, and
the notes brAIn's own turns said were worth keeping. The add-on's `vesper`
sensor carries that as `vesper_learned` — short lines in fixed words, one
per person and key — so the game and the house are one memory: a card, the
chat or voice can recall "what does Kaz like building" without going to look.

The least invasive path in: the same one GardenRX's season takes
(`garden_facts`). Each checks pass reads the attribute off the states it
already fetched — no request, no new service, nothing the add-on writes
into brAIn's files — and keeps ONE fact per person and key
(`facts_store.replace_keyed`), so a moving figure is a fact that moves, not
a pile of old ones. Every line passes `occasions.untrusted` first: a
grown-up's request is quoted words from a game's chat, and a line shaped
like an instruction is dropped rather than remembered. Facts expire a
fortnight on, so a world that stopped being played is not described forever.

No sensor, an unavailable one or an attribute that is not a list leaves the
facts as they are ("could not look" is not "learned nothing").
"""
from __future__ import annotations

import re
import time

import facts_store
import occasions

SOURCE = "bruh_minecraft"
ATTR = "vesper_learned"
PREDICATE = "minecraft:"
EXPIRES_DAYS = 14
MAX_FACTS = 60
TEXT_MAX = 300
_NO_READING = frozenset({"unavailable", "unknown", ""})
_KEY = re.compile(r"[^a-z0-9_]")


def vesper_sensor(states: dict) -> tuple[str, dict] | None:
    """The Vesper sensor's entity id and attributes, or None."""
    for eid, row in sorted((states or {}).items()):
        if not isinstance(row, dict) or not str(eid).startswith("sensor."):
            continue
        attrs = row.get("attributes") or {}
        if isinstance(attrs, dict) and ATTR in attrs:
            if str(row.get("state") or "").lower() in _NO_READING:
                return None
            return eid, attrs
    return None


def facts_from_states(states: dict, now: float | None = None) -> list[dict] | None:
    """This pass's game facts, or None when the game could not be read."""
    now = time.time() if now is None else float(now)
    found = vesper_sensor(states)
    if found is None:
        return None
    eid, attrs = found
    rows = attrs.get(ATTR)
    if not isinstance(rows, list):
        return None
    out: list[dict] = []
    seen: set[str] = set()
    for row in rows[:MAX_FACTS]:
        if not isinstance(row, dict):
            continue
        person = " ".join(str(row.get("person") or "").split())[:40]
        key = _KEY.sub("", str(row.get("key") or "").lower())[:20]
        text = occasions.untrusted(row.get("text"), TEXT_MAX)
        if not person or not key or not text:
            continue
        predicate = f"{PREDICATE}{person.lower()}:{key}"
        if predicate in seen:
            continue
        seen.add(predicate)
        out.append({"text": text if text.endswith(".") else text + ".",
                    "predicate": predicate, "subject": eid,
                    "extra_subjects": [f"person:{person.lower()}"],
                    "expires": facts_store._day(now + EXPIRES_DAYS * 86400)})
    return out


def sync(states: dict, now: float | None = None) -> int | None:
    """File this pass's game facts. None when the game could not be read
    (nothing touched); otherwise how many are now remembered."""
    facts = facts_from_states(states, now)
    if facts is None:
        return None
    return facts_store.replace_keyed(SOURCE, facts, ts=now)


__all__ = ["facts_from_states", "sync", "vesper_sensor"]
