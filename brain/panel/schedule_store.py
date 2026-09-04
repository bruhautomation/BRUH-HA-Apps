"""When brAIn last spoke, across a restart.

Both scheduled messages — the morning brief and the weekly report — are
guarded by a "once a day" / "once a week" stamp, and both kept that stamp
in memory only. So a restart set it back to zero, and the next time the
window came round the message went out again: a second brief on the same
morning, or a second weekly report about the same week. Restarting the
add-on is the first thing anybody does after changing an option, which
makes that the ordinary case rather than the unlucky one.

It is deliberately not a store with a schema. Two floats, a file, and
every failure reading as "never sent" — which is the safe direction: a
lost stamp costs one duplicate message, and a stamp that could not be
*written* must not stop the message it was recording.
"""
from __future__ import annotations

import json
import logging
import os

log = logging.getLogger("brain.schedule")

STORE = os.environ.get("BRAIN_SCHEDULE_FILE", "/data/schedule.json")


def load(path: str | None = None) -> dict:
    try:
        with open(path or STORE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def get(key: str, path: str | None = None) -> float:
    """The stamp, or 0.0 — which every caller already reads as "never"."""
    value = load(path).get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value)


def set(key: str, when: float, path: str | None = None) -> None:  # noqa: A001
    """Record a stamp. Never raises: the message already went out."""
    import atomic_write  # noqa: PLC0415 — panel-local

    target = path or STORE
    parent = os.path.dirname(target)
    if parent and not os.path.isdir(parent):
        return
    data = load(target)
    data[str(key)] = float(when)
    try:
        atomic_write.write_json(target, data)
    except OSError as exc:
        log.warning("could not record %s: %s", key, exc)


__all__ = ["STORE", "get", "load", "set"]
