#!/usr/bin/env python3
"""What Home Assistant exposes to Assist, applied to voice.

Home Assistant has a switch on every entity — Settings → Voice assistants
→ Expose — and until 2.3 it had no effect on brAIn: the conversation entity
handed voice an area map of every controllable entity in the house and an
MCP server that would read or act on any of them, so un-exposing the front
door lock did nothing a person could see. That is a real surprise for an
integration that registers itself as a voice assistant, and the design
page names it as one.

This is the one implementation of the answer, read by three processes
that cannot import each other's copies: the worker pool and the classic
listener filter the area map through `filter_map`, and the MCP server
launched for a voice turn (`BRAIN_EXPOSED_ONLY=1`) refuses to read or act
on anything `is_exposed` says no to. One module, one rule.

**The rule is Home Assistant's own, not one invented here.** The
`homeassistant/expose_entity/list` command answers only for entities
somebody (or HA's default agent) has settled a setting on; for the rest
Core applies a default — expose new entities of a dozen domains, plus the
sensors of a few device classes, never anything hidden or with an entity
category — and writes that answer back the first time it is asked. The
lists below are copied from Core's `exposed_entities.py` so an entity
nothing has settled yet is answered the way Core would answer it. An
explicit setting always wins over the default.

**A snapshot that could not be read fails closed.** The map is emptied
and the log says why, acting is refused, and `assist_exposure: all` is
the switch that ends it — a voice command refused with a sentence is
better than one that reaches an unexposed lock because a WebSocket was
down at the moment it was asked.
"""
from __future__ import annotations

import json
import os
import sys
import time

CACHE_FILE = os.environ.get(
    "BRAIN_EXPOSED_CACHE",
    os.path.join(os.environ.get("BRAIN_SHARED_DIR", "/config/.brain"),
                 "cache", "exposed_entities.json"))
# How long a snapshot is served before it is refreshed. Exposure changes
# when a person flips a switch in Settings, which is rare, and a stale
# minute costs one voice turn seeing the old answer.
TTL_S = 60.0
ASSISTANT = "conversation"

# Core's `DEFAULT_EXPOSED_DOMAINS`, `DEFAULT_EXPOSED_BINARY_SENSOR_DEVICE_CLASSES`
# and `DEFAULT_EXPOSED_SENSOR_DEVICE_CLASSES`. A lock is deliberately not in
# the first: Core does not expose one to Assist unless somebody says so.
DEFAULT_EXPOSED_DOMAINS = frozenset({
    "climate", "cover", "fan", "humidifier", "light", "media_player",
    "scene", "script", "switch", "todo", "vacuum", "water_heater",
})
DEFAULT_EXPOSED_BINARY_SENSOR_CLASSES = frozenset({
    "battery", "battery_charging", "carbon_monoxide", "cold", "connectivity",
    "door", "garage_door", "gas", "heat", "light", "lock", "moisture",
    "motion", "moving", "occupancy", "opening", "plug", "power", "presence",
    "problem", "running", "safety", "smoke", "sound", "tamper", "update",
    "vibration", "window",
})
DEFAULT_EXPOSED_SENSOR_CLASSES = frozenset({
    "aqi", "battery", "carbon_dioxide", "carbon_monoxide", "humidity",
    "illuminance", "pm1", "pm10", "pm25", "temperature",
    "volatile_organic_compounds", "volatile_organic_compounds_parts",
})
# Core's `CLOUD_NEVER_EXPOSED_ENTITIES`.
NEVER_EXPOSED = frozenset({"group.all_locks"})


def default_exposed(entity_id: str, *, expose_new: bool,
                    hidden: bool = False, category: str | None = None,
                    device_class: str | None = None) -> bool:
    """Core's answer for an entity nothing has settled a setting on."""
    if not expose_new or hidden or category:
        return False
    domain = str(entity_id).split(".", 1)[0]
    if domain in DEFAULT_EXPOSED_DOMAINS:
        return True
    if domain == "binary_sensor":
        return device_class in DEFAULT_EXPOSED_BINARY_SENSOR_CLASSES
    if domain == "sensor":
        return device_class in DEFAULT_EXPOSED_SENSOR_CLASSES
    return False


def snapshot(ws) -> dict:
    """Read the exposure out of Core over `ws(payload) -> result`.

    `ws` is the caller's own WebSocket command (the MCP server's
    `_ws_command`, or `_default_ws` below for the CLI), so the handshake
    is not written down a third time. Raises on anything that stops it
    answering, because a half-read exposure is the one answer worse than
    none.
    """
    listed = ws({"type": "homeassistant/expose_entity/list"})
    new = ws({"type": "homeassistant/expose_new_entities/get",
              "assistant": ASSISTANT})
    registry = ws({"type": "config/entity_registry/list"})
    if not isinstance(listed, dict) or "exposed_entities" not in listed:
        raise ValueError(f"expose_entity/list answered {str(listed)[:120]}")
    if not isinstance(new, dict) or "expose_new" not in new:
        raise ValueError(f"expose_new_entities/get answered {str(new)[:120]}")
    if not isinstance(registry, list):
        raise ValueError(f"entity_registry/list answered {str(registry)[:120]}")
    explicit: dict[str, bool] = {}
    for eid, settings in (listed.get("exposed_entities") or {}).items():
        if isinstance(settings, dict) and ASSISTANT in settings:
            explicit[str(eid)] = bool(settings[ASSISTANT])
    expose_new = bool(new["expose_new"])
    exposed: list[str] = []
    hidden: list[str] = []
    seen: set[str] = set()
    for row in registry:
        if not isinstance(row, dict) or not row.get("entity_id"):
            continue
        eid = str(row["entity_id"])
        seen.add(eid)
        if eid in NEVER_EXPOSED:
            hidden.append(eid)
            continue
        if eid in explicit:
            (exposed if explicit[eid] else hidden).append(eid)
            continue
        yes = default_exposed(
            eid, expose_new=expose_new,
            hidden=bool(row.get("hidden_by")),
            category=row.get("entity_category"),
            device_class=row.get("device_class") or row.get("original_device_class"))
        (exposed if yes else hidden).append(eid)
    for eid, yes in explicit.items():
        if eid not in seen:
            (exposed if yes else hidden).append(eid)
    return {"at": time.time(), "expose_new": expose_new,
            "exposed": sorted(exposed), "hidden": sorted(hidden)}


