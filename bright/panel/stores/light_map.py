"""The light map: what fixtures exist, where they are, and what they're for.

The map is the director's cast list. A fixture is a LIFX bulb (driven
directly) or an HA entity (a party light or laser on a switch — driven
through Core with its measured latency). Roles are a CLOSED vocabulary
shared with the palette rules: the director reasons in roles, never in
device models, so a new bulb slots into a show by being told what it is.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import atomic_write

MAP_FILE = Path(os.environ.get("BRIGHT_STATE", "/data")) / "light-map.json"

ROLES = ("candle", "downlight", "lamp", "strip", "party", "laser")
KINDS = ("lifx", "ha")

_SERIAL_RE = re.compile(r"^[0-9a-f]{12}$")
_ENTITY_RE = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")
_ZONE_RE = re.compile(r"^[A-Za-z0-9 _-]{0,32}$")


def load() -> dict:
    try:
        data = json.loads(MAP_FILE.read_text())
        if isinstance(data.get("fixtures"), list):
            return data
    except (OSError, ValueError):
        # No map yet, or an unreadable one — either way the empty map
        # below is the honest answer and the next save rewrites the file.
        pass
    return {"version": 1, "fixtures": []}


def _save(data: dict) -> None:
    data["updated_at"] = time.time()
    atomic_write.write_json(MAP_FILE, data, indent=2)


def clean_fixture(raw: dict) -> dict:
    """Validate one fixture off the wire. Raises ValueError with a message
    the panel can show."""
    kind = raw.get("kind")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    fixture: dict = {"kind": kind}
    if kind == "lifx":
        serial = str(raw.get("serial", "")).lower()
        if not _SERIAL_RE.fullmatch(serial):
            raise ValueError("lifx fixtures need a 12-hex-digit serial")
        fixture["serial"] = serial
        fixture["id"] = f"lifx-{serial}"
    else:
        entity_id = str(raw.get("entity_id", ""))
        if not _ENTITY_RE.fullmatch(entity_id):
            raise ValueError("ha fixtures need a valid entity_id")
        fixture["entity_id"] = entity_id
        fixture["id"] = entity_id
    role = raw.get("role")
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    fixture["role"] = role
    zone = str(raw.get("zone", "") or "")
    if not _ZONE_RE.fullmatch(zone):
        raise ValueError("zone: letters, digits, spaces, - and _ only")
    fixture["zone"] = zone
    fixture["label"] = str(raw.get("label", "") or fixture["id"])[:64]
    try:
        fixture["x"] = min(1.0, max(0.0, float(raw.get("x", 0.5))))
        fixture["y"] = min(1.0, max(0.0, float(raw.get("y", 0.5))))
    except (TypeError, ValueError):
        raise ValueError("x and y must be numbers in 0..1") from None
    return fixture


def upsert(raw: dict) -> dict:
    fixture = clean_fixture(raw)
    data = load()
    fixtures = [f for f in data["fixtures"] if f.get("id") != fixture["id"]]
    fixtures.append(fixture)
    data["fixtures"] = sorted(fixtures, key=lambda f: (f["role"], f["id"]))
    _save(data)
    return fixture


def remove(fixture_id: str) -> bool:
    data = load()
    before = len(data["fixtures"])
    data["fixtures"] = [f for f in data["fixtures"]
                        if f.get("id") != fixture_id]
    if len(data["fixtures"]) == before:
        return False
    _save(data)
    return True


def merge_lifx(devices: dict[str, dict]) -> int:
    """Every discovered bulb becomes a fixture (default role: lamp) unless
    the map already knows it — discovery must never overwrite a person's
    placement."""
    data = load()
    known = {f.get("serial") for f in data["fixtures"] if f.get("kind") == "lifx"}
    added = 0
    for serial, device in devices.items():
        if serial in known or not _SERIAL_RE.fullmatch(serial):
            continue
        data["fixtures"].append({
            "id": f"lifx-{serial}",
            "kind": "lifx",
            "serial": serial,
            "label": device.get("label") or serial,
            "role": "lamp",
            "zone": "",
            "x": 0.5,
            "y": 0.5,
        })
        added += 1
    if added:
        _save(data)
    return added


def lifx_fixtures(devices: dict[str, dict]) -> list[dict]:
    """Map fixtures that are actually reachable right now (in the device
    registry), each annotated with its address info."""
    reachable = []
    for fixture in load()["fixtures"]:
        if fixture.get("kind") != "lifx":
            continue
        device = devices.get(fixture.get("serial", ""))
        if device is None:
            continue
        reachable.append({**fixture, "rtt": device.get("rtt")})
    return reachable


def ha_fixtures() -> list[dict]:
    return [f for f in load()["fixtures"] if f.get("kind") == "ha"]
