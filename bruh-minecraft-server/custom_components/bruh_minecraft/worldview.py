"""The world's state as Home Assistant's sensors say it.

Pure functions over the add-on's `world.json` (panel/mcworld.py), kept out
of sensor.py so they can be read and tested without Home Assistant.

Attributes are kept small on purpose: the recorder warns past 16 KB of
attributes, and an entity that changes every few seconds while somebody
plays writes a row each time. Lists are capped and long words clipped;
sensor.py also keeps the fast-moving ones out of the recorder.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

MAX_PLAYERS = 12
MAX_EVENTS = 15
MAX_RECENT_JOBS = 5
TEXT_CAP = 160
STATE_CAP = 255

DIMENSIONS = {"minecraft:overworld": "Overworld", "minecraft:the_nether": "Nether",
              "minecraft:the_end": "End"}


def _clip(text: Any, cap: int = TEXT_CAP) -> str:
    text = str(text or "")
    return text if len(text) <= cap else text[:cap - 1] + "…"


def _when(stamp: Any) -> datetime | None:
    if not isinstance(stamp, (int, float)) or stamp <= 0:
        return None
    return datetime.fromtimestamp(stamp, tz=timezone.utc)


def dimension_name(dim: Any) -> str:
    d = str(dim or "")
    return DIMENSIONS.get(d, d.split(":", 1)[-1].replace("_", " ").title())


def where(player: dict[str, Any]) -> str:
    """A player's whereabouts in words: near a place, or rounded coordinates."""
    dim = dimension_name(player.get("dimension")) if player.get("dimension") else ""
    if player.get("near"):
        spot = f"near {player['near']}"
    elif player.get("x") is not None:
        spot = f"{player['x']}, {player['y']}, {player['z']}"
    else:
        spot = ""
    return " · ".join(p for p in (dim, spot) if p)


# -- time and weather --------------------------------------------------------
def time_state(world: dict[str, Any]) -> str | None:
    t = world.get("time") or {}
    return t.get("phase")


def time_attrs(world: dict[str, Any]) -> dict[str, Any]:
    t = world.get("time") or {}
    if not t:
        return {}
    # The hour only: the in-game minute moves every 0.8 s of real time.
    hour = t.get("hour")
    return {"hour": hour, "clock": f"{hour:02d}:00" if isinstance(hour, int) else None,
            "day": t.get("day")}


def day_state(world: dict[str, Any]) -> int | None:
    t = world.get("time") or {}
    return t.get("day") if isinstance(t.get("day"), int) else None


def weather_state(world: dict[str, Any]) -> str | None:
    w = world.get("weather") or {}
    return w.get("state")


def weather_attrs(world: dict[str, Any]) -> dict[str, Any]:
    w = world.get("weather") or {}
    if not w:
        return {}
    return {"source": "the server" if w.get("source") == "server" else "the last save",
            "as_of": _when(w.get("as_of")).isoformat() if _when(w.get("as_of")) else None}


# -- players -----------------------------------------------------------------
def players_attrs(world: dict[str, Any]) -> dict[str, Any]:
    """Each online player: where, in what mode, how healthy."""
    out = []
    for p in (world.get("players") or [])[:MAX_PLAYERS]:
        out.append({
            "name": _clip(p.get("name"), 40),
            "dimension": dimension_name(p.get("dimension")) if p.get("dimension") else None,
            "x": p.get("x"), "y": p.get("y"), "z": p.get("z"),
            "near": _clip(p.get("near"), 60) or None,
            "where": _clip(where(p), 80),
            "gamemode": p.get("gamemode"), "health": p.get("health"), "food": p.get("food"),
        })
    return {"details": out}


# -- the feed ----------------------------------------------------------------
def feed_state(world: dict[str, Any]) -> str | None:
    feed = world.get("feed") or []
    return _clip(feed[0].get("text"), STATE_CAP) if feed else None


