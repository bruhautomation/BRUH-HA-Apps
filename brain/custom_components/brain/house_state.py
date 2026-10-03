"""What `sensor.brain_house` reads, with no Home Assistant import.

The add-on publishes its reading of the house to
`/config/.brain/situation.json` every few minutes (`panel/situation.py`).
This turns that file into the sensor's state and attributes, and it lives
apart from `sensor.py` for one reason: it imports nothing from Home
Assistant, so the suite drives it directly — a reader tested only through
a stubbed entity is a reader tested against the stub.

Two rules, both `BrainHealthSensor`'s.

**It never goes unavailable.** Home Assistant hides the attributes of an
unavailable entity, so an entity that vanished would take its own reason
with it. A file that was never written, one that cannot be parsed and one
that has stopped changing are all the state `unknown` with a `reason`.

**A stale reading is `unknown`, never the last mode.** The panel rewrites
the file on every frame, so a file older than the window the file itself
states (`stale_after_s`) means the panel stopped reading the house — and
an `away` from an hour ago is exactly the reading an automation must not
act on. The age is the file's mtime, never a stamp inside it: a corrected
clock leaves a stamp in the future, and a reading that can never go stale
is a reading nothing can correct.
"""
from __future__ import annotations

import json
import os
import time

SITUATION_FILENAME = "situation.json"
MODES = ("home", "away", "asleep", "waking", "guests", "unknown")
# The fallback window for a file written by a version that did not say.
DEFAULT_STALE_S = 20 * 60
MAX_TEXT = 300


def _clip(value, limit: int = MAX_TEXT) -> str:
    return str(value or "").strip()[:limit]


def read(path: str, now: float | None = None) -> tuple[str, dict]:
    """`(state, attributes)` for the sensor. Never raises."""
    now = time.time() if now is None else float(now)
    try:
        stat = os.stat(path)
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return "unknown", {"reason": "brAIn has not published a reading of "
                                     "the house yet", "sentence": "",
                           "rooms_in_use": [], "unusual_together": [],
                           "because": "", "generated_at": None}
    if not isinstance(data, dict):
        return "unknown", {"reason": "the reading could not be read",
                           "sentence": "", "rooms_in_use": [],
                           "unusual_together": [], "because": "",
                           "generated_at": None}
    age = max(0.0, now - stat.st_mtime)
    window = data.get("stale_after_s")
    window = window if isinstance(window, (int, float)) and window > 0 \
        else DEFAULT_STALE_S
    mode = data.get("house_mode")
    mode = mode if mode in MODES else "unknown"
    together = [
        {"text": _clip(item.get("text"), 160),
         "cites": [str(c)[:120] for c in (item.get("cites") or [])][:6]}
        for item in (data.get("unusual_together") or [])
        if isinstance(item, dict)][:3]
    attrs = {
        "sentence": _clip(data.get("sentence")),
        "sentence_stale": bool(data.get("sentence_stale")),
        "rooms_in_use": [str(r)[:80] for r in
                         (data.get("rooms_in_use") or [])][:12],
        "unusual_together": together,
        "because": _clip(data.get("because"), 200),
        "reason": _clip(data.get("reason"), 200),
        "source": _clip(data.get("source"), 20),
        "generated_at": data.get("generated_at"),
        "coming_up": [str(o)[:120] for o in (data.get("occasions") or [])][:6],
        "published_age_minutes": round(age / 60),
    }
    if age > window:
        attrs["reason"] = (f"brAIn last published a reading "
                           f"{round(age / 60)} minutes ago, so it is not "
                           "running; the last mode is not shown")
        attrs["sentence_stale"] = bool(attrs["sentence"])
        attrs["rooms_in_use"] = []
        attrs["unusual_together"] = []
        return "unknown", attrs
    return mode, attrs
