"""Make brAIn's learning visible inside Home Assistant.

Memory is a markdown file on disk, which is fine for brAIn and invisible to
everyone else. This module surfaces it where people already look:

  * a ``brain_learned`` event per new fact, so learning shows up in the
    **logbook** next to lights and doors — the cheapest, most legible signal
    that the house is getting smarter
  * sensors for how much it knows and when it last learned something
  * a binary sensor for "brAIn is waiting on you", which is automatable —
    that is what lets a guess reach a phone instead of a panel nobody has
    open

Everything here is read-only over files the add-on owns. Nothing in this
module writes memory; if the add-on is stopped these entities simply go
stale rather than disagreeing with it.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from homeassistant.core import HomeAssistant

from .const import MEMORY_DIR, SHARED_DIR

EVENT_LEARNED = "brain_learned"

MEMORY_LOG_FILENAME = "memory.log.jsonl"
HYPOTHESES_FILENAME = "hypotheses.jsonl"

# Read caps: these files are bounded by the add-on, but a corrupted or
# hand-edited one must not be able to stall the event loop.
MAX_LOG_BYTES = 512 * 1024
MAX_LINES = 400


def _read_jsonl(path: str) -> list[dict]:
    """Parse a JSONL file, skipping torn lines rather than failing whole."""
    try:
        if os.path.getsize(path) > MAX_LOG_BYTES:
            with open(path, "rb") as fh:
                fh.seek(-MAX_LOG_BYTES, os.SEEK_END)
                raw = fh.read().decode("utf-8", errors="replace")
                raw = raw.split("\n", 1)[-1]  # drop the partial first line
        else:
            with open(path, "r", encoding="utf-8") as fh:
                raw = fh.read()
    except OSError:
        return []

    out: list[dict] = []
    for line in raw.splitlines()[-MAX_LINES:]:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict):
            out.append(entry)
    return out


def memory_log_path(hass: HomeAssistant) -> str:
    return hass.config.path(SHARED_DIR, MEMORY_DIR, MEMORY_LOG_FILENAME)


def hypotheses_path(hass: HomeAssistant) -> str:
    return hass.config.path(SHARED_DIR, MEMORY_DIR, HYPOTHESES_FILENAME)


def read_changes(hass: HomeAssistant) -> list[dict]:
    """Consolidation entries, oldest first: {ts, added[], removed[], source}."""
    out = []
    for entry in _read_jsonl(memory_log_path(hass)):
        added = entry.get("added")
        removed = entry.get("removed")
        out.append({
            "ts": float(entry.get("ts") or 0),
            "added": [str(a) for a in added] if isinstance(added, list) else [],
            "removed": [str(r) for r in removed] if isinstance(removed, list) else [],
            "source": str(entry.get("source") or "consolidation"),
        })
    return out


def read_open_hypotheses(hass: HomeAssistant) -> list[dict]:
    out = []
    for entry in _read_jsonl(hypotheses_path(hass)):
        if entry.get("status") != "open" or not entry.get("text"):
            continue
        out.append({
            "ts": int(entry.get("ts") or 0),
            "text": str(entry.get("text")),
            "topic": str(entry.get("topic") or ""),
        })
    return out


def total_learned(hass: HomeAssistant) -> int:
    """Net facts the memory document currently holds, per the change log."""
    total = 0
    for change in read_changes(hass):
        total += len(change["added"]) - len(change["removed"])
    return max(0, total)


def last_learned(hass: HomeAssistant) -> tuple[datetime | None, list[str]]:
    """When something was last added, and what."""
    for change in reversed(read_changes(hass)):
        if change["added"]:
            when = datetime.fromtimestamp(change["ts"], tz=timezone.utc)
            return when, change["added"]
    return None, []


class LearningWatcher:
    """Fires a logbook event for each newly-learned fact.

    The watermark is the timestamp of the newest change already announced,
    persisted in hass.data. On a restart it is rebuilt from the log's own
    newest entry rather than zero — otherwise every restart would replay
    the entire history into the logbook.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._seen_ts: float | None = None

    def prime(self) -> None:
        """Adopt the current tip without announcing it."""
        changes = read_changes(self.hass)
        self._seen_ts = changes[-1]["ts"] if changes else 0.0

    async def async_poll(self, _now=None) -> None:
        await self.hass.async_add_executor_job(self._poll)

    def _poll(self) -> None:
        changes = read_changes(self.hass)
        if not changes:
            return
        if self._seen_ts is None:
            self._seen_ts = changes[-1]["ts"]
            return

        fresh = [c for c in changes if c["ts"] > self._seen_ts]
        if not fresh:
            return
        self._seen_ts = changes[-1]["ts"]

        for change in fresh:
            for fact in change["added"]:
                self.hass.bus.fire(EVENT_LEARNED, {
                    "fact": fact,
                    "source": change["source"],
                    # The logbook renders this verbatim, so it has to read as
                    # a sentence rather than a field dump.
                    "name": "brAIn",
                    "message": f"learned: {fact}",
                })
            for fact in change["removed"]:
                self.hass.bus.fire(EVENT_LEARNED, {
                    "fact": fact,
                    "source": change["source"],
                    "name": "brAIn",
                    "message": f"forgot: {fact}",
                })
