"""What `sensor.brain_status`, `binary_sensor.brain_needs_you` and the facts
sensor read, with no Home Assistant import.

The add-on publishes `/config/.brain/status.json` every minute: the status
line the panel's Today screen shows (`panel/brain_status.py`) and the three
counts a person compares across screens — the queue, Your list and the
facts — each from its one derivation in the panel. These entities read
that file and nothing else, so Home Assistant and the panel cannot give
two answers to "is brAIn working" or "how many things are waiting on me".

`house_state.py`'s two rules, for its reasons:

**Never raises, never unavailable.** A file that was never written, one
that cannot be parsed and one that has stopped changing are each an
answer — `unknown` with a `reason` — because Home Assistant hides the
attributes of an unavailable entity and the reason would go with it.

**Stale is unknown, never the last answer.** The panel rewrites the file
every minute, so a file older than the window it states (`stale_after_s`)
means the panel has stopped, and "watching" from an hour ago is the one
reading this sensor must not give. Age is the file's mtime, never a stamp
inside it.
"""
from __future__ import annotations

import json
import os
import time

STATUS_FILENAME = "status.json"
STATES = ("watching", "paused", "needs_restart", "signed_out", "degraded",
          "unknown")
DEFAULT_STALE_S = 600
MAX_BYTES = 64 * 1024
MAX_TEXT = 300


def _clip(value, limit: int = MAX_TEXT) -> str:
    return str(value or "").strip()[:limit]


def load(path: str, now: float | None = None) -> tuple[dict | None, str]:
    """`(data, reason)`: the mirror when it is fresh, else None and why."""
    now = time.time() if now is None else float(now)
    try:
        stat = os.stat(path)
        if stat.st_size > MAX_BYTES:
            return None, "the status file is too large to be brAIn's"
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return None, "brAIn has not published its status yet"
    except (OSError, ValueError):
        return None, "the status file could not be read"
    if not isinstance(data, dict):
        return None, "the status file could not be read"
    age = max(0.0, now - stat.st_mtime)
    window = data.get("stale_after_s")
    window = window if isinstance(window, (int, float)) and window > 0 \
        else DEFAULT_STALE_S
    if age > window:
        return None, (f"brAIn last published its status {round(age / 60)} "
                      "minutes ago, so the add-on is not running")
    data["_age_s"] = age
    return data, ""


def status(path: str, now: float | None = None) -> tuple[str, dict]:
    """`(state, attributes)` for `sensor.brain_status`. Never raises."""
    try:
        data, reason = load(path, now)
    except Exception:  # noqa: BLE001 — see the module docstring
        data, reason = None, "the status file could not be read"
    if data is None:
        return "unknown", {"label": "Unknown", "sentence": "",
                           "reason": reason, "since": None, "back_at": None,
                           "last_look_at": None}
    st = data.get("status") if isinstance(data.get("status"), dict) else {}
    state = st.get("state") if st.get("state") in STATES else "unknown"
    attrs = {
        "label": _clip(st.get("label"), 40) or state.replace("_", " ").capitalize(),
        "sentence": _clip(st.get("sentence")),
        "reason": "" if state != "unknown" else "the status could not be read",
        "since": st.get("since") if isinstance(st.get("since"), int) else None,
        "back_at": st.get("back_at") if isinstance(st.get("back_at"), int) else None,
        "last_look_at": st.get("last_look_at")
        if isinstance(st.get("last_look_at"), int) else None,
        "version": _clip(data.get("version"), 40),
        "published_age_seconds": round(float(data.get("_age_s") or 0)),
    }
    return state, attrs


def count(path: str, key: str, now: float | None = None) -> tuple[int | None, str]:
    """`(value, reason)` for one of the counts: `queue_count`,
    `list_count`, `facts_count`. None — unknown — with the reason when the
    mirror is missing or stale or the panel could not count it."""
    try:
        data, reason = load(path, now)
    except Exception:  # noqa: BLE001
        data, reason = None, "the status file could not be read"
    if data is None:
        return None, reason
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None, "brAIn could not count this just now"
    return value, ""


__all__ = ["STATES", "STATUS_FILENAME", "count", "load", "status"]
