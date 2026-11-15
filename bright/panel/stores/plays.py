"""When each track's show was last played.

One small file in the add-on's own data: track hash -> epoch seconds. It is
written where a show actually starts playing (the conductor), so a party, a
single Play and an automation all count, and read by the library listing so
the Shows tab can say "Never played" or "Played 3 d ago" instead of the age
of the compile, which is the same for every show built in one sitting.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import atomic_write
from analyzer import library

PLAYS_FILE = Path(os.environ.get("BRIGHT_STATE", "/data")) / "last-played.json"

# A listing of a few thousand tracks is the most this ever holds; the cap is
# only here so a damaged file cannot grow without bound.
MAX_TRACKS = 5000


def load() -> dict[str, float]:
    try:
        data = json.loads(PLAYS_FILE.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {h: float(t) for h, t in data.items()
            if isinstance(h, str) and library.is_track_hash(h)
            and isinstance(t, (int, float)) and not isinstance(t, bool)}


def mark(track_hash: str, when: float | None = None) -> None:
    """Record that this track's show just started. Never raises: a note about
    a show must not be what stops the show."""
    try:
        if not library.is_track_hash(track_hash):
            return
        plays = load()
        plays[track_hash] = float(when if when is not None else time.time())
        if len(plays) > MAX_TRACKS:
            newest = sorted(plays.items(), key=lambda kv: kv[1])[-MAX_TRACKS:]
            plays = dict(newest)
        atomic_write.write_json(PLAYS_FILE, plays)
    except (OSError, ValueError):
        pass
