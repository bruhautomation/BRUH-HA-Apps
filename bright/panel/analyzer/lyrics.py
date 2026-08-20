"""Time-synced lyrics from LRCLIB — free, keyless, and exactly the shape a
lyric-aware light show needs (a timestamp per line).

Absence is normal and never a failure: an instrumental, an obscure remix
or a network-less evening all degrade to "no lyrics", and the director
simply choreographs from the music alone.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request

LRCLIB_URL = "https://lrclib.net/api/get"
TIMEOUT_S = 10.0

# [mm:ss.xx] — LRC's timestamp, possibly several per line.
_LRC_STAMP = re.compile(r"\[(\d+):(\d{2}(?:\.\d+)?)\]")


def parse_lrc(text: str) -> list[dict]:
    """LRC text to [{"t": seconds, "text": line}], sorted, empties dropped."""
    lines = []
    for raw in text.splitlines():
        stamps = list(_LRC_STAMP.finditer(raw))
        if not stamps:
            continue
        content = _LRC_STAMP.sub("", raw).strip()
        if not content:
            continue
        for stamp in stamps:
            seconds = int(stamp.group(1)) * 60 + float(stamp.group(2))
            lines.append({"t": round(seconds, 2), "text": content})
    return sorted(lines, key=lambda line: line["t"])


def fetch(artist: str, title: str, album: str = "",
          duration_s: float | None = None,
          *, opener=urllib.request.urlopen) -> dict:
    """One lookup. Returns {"source", "synced", "lines"} — lines empty when
    nothing matched, which callers treat as an instrumental."""
    empty = {"source": "lrclib", "synced": False, "lines": []}
    if not artist or not title:
        return empty
    params = {"artist_name": artist, "track_name": title}
    if album:
        params["album_name"] = album
    if duration_s:
        params["duration"] = str(int(round(duration_s)))
    url = f"{LRCLIB_URL}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={
        # LRCLIB asks integrations to identify themselves.
        "User-Agent": "BRight/https://github.com/bruhautomation/BRUH-HA-Apps",
    })
    try:
        with opener(request, timeout=TIMEOUT_S) as response:
            payload = json.loads(response.read().decode())
    except (urllib.error.URLError, OSError, ValueError):
        return empty
    synced = payload.get("syncedLyrics") if isinstance(payload, dict) else None
    if synced:
        lines = parse_lrc(synced)
        if lines:
            return {"source": "lrclib", "synced": True, "lines": lines}
    plain = payload.get("plainLyrics") if isinstance(payload, dict) else None
    if plain:
        # Un-synced words can still steer palettes/mood, just not moments.
        return {"source": "lrclib", "synced": False,
                "lines": [{"t": None, "text": line.strip()}
                          for line in plain.splitlines() if line.strip()]}
    return empty