def is_exposed(entity_id: str, snap: dict | None) -> bool:
    """Whether voice may see this entity, off a snapshot.

    An id the snapshot never met is an entity with no registry entry —
    a YAML sensor without a `unique_id` — and gets Core's domain default
    with no device class to consult, which is what Core does for one too.
    A missing snapshot answers **no** for everything: fail closed.
    """
    if not isinstance(snap, dict):
        return False
    eid = str(entity_id or "").strip().lower()
    if not eid or "." not in eid:
        return False
    if eid in snap.get("_exposed_set", ()) or eid in set(snap.get("exposed") or ()):
        return True
    if eid in snap.get("_hidden_set", ()) or eid in set(snap.get("hidden") or ()):
        return False
    return default_exposed(eid, expose_new=bool(snap.get("expose_new")))


def index(snap: dict | None) -> dict | None:
    """The snapshot with its two lists as sets, for a caller asking often."""
    if not isinstance(snap, dict):
        return None
    out = dict(snap)
    out["_exposed_set"] = frozenset(str(e).lower() for e in snap.get("exposed") or ())
    out["_hidden_set"] = frozenset(str(e).lower() for e in snap.get("hidden") or ())
    return out


def load(path: str = CACHE_FILE, max_age: float | None = None) -> dict | None:
    """The cached snapshot, or None when there is none or it is too old."""
    try:
        with open(path, encoding="utf-8") as fh:
            snap = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(snap, dict) or not isinstance(snap.get("exposed"), list):
        return None
    if max_age is not None:
        try:
            if time.time() - float(snap.get("at") or 0) > max_age:
                return None
        except (TypeError, ValueError):
            return None
    return index(snap)


def refresh(ws, path: str = CACHE_FILE) -> dict:
    """Read Core and write the cache; raises when Core could not be read."""
    snap = snapshot(ws)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(snap, fh)
    os.replace(tmp, path)
    return index(snap)


def load_or_refresh(ws, path: str = CACHE_FILE, max_age: float = TTL_S) -> dict | None:
    """A fresh-enough cached snapshot, else one read now; None when neither."""
    snap = load(path, max_age)
    if snap is not None:
        return snap
    try:
        return refresh(ws, path)
    except Exception:  # noqa: BLE001 — the caller reads None as "fail closed"
        return None


def filter_map(text: str, snap: dict | None) -> str:
    """The area map with every unexposed entity taken out.

    The map is `Name: id, id, id` lines; a line left with no ids is
    dropped, because an area with nothing voice may touch is a word that
    invites a command about it. A missing snapshot empties the map: an
    empty map and a map of things voice will then be refused are two
    answers, and only the first sends the model to say it cannot see it.
    """
    if snap is None:
        return ""
    out = []
    for line in str(text or "").splitlines():
        if ":" not in line:
            continue
        name, _sep, rest = line.partition(":")
        ids = [i.strip() for i in rest.split(",") if i.strip()]
        kept = [i for i in ids if is_exposed(i, snap)]
        if kept:
            out.append(f"{name}: {', '.join(kept)}")
    return "\n".join(out) + ("\n" if out else "")


def _default_ws():
    """The MCP server's own WebSocket command, imported from beside this.

    The handshake lives in `ha_mcp_server._ws_command` and is not copied
    here: `/opt/scripts` and `/opt/ha-mcp-server` are siblings in the
    image exactly as `brain/scripts` and `brain/ha-mcp-server` are in the
    repository, so the relative path holds in both.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.join(here, "..", "ha-mcp-server"))
    import ha_mcp_server  # noqa: PLC0415
    return ha_mcp_server._ws_command


def main(argv: list[str]) -> int:
    """`refresh` writes the cache; `filter` filters a map on stdin."""
    verb = argv[1] if len(argv) > 1 else ""
    path = argv[2] if len(argv) > 2 else CACHE_FILE
    if verb == "refresh":
        try:
            snap = refresh(_default_ws(), path)
        except Exception as exc:  # noqa: BLE001
            print(f"exposure: could not read Home Assistant: {exc}", file=sys.stderr)
            return 1
        print(f"exposure: {len(snap['exposed'])} exposed, {len(snap['hidden'])} not")
        return 0
    if verb == "filter":
        snap = load(path, TTL_S)
        if snap is None:
            try:
                snap = refresh(_default_ws(), path)
            except Exception as exc:  # noqa: BLE001
                print(f"exposure: could not read Home Assistant: {exc}", file=sys.stderr)
                snap = None
        sys.stdout.write(filter_map(sys.stdin.read(), snap))
        return 0 if snap is not None else 1
    print("usage: brain_exposed.py refresh|filter [cache-path]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