def feed_attrs(world: dict[str, Any]) -> dict[str, Any]:
    events = []
    for e in (world.get("feed") or [])[:MAX_EVENTS]:
        when = _when(e.get("t"))
        events.append({"time": when.isoformat() if when else None, "kind": e.get("kind"),
                       "player": _clip(e.get("player"), 40) or None,
                       "text": _clip(e.get("text"))})
    seen = sorted((world.get("last_seen") or {}).items(), key=lambda kv: kv[1], reverse=True)
    return {"events": events,
            "last_seen": {_clip(k, 40): _when(v).isoformat() for k, v in seen[:MAX_PLAYERS]
                          if _when(v)}}


# -- saves and backups -------------------------------------------------------
def last_save(world: dict[str, Any]) -> datetime | None:
    return _when(world.get("last_save"))


def last_backup(world: dict[str, Any]) -> datetime | None:
    return _when(world.get("last_backup"))


# -- Vesper ------------------------------------------------------------------
def _job(job: dict[str, Any] | None) -> dict[str, Any] | None:
    if not job:
        return None
    return {"id": job.get("id"), "title": _clip(job.get("title"), 120),
            "part": _clip(job.get("part"), 60) or None, "status": job.get("status"),
            "progress": job.get("progress"),
            "started": _when(job.get("started_at")).isoformat() if _when(job.get("started_at")) else None,
            "finished": _when(job.get("finished_at")).isoformat() if _when(job.get("finished_at")) else None,
            "image": _clip(job.get("image"), 300) or None}


def building_state(world: dict[str, Any]) -> str:
    current = (world.get("builds") or {}).get("current")
    return _clip(current.get("title"), STATE_CAP) if current else "idle"


def building_attrs(world: dict[str, Any]) -> dict[str, Any]:
    builds = world.get("builds") or {}
    current = _job(builds.get("current"))
    return {"progress": current.get("progress") if current else None,
            "part": current.get("part") if current else None,
            "current": current,
            "queued": builds.get("queued", 0),
            "recent": [_job(j) for j in (builds.get("recent") or [])[:MAX_RECENT_JOBS]]}


# -- Vesper in the game (panel/vesper.py) ------------------------------------
def vesper_state(world: dict[str, Any]) -> str:
    """off, paused, idle, acting, asking, bedtime or waiting."""
    v = world.get("vesper") or {}
    if not v:
        return "off"
    if not v.get("enabled"):
        return "off"
    if v.get("paused"):
        return "paused"
    return str(v.get("state") or "idle")


MAX_LEARNED = 40


def _learned(v: dict[str, Any]) -> list[dict[str, Any]]:
    """What Vesper learned about each person, for brAIn's facts store
    (brAIn's panel files one fact per person and key off this attribute)."""
    out = []
    for row in (v.get("learned") or [])[:MAX_LEARNED]:
        if isinstance(row, dict) and row.get("person") and row.get("key") and row.get("text"):
            out.append({"person": _clip(row["person"], 40), "key": _clip(row["key"], 20),
                        "text": _clip(row["text"], 300)})
    return out


def vesper_attrs(world: dict[str, Any]) -> dict[str, Any]:
    v = world.get("vesper") or {}
    last = v.get("last_action") or None
    q = v.get("open_question") or None
    return {"enabled": bool(v.get("enabled")), "paused": bool(v.get("paused")),
            "name": _clip(v.get("name") or "Vesper", 16),
            "chat_commands": v.get("commands") or "on",
            "vesper_learned": _learned(v),
            "budget": v.get("budget") or {},
            "queued_questions": v.get("queued_questions", 0),
            "open_question": ({"id": q.get("id"), "person": _clip(q.get("person"), 40),
                               "text": _clip(q.get("text"), 200)} if q else None),
            "last_action": ({"id": last.get("id"), "kind": last.get("kind"),
                             "person": _clip(last.get("person"), 40),
                             "text": _clip(last.get("text"), 200), "status": last.get("status"),
                             "when": _when(last.get("t")).isoformat() if _when(last.get("t")) else None}
                            if last else None)}
