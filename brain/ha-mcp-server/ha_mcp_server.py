#!/usr/bin/env python3
"""
Home Assistant MCP Server for brAIn

Provides Claude Code with real-time access to Home Assistant via the
Model Context Protocol (MCP). This server exposes HA entity states,
service calls, device control, automation traces, area listings
(via the template engine), and log access as MCP tools.

Runs as a stdio-based MCP server that Claude Code launches automatically.
"""

import base64
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import urllib.error

# Pillow is optional: camera snapshots are downscaled when it's available
# and passed through untouched when it isn't.
try:
    from PIL import Image
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False

# ============================================================================
# Configuration
# ============================================================================

SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
HA_BASE_URL = os.environ.get("HA_BASE_URL", "http://supervisor/core/api")
SUPERVISOR_API_URL = os.environ.get("SUPERVISOR_API_URL", "http://supervisor")

# Per-channel service deny-list (e.g. a voice agent forbidden from
# lock.unlock). Comma-separated patterns: exact "domain.service" or a
# whole-domain "domain.*". Set per worker via env (see assist-worker-pool.py),
# so it is inherited by this MCP subprocess. Every control_* tool routes
# through call_service(), so enforcing here covers all of them.
DENIED_SERVICES = [
    p.strip().lower() for p in os.environ.get("BRAIN_DENIED_SERVICES", "").split(",")
    if p.strip()
]


# Long-term memory store shared with the brain memory tooling and the
# consolidator daemon. Env-overridable so tests can point it at a temp dir.
MEMORY_DIR = os.environ.get("BRAIN_MEMORY_DIR", "/config/.brain/memory")

# Protected entities: the add-on's `protected_entities` option, exported by
# run.sh as a comma-separated list of entity ids or `domain.*` patterns.
# Where DENIED_SERVICES restricts a *channel* (voice may not unlock), this
# restricts an *entity* for every channel at once — the terminal, the chat,
# the fixer, voice and automations all reach the house through this one
# process, so "brAIn never touches the front door lock" is enforced here
# and nowhere else. Read-only tools are unaffected: a protected entity can
# still be looked at, it cannot be acted on.
PROTECTED_ENTITIES = [
    p.strip().lower() for p in os.environ.get("BRAIN_PROTECTED_ENTITIES", "").split(",")
    if p.strip()
]

# The action ledger: every service call brAIn makes, appended here so the
# panel's action miner can tell brAIn's own changes from everybody else's.
# Nothing in Home Assistant's context chain can do that — this process
# calls Core over the REST API with the Supervisor's token, exactly like
# every other add-on, so a light brAIn turned on looks in the logbook like
# a light any integration turned on. The only honest answer is to write
# down what we did, which is what this is. The reader is
# `panel/actions.py:read_ledger`; it is a different process running as a
# different user and cannot import this file, so the two halves agree by
# contract and `tests/test_actions.py` drives this writer into that reader
# rather than describing the shape twice.
ACTION_LEDGER = os.environ.get("BRAIN_ACTION_LEDGER",
                               "/config/.brain/actions.jsonl")
# Roughly a fortnight of a busy house. The file is trimmed rather than
# rotated: a second file would need a second reader.
ACTION_LEDGER_MAX_BYTES = 2 * 1024 * 1024


def _call_entities(data):
    """The entity ids a service call names, at either of the two places.

    A call may put `entity_id` at the top level or inside `target`, and
    either may be a string or a list. Area, device, label and floor
    targets are recorded under `target` and deliberately not resolved:
    resolving one needs the registries as they were at the time of the
    call, and a wrong expansion would attribute somebody else's change to
    brAIn — which is the one mistake this ledger exists to prevent.
    """
    out = []
    for source in (data or {}, (data or {}).get("target") or {}):
        if not isinstance(source, dict):
            continue
        value = source.get("entity_id")
        if isinstance(value, str):
            value = [value]
        if isinstance(value, list):
            out.extend(str(v) for v in value if isinstance(v, str) and "." in v)
    seen = set()
    return [e for e in out if not (e in seen or seen.add(e))]


def record_action(domain, service, data):
    """Append one service call to the ledger. Never raises.

    Accounting must not fail the call it is accounting for — the same rule
    the panel's run journal follows. A ledger this cannot write costs the
    timeline an attribution; a ledger that raises costs somebody their
    lights.
    """
    try:
        target = {}
        for key in ("area_id", "device_id", "label_id", "floor_id"):
            for source in (data or {}, (data or {}).get("target") or {}):
                if isinstance(source, dict) and source.get(key):
                    target[key] = source[key]
        row = {
            "ts": time.time(),
            "domain": domain,
            "service": service,
            "entities": _call_entities(data),
        }
        if target:
            row["target"] = target
        path = ACTION_LEDGER
        try:
            if os.path.getsize(path) > ACTION_LEDGER_MAX_BYTES:
                with open(path, "r", encoding="utf-8") as fh:
                    lines = fh.readlines()
                with open(path, "w", encoding="utf-8") as fh:
                    fh.writelines(lines[len(lines) // 2:])
        except OSError:
            # A ledger that cannot be trimmed is still a ledger that can be
            # appended to. Losing the trim costs disk; refusing the append
            # would cost the timeline every action from here on.
            pass
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
    except Exception:  # noqa: BLE001 - see docstring
        pass


def _service_denied(domain, service):
    """True if calling domain.service is forbidden for this channel."""
    target = f"{domain}.{service}".lower()
    for pattern in DENIED_SERVICES:
        if pattern == target or pattern == f"{domain.lower()}.*" or pattern == "*":
            return True
    return False


# The homeassistant.* meta-services forward to the target entity's own
# domain — homeassistant.turn_on on cover.garage_door opens the cover — so
# matching them by their spelled name alone lets every entity-level denial
# be rewritten as a meta-call: deny cover.open_cover and
# `homeassistant.turn_on {"entity_id": "cover.garage_door"}` still opens
# the garage. They are checked against their *targets* instead, and
# conservatively: a meta-call touching any entity whose domain appears in a
# denied pattern is refused outright, because the exact domain service a
# meta-call resolves to is Home Assistant's mapping, not ours, and a
# restricted channel failing closed beats one failing open. The entity's
# own domain service remains the route for whatever is actually permitted.
_META_SERVICES = ("turn_on", "turn_off", "toggle")


def _meta_call_denied(payload):
    """Why a homeassistant.* meta-service call is refused, or None."""
    if not DENIED_SERVICES:
        return None
    payload = payload if isinstance(payload, dict) else {}
    target = payload.get("target")
    scopes = [payload] + ([target] if isinstance(target, dict) else [])

    entity_ids = []
    for scope in scopes:
        raw = scope.get("entity_id")
        if isinstance(raw, str):
            entity_ids.extend(x.strip() for x in raw.split(",") if x.strip())
        elif isinstance(raw, list):
            entity_ids.extend(str(x) for x in raw)
        # Area/device/label/floor targets resolve to entities inside HA,
        # where this check cannot see them.
        for key in ("area_id", "device_id", "label_id", "floor_id"):
            if scope.get(key):
                return ("it targets an area, device, label or floor, whose "
                        "member entities cannot be checked against this "
                        "assistant's restrictions")

    if not entity_ids or any(e.lower() == "all" for e in entity_ids):
        # No entity list (or the "all" sentinel) means every entity on the
        # system, which certainly includes restricted ones.
        return "it addresses all entities, including restricted ones"

    denied_domains = {p.split(".", 1)[0] for p in DENIED_SERVICES}
    for eid in entity_ids:
        edomain = eid.split(".", 1)[0].lower()
        if edomain in denied_domains:
            return (f"it targets {eid}, and {edomain} services are "
                    "restricted for this assistant")
    return None


def _entity_protected(entity_id):
    """True if this entity id matches the protected list."""
    target = str(entity_id or "").strip().lower()
    if not target:
        return False
    domain = target.split(".", 1)[0]
    for pattern in PROTECTED_ENTITIES:
        if pattern == target or pattern == f"{domain}.*" or pattern == "*":
            return True
    return False


_PROTECTED_SCOPES = {"at": 0.0, "areas": set(), "devices": set()}
_PROTECTED_SCOPES_TTL = 60.0


def _protected_scopes():
    """The area and device ids that hold a protected entity.

    An area or device target resolves to entities inside Home Assistant,
    where this check cannot see it — so the registry is asked which areas
    and devices a protected entity lives in, and a call aimed at one of
    those is refused. Cached briefly; the registry does not move fast.
    Unreadable registry → empty sets, and the caller fails closed on any
    area/device target while a protected list exists.
    """
    import time as _time
    now = _time.time()
    if now - _PROTECTED_SCOPES["at"] < _PROTECTED_SCOPES_TTL:
        return _PROTECTED_SCOPES["areas"], _PROTECTED_SCOPES["devices"], True
    areas, devices, ok = set(), set(), False
    try:
        entities = _ws_command({"type": "config/entity_registry/list"})
        device_rows = _ws_command({"type": "config/device_registry/list"})
        if isinstance(entities, list) and isinstance(device_rows, list):
            device_area = {d.get("id"): d.get("area_id") for d in device_rows
                           if isinstance(d, dict)}
            for e in entities:
                if not isinstance(e, dict) or not _entity_protected(e.get("entity_id")):
                    continue
                if e.get("device_id"):
                    devices.add(e["device_id"])
                area = e.get("area_id") or device_area.get(e.get("device_id"))
                if area:
                    areas.add(area)
            ok = True
    except Exception:  # noqa: BLE001 — an unreadable registry fails closed below
        ok = False
    if ok:
        _PROTECTED_SCOPES.update(at=now, areas=areas, devices=devices)
    return areas, devices, ok


def _protected_target(payload, empty_is_all=False):
    """Why a service call's targets touch a protected entity, or None.

    ``empty_is_all`` is the meta-service rule: a ``homeassistant.turn_off``
    that names no entity, area or device addresses every entity Core has,
    which certainly includes the protected ones — `_meta_call_denied`
    has read it that way since it was written, and this did not, so the
    two chokepoint checks disagreed about the same payload. It is opt-in
    because most services legitimately take no entity target at all
    (notify, reload, the brain.* registry services), and refusing those
    while a protected list exists would take the add-on's own tooling away.
    """
    if not PROTECTED_ENTITIES:
        return None
    payload = payload if isinstance(payload, dict) else {}
    target = payload.get("target")
    scopes = [payload] + ([target] if isinstance(target, dict) else [])
    entity_ids = []
    area_ids = []
    device_ids = []
    for scope in scopes:
        raw = scope.get("entity_id")
        if isinstance(raw, str):
            entity_ids.extend(x.strip() for x in raw.split(",") if x.strip())
        elif isinstance(raw, list):
            entity_ids.extend(str(x) for x in raw)
        for key, bucket in (("area_id", area_ids), ("device_id", device_ids)):
            val = scope.get(key)
            if isinstance(val, str):
                bucket.append(val)
            elif isinstance(val, list):
                bucket.extend(str(x) for x in val)
        for key in ("label_id", "floor_id"):
            if scope.get(key):
                return ("it targets a label or floor, whose member entities "
                        "cannot be checked against the protected list")
    if empty_is_all and not (entity_ids or area_ids or device_ids):
        return "it names no target, which addresses all entities, including protected ones"
    for eid in entity_ids:
        if eid.lower() == "all":
            return "it addresses all entities, including protected ones"
        if _entity_protected(eid):
            return f"{eid} is a protected entity"
    if area_ids or device_ids:
        areas, devices, ok = _protected_scopes()
        if not ok:
            return ("it targets an area or device and the registry could "
                    "not be read to check whether a protected entity is in it")
        for a in area_ids:
            if a in areas:
                return f"area {a} contains a protected entity"
        for d in device_ids:
            if d in devices:
                return f"device {d} is a protected entity's device"
    return None


# What Home Assistant exposes to Assist, applied to the voice channel.
# `BRAIN_EXPOSED_ONLY=1` is set by the worker pool and the classic listener
# on every voice process whose agent's level is `voice` (the default),
# and by nothing else: the terminal, the chat, the fixer and the automation
# listener see the whole house, exactly as before. Where DENIED_SERVICES
# restricts a channel by SERVICE and PROTECTED_ENTITIES restricts every
# channel by ENTITY, this restricts one channel by what the person has
# exposed in Settings → Voice assistants — which is the switch Home
# Assistant already has for exactly this question, and the one an
# integration that registers itself as a voice assistant is expected to
# honour. The rule itself lives in `scripts/brain_exposed.py`, the one
# module the pool, the listener and this server all read, so the map
# voice is shown and the gate voice meets cannot disagree.
EXPOSED_ONLY = os.environ.get("BRAIN_EXPOSED_ONLY", "") == "1"
EXPOSURE_TTL_S = 60.0
_EXPOSURE = {"at": 0.0, "snap": None}


def _exposure():
    """The exposure snapshot, or None when it could not be read.

    Cached in-process for `EXPOSURE_TTL_S` and on disk by the module for
    the same window, so a voice turn making six tool calls reads Core
    once. None means fail closed: every caller refuses on it.
    """
    now = time.time()
    if _EXPOSURE["snap"] is not None and now - _EXPOSURE["at"] < EXPOSURE_TTL_S:
        return _EXPOSURE["snap"]
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        "..", "scripts"))
        import brain_exposed  # noqa: PLC0415 — sibling directory, see the module
        snap = brain_exposed.load_or_refresh(_ws_command)
    except Exception:  # noqa: BLE001 — unreadable is "fail closed", below
        snap = None
    if snap is not None:
        _EXPOSURE.update(at=now, snap=snap)
    return snap


def _entity_exposed(entity_id):
    """Whether the voice channel may see this entity; True off the channel."""
    if not EXPOSED_ONLY:
        return True
    snap = _exposure()
    if snap is None:
        return False
    import brain_exposed  # noqa: PLC0415 — on sys.path once _exposure ran
    return brain_exposed.is_exposed(entity_id, snap)


UNEXPOSED_READ = (
    "{eid} is not exposed to voice assistants in Home Assistant, so this "
    "assistant cannot see it. Tell the user it can be exposed under "
    "Settings → Voice assistants; do not retry."
)


def _exposure_refusal(payload):
    """Why a service call's targets reach something voice cannot see, or None.

    Only entity targets can be checked against the exposure list; an area,
    device, label or floor target is refused while the channel is gated,
    because expanding one needs registries this check does not hold and a
    hidden entity reached through its room is the bypass. The area map
    voice is shown lists the exposed ids per area, so the model can name
    them — which is what the sentence asks for.
    """
    if not EXPOSED_ONLY:
        return None
    payload = payload if isinstance(payload, dict) else {}
    target = payload.get("target")
    scopes = [payload] + ([target] if isinstance(target, dict) else [])
    entity_ids = []
    for scope in scopes:
        raw = scope.get("entity_id")
        if isinstance(raw, str):
            entity_ids.extend(x.strip() for x in raw.split(",") if x.strip())
        elif isinstance(raw, list):
            entity_ids.extend(str(x) for x in raw)
        for key in ("area_id", "device_id", "label_id", "floor_id"):
            if scope.get(key):
                return ("it targets an area, device, label or floor, and voice "
                        "may only act on the entities Home Assistant exposes "
                        "to it — name the entity ids instead")
    if _exposure() is None:
        return ("Home Assistant's exposure settings could not be read, and "
                "voice may only act on what is exposed to it")
    for eid in entity_ids:
        if eid.lower() == "all":
            return "it addresses all entities, including ones not exposed to voice"
        if not _entity_exposed(eid):
            return f"{eid} is not exposed to voice assistants in Home Assistant"
    return None


def ha_api_request(endpoint, method="GET", data=None, accept=None):
    """Make a request to the Home Assistant API."""
    if endpoint.startswith("/api/"):
        url = f"{HA_BASE_URL}{endpoint[4:]}"
    elif endpoint.startswith("/"):
        url = f"{SUPERVISOR_API_URL}{endpoint}"
    else:
        url = f"{HA_BASE_URL}/{endpoint}"

    headers = {
        "Authorization": f"Bearer {SUPERVISOR_TOKEN}",
        "Content-Type": "application/json",
    }
    if accept:
        headers["Accept"] = accept

    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read().decode()
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                # Some endpoints (e.g., logs) return plain text
                return raw
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        return {"error": f"HTTP {e.code}: {e.reason}", "details": error_body}
    except Exception as e:
        return {"error": str(e)}


def ha_api_request_raw(endpoint):
    """GET a Home Assistant API endpoint, returning raw bytes (e.g. images)."""
    if endpoint.startswith("/api/"):
        url = f"{HA_BASE_URL}{endpoint[4:]}"
    else:
        url = f"{HA_BASE_URL}/{endpoint.lstrip('/')}"
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {SUPERVISOR_TOKEN}"}
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read()


def _ws_command(payload, timeout=15):
    """Run one authenticated command against HA's WebSocket API.

    Some data (long-term statistics) is WebSocket-only. The `websockets`
    package ships in the add-on image; import lazily so environments
    without it (tests) degrade to a clear error instead of failing import.

    max_size=None is load-bearing: the websockets default (1 MiB) is
    smaller than a real install's entity-registry response, so without it
    the connection dies on receive and no post-hoc filtering can ever run.
    Responses are trimmed/capped by the callers instead.
    """
    from websockets.sync.client import connect  # lazy: optional dependency

    url = HA_BASE_URL.replace("http://", "ws://").replace("https://", "wss://")
    url = url.rsplit("/api", 1)[0] + "/websocket"
    with connect(url, open_timeout=timeout, close_timeout=5, max_size=None) as ws:
        json.loads(ws.recv(timeout=timeout))  # auth_required
        ws.send(json.dumps({"type": "auth", "access_token": SUPERVISOR_TOKEN}))
        auth = json.loads(ws.recv(timeout=timeout))
        if auth.get("type") != "auth_ok":
            return {"error": f"WebSocket auth failed: {auth.get('message', auth)}"}
        payload = {"id": 1, **payload}
        ws.send(json.dumps(payload))
        while True:
            msg = json.loads(ws.recv(timeout=timeout))
            if msg.get("id") == 1 and msg.get("type") == "result":
                if not msg.get("success"):
                    return {"error": str(msg.get("error", "WebSocket command failed"))}
                return msg.get("result")


# ============================================================================
# MCP Tool Implementations — Core
# ============================================================================

def get_entity_state(entity_id):
    """Get the current state of a specific entity."""
    if not _entity_exposed(entity_id):
        return {"error": UNEXPOSED_READ.format(eid=entity_id)}
    result = ha_api_request(f"/api/states/{entity_id}")
    if "error" not in result:
        return {
            "entity_id": result.get("entity_id"),
            "state": result.get("state"),
            "attributes": result.get("attributes", {}),
            "last_changed": result.get("last_changed"),
            "last_updated": result.get("last_updated"),
        }
    return result


# Cap on get_all_states results: an unfiltered dump of a large install is a
# huge tool result that slows every model turn and can blow the context.
MAX_STATE_RESULTS = 300


def get_all_states(domain=None, name_filter=None):
    """Get states of all entities, filtered by domain and/or name substring."""
    result = ha_api_request("/api/states")
    if isinstance(result, list):
        if domain:
            result = [e for e in result if e.get("entity_id", "").startswith(f"{domain}.")]
        if EXPOSED_ONLY:
            # A gated channel is shown the exposed rows and nothing else; a
            # snapshot that could not be read shows nothing, which sends the
            # model to say it cannot see rather than to act on a row it
            # would then be refused.
            result = [e for e in result if _entity_exposed(e.get("entity_id"))]
        entities = [
            {
                "entity_id": e.get("entity_id"),
                "state": e.get("state"),
                "friendly_name": e.get("attributes", {}).get("friendly_name", ""),
            }
            for e in result
        ]
        if name_filter:
            needle = str(name_filter).lower()
            entities = [
                e for e in entities
                if needle in (e["entity_id"] or "").lower()
                or needle in (e["friendly_name"] or "").lower()
            ]
        if len(entities) > MAX_STATE_RESULTS:
            return {
                "total_matches": len(entities),
                "returned": MAX_STATE_RESULTS,
                "note": "Result truncated — narrow the search with the domain and/or name_filter arguments.",
                "entities": entities[:MAX_STATE_RESULTS],
            }
        return entities
    return result


def call_service(domain, service, data=None, return_response=False):
    """Call a Home Assistant service.

    Single chokepoint: every control_* tool, activate_scene, run_script,
    send_notification, and reload_config funnel through here, so the
    deny-list check covers all of them, not just direct call_service use.

    With return_response the call goes over the WebSocket API, which is the
    only transport that returns service response data (e.g. the area_id
    from brain.create_area, or the orphan list from
    brain.delete_orphaned_entities).
    """
    if _service_denied(domain, service):
        return {"error": (
            f"Service {domain}.{service} is not permitted for this assistant. "
            "Tell the user this action is restricted; do not retry."
        )}
    if domain.lower() == "homeassistant" and service.lower() in _META_SERVICES:
        reason = _meta_call_denied(data)
        if reason:
            return {"error": (
                f"homeassistant.{service} is not permitted here because "
                f"{reason}. Call the entity's own domain service instead; "
                "if that is also refused, tell the user the action is "
                "restricted and do not retry."
            )}
    protected = _protected_target(
        data,
        empty_is_all=(domain.lower() == "homeassistant"
                      and service.lower() in _META_SERVICES))
    if protected:
        return {"error": (
            f"{domain}.{service} is refused because {protected}. The "
            "homeowner has put it on brAIn's protected list, and nothing "
            "brAIn does may act on it. Tell the user; do not retry or "
            "look for another route."
        )}
    if EXPOSED_ONLY and (domain.lower(), service.lower()) in VOICE_ADMIN_SERVICES:
        return {"error": ADDON_VOICE_REFUSAL.format(what=f"{domain}.{service}")}
    unexposed = _exposure_refusal(data)
    if unexposed:
        return {"error": (
            f"{domain}.{service} is refused because {unexposed}. Tell the "
            "user it can be exposed under Settings → Voice assistants; do "
            "not retry or look for another route."
        )}
    payload = data or {}
    record_action(domain, service, payload)
    if return_response:
        try:
            result = _ws_command({
                "type": "call_service",
                "domain": domain,
                "service": service,
                "service_data": payload,
                "return_response": True,
            })
        except ImportError:
            return {"error": "websockets package not available in this environment"}
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}
        if isinstance(result, dict) and "error" in result:
            return result
        return {"response": (result or {}).get("response")}
    result = ha_api_request(f"/api/services/{domain}/{service}", method="POST", data=payload)
    return result


PANEL_URL = os.environ.get("BRAIN_PANEL_URL", "http://127.0.0.1:8099")


def _panel_get(path, timeout=60):
    """GET one of the panel's own API endpoints over loopback.

    The panel is where the action miner lives, and a second copy of "who
    caused this state change" written here would be a second answer. Same
    reasoning as `brain findings` going through the API rather than the
    store files: one implementation, one answer. A panel that is not up is
    reported as such rather than as an empty house.
    """
    req = urllib.request.Request(f"{PANEL_URL}{path}",
                                 headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode())
    except Exception as e:  # noqa: BLE001
        return {"error": f"the brAIn panel did not answer: {e}"}


def _window(result):
    """How many hours the panel actually read, from the window it returned."""
    try:
        return round((float(result["end"]) - float(result["start"])) / 3600.0, 2)
    except (KeyError, TypeError, ValueError):
        return None


def get_baseline(entity_id):
    """What is normal for one entity, and how far outside it the reading is.

    This is what turns "unusual" from a word into a number. Without it a
    model asked whether a reading is odd has to invent a threshold, and
    the threshold it invents is the same one for a freezer and a water
    meter.
    """
    if not re.match(r"^[a-z0-9_]+\.[a-z0-9_]+$", str(entity_id or "")):
        return {"error": (
            f"'{str(entity_id)[:64]}' is not an entity id. They look like "
            "sensor.hall_temperature."
        )}
    quoted = urllib.parse.quote(str(entity_id), safe="")
    result = _panel_get(f"/api/baselines?entity_id={quoted}")
    if isinstance(result, dict) and result.get("error"):
        return result
    baseline = (result or {}).get("baseline")
    if not baseline:
        measured = (result or {}).get("measured", 0)
        return {"entity_id": entity_id, "baseline": None, "note": (
            "brAIn has no baseline for this entity. It measures numeric "
            "sensors with long-term statistics overnight" + (
                f" ({measured} measured so far)" if measured else
                " and has not run yet") + ". An entity that never changes "
            "is deliberately not given one."
        )}
    if baseline.get("flat"):
        return {"entity_id": entity_id, "baseline": None, "note": (
            f"This entity has read {baseline.get('value')} for its whole "
            "history, so it has no spread to measure oddness against. Any "
            "change at all is worth looking at on its own terms."
        )}
    return {
        "entity_id": entity_id,
        "measured_over_days": (result or {}).get("days"),
        "timezone": (result or {}).get("tz"),
        "stale": (result or {}).get("stale"),
        "unit": baseline.get("unit"),
        "overall": baseline.get("overall"),
        "samples": baseline.get("samples"),
        "by_hour_of_week": baseline.get("buckets"),
        # The band and the drift are different questions and a model has to
        # be able to ask both: a reading can be squarely inside its usual
        # range and still be six degrees from where it was a month ago,
        # which is a fact about the house that the buckets cannot express.
        "trend": baseline.get("trend"),
        "note": ("`spread` is a median absolute deviation, not a standard "
                 "deviation — about two thirds of one for ordinary data. "
                 "Hour-of-week buckets are 0 = Monday 00:00 local. `trend` "
                 "is a separate question: how far the reading has TRAVELLED "
                 "across the window (`move`, over `days`), in units of the "
                 "noise it travelled through (`spreads`). A drift hides "
                 "from the buckets, because the buckets moved with it — so "
                 "a reading can be entirely normal and still be somewhere "
                 "it has never been. `consistent` false means the window "
                 "turned around in the middle and is not a drift at all; "
                 "absent means this is a total that only ever goes up, or "
                 "there was not enough history to fit a line through."),
    }


def explain_change(entity_id, hours=24):
    """Why an entity is the way it is: its recent changes, and what caused each.

    This is the one question a state cannot answer. `get_history` says a
    light went on at 18:04; this says the evening automation did it, or
    that somebody pressed the switch, or that brAIn did.
    """
    if not re.match(r"^[a-z0-9_]+\.[a-z0-9_]+$", str(entity_id or "")):
        return {"error": (
            f"'{str(entity_id)[:64]}' is not an entity id. They look like "
            "light.kitchen — use get_all_states to find the one you mean."
        )}
    try:
        hours = max(1, float(hours or 24))
    except (TypeError, ValueError):
        hours = 24
    quoted = urllib.parse.quote(str(entity_id), safe="")
    result = _panel_get(f"/api/activity/entity/{quoted}?hours={hours}")
    if isinstance(result, dict) and result.get("error"):
        return result
    if isinstance(result, dict) and not result.get("available"):
        return {"error": (
            "Home Assistant's logbook could not be read, so nothing can say "
            "what caused a change. The logbook integration may not be set up."
        )}
    # The window the PANEL used, not the one asked for. It caps how long a
    # window may be (a week of unfiltered logbook is a download, not a
    # window), and echoing the argument here would report a window that was
    # never read.
    window = _window(result)
    changes = (result or {}).get("changes") or []
    if not changes:
        return {"entity_id": entity_id, "hours": window, "changes": [],
                "note": "nothing changed this entity in that window"}
    return {"entity_id": entity_id, "hours": window, "changes": changes}


def get_house_model():
    """What brAIn has measured about this house, and what it is still missing.

    Seven measurements — when the house gets up, what each reading normally
    is, how fast each room loses heat, how often each door is open, what
    each machine's power looks like, what somebody does by hand often
    enough to be a habit, and what the electricity did last week — each
    with how far along it is and one sentence saying so.

    Read this BEFORE deciding a house is quiet or a sensor is normal: a
    measurement that has not been made yet says nothing, and reading its
    silence as "nothing is wrong" is the one mistake it cannot recover
    from. The `state` of each store says which it is.
    """
    result = _panel_get("/api/knowledge/house")
    if isinstance(result, dict) and result.get("error"):
        return result
    stores = (result or {}).get("stores") or {}
    return {
        "generated_at": (result or {}).get("generated_at"),
        # Trimmed to what a model can act on: the whole `detail` of every
        # store is the drill-down's job and would be most of a house.
        "stores": {name: {k: row.get(k) for k in
                          ("state", "have", "need", "unit", "summary",
                           "reason", "updated_at")}
                   for name, row in stores.items() if isinstance(row, dict)},
        "brief": (result or {}).get("brief") or {},
        "weekly": (result or {}).get("weekly") or {},
    }


# ---------------------------------------------------------------------------
# The measurements, as tools — 2.2
# ---------------------------------------------------------------------------
#
# Every store the checks read (`baselines`, `thermal`, `appliances`,
# `rhythm`, `closures`, the three ledgers) used to be readable by rules and
# by nobody else: a card asked whether a reading was odd had to guess a
# threshold, and voice asked "is the dishwasher done" had no way to know.
# Each of these calls the panel's own route over loopback, `explain_change`'s
# arrangement, because the panel already holds the one implementation of
# each answer and a second copy here would be a second answer. A panel
# that is not up is reported as such rather than as a house with nothing
# measured, and a store that has not measured yet says so in words — a
# measurement that has not been made is not "nothing is wrong".

_ENTITY_RE = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")


def _entity_or_error(entity_id, example):
    if not _ENTITY_RE.match(str(entity_id or "")):
        return {"error": (
            f"'{str(entity_id)[:64]}' is not an entity id. They look like "
            f"{example} — use get_all_states to find the one you mean."
        )}
    return None


def what_is_normal(entity_id):
    """What this entity normally reads NOW, how far from that it is, and
    where it has been heading — `get_baseline` with the question a run
    actually asks answered at the top."""
    bad = _entity_or_error(entity_id, "sensor.freezer_temp")
    if bad:
        return bad
    base = get_baseline(entity_id)
    if base.get("error") or not base.get("baseline", True):
        return base
    quoted = urllib.parse.quote(str(entity_id), safe="")
    state = ha_api_request(f"/api/states/{quoted}")
    reading = None
    try:
        reading = float((state or {}).get("state"))
    except (TypeError, ValueError, AttributeError):
        # `unavailable`, `unknown` or a Core that did not answer: the reading
        # stays None and the answer says so beside the baseline.
        pass
    overall = base.get("overall") or {}
    out = {
        "entity_id": entity_id,
        "reading_now": reading,
        "unit": base.get("unit"),
        "usual": overall,
        "trend": base.get("trend"),
        "measured_over_days": base.get("measured_over_days"),
        "stale": base.get("stale"),
    }
    median = overall.get("median")
    spread = overall.get("spread")
    if reading is not None and median is not None and spread:
        out["spreads_from_usual"] = round((reading - median) / spread, 2)
        out["note"] = ("`spreads_from_usual` is how far outside its own "
                       "normal the reading is, in its own median absolute "
                       "deviations; past about six is unusual for this "
                       "house. Ask `get_baseline` for the hour-of-week "
                       "buckets when the time of day matters.")
    else:
        out["note"] = ("No live reading to compare, or no spread to compare "
                       "it against — see `usual` and `trend`.")
    return out


def room_physics(area):
    """How fast a room loses heat and gains it, from a month of nights."""
    result = _panel_get("/api/knowledge/house/thermal")
    if isinstance(result, dict) and result.get("error"):
        return result
    rooms = (result or {}).get("rooms") or []
    want = str(area or "").strip().lower()
    match = [r for r in rooms if isinstance(r, dict) and want in (
        str(r.get("area") or "").lower(), str(r.get("name") or "").lower(),
        str(r.get("id") or "").lower())]
    if not match and want:
        match = [r for r in rooms if isinstance(r, dict) and want in
                 (str(r.get("area") or "") + " " + str(r.get("name") or "")).lower()]
    if not rooms:
        return {"area": area, "rooms": [], "note": (
            "brAIn has not fitted a heat model to any room yet — it needs "
            "a month of nights with an outdoor reference, and says which "
            "rooms it could not fit and why in the Knowledge tab.")}
    if not match:
        return {"area": area, "rooms": [], "known_rooms": [
            r.get("area") or r.get("name") for r in rooms if isinstance(r, dict)],
            "note": "no measured room by that name — see known_rooms"}
    return {"area": area, "outdoor_reference": (result or {}).get("outdoor"),
            "unit": (result or {}).get("unit"),
            "rooms": match,
            "note": ("`k` is the loss rate per hour (its reciprocal `tau_h` is "
                     "the time constant in hours), `gain` the degrees per "
                     "hour with the heating on, `hours_to_warm` measured "
                     "between the room's own `coolest` and `warmest` on the "
                     "coldest night the month held.")}


def appliance_status(entity_id):
    """Idle, running, or finished-and-waiting, by this machine's OWN
    measured thresholds — never a wattage somebody typed."""
    bad = _entity_or_error(entity_id, "sensor.dishwasher_power")
    if bad:
        return bad
    result = _panel_get("/api/knowledge/house/appliances")
    if isinstance(result, dict) and result.get("error"):
        return result
    rows = (result or {}).get("appliances") or []
    for row in rows:
        if isinstance(row, dict) and row.get("entity_id") == entity_id:
            live = row.get("now") if isinstance(row.get("now"), dict) else {}
            return {"entity_id": entity_id, "state": live.get("state"),
                    "now": live, "name": row.get("name"),
                    "chore_kind": row.get("chore_kind"),
                    "thresholds": {k: row.get(k) for k in
                                   ("idle_w", "running_w", "threshold_w",
                                    "settle_min", "cycles") if k in row},
                    "live_error": (result or {}).get("live_error"),
                    "note": (
                "`state` is idle / running / finished from the machine's own "
                "power shape; `finished` means the draw dropped past its "
                "measured settle and nothing has run since — not that it "
                "has been emptied, which no power reading can see.")}
    return {"entity_id": entity_id, "state": None, "note": (
        "brAIn has no power profile for this entity. It profiles power "
        "sensors whose draw is clearly two-level (idle and running) from "
        "ten days of five-minute statistics; a router or a fridge's "
        "standing draw gets none on purpose.")}


def house_rhythm():
    """When this house wakes and settles, weekdays and weekends apart."""
    result = _panel_get("/api/knowledge/house/rhythm")
    if isinstance(result, dict) and result.get("error"):
        return result
    return {**(result or {}), "note": (
        "Measured from the first and last thing a PERSON did each day — "
        "not a motion sensor and not a light. A half with too few days or "
        "too wide a spread reports no time, which is the floor doing its "
        "job and not an error.")}


def door_habits(entity_id):
    """How much of each hour of the week this closure is usually open."""
    bad = _entity_or_error(entity_id, "binary_sensor.back_door")
    if bad:
        return bad
    result = _panel_get("/api/knowledge/house/closures")
    if isinstance(result, dict) and result.get("error"):
        return result
    rows = result if isinstance(result, list) else (result or {}).get("rows") or []
    for row in rows:
        if isinstance(row, dict) and row.get("entity_id") == entity_id:
            return {**row, "note": (
                "`buckets` are hour-of-week (0 = Monday 00:00 local) → share "
                "of that hour it was open, over the weeks watched; a missing "
                "bucket was never watched, which is not 'never open then'. "
                "`overall` is the share across the whole window.")}
    return {"entity_id": entity_id, "buckets": None, "note": (
        "brAIn has not measured this closure — it watches doors, windows, "
        "locks, covers and garages by device class, nightly, and needs a "
        "few days before a bucket means anything.")}


def habits(entity_id):
    """What a person does with this entity by hand, often enough to be a
    habit — the days, the time, the share — and what keeps undoing it."""
    bad = _entity_or_error(entity_id, "light.porch")
    if bad:
        return bad
    quoted = urllib.parse.quote(str(entity_id), safe="")
    result = _panel_get(f"/api/habits?entity_id={quoted}")
    if isinstance(result, dict) and result.get("error"):
        return result
    return {**(result or {}), "note": (
        "`habit` is the strongest shape across the entity's states "
        "(days, share of the days it could have happened on, circular "
        "median time, spread); `overrides` are automations somebody keeps "
        "undoing about it; `odd` are recent presses far outside the "
        "shape. `automated` says something already does this.")}


def simulate_automation(config, days=7):
    """When an automation WOULD have fired over the last days — replayed
    against recorded history, calling nothing — and whether a person did
    the same thing, the opposite, or nothing in that window."""
    if not isinstance(config, dict):
        return {"error": "config must be a Home Assistant automation object "
                         "(trigger/condition/action)"}
    try:
        days = max(1, min(int(days or 7), 28))
    except (TypeError, ValueError):
        days = 7
    body = json.dumps({"config": config, "days": days}).encode()
    req = urllib.request.Request(
        f"{PANEL_URL}/api/simulate", data=body, method="POST",
        headers={"Accept": "application/json",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            result = json.loads(response.read().decode())
    except Exception as e:  # noqa: BLE001
        return {"error": f"the brAIn panel did not answer: {e}"}
    if result.get("refused"):
        return {"refused": True, "days": days,
                "error": (result.get("error")
                          or (result.get("replay") or {}).get("error")
                          or "brAIn cannot replay this automation"),
                "note": ("Only time, state, numeric_state and template "
                         "triggers can be replayed from the recorder; the "
                         "refusal is whole, never a partial count.")}
    return {**result, "note": (
        "`replay.count` is how many times it would have fired; "
        "`against_you` grades each firing against what a person did "
        "within a few minutes: agreed (the same change), contradicted "
        "(the opposite), disagreed (nothing).")}


def recall(query="", subject="", limit=10):
    """What brAIn remembers about this — ranked facts, each with where it
    came from and when. Ask by subject (an entity id, `area:<id>`,
    `person:<id>`, `house`) or by a few words."""
    params = urllib.parse.urlencode({
        "query": str(query or "")[:200], "subject": str(subject or "")[:255],
        "limit": max(1, min(int(limit or 10), 50))})
    result = _panel_get(f"/api/facts?{params}")
    if isinstance(result, dict) and result.get("error"):
        return result
    rows = [{k: row.get(k) for k in
             ("text", "subject", "subjects", "source", "observed",
              "confidence", "run_id", "predicate")}
            for row in (result or {}).get("facts") or [] if isinstance(row, dict)]
    if EXPOSED_ONLY:
        # A fact about an entity voice cannot see is a read of that entity.
        rows = [r for r in rows
                if all(":" in str(s) or "." not in str(s) or _entity_exposed(s)
                       for s in (r.get("subjects") or [r.get("subject")]) if s)]
    if not rows:
        return {"facts": [], "note": (
            "nothing remembered about that yet. Facts arrive from the "
            "memory inbox — a correction on a finding, a study session, "
            "something said in the chat, the terminal or by voice — and "
            "`remember_fact` queues one.")}
    return {"facts": rows, "note": (
        "`source` says who taught it (a `correction` is the homeowner "
        "saying brAIn had something wrong and wins over an older fact); "
        "`predicate: exception:<check>` means a rule has been told to "
        "stand down for that entity.")}


# What one finding is reported as to a model: the row's own fields, less
# the bookkeeping (undo tokens, snooze stamps, the run id). Named so the
# list is one shape wherever a run reads it.
_FINDING_FIELDS = ("ts", "severity", "text", "detail", "fix", "fix_by",
                   "entity_id", "source_title", "status", "fixable")


def get_findings(status="open", limit=50):
    """What is on the Findings tab, for a run that wants to know what needs
    attention rather than guess.

    Reads the panel's own listing over loopback — `brain findings`' rule:
    one implementation, one answer, and the panel is where the store, the
    triage verdicts and the settled ledger all meet. A panel that is not
    up is reported as such rather than as a house with nothing wrong.
    `held` rows are the ones a look judged not worth showing; they are
    offered on request because "is anything broken" and "what did you
    decide not to tell me" are both fair questions, but the default is
    the list a person sees.
    """
    status = str(status or "open").strip().lower()
    if status not in ("open", "held", "all"):
        return {"error": "status must be open, held or all"}
    try:
        limit = max(1, min(200, int(limit or 50)))
    except (TypeError, ValueError):
        limit = 50
    result = _panel_get("/api/findings")
    if isinstance(result, dict) and result.get("error"):
        return result
    rows = (result or {}).get("findings") or []
    if status == "open":
        rows = [r for r in rows if r.get("status") in
                ("open", "fixing", "fixed", "failed", "needs_you")]
    elif status == "held":
        rows = [r for r in rows if r.get("status") == "held"]
    out = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        item = {k: row.get(k) for k in _FINDING_FIELDS if k in row}
        verdict = row.get("triage") or {}
        if isinstance(verdict, dict) and verdict.get("reason"):
            item["looked"] = verdict.get("reason")
        out.append(item)
    hypotheses = [{"ts": h.get("ts"), "claim": h.get("claim") or h.get("text")}
                  for h in ((result or {}).get("hypotheses") or [])
                  if isinstance(h, dict)]
    return {
        "open": (result or {}).get("open", 0),
        "findings": out,
        # Guesses waiting to be confirmed ride the same tab, because they
        # are the same job: a question only the person living there can
        # answer.
        "hypotheses": hypotheses[:limit],
        "note": ("Nothing here is settled by reading it. If the homeowner "
                 "is discussing one of these with you, offer_resolutions "
                 "is how a decision reaches the card."),
    }


def get_health():
    """Is brAIn working — the verdict the panel, the mirror and the health
    sensor all read, and nothing derived a second time here.

    The whole diagnostics payload is a page of JSON; what a model can act
    on is the verdict with its sentence and switch, the sign-in, the usage
    tracker's last word, and the daemon roll-call. Everything else is the
    report's job (`brain report`).
    """
    result = _panel_get("/api/diagnostics")
    if isinstance(result, dict) and result.get("error"):
        return result
    result = result or {}
    health = result.get("health") or {}
    usage = result.get("usage") or {}
    daemons = result.get("daemons") or {}
    return {
        "state": health.get("state"),
        "reason": health.get("reason"),
        "fix": health.get("fix"),
        "problems": [{k: p.get(k) for k in ("id", "state", "reason", "fix")}
                     for p in (health.get("problems") or [])
                     if isinstance(p, dict)],
        "signed_in": (result.get("auth") or {}).get("state"),
        "usage": {
            "source": usage.get("source"),
            "limits": usage.get("limits") or None,
        },
        "daemons": {name: bool((row or {}).get("running"))
                    for name, row in daemons.items()
                    if isinstance(row, dict)},
        "versions": result.get("versions") or {},
        "faults": [f for f in (result.get("faults") or [])
                   if isinstance(f, dict)][:20],
    }



# ---------------------------------------------------------------------------
# ESPHome — through the panel, which owns the files, the dashboard route and
# the jobs. A second implementation here would be a second answer to "which
# dashboard" and "is this device protected", so every tool is one request.
# ---------------------------------------------------------------------------

def _panel_send(method, path, body=None, timeout=60):
    """A request to the panel that reads the body of a refusal too.

    `_panel_get` reports a 409 as "the panel did not answer", which throws
    away the one sentence that says why — a protected device, a file that
    changed on disk, a dashboard nobody can reach. The panel answers every
    refusal as JSON with an `error`, so that is what comes back here.
    """
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        f"{PANEL_URL}{path}", data=data, method=method,
        headers={"Accept": "application/json",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            answer = json.loads(e.read().decode() or "{}")
            if isinstance(answer, dict):
                answer.setdefault("error", f"HTTP {e.code}")
                return answer
        except Exception:  # noqa: BLE001
            pass
        return {"error": f"the brAIn panel refused: HTTP {e.code}"}
    except Exception as e:  # noqa: BLE001
        return {"error": f"the brAIn panel did not answer: {e}"}


def _esphome_name(configuration):
    name = str(configuration or "").strip()
    if name and not name.endswith((".yaml", ".yml")):
        name += ".yaml"
    return urllib.parse.quote(name, safe="")


def _job_tail(job, lines=120):
    if not isinstance(job, dict):
        return job
    out = dict(job)
    rows = out.get("lines") or []
    if len(rows) > lines:
        out["lines"] = rows[-lines:]
        out["lines_omitted"] = len(rows) - lines
    return out


def _esphome_run(action, configuration, wait_seconds, port=None):
    body = {"port": port} if port else {}
    started = _panel_send(
        "POST", f"/api/esphome/config/{_esphome_name(configuration)}/{action}",
        body, timeout=60)
    job = (started or {}).get("job") if isinstance(started, dict) else None
    if not job or not started.get("ok"):
        return started
    try:
        wait_seconds = max(0, min(int(wait_seconds or 0), 540))
    except (TypeError, ValueError):
        wait_seconds = 0
    if wait_seconds and job.get("state") == "running":
        followed = _panel_get(
            f"/api/esphome/job/{job['id']}?wait={wait_seconds}",
            timeout=wait_seconds + 30)
        if isinstance(followed, dict) and followed.get("job"):
            job = followed["job"]
    result = {"job": _job_tail(job)}
    if job.get("state") == "running":
        result["note"] = (f"Still running — call esphome_job with job_id "
                          f"{job['id']} to follow it.")
    return result


def esphome_list_devices(refresh=False):
    """Every ESPHome device file, what the dashboard knows of it (address,
    deployed and current firmware version, online), which Home Assistant
    device it is, and whether the dashboard can be reached at all."""
    result = _panel_get("/api/esphome" + ("?fresh=1" if refresh else ""))
    if isinstance(result, dict) and result.get("error") and "devices" not in result:
        return result
    result = result or {}
    keep = ("configuration", "name", "friendly_name", "platform", "board",
            "comment", "error", "is_device", "address", "online",
            "deployed_version", "current_version", "update_available",
            "ha_name", "area_id", "entity_count", "update_entity", "protected")
    return {
        "folder": result.get("dir"),
        "dashboard": result.get("dashboard"),
        "devices": [{k: d.get(k) for k in keep if d.get(k) not in (None, "", [])}
                    for d in (result.get("devices") or []) if isinstance(d, dict)],
        "discovered_not_adopted": result.get("importable") or [],
        "secret_keys": result.get("secret_keys") or [],
        "running_jobs": [j for j in (result.get("jobs") or [])
                         if isinstance(j, dict) and j.get("state") == "running"],
    }


def esphome_get_config(configuration):
    """One device's YAML, exactly as it is on disk."""
    if str(configuration or "").strip() in ("secrets.yaml", "secrets"):
        keys = _panel_get("/api/esphome/secrets")
        return {"error": "secrets.yaml is not read out — its values are "
                         "passwords. Its keys are listed here; set one with "
                         "esphome_set_secret.",
                "keys": (keys or {}).get("keys", [])}
    return _panel_send("GET", f"/api/esphome/config/{_esphome_name(configuration)}")


def esphome_write_config(configuration, content, create=False):
    """Save a device's YAML (the old file is snapshotted first, so `brain
    undo` puts it back). Validate afterwards; install to put it on the
    device."""
    return _panel_send(
        "PUT", f"/api/esphome/config/{_esphome_name(configuration)}",
        {"content": content, "create": bool(create)})


def esphome_create_device(name, platform="esp32", board="", friendly_name=""):
    """Start a new device file the way the dashboard's wizard does."""
    return _panel_send("POST", "/api/esphome/create",
                       {"name": name, "platform": platform, "board": board,
                        "friendly_name": friendly_name})


def esphome_delete_device(configuration):
    """Move a device file into the archive folder (not a hard delete)."""
    return _panel_send(
        "POST", f"/api/esphome/config/{_esphome_name(configuration)}/delete", {})


def esphome_validate(configuration, wait_seconds=90):
    """Check a device's YAML the way ESPHome itself does, changing nothing."""
    return _esphome_run("validate", configuration, wait_seconds)


def esphome_compile(configuration, wait_seconds=60):
    """Build a device's firmware without installing it."""
    return _esphome_run("compile", configuration, wait_seconds)


def esphome_install(configuration, target="OTA", wait_seconds=60):
    """Compile and install a device's firmware (over the air by default)."""
    return _esphome_run("install", configuration, wait_seconds, port=target)


def esphome_update_firmware(configuration, wait_seconds=30):
    """Install the waiting firmware update through Home Assistant's own
    update entity — for when the dashboard cannot be reached directly."""
    return _esphome_run("update", configuration, wait_seconds)


def esphome_clean(configuration):
    """Delete a device's build files so the next compile starts clean."""
    return _esphome_run("clean", configuration, 60)


def esphome_logs(configuration, seconds=20):
    """Read a device's live log for a few seconds and stop."""
    try:
        seconds = max(3, min(int(seconds or 20), 120))
    except (TypeError, ValueError):
        seconds = 20
    started = _panel_send(
        "POST", f"/api/esphome/config/{_esphome_name(configuration)}/logs",
        {}, timeout=60)
    job = (started or {}).get("job") if isinstance(started, dict) else None
    if not job or not started.get("ok"):
        return started
    time.sleep(seconds)
    _panel_send("POST", f"/api/esphome/job/{job['id']}/stop", {})
    followed = _panel_get(f"/api/esphome/job/{job['id']}?wait=5", timeout=40)
    return {"job": _job_tail((followed or {}).get("job") or job, lines=200)}


def esphome_job(job_id, since=0):
    """Follow a running or finished ESPHome command by its job id."""
    try:
        since = max(0, int(since or 0))
    except (TypeError, ValueError):
        since = 0
    result = _panel_get(f"/api/esphome/job/{urllib.parse.quote(str(job_id), safe='')}"
                        f"?since={since}")
    if isinstance(result, dict) and result.get("job"):
        return {"job": _job_tail(result["job"], lines=200)}
    return result


def esphome_set_secret(key, value):
    """Set one key in ESPHome's secrets.yaml (the value is never read back)."""
    return _panel_send(
        "PUT", f"/api/esphome/secret/{urllib.parse.quote(str(key or ''), safe='')}",
        {"value": value})


# ---------------------------------------------------------------------------
# Music Assistant — through the panel, which finds the server, signs in with
# Home Assistant's own Music Assistant token (or an admin's), and asks
# protected_entities about every player. One request per tool, the ESPHome
# arrangement, so there is one answer to "which server" and "may brAIn touch
# this player".
# ---------------------------------------------------------------------------

MA_VOICE_REFUSAL = (
    "Music Assistant administration is not available to voice. To play "
    "something, call the music_assistant.play_media service (or a "
    "media_player service) on an exposed media_player entity with "
    "call_service; do not retry this tool."
)


def _ma_path(player_id):
    return urllib.parse.quote(str(player_id or ""), safe="")


def music_assistant_status():
    """The Music Assistant server, its sign-in, every player (with what it is
    playing), the players worth clearing out, and every provider."""
    if EXPOSED_ONLY:
        return {"error": MA_VOICE_REFUSAL}
    return _panel_send("GET", "/api/music-assistant", timeout=90)


def music_assistant_query(command, args=None):
    """Run one read-only Music Assistant API command."""
    if EXPOSED_ONLY:
        return {"error": MA_VOICE_REFUSAL}
    return _panel_send("POST", "/api/music-assistant/command",
                       {"command": command, "args": args or {},
                        "read_only": True}, timeout=150)


def music_assistant_search(query, media_types=None, limit=10):
    """Search Music Assistant's library and every music provider."""
    if EXPOSED_ONLY:
        return {"error": MA_VOICE_REFUSAL}
    try:
        limit = max(1, min(int(limit or 10), 50))
    except (TypeError, ValueError):
        limit = 10
    args = {"search_query": str(query or ""), "limit": limit}
    if media_types:
        args["media_types"] = [str(t) for t in media_types] \
            if isinstance(media_types, list) else [str(media_types)]
    return _panel_send("POST", "/api/music-assistant/command",
                       {"command": "music/search", "args": args,
                        "read_only": True}, timeout=150)


def music_assistant_command(command, args=None):
    """Run any Music Assistant API command (players, queues, library,
    providers, settings)."""
    if EXPOSED_ONLY:
        return {"error": MA_VOICE_REFUSAL}
    return _panel_send("POST", "/api/music-assistant/command",
                       {"command": command, "args": args or {}}, timeout=150)


def music_assistant_player(player_id, action, value=None):
    """One action on one Music Assistant player."""
    if EXPOSED_ONLY:
        return {"error": MA_VOICE_REFUSAL}
    return _panel_send(
        "POST", f"/api/music-assistant/player/{_ma_path(player_id)}/"
                f"{urllib.parse.quote(str(action or ''), safe='')}",
        {"value": value}, timeout=90)


def music_assistant_play(player_id, media, option="", radio_mode=False):
    """Play media on a Music Assistant player."""
    if EXPOSED_ONLY:
        return {"error": MA_VOICE_REFUSAL}
    return _panel_send(
        "POST", f"/api/music-assistant/player/{_ma_path(player_id)}/play",
        {"media": media, "option": option or "", "radio_mode": bool(radio_mode)},
        timeout=90)


def music_assistant_remove_players(player_ids=None, provider="", stale_only=True,
                                   dry_run=True, disable_if_held=False):
    """Forget players Music Assistant should not have any more."""
    if EXPOSED_ONLY:
        return {"error": MA_VOICE_REFUSAL}
    return _panel_send(
        "POST", "/api/music-assistant/players/remove",
        {"player_ids": player_ids or [], "provider": provider or "",
         "stale_only": stale_only is not False, "dry_run": dry_run is not False,
         "disable_if_held": bool(disable_if_held)}, timeout=150)


# ---------------------------------------------------------------------------
# The BRUH add-ons — Minecraft, BRight and BRUH Print — through their own
# Home Assistant integrations' services. Every call goes through
# `call_service`, so an agent's blocked-services list and the deny-list
# apply here exactly as they do to any other service; the services answer
# with response data, which is how a tool reports what the server said
# rather than a bare "done". The add-ons themselves hold the one
# implementation of each action (the Minecraft bridge, BRight's conductor,
# BRUH Print's printer lock); nothing here talks to them another way.
#
# Voice: a voice-level agent (BRAIN_EXPOSED_ONLY=1) may play — teleport,
# give, game mode, time, weather, chat, start a show, print a label — and
# may not administer: op, ban, kick, the whitelist, a raw console command,
# stopping the server or installing add-ons all need an agent set to Whole
# house or Full admin. A misheard sentence that bans a child from the family
# server is the case this is for.
# ---------------------------------------------------------------------------

ADDON_VOICE_REFUSAL = (
    "{what} is an administration action, and this voice agent is set to "
    "'Voice assistant'. Tell the user it needs an agent set to 'Whole house' "
    "or 'Full admin' (Settings → Devices & services → brAIn → the agent → "
    "Configure); do not retry or use call_service to get round it."
)

# The same split, held at the chokepoint: without it a voice agent refused
# `minecraft_player(ban)` could call `bruh_minecraft.ban_player` through
# call_service and get the same result by the side door.
VOICE_ADMIN_SERVICES = frozenset({
    ("bruh_minecraft", s) for s in (
        "rcon_command", "op_player", "deop_player", "kick_player", "ban_player",
        "pardon_player", "whitelist_add", "whitelist_remove", "restart_server",
        "stop_server", "install_addon", "remove_addon")
})

ADDON_NAMES = {
    "bruh_minecraft": ("BRUH Minecraft", "BRUH Minecraft"),
    "bright": ("BRight", "BRight"),
    "bruh_print": ("BRUH Print", "BRUH Print"),
}


def _addon_call(domain, service, data=None):
    """One service call with response data, its failure said in words."""
    result = call_service(domain, service, data or {}, return_response=True)
    if isinstance(result, dict) and result.get("error"):
        text = str(result["error"])
        if "not found" in text.lower() and "service" in text.lower():
            name = ADDON_NAMES.get(domain, (domain,))[0]
            return {"error": (
                f"{name}'s Home Assistant integration is not set up, or is older "
                f"than this action ({domain}.{service}). Tell the user to install "
                f"or update the {name} add-on and add its integration.")}
        return {"error": text}
    response = result.get("response") if isinstance(result, dict) else None
    return response if isinstance(response, dict) else {}


def _voice_admin_refusal(what):
    return {"error": ADDON_VOICE_REFUSAL.format(what=what)} if EXPOSED_ONLY else None


# -- Minecraft ---------------------------------------------------------------

MC_SELECTORS = {"everyone": "@a", "everybody": "@a", "all": "@a", "all players": "@a",
                "@a": "@a", "@p": "@p", "@r": "@r", "@s": "@s",
                "nearest": "@p", "random": "@r"}


def _mc_bare(name):
    """A name as a person would say it: no Bedrock prefix, no case, no spaces."""
    return re.sub(r"[\s_.*]", "", str(name or "")).lower()


def _mc_resolve(name, online):
    """The online player a spoken name means, or (None, why).

    Voice hears "teleport Emma to Dad" and the server knows `.EmmaPlays`
    and `DadCraft42`. Exact (ignoring case and a Bedrock prefix) wins, then
    one online name containing it; two candidates is a question to ask,
    not a guess to make, because teleporting the wrong child is the whole
    failure. With no online list to check against the name goes through
    as given and the server's own reply says whether it knew it.
    """
    raw = str(name or "").strip()
    if not raw:
        return None, "No player was named."
    selector = MC_SELECTORS.get(raw.lower())
    if selector:
        return selector, ""
    if online is None:
        return raw, ""
    want = _mc_bare(raw)
    exact = [p for p in online if _mc_bare(p) == want]
    if len(exact) == 1:
        return exact[0], ""
    partial = [p for p in online if want and want in _mc_bare(p)]
    if len(partial) == 1:
        return partial[0], ""
    who = ", ".join(online) if online else "nobody"
    if len(partial) > 1:
        return None, (f"'{raw}' could be any of {', '.join(partial)} — ask which "
                      "one they meant.")
    return None, f"No player called '{raw}' is online. Online now: {who}."


def _mc_online():
    status = _addon_call("bruh_minecraft", "get_status")
    if status.get("error") or not status.get("reachable", True):
        return None
    return [str(p) for p in status.get("players") or []]


def minecraft_status():
    """Who is on the Minecraft server, and how it is doing."""
    status = _addon_call("bruh_minecraft", "get_status")
    if status.get("error"):
        return status
    stats = status.get("stats") or {}
    state = status.get("state") or {}
    return {
        "reachable": status.get("reachable"),
        "online": status.get("online"),
        "max": status.get("max"),
        "players": status.get("players") or [],
        "world": state.get("active_world") or state.get("world"),
        "server_type": state.get("server_type") or stats.get("server_type"),
        "version": stats.get("version"),
        "tps": stats.get("tps_1m"),
        "note": status.get("note", ""),
    }


def minecraft_teleport(player, to_player=None, x=None, y=None, z=None):
    """Move a player to another player, or to coordinates."""
    online = _mc_online()
    who, why = _mc_resolve(player, online)
    if who is None:
        return {"error": why}
    data = {"player": who}
    if to_player:
        target, why = _mc_resolve(to_player, online)
        if target is None:
            return {"error": why}
        data["to_player"] = target
    else:
        for key, value in (("x", x), ("y", y), ("z", z)):
            if value is not None and str(value).strip() != "":
                data[key] = str(value)
    result = _addon_call("bruh_minecraft", "teleport", data)
    if result.get("error"):
        return result
    return {"done": True, **data, "server_reply": result.get("reply", "")}


MC_ADMIN_ACTIONS = {"op": "op_player", "deop": "deop_player", "kick": "kick_player",
                    "ban": "ban_player", "pardon": "pardon_player",
                    "whitelist_add": "whitelist_add",
                    "whitelist_remove": "whitelist_remove"}


def minecraft_player(player, action, value=None, amount=None):
    """One thing done to one player: a game mode, an item, or an admin action."""
    action = str(action or "").strip().lower()
    if action in MC_ADMIN_ACTIONS:
        refusal = _voice_admin_refusal(f"Minecraft '{action}'")
        if refusal:
            return refusal
    # An admin action on somebody offline is ordinary (whitelisting a friend
    # before they join); only resolve against who is on when that is the
    # only sensible reading.
    needs_online = action in ("gamemode", "give", "kick")
    who, why = _mc_resolve(player, _mc_online() if needs_online else None)
    if who is None:
        return {"error": why}
    if action == "gamemode":
        mode = str(value or "").strip().lower()
        if mode not in ("survival", "creative", "adventure", "spectator"):
            return {"error": "Game mode must be survival, creative, adventure or spectator."}
        result = _addon_call("bruh_minecraft", "set_gamemode", {"player": who, "gamemode": mode})
    elif action == "give":
        item = str(value or "").strip().lower().replace(" ", "_")
        if not item:
            return {"error": "Name the item to give, e.g. diamond or minecraft:oak_log."}
        data = {"player": who, "item": item if ":" in item else f"minecraft:{item}"}
        if amount:
            try:
                data["amount"] = max(1, min(int(amount), 64))
            except (TypeError, ValueError):  # an unreadable amount gives the default one
                pass
        result = _addon_call("bruh_minecraft", "give", data)
    elif action in MC_ADMIN_ACTIONS:
        result = _addon_call("bruh_minecraft", MC_ADMIN_ACTIONS[action], {"player": who})
    else:
        return {"error": ("Unknown action. Use gamemode, give, op, deop, kick, ban, "
                          "pardon, whitelist_add or whitelist_remove.")}
    if result.get("error"):
        return result
    return {"done": True, "player": who, "action": action,
            "server_reply": result.get("reply", "")}


def minecraft_world(action, value=None):
    """The world everyone is in: time of day, weather, or a chat message."""
    action = str(action or "").strip().lower()
    value = "" if value is None else str(value).strip()
    if action == "time":
        spoken = {"morning": "day", "sunrise": "day", "evening": "night",
                  "sunset": "night", "dusk": "night", "dawn": "day"}
        value = spoken.get(value.lower(), value.lower())
        result = _addon_call("bruh_minecraft", "set_time", {"time": value})
    elif action == "weather":
        spoken = {"sunny": "clear", "sun": "clear", "storm": "thunder",
                  "thunderstorm": "thunder", "raining": "rain"}
        result = _addon_call("bruh_minecraft", "set_weather",
                             {"weather": spoken.get(value.lower(), value.lower())})
    elif action == "say":
        if not value:
            return {"error": "Nothing to say."}
        result = _addon_call("bruh_minecraft", "say", {"message": value[:256]})
    else:
        return {"error": "Use time (day/night/noon/midnight or ticks), weather (clear/rain/thunder) or say."}
    if result.get("error"):
        return result
    return {"done": True, "action": action, "value": value,
            "server_reply": result.get("reply", "")}


def minecraft_command(command):
    """Any server console command, and what the server replied."""
    refusal = _voice_admin_refusal("A raw Minecraft console command")
    if refusal:
        return refusal
    command = str(command or "").strip().lstrip("/")
    if not command:
        return {"error": "No command given."}
    result = _addon_call("bruh_minecraft", "rcon_command", {"command": command})
    if result.get("error"):
        return result
    return {"command": command, "server_reply": result.get("reply", "")}


def minecraft_server(action):
    """Back up, restart or stop the Minecraft server."""
    action = str(action or "").strip().lower()
    service = {"backup": "backup_now", "restart": "restart_server",
               "stop": "stop_server"}.get(action)
    if not service:
        return {"error": "Use backup, restart or stop."}
    refusal = _voice_admin_refusal(f"Minecraft server {action}")
    if refusal:
        return refusal
    result = _addon_call("bruh_minecraft", service)
    if result.get("error"):
        return result
    return {"done": True, "action": action, **({"output": result["output"]}
                                               if result.get("output") else {})}


def minecraft_addons(action, query="", kind="", project_id=""):
    """The Minecraft add-on browser: list, search, install or remove."""
    action = str(action or "").strip().lower()
    if action == "list":
        return _addon_call("bruh_minecraft", "list_addons")
    if action == "search":
        data = {"query": str(query or "")}
        if kind:
            data["kind"] = str(kind)
        return _addon_call("bruh_minecraft", "search_addons", data)
    if action in ("install", "remove"):
        refusal = _voice_admin_refusal(f"Installing or removing a Minecraft add-on ({action})")
        if refusal:
            return refusal
        if not project_id:
            return {"error": "Give the project_id from a search."}
        if action == "install":
            if not kind:
                return {"error": "Give the kind (plugin, datapack, mod or resourcepack) from the search."}
            return _addon_call("bruh_minecraft", "install_addon",
                               {"id": str(project_id), "kind": str(kind)})
        return _addon_call("bruh_minecraft", "remove_addon", {"id": str(project_id)})
    return {"error": "Use list, search, install or remove."}


# -- BRUH Print --------------------------------------------------------------

PRINT_VOICE_MAX_COPIES = 10


def label_printer_status():
    """What is loaded in the label printer and which templates exist."""
    return _addon_call("bruh_print", "get_status")


def print_label(text="", template="", fields=None, stock="", copies=1):
    """Print a label: text fitted as large as it will go, or a saved template."""
    try:
        copies = max(1, int(copies or 1))
    except (TypeError, ValueError):
        copies = 1
    if EXPOSED_ONLY and copies > PRINT_VOICE_MAX_COPIES:
        return {"error": (f"Voice prints at most {PRINT_VOICE_MAX_COPIES} copies at once — "
                          "a misheard 'two hundred' is a roll of labels. Ask the user to "
                          "confirm a smaller number.")}
    copies = min(copies, 500)
    if template:
        data = {"template": str(template), "copies": copies}
        if isinstance(fields, dict) and fields:
            data["fields"] = {str(k): str(v) for k, v in fields.items()}
        result = _addon_call("bruh_print", "print_template", data)
    elif str(text or "").strip():
        data = {"text": str(text).strip(), "copies": copies}
        if stock:
            data["stock"] = str(stock)
        result = _addon_call("bruh_print", "print_text", data)
    else:
        return {"error": "Give the text to print, or a template name from label_printer_status."}
    if result.get("error"):
        return result
    return {"printed": result.get("printed", 0), "roll": result.get("side", ""),
            "notes": result.get("notes") or []}


# -- BRight -------------------------------------------------------------------

def bright_status():
    """What BRight is doing, its saved sets, and the tracks with a show."""
    return _addon_call("bright", "get_status")


def _entity_arg_refusal(entity_id):
    """An entity named in a field other than entity_id still has to be allowed."""
    if not entity_id:
        return None
    if _entity_protected(entity_id):
        return {"error": f"{entity_id} is on brAIn's protected list; nothing brAIn does may act on it."}
    if not _entity_exposed(entity_id):
        return {"error": UNEXPOSED_READ.format(eid=entity_id)}
    return None


def bright_show(action, party="", track="", media_player="", scene=""):
    """Start a saved set, play one track's show, run party mode, or stop."""
    action = str(action or "").strip().lower()
    for eid in (media_player, scene):
        refusal = _entity_arg_refusal(str(eid or "").strip())
        if refusal:
            return refusal
    data = {}
    if media_player:
        data["media_player"] = str(media_player)
    if action == "stop":
        if scene:
            data = {"scene": str(scene)}
        else:
            data = {}
        result = _addon_call("bright", "stop_show", data)
    elif action == "party":
        if party:
            data["party"] = str(party)
            if scene:
                data["end_scene"] = str(scene)
            result = _addon_call("bright", "start_party", data)
        else:
            if scene:
                data["end_scene"] = str(scene)
            result = _addon_call("bright", "party_mode", data)
    elif action == "track":
        if not track:
            return {"error": "Give the track's file path from bright_status."}
        data["track"] = str(track)
        result = _addon_call("bright", "start_show", data)
    else:
        return {"error": "Use party (with a saved set's name, or none for party mode), track, or stop."}
    if isinstance(result, dict) and result.get("error"):
        return result
    return {"done": True, "action": action}


def get_activity(hours=24, cause=None, limit=200):
    """What changed in the house recently, with a cause on every row.

    Answers "what happened last night" and "what has brAIn been doing"
    without a single guess: every row names what caused it, or says
    plainly that nothing did.
    """
    try:
        hours = max(1, float(hours or 24))
    except (TypeError, ValueError):
        hours = 24
    try:
        limit = max(1, min(1000, int(limit or 200)))
    except (TypeError, ValueError):
        limit = 200
    path = f"/api/activity?hours={hours}&limit={limit}"
    if cause:
        path += f"&cause={urllib.parse.quote(str(cause), safe='')}"
    result = _panel_get(path)
    if isinstance(result, dict) and result.get("error"):
        return result
    if isinstance(result, dict) and not result.get("available"):
        return {"error": (
            "Home Assistant's logbook could not be read. The logbook "
            "integration may not be set up."
        )}
    return {
        "hours": _window(result),
        "counts": (result or {}).get("counts") or {},
        "total": (result or {}).get("total", 0),
        "overrides": (result or {}).get("overrides") or [],
        "actions": (result or {}).get("actions") or [],
    }


def get_service_details(domain, service=None):
    """Get detailed service schemas for a domain, or one service of it.

    Some domains (e.g. brain) expose dozens of services whose
    combined schemas run to tens of KB — the optional service filter
    returns just the one schema instead of the whole domain dump.
    """
    result = ha_api_request("/api/services")
    if isinstance(result, list):
        for svc in result:
            if svc.get("domain") == domain:
                if service:
                    services = svc.get("services", {})
                    if service in services:
                        return {"domain": domain, "service": service,
                                "details": services[service]}
                    return {"error": (f"Service '{service}' not found in "
                                      f"domain '{domain}'. Available: "
                                      f"{', '.join(sorted(services))}")}
                return svc
        return {"error": f"Domain '{domain}' not found"}
    return result


# ============================================================================
# MCP Tool Implementations — Domain-Specific Device Control
# ============================================================================

def control_light(entity_id, action, brightness=None, brightness_pct=None,
                  rgb_color=None, hs_color=None, xy_color=None, color_temp_kelvin=None,
                  color_name=None, effect=None, transition=None, flash=None,
                  white=None):
    """Control a light entity."""
    if action == "turn_off":
        data = {"entity_id": entity_id}
        if transition is not None:
            data["transition"] = transition
        return call_service("light", "turn_off", data)

    if action == "toggle":
        return call_service("light", "toggle", {"entity_id": entity_id})

    # turn_on
    data = {"entity_id": entity_id}
    if brightness is not None:
        data["brightness"] = brightness
    if brightness_pct is not None:
        data["brightness_pct"] = brightness_pct
    if rgb_color is not None:
        data["rgb_color"] = rgb_color
    if hs_color is not None:
        data["hs_color"] = hs_color
    if xy_color is not None:
        data["xy_color"] = xy_color
    if color_temp_kelvin is not None:
        data["color_temp_kelvin"] = color_temp_kelvin
    if color_name is not None:
        data["color_name"] = color_name
    if effect is not None:
        data["effect"] = effect
    if transition is not None:
        data["transition"] = transition
    if flash is not None:
        data["flash"] = flash
    if white is not None:
        data["white"] = white
    return call_service("light", "turn_on", data)


def control_climate(entity_id, action, temperature=None, target_temp_high=None,
                    target_temp_low=None, hvac_mode=None, fan_mode=None,
                    preset_mode=None, humidity=None, swing_mode=None):
    """Control a climate entity."""
    if action == "turn_off":
        return call_service("climate", "turn_off", {"entity_id": entity_id})
    if action == "turn_on":
        return call_service("climate", "turn_on", {"entity_id": entity_id})

    if action == "set_hvac_mode" and hvac_mode:
        return call_service("climate", "set_hvac_mode", {
            "entity_id": entity_id, "hvac_mode": hvac_mode
        })

    if action == "set_fan_mode" and fan_mode:
        return call_service("climate", "set_fan_mode", {
            "entity_id": entity_id, "fan_mode": fan_mode
        })

    if action == "set_preset_mode" and preset_mode:
        return call_service("climate", "set_preset_mode", {
            "entity_id": entity_id, "preset_mode": preset_mode
        })

    if action == "set_humidity" and humidity is not None:
        return call_service("climate", "set_humidity", {
            "entity_id": entity_id, "humidity": humidity
        })

    if action == "set_swing_mode" and swing_mode:
        return call_service("climate", "set_swing_mode", {
            "entity_id": entity_id, "swing_mode": swing_mode
        })

    # Default: set_temperature
    data = {"entity_id": entity_id}
    if temperature is not None:
        data["temperature"] = temperature
    if target_temp_high is not None:
        data["target_temp_high"] = target_temp_high
    if target_temp_low is not None:
        data["target_temp_low"] = target_temp_low
    if hvac_mode:
        data["hvac_mode"] = hvac_mode
    return call_service("climate", "set_temperature", data)


def control_media_player(entity_id, action, volume_level=None, source=None,
                         media_content_id=None, media_content_type=None,
                         seek_position=None, shuffle=None, repeat=None):
    """Control a media player entity."""
    action_map = {
        "turn_on": "turn_on",
        "turn_off": "turn_off",
        "toggle": "toggle",
        "play": "media_play",
        "pause": "media_pause",
        "stop": "media_stop",
        "play_pause": "media_play_pause",
        "next": "media_next_track",
        "previous": "media_previous_track",
        "volume_up": "volume_up",
        "volume_down": "volume_down",
        "volume_mute": "volume_mute",
        "clear_playlist": "clear_playlist",
    }

    # Simple actions
    if action in action_map:
        data = {"entity_id": entity_id}
        if action == "volume_mute":
            data["is_volume_muted"] = True
        return call_service("media_player", action_map[action], data)

    if action == "volume_unmute":
        return call_service("media_player", "volume_mute", {
            "entity_id": entity_id, "is_volume_muted": False
        })

    if action == "set_volume" and volume_level is not None:
        return call_service("media_player", "volume_set", {
            "entity_id": entity_id, "volume_level": volume_level
        })

    if action == "select_source" and source:
        return call_service("media_player", "select_source", {
            "entity_id": entity_id, "source": source
        })

    if action == "play_media" and media_content_id:
        data = {
            "entity_id": entity_id,
            "media_content_id": media_content_id,
            "media_content_type": media_content_type or "music",
        }
        return call_service("media_player", "play_media", data)

    if action == "seek" and seek_position is not None:
        return call_service("media_player", "media_seek", {
            "entity_id": entity_id, "seek_position": seek_position
        })

    if action == "set_shuffle" and shuffle is not None:
        return call_service("media_player", "shuffle_set", {
            "entity_id": entity_id, "shuffle": shuffle
        })

    if action == "set_repeat" and repeat:
        return call_service("media_player", "repeat_set", {
            "entity_id": entity_id, "repeat": repeat
        })

    return {"error": f"Unknown media_player action: {action}"}


def control_cover(entity_id, action, position=None, tilt_position=None):
    """Control a cover entity."""
    if action == "open":
        return call_service("cover", "open_cover", {"entity_id": entity_id})
    if action == "close":
        return call_service("cover", "close_cover", {"entity_id": entity_id})
    if action == "stop":
        return call_service("cover", "stop_cover", {"entity_id": entity_id})
    if action == "toggle":
        return call_service("cover", "toggle", {"entity_id": entity_id})
    if action == "set_position" and position is not None:
        return call_service("cover", "set_cover_position", {
            "entity_id": entity_id, "position": position
        })
    if action == "set_tilt" and tilt_position is not None:
        return call_service("cover", "set_cover_tilt_position", {
            "entity_id": entity_id, "tilt_position": tilt_position
        })
    return {"error": f"Unknown cover action: {action}"}


def control_fan(entity_id, action, percentage=None, preset_mode=None,
                direction=None, oscillating=None):
    """Control a fan entity."""
    if action == "turn_on":
        data = {"entity_id": entity_id}
        if percentage is not None:
            data["percentage"] = percentage
        if preset_mode:
            data["preset_mode"] = preset_mode
        return call_service("fan", "turn_on", data)
    if action == "turn_off":
        return call_service("fan", "turn_off", {"entity_id": entity_id})
    if action == "toggle":
        return call_service("fan", "toggle", {"entity_id": entity_id})
    if action == "set_percentage" and percentage is not None:
        return call_service("fan", "set_percentage", {
            "entity_id": entity_id, "percentage": percentage
        })
    if action == "set_preset_mode" and preset_mode:
        return call_service("fan", "set_preset_mode", {
            "entity_id": entity_id, "preset_mode": preset_mode
        })
    if action == "set_direction" and direction:
        return call_service("fan", "set_direction", {
            "entity_id": entity_id, "direction": direction
        })
    if action == "oscillate" and oscillating is not None:
        return call_service("fan", "oscillate", {
            "entity_id": entity_id, "oscillating": oscillating
        })
    return {"error": f"Unknown fan action: {action}"}


def control_switch(entity_id, action):
    """Control a switch, input_boolean, or similar toggle entity."""
    domain = entity_id.split(".")[0] if "." in entity_id else "switch"
    if action == "turn_on":
        return call_service(domain, "turn_on", {"entity_id": entity_id})
    if action == "turn_off":
        return call_service(domain, "turn_off", {"entity_id": entity_id})
    if action == "toggle":
        return call_service(domain, "toggle", {"entity_id": entity_id})
    return {"error": f"Unknown switch action: {action}"}


def control_lock(entity_id, action, code=None):
    """Control a lock entity."""
    data = {"entity_id": entity_id}
    if code:
        data["code"] = code
    if action == "lock":
        return call_service("lock", "lock", data)
    if action == "unlock":
        return call_service("lock", "unlock", data)
    if action == "open":
        return call_service("lock", "open", data)
    return {"error": f"Unknown lock action: {action}"}


def control_alarm(entity_id, action, code=None):
    """Control an alarm panel entity."""
    data = {"entity_id": entity_id}
    if code:
        data["code"] = code
    action_map = {
        "arm_away": "alarm_arm_away",
        "arm_home": "alarm_arm_home",
        "arm_night": "alarm_arm_night",
        "arm_vacation": "alarm_arm_vacation",
        "arm_custom": "alarm_arm_custom_bypass",
        "disarm": "alarm_disarm",
        "trigger": "alarm_trigger",
    }
    svc = action_map.get(action)
    if svc:
        return call_service("alarm_control_panel", svc, data)
    return {"error": f"Unknown alarm action: {action}"}


def control_vacuum(entity_id, action, command=None, params=None):
    """Control a vacuum entity."""
    simple_actions = {
        "start": "start",
        "stop": "stop",
        "pause": "pause",
        "return_home": "return_to_base",
        "locate": "locate",
        "clean_spot": "clean_spot",
    }
    svc = simple_actions.get(action)
    if svc:
        return call_service("vacuum", svc, {"entity_id": entity_id})
    if action == "send_command" and command:
        data = {"entity_id": entity_id, "command": command}
        if params:
            data["params"] = params
        return call_service("vacuum", "send_command", data)
    if action == "set_fan_speed" and command:
        return call_service("vacuum", "set_fan_speed", {
            "entity_id": entity_id, "fan_speed": command
        })
    return {"error": f"Unknown vacuum action: {action}"}


def send_notification(message, title=None, target=None, data=None):
    """Send a notification through Home Assistant."""
    payload = {"message": message}
    if title:
        payload["title"] = title
    if data:
        payload["data"] = data

    if target:
        # target = "mobile_app_phone" -> notify.mobile_app_phone
        return call_service("notify", target, payload)

    # Default: persistent notification
    if title:
        payload["notification_id"] = title.lower().replace(" ", "_")
    return call_service("persistent_notification", "create", payload)


def activate_scene(entity_id, transition=None):
    """Activate a scene."""
    data = {"entity_id": entity_id}
    if transition is not None:
        data["transition"] = transition
    return call_service("scene", "turn_on", data)


def run_script(entity_id, variables=None):
    """Run a script with optional variables."""
    data = {"entity_id": entity_id}
    if variables:
        data["variables"] = variables
    return call_service("script", "turn_on", data)


# ============================================================================
# MCP Tool Implementations — Vision
# ============================================================================

# Snapshots above this size are rejected even after downscaling — a huge
# image would blow the model's context for no benefit.
MAX_SNAPSHOT_B64 = 1_500_000


def _downscale_jpeg(data, max_dim):
    """Downscale image bytes to max_dim and re-encode as JPEG.

    Returns the original bytes when Pillow is unavailable or the image is
    already small enough.
    """
    if not _PIL_AVAILABLE:
        return data, "original (Pillow unavailable)"
    try:
        img = Image.open(io.BytesIO(data))
        if max(img.size) > max_dim:
            img.thumbnail((max_dim, max_dim))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=70)
        return out.getvalue(), f"{img.size[0]}x{img.size[1]} jpeg"
    except Exception:  # noqa: BLE001 — fall back to the original bytes
        return data, "original (downscale failed)"


def get_camera_snapshot(entity_id, max_dim=1024):
    """Fetch a camera snapshot and return it as an MCP image."""
    if not entity_id.startswith("camera."):
        return {"error": f"Not a camera entity: {entity_id}"}
    try:
        max_dim = max(256, min(int(max_dim), 1920))
    except (TypeError, ValueError):
        max_dim = 1024
    try:
        raw = ha_api_request_raw(f"/api/camera_proxy/{entity_id}")
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.reason} (is the camera available?)"}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}
    if not raw:
        return {"error": f"Camera {entity_id} returned no image data"}

    scaled, detail = _downscale_jpeg(raw, max_dim)
    encoded = base64.b64encode(scaled).decode()
    if len(encoded) > MAX_SNAPSHOT_B64:
        return {
            "error": (
                f"Snapshot too large ({len(encoded)} b64 bytes) even after "
                f"downscaling — retry with a smaller max_dim."
            )
        }
    return {
        "_mcp_image": {"data": encoded, "mimeType": "image/jpeg"},
        "entity_id": entity_id,
        "image": detail,
    }


# ============================================================================
# MCP Tool Implementations — System
# ============================================================================

def get_automations():
    """List all automations with their states."""
    states = ha_api_request("/api/states")
    if isinstance(states, list):
        automations = [s for s in states if s.get("entity_id", "").startswith("automation.")]
        return [
            {
                "entity_id": a.get("entity_id"),
                "state": a.get("state"),
                "friendly_name": a.get("attributes", {}).get("friendly_name", ""),
                "last_triggered": a.get("attributes", {}).get("last_triggered"),
            }
            for a in automations
        ]
    return states


# Cap on the stored-trace payload: one trace of a complex automation can
# carry every step's changed variables and dwarf the rest of the response.
MAX_TRACE_BYTES = 60_000


def get_automation_trace(automation_id):
    """Get recent traces for an automation.

    The trace API is WebSocket-only (no REST endpoint).  This function
    combines the automation's entity state (last_triggered, mode, etc.)
    with stored trace data read from HA's .storage directory.
    """
    # Normalise entity_id
    entity_id = automation_id
    if not entity_id.startswith("automation."):
        entity_id = f"automation.{entity_id}"

    output = {}

    # 1. Always-available: entity state from REST API
    state = ha_api_request(f"/api/states/{entity_id}")
    if isinstance(state, dict) and "error" not in state:
        attrs = state.get("attributes", {})
        output["entity_id"] = state.get("entity_id", entity_id)
        output["state"] = state.get("state")
        output["last_triggered"] = attrs.get("last_triggered")
        output["last_changed"] = state.get("last_changed")
        output["mode"] = attrs.get("mode")
        output["current"] = attrs.get("current", 0)
        output["friendly_name"] = attrs.get("friendly_name")
    else:
        output["entity_state_error"] = state

    # 2. Try reading stored traces from disk (HA saves them in .storage)
    traces = _read_stored_traces(automation_id, entity_id)
    if traces:
        # Stored traces can be arbitrarily large (every step's changed
        # variables) — cap the payload like the other listing tools do.
        while (len(traces) > 1
               and len(json.dumps(traces, default=str)) > MAX_TRACE_BYTES):
            traces = traces[1:]  # drop oldest first
        if len(json.dumps(traces, default=str)) > MAX_TRACE_BYTES:
            newest = traces[-1]
            traces = [{
                k: newest.get(k)
                for k in ("run_id", "state", "script_execution", "timestamp",
                          "error", "last_step")
                if isinstance(newest, dict) and newest.get(k) is not None
            }]
            output["traces_note"] = (
                "Trace detail truncated (payload too large) — summary of the "
                "most recent run only. Full traces: Settings > Automations > "
                "(automation) > Traces in the HA UI."
            )
        output["traces"] = traces
    else:
        output["traces_note"] = (
            "No stored traces found on disk. Traces are available in the "
            "HA UI under Settings > Automations > (select automation) > Traces."
        )

    return output


def _read_stored_traces(automation_id, entity_id):
    """Read stored automation traces from HA's .storage directory."""
    import os
    storage_path = "/config/.storage/trace.saved_traces"
    if not os.path.isfile(storage_path):
        return None
    try:
        with open(storage_path) as fh:
            store = json.load(fh)
        data = store.get("data", {})

        # Try both the entity_id and the bare automation id as keys
        traces = data.get(entity_id)
        if traces is None:
            traces = data.get(automation_id)
        if traces is None:
            # HA may nest under domain key: data.automation.{id}
            auto_data = data.get("automation", {})
            bare_id = entity_id.replace("automation.", "", 1)
            traces = auto_data.get(entity_id) or auto_data.get(bare_id)

        if not traces:
            return None

        # Return the most recent traces (limit to 5)
        if isinstance(traces, list):
            return traces[-5:]
        if isinstance(traces, dict):
            # Some versions store as dict keyed by run_id
            items = sorted(traces.values(), key=lambda t: t.get("timestamp", {}).get("start", ""), reverse=True)
            return items[:5]
        return traces
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return None


def get_config():
    """Get Home Assistant configuration."""
    return ha_api_request("/api/config")


def get_services():
    """Get all available services."""
    result = ha_api_request("/api/services")
    if isinstance(result, list):
        summary = []
        for svc in result:
            domain = svc.get("domain", "")
            services = list(svc.get("services", {}).keys())
            summary.append({"domain": domain, "services": services})
        return summary
    return result


def get_device_registry():
    """Get device registry summary from entity states."""
    states = ha_api_request("/api/states")
    if isinstance(states, list):
        domains = {}
        for s in states:
            eid = s.get("entity_id", "")
            domain = eid.split(".")[0] if "." in eid else "unknown"
            if domain not in domains:
                domains[domain] = 0
            domains[domain] += 1
        return {
            "total_entities": len(states),
            "domains": domains,
        }
    return {"error": "Could not retrieve device information"}


def get_logbook(hours=1, entity_id=None):
    """Get logbook entries."""
    from datetime import datetime, timedelta, timezone
    try:
        hours = max(0.1, min(float(hours or 1), 24))  # Clamp between 0.1 and 24
    except (TypeError, ValueError):
        hours = 1
    start = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    endpoint = f"/api/logbook/{start}"
    if entity_id:
        endpoint += f"?entity={entity_id}"
    result = ha_api_request(endpoint)
    if isinstance(result, list):
        return result[:50]  # Limit to 50 entries
    return result


def get_history(entity_id, hours=24):
    """Get recent state history for one entity (recorder, detailed)."""
    from datetime import datetime, timedelta, timezone
    if not _entity_exposed(entity_id):
        return {"error": UNEXPOSED_READ.format(eid=entity_id)}
    try:
        hours = max(1, min(int(hours), 168))
    except (TypeError, ValueError):
        hours = 24
    start = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    result = ha_api_request(
        f"/api/history/period/{start}"
        f"?filter_entity_id={entity_id}&minimal_response&no_attributes"
    )
    if isinstance(result, dict) and "error" in result:
        return result
    if not isinstance(result, list) or not result or not result[0]:
        return {"entity_id": entity_id, "hours": hours, "changes": [],
                "note": "No recorded history in this window."}

    points = [
        {"state": p.get("state"), "at": p.get("last_changed") or p.get("last_updated")}
        for p in result[0]
    ]
    summary = {"entity_id": entity_id, "hours": hours, "change_count": len(points)}

    numeric = []
    for p in points:
        try:
            numeric.append(float(p["state"]))
        except (TypeError, ValueError):
            # "unavailable" and "unknown" are states, not readings. The summary is
            # built from the points that are numbers.
            pass
    if numeric:
        summary["min"] = min(numeric)
        summary["max"] = max(numeric)
        summary["first"] = points[0]["state"]
        summary["last"] = points[-1]["state"]

    # Downsample long histories so the tool result stays small
    if len(points) > 100:
        step = len(points) // 100 + 1
        sampled = points[::step]
        if sampled[-1] is not points[-1]:
            sampled.append(points[-1])
        points = sampled
        summary["note"] = "Changes downsampled; min/max cover the full window."
    summary["changes"] = points
    return summary


def get_statistics(entity_id, period="hour", days=7):
    """Get long-term statistics (mean/min/max) via the WebSocket API.

    Long-term statistics survive recorder purging, so this answers
    questions like 'how cold did it get last week' that get_history can't.
    """
    from datetime import datetime, timedelta, timezone
    if not _entity_exposed(entity_id):
        return {"error": UNEXPOSED_READ.format(eid=entity_id)}
    if period not in ("5minute", "hour", "day", "week", "month"):
        period = "hour"
    try:
        days = max(1, min(int(days), 365))
    except (TypeError, ValueError):
        days = 7
    start = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        # Statistics queries are among the slowest recorder operations —
        # give them more headroom than the default WS timeout.
        result = _ws_command({
            "type": "recorder/statistics_during_period",
            "start_time": start,
            "statistic_ids": [entity_id],
            "period": period,
        }, timeout=30)
    except ImportError:
        return {"error": "websockets package not available in this environment"}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}

    if isinstance(result, dict) and "error" in result:
        return result
    rows = (result or {}).get(entity_id, [])
    if not rows:
        return {
            "entity_id": entity_id, "period": period, "days": days, "stats": [],
            "note": ("No long-term statistics for this entity. Statistics exist "
                     "only for numeric sensors with state_class set."),
        }
    # The WebSocket API returns start/end as epoch-milliseconds; every other
    # tool speaks ISO 8601, and brain.import_statistics requires ISO
    # for start — convert so rows can round-trip without manual conversion.
    def _iso(value):
        if isinstance(value, (int, float)):
            try:
                return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat()
            except (OverflowError, OSError, ValueError):
                return value
        return value

    stats = [
        {k: (_iso(r.get(k)) if k == "start" else r.get(k))
         for k in ("start", "mean", "min", "max", "sum") if r.get(k) is not None}
        for r in rows
    ]
    if len(stats) > 200:
        stats = stats[-200:]
    return {"entity_id": entity_id, "period": period, "days": days, "stats": stats}


def get_weather_forecast(entity_id, forecast_type="daily"):
    """Get a weather forecast via weather.get_forecasts (WebSocket).

    Modern HA removed the `forecast` attribute from weather entities; the
    only reliable source is the get_forecasts service WITH response data,
    which the REST API can't return — hence the WebSocket call.
    """
    if not entity_id.startswith("weather."):
        return {"error": f"Not a weather entity: {entity_id}"}

    # Entities support only a subset of forecast types, and HA hard-errors
    # on an unsupported one (e.g. an hourly-only entity asked for daily —
    # the default). Try the requested type first, then fall back to the
    # others so a bare get_weather_forecast(entity) always returns whatever
    # the entity CAN provide.
    if forecast_type in ("daily", "hourly", "twice_daily"):
        types_to_try = [forecast_type]
    else:
        types_to_try = []
    for candidate in ("daily", "hourly", "twice_daily"):
        if candidate not in types_to_try:
            types_to_try.append(candidate)

    failures = {}
    for ftype in types_to_try:
        try:
            result = _ws_command({
                "type": "call_service",
                "domain": "weather",
                "service": "get_forecasts",
                "target": {"entity_id": entity_id},
                "service_data": {"type": ftype},
                "return_response": True,
            })
        except ImportError:
            return {"error": "websockets package not available in this environment"}
        except Exception as e:  # noqa: BLE001
            failures[ftype] = str(e)
            continue
        if isinstance(result, dict) and "error" in result:
            failures[ftype] = str(result.get("error"))
            continue

        response = (result or {}).get("response") or {}
        forecast = (response.get(entity_id) or {}).get("forecast") or []
        if not forecast:
            failures[ftype] = "no forecast returned"
            continue

        keep = ("datetime", "condition", "temperature", "templow",
                "precipitation", "precipitation_probability", "humidity",
                "wind_speed")
        trimmed = [
            {k: item.get(k) for k in keep if item.get(k) is not None}
            for item in forecast[:24]
        ]
        payload = {"entity_id": entity_id, "type": ftype, "forecast": trimmed}
        if ftype != types_to_try[0]:
            payload["note"] = (
                f"The entity does not support a {types_to_try[0]} forecast — "
                f"returning its {ftype} forecast instead."
            )
        return payload

    # Nothing worked. If a real error occurred (auth/transport/service),
    # surface it as an error; only report "no forecast" when every type
    # genuinely came back empty.
    ws_errors = {t: msg for t, msg in failures.items() if msg != "no forecast returned"}
    if ws_errors:
        return {
            "entity_id": entity_id,
            "error": next(iter(ws_errors.values())),
            "tried": failures,
        }
    return {
        "entity_id": entity_id, "forecast": [],
        "note": "No forecast available from this entity for any forecast type.",
        "tried": failures,
    }


# Line count alone doesn't bound the payload — tracebacks with huge single
# lines (template errors embedding full configs) still need a byte cap.
MAX_ERROR_LOG_BYTES = 50_000


def get_error_log():
    """Get the Home Assistant error log.

    Uses the Supervisor /core/logs endpoint which reads from the systemd
    journal.  This works reliably on HA 2025.11+ where the traditional
    home-assistant.log file was removed on supervised installations.
    Falls back to the legacy /api/error_log REST endpoint for
    non-supervised setups.
    """
    # Primary: Supervisor journal logs (works on HAOS / Supervised)
    result = ha_api_request("/core/logs", accept="text/plain")
    if isinstance(result, str) and result.strip():
        lines = result.strip().split("\n")
        return "\n".join(lines[-100:])[-MAX_ERROR_LOG_BYTES:]

    # Fallback: legacy HA Core REST endpoint (works if log file exists)
    if isinstance(result, dict) and "error" in result:
        result = ha_api_request("/api/error_log")
        if isinstance(result, str) and result.strip():
            lines = result.strip().split("\n")
            return "\n".join(lines[-100:])[-MAX_ERROR_LOG_BYTES:]

    if isinstance(result, dict) and "error" in result:
        return {
            "error": "Could not retrieve logs from Supervisor or HA Core. "
                     "Check Settings > System > Logs in the HA UI instead.",
            "details": result.get("details", ""),
        }
    return result or {"error": "No log data available."}


def render_template(template):
    """Render a Jinja2 template in Home Assistant."""
    result = ha_api_request(
        "/api/template",
        method="POST",
        data={"template": template}
    )
    return result


def get_areas():
    """List every area and the entities assigned to it.

    The HA REST API does not expose the area/entity registry directly (it
    lives behind the WebSocket API), so we obtain it through the template
    engine, which DOES expose `areas()` / `area_name()` / `area_entities()`.
    This gives Claude the area awareness it needs for voice-style requests
    like "turn off the bedroom lights" without it having to guess entity
    ids from friendly names.
    """
    template = (
        "{% set ns = namespace(items=[]) %}"
        "{% for a in areas() %}"
        "{% set ns.items = ns.items + [{"
        "'area_id': a, 'name': area_name(a), 'entities': area_entities(a)"
        "}] %}"
        "{% endfor %}"
        "{{ ns.items | tojson }}"
    )
    result = render_template(template)

    # `ha_api_request` auto-parses JSON, so a `| tojson` array usually comes
    # back already decoded as a list. Handle list, raw-string, and the
    # error-dict passthrough cases explicitly.
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except json.JSONDecodeError:
            return {
                "error": "Could not parse areas from template output",
                "raw": result[:500],
            }
    if isinstance(result, list):
        if EXPOSED_ONLY:
            # The voice channel is shown each room's exposed entities only,
            # which is the same list the area map in its prompt carries.
            for area in result:
                if isinstance(area, dict):
                    area["entities"] = [e for e in area.get("entities") or []
                                        if _entity_exposed(e)]
        return {"area_count": len(result), "areas": result}
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
            return {"area_count": len(parsed), "areas": parsed}
        except json.JSONDecodeError:
            return {
                "error": "Could not parse areas from template output",
                "raw": result[:500],
            }
    # dict (typically an {"error": ...} from the API) — pass through
    return result



# Registry listing: which WS command serves each registry, and which fields
# survive into the (context-friendly) trimmed result.
_REGISTRY_COMMANDS = {
    "areas": "config/area_registry/list",
    "floors": "config/floor_registry/list",
    "labels": "config/label_registry/list",
    "devices": "config/device_registry/list",
    "entities": "config/entity_registry/list",
    "integrations": "config_entries/get",
    "users": "config/auth/list",
}

MAX_REGISTRY_RESULTS = 300


def _trim_registry_item(registry, item):
    """Reduce a registry row to the fields useful for management calls."""
    if registry == "areas":
        keep = {"area_id", "name", "floor_id", "icon", "aliases", "labels"}
    elif registry == "floors":
        keep = {"floor_id", "name", "level", "icon", "aliases"}
    elif registry == "labels":
        keep = {"label_id", "name", "icon", "color", "description"}
    elif registry == "devices":
        trimmed = {
            "device_id": item.get("id"),
            "name": item.get("name_by_user") or item.get("name"),
            "area_id": item.get("area_id"),
            "manufacturer": item.get("manufacturer"),
            "model": item.get("model"),
            "disabled_by": item.get("disabled_by"),
            "labels": item.get("labels"),
        }
        return {k: v for k, v in trimmed.items() if v not in (None, [], "")}
    elif registry == "entities":
        keep = {"entity_id", "name", "original_name", "device_id", "area_id",
                "platform", "disabled_by", "hidden_by", "labels"}
    elif registry == "users":
        trimmed = {
            "user_id": item.get("id"),
            "name": item.get("name"),
            "username": item.get("username"),
            "is_owner": item.get("is_owner"),
            "is_active": item.get("is_active"),
            "system_generated": item.get("system_generated"),
        }
        # Keep False values here: is_active/is_owner False is the signal.
        return {k: v for k, v in trimmed.items() if v is not None and v != ""}
    else:  # integrations
        trimmed = {
            "config_entry_id": item.get("entry_id"),
            "domain": item.get("domain"),
            "title": item.get("title"),
            "state": item.get("state"),
            "disabled_by": item.get("disabled_by"),
        }
        return {k: v for k, v in trimmed.items() if v not in (None, [], "")}
    return {k: v for k, v in item.items() if k in keep and v not in (None, [], "")}


def get_registry(registry, name_filter=None):
    """List a Home Assistant registry (areas, floors, labels, devices,
    entities, integrations) with the ids needed by the brain.*
    management services.

    This is the safe, read-only counterpart to editing /config/.storage —
    the registry files should never be modified by hand.
    """
    command = _REGISTRY_COMMANDS.get(registry)
    if not command:
        return {"error": (
            f"Unknown registry '{registry}'. "
            f"Choose one of: {', '.join(sorted(_REGISTRY_COMMANDS))}"
        )}
    try:
        # Registry dumps on large installs are big and slow; the transport
        # accepts unbounded frames (max_size=None) and gets extra time.
        result = _ws_command({"type": command}, timeout=30)
    except ImportError:
        return {"error": "websockets package not available in this environment"}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}
    if isinstance(result, dict) and "error" in result:
        return result

    items = [_trim_registry_item(registry, item) for item in (result or [])]
    if name_filter:
        needle = str(name_filter).lower()
        items = [
            item for item in items
            if any(
                isinstance(v, str) and needle in v.lower()
                for v in item.values()
            )
        ]
    if len(items) > MAX_REGISTRY_RESULTS:
        return {
            "registry": registry,
            "count": len(items),
            "note": (f"Result truncated to {MAX_REGISTRY_RESULTS} — "
                     "narrow the search with name_filter."),
            "items": items[:MAX_REGISTRY_RESULTS],
        }
    return {"registry": registry, "count": len(items), "items": items}


def list_dashboards(include_resources=False):
    """List Lovelace dashboards (the default dashboard is not in the
    collection — reach it by omitting url_path in get_dashboard)."""
    try:
        result = _ws_command({"type": "lovelace/dashboards/list"})
    except ImportError:
        return {"error": "websockets package not available in this environment"}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}
    if isinstance(result, dict) and "error" in result:
        return result
    dashboards = [
        {k: d.get(k) for k in ("url_path", "title", "mode", "icon", "show_in_sidebar")
         if d.get(k) is not None}
        for d in (result or [])
    ]
    payload = {
        "count": len(dashboards),
        "dashboards": dashboards,
        "note": ("The default dashboard is not listed — fetch it with "
                 "get_dashboard and no url_path."),
    }
    # Registered resources (custom card modules) only on request — they're
    # noise for the common "which dashboards exist" call.
    if include_resources:
        try:
            resources = _ws_command({"type": "lovelace/resources"})
            if isinstance(resources, list):
                payload["resources"] = [
                    {k: r.get(k) for k in ("url", "type") if r.get(k) is not None}
                    for r in resources
                ]
        except Exception:  # noqa: BLE001
            pass
    return payload


MAX_DASHBOARD_BYTES = 200_000


# The token that means "the one you get when you ask for nothing". It is
# `brain.update_dashboard`'s own (`power_tools._dashboard_key` maps it and
# None to the same storage key), and the two tools have to agree on it: the
# documented workflow is fetch, edit, save, so a word one of them hands back
# and the other refuses breaks the round trip at the first step. `url_path:
# "default"` is exactly what get_dashboard used to report and then reject.
DEFAULT_DASHBOARD = "default"


def _dashboard_wire_path(url_path):
    """What to put on the wire — None for the default dashboard.

    `lovelace/config` takes the real url_path or null, and has never heard
    of "default": passing it through asks for a dashboard nobody has, which
    comes back as config_not_found and reads as "you have no such dashboard".
    """
    if url_path in (None, "", DEFAULT_DASHBOARD):
        return None
    return url_path


def _dashboard_named(url_path, config=None, registered=None):
    """Which dashboard this actually is, never an echo of the argument.

    The old report was `url_path or "default"`, which says nothing a caller
    did not already know and cannot tell "I asked for nothing and got the
    default" from "I asked for a dashboard called default". What is useful is
    the same two facts every time: the token that fetches it again, and
    enough of a name to recognise it by — so a fetch that read the wrong
    dashboard is visible in its own answer rather than at the save.
    """
    wire = _dashboard_wire_path(url_path)
    out = {"url_path": wire or DEFAULT_DASHBOARD, "is_default": wire is None}
    title = None
    if isinstance(config, dict) and isinstance(config.get("title"), str):
        title = config["title"]
    if not title and isinstance(registered, list):
        for row in registered:
            if isinstance(row, dict) and row.get("url_path") == wire:
                title = row.get("title")
                break
    if not title and wire is None:
        # The one dashboard with no registry row of its own: Home Assistant
        # serves it at /lovelace and reports no url_path for it at all.
        title = "the default dashboard (served at /lovelace)"
    if title:
        out["dashboard"] = title
    return out


def get_dashboard(url_path=None, view_index=None):
    """Fetch a dashboard's configuration (default dashboard when url_path
    is omitted, or url_path="default"). Pair with brain.update_dashboard to
    edit: fetch, modify the JSON, save — the service backs up the old config
    automatically. The answer says which dashboard it actually read and the
    url_path that fetches it again.

    Large dashboards are retrievable in full through view_index: when the
    whole config exceeds MAX_DASHBOARD_BYTES the response is a view
    summary, and each view can then be fetched individually. Never read
    /config/.storage instead — it lags actual state for ~10s after a save
    (HA's delayed writes) and must never be treated as a source of truth.
    """
    try:
        result = _ws_command(
            {"type": "lovelace/config",
             "url_path": _dashboard_wire_path(url_path)},
            timeout=30)
    except ImportError:
        return {"error": "websockets package not available in this environment"}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}
    if isinstance(result, dict) and "error" in result:
        if "config_not_found" in str(result.get("error", "")):
            # config_not_found covers two very different cases: a registered
            # dashboard that has never been saved (auto-generated), and a
            # url_path that doesn't exist at all. Distinguish them — the old
            # blanket "save it to take control" note pointed callers at an
            # update_dashboard call that cannot succeed for the latter.
            registered = None
            if _dashboard_wire_path(url_path):
                try:
                    registered = _ws_command({"type": "lovelace/dashboards/list"})
                except Exception:  # noqa: BLE001
                    registered = None
                if isinstance(registered, list):
                    known = {d.get("url_path") for d in registered}
                    if url_path not in known:
                        available = ", ".join(sorted(k for k in known if k))
                        return {"error": (
                            f"Dashboard not found: {url_path}."
                            + (f" Existing: {available}" if available else "")
                        )}
                else:
                    # "I could not look" is not "it is registered". Claiming
                    # the second sends a caller to take_control on a
                    # dashboard that may not exist, and the save is where
                    # they find out.
                    return {"error": (
                        f"Home Assistant has no stored config for "
                        f"{url_path}, and the dashboard list could not be "
                        "read — so whether it exists at all is unknown. "
                        "Try list_dashboards.")}
            return {
                **_dashboard_named(url_path, registered=registered),
                "note": ("This dashboard is registered but has no stored "
                         "config yet (it is auto-generated). Saving with "
                         "brain.update_dashboard (take_control: true) "
                         "will take manual control of it."),
            }
        return result

    views = (result or {}).get("views") or []

    if view_index is not None:
        try:
            view_index = int(view_index)
        except (TypeError, ValueError):
            return {"error": f"view_index must be an integer, got {view_index!r}"}
        if not 0 <= view_index < len(views):
            return {"error": (f"view_index {view_index} out of range — this "
                              f"dashboard has {len(views)} views (0-"
                              f"{max(len(views) - 1, 0)})")}
        return {
            **_dashboard_named(url_path, result),
            "view_index": view_index,
            "view_count": len(views),
            "view": views[view_index],
        }

    payload = {**_dashboard_named(url_path, result), "config": result}
    if len(json.dumps(payload)) > MAX_DASHBOARD_BYTES:
        return {
            **_dashboard_named(url_path, result),
            "note": (f"Config too large to return whole (> {MAX_DASHBOARD_BYTES} "
                     "bytes) — view summary below. Fetch each view with "
                     "get_dashboard(url_path, view_index=N). Do NOT read "
                     "/config/.storage as a workaround: it lags real state "
                     "for ~10s after saves and is not a reliable channel."),
            "views": [
                {
                    "index": i,
                    "title": v.get("title"),
                    "path": v.get("path"),
                    "cards": len(v.get("cards") or []),
                }
                for i, v in enumerate(views)
            ],
        }
    return payload


def fire_event(event_type, event_data=None):
    """Fire a Home Assistant event.

    Refused wholesale on a channel with any service restrictions: an event
    can trigger any automation — including one that does exactly what the
    deny-list forbids — and an event name is not a service name, so there
    is nothing to match the patterns against. Fail closed, same rule as
    the meta-services above.
    """
    if DENIED_SERVICES:
        return {"error": (
            "fire_event is not permitted for this assistant: its service "
            "restrictions cannot be enforced on events, which can trigger "
            "any automation. Tell the user this action is restricted; "
            "do not retry."
        )}
    # The protected list gets the same answer for the same reason. A
    # protected entity is refused at call_service for every channel, and an
    # event reaches the house through whatever automations listen for it —
    # one of which may act on exactly that entity — with nothing here able
    # to see which. That is the label/floor rule in `_protected_target`:
    # a target this process cannot resolve is refused while the list is
    # non-empty, not waved through because it could not be checked.
    if PROTECTED_ENTITIES:
        return {"error": (
            "fire_event is refused while brAIn has protected entities: an "
            "event can reach a protected entity through any automation "
            "that listens for it, and which automations do cannot be "
            "checked from here. Tell the user; do not retry or look for "
            "another route."
        )}
    result = ha_api_request(
        f"/api/events/{event_type}",
        method="POST",
        data=event_data or {}
    )
    return result


def get_supervisor_info():
    """Get Supervisor system information."""
    info = ha_api_request("/core/info")
    addons = ha_api_request("/addons")
    host = ha_api_request("/host/info")
    return {
        "core": info.get("data", info),
        "host": host.get("data", host),
        "addons_count": len(addons.get("data", {}).get("addons", [])) if isinstance(addons, dict) else 0,
    }


def reload_config(target):
    """Reload a specific HA configuration area."""
    reload_map = {
        "automations": "/api/services/automation/reload",
        "scripts": "/api/services/script/reload",
        "scenes": "/api/services/scene/reload",
        "groups": "/api/services/group/reload",
        "input_booleans": "/api/services/input_boolean/reload",
        "input_numbers": "/api/services/input_number/reload",
        "input_selects": "/api/services/input_select/reload",
        "input_texts": "/api/services/input_text/reload",
        "input_datetimes": "/api/services/input_datetime/reload",
        "timers": "/api/services/timer/reload",
        "counters": "/api/services/counter/reload",
        "core": "/api/services/homeassistant/reload_core_config",
        "all": "/api/services/homeassistant/reload_all",
    }

    if target not in reload_map:
        return {"error": f"Unknown reload target: {target}", "valid_targets": list(reload_map.keys())}

    endpoint = reload_map[target]
    domain_service = endpoint.replace("/api/services/", "").split("/")
    if len(domain_service) == 2:
        return call_service(domain_service[0], domain_service[1])
    return {"error": "Invalid reload endpoint"}


def remember_fact(fact, confidence="high", subject="", person=""):
    """Queue a durable household fact for the memory consolidator.

    Appends one JSONL record to a fresh inbox file (one file per call —
    lock-free by construction). The brain memory consolidator later merges
    pending records into /config/.brain/memory/memory.md, and the panel's
    facts store files the same line under `subject` (an entity id,
    `area:<id>`, `person:<id>` or `house`) — a writer that knows what its
    fact is about beats a scan of the sentence. `person` is the person it
    is about, for a preference that is theirs and not the house's.
    """
    if not isinstance(fact, str) or not fact.strip():
        return {"error": "fact must be a non-empty string"}
    if confidence not in ("high", "medium", "low"):
        confidence = "high"
    subject = str(subject or "").strip()[:255]
    person = str(person or "").strip()[:64]

    inbox_dir = os.path.join(MEMORY_DIR, "inbox")
    try:
        os.makedirs(inbox_dir, exist_ok=True)
        now = int(time.time())
        record = {
            "ts": now,
            "source": "assist",
            "fact": fact.strip(),
            "confidence": confidence,
        }
        if subject:
            record["subject"] = subject
        if person:
            record["person"] = person
        path = os.path.join(inbox_dir, f"{now}-assist.jsonl")
        with open(path, "a") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError as exc:
        return {"error": f"Could not store fact: {exc}"}
    return {
        "status": "remembered",
        "fact": fact.strip(),
        "confidence": confidence,
        "note": "Queued for memory consolidation.",
    }


# ---------------------------------------------------------------------------
# The ways a finding could end, offered inside the conversation about it
# ---------------------------------------------------------------------------

# What an option may be. These are the panel's own ending verbs rather than
# a friendlier set translated at the far end: one vocabulary from the tool
# schema to the HTTP route is one fewer place for two answers to the same
# question to drift apart.
RESOLUTION_KINDS = ("done", "wrong", "todo", "advice")
MAX_RESOLUTIONS = 4
MAX_RESOLUTION_LABEL = 90
# `advice` replaces the card's "What you'd need to do" with the sentence
# the conversation reached, and settles nothing — so its label is a
# paragraph's worth rather than a button's, capped at what the findings
# store keeps for that field.
MAX_ADVICE_LABEL = 600


def offer_resolutions(options):
    """Put the ways this finding could end on the homeowner's screen.

    This tool changes NOTHING — not the house, not brAIn, not the finding.
    The panel is already streaming this conversation, so it reads the call
    itself and renders one button per option; pressing one is what settles
    the finding, and it settles it in the words of the option pressed.

    Which is why the label IS the record: there is no second string a person
    cannot see before they press. A label written as "Replaced the CR2032"
    is what goes into memory; one written as "that cupboard is never opened"
    is what corrects brAIn about the house.

    It only means anything inside a finding discussion, which is the panel's
    Discuss button. Anywhere else there is no finding to attach options to
    and nothing is shown — so this is not a way to ask a general question.
    """
    if not isinstance(options, list) or not options:
        return {"error": "options must be a non-empty list of "
                         "{label, kind} objects"}
    if len(options) > MAX_RESOLUTIONS:
        return {"error": f"at most {MAX_RESOLUTIONS} options — this is a row "
                         "of buttons on a phone, not a menu"}
    cleaned = []
    for option in options:
        if not isinstance(option, dict):
            return {"error": "each option is an object with label and kind"}
        label = option.get("label")
        kind = option.get("kind")
        if not isinstance(label, str) or not label.strip():
            return {"error": "every option needs a label — it is both the "
                             "button and what gets recorded"}
        if kind not in RESOLUTION_KINDS:
            return {"error": "kind must be one of "
                             + ", ".join(RESOLUTION_KINDS)}
        cap = MAX_ADVICE_LABEL if kind == "advice" else MAX_RESOLUTION_LABEL
        cleaned.append({"label": label.strip()[:cap], "kind": kind})
    return {
        "status": "offered",
        "options": cleaned,
        "note": "Shown as buttons under this message. The homeowner presses "
                "one, or none — you are not told which, and nothing is "
                "settled until they do. An `advice` option settles nothing "
                "either way: pressing it puts your sentence on the card as "
                "what to do about it.",
    }


# ============================================================================
# MCP Tool Definitions
# ============================================================================

TOOLS = [
    # The BRUH add-ons, through their own integrations' services.
    {
        "name": "minecraft_status",
        "description": (
            "The BRUH Minecraft server: whether it is answering, who is online "
            "right now (exact names — Bedrock/iPad players carry a '.' prefix), "
            "the world, server type, version and TPS. Read-only. Call it before "
            "acting on a player so you use the name the server knows."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "minecraft_teleport",
        "description": (
            "Teleport a Minecraft player to another player, or to x/y/z. Names "
            "are matched against who is online (case, spaces and the Bedrock "
            "prefix ignored; a unique partial match counts), 'everyone' means "
            "all players. An ambiguous or offline name comes back as a question "
            "to ask, never a guess. Returns the server's reply."
        ),
        "inputSchema": {"type": "object", "properties": {
            "player": {"type": "string", "description": "Who to move, or 'everyone'."},
            "to_player": {"type": "string", "description": "Who to move them to."},
            "x": {"type": "string"}, "y": {"type": "string"}, "z": {"type": "string"}},
            "required": ["player"]},
    },
    {
        "name": "minecraft_player",
        "description": (
            "Do one thing to one Minecraft player: gamemode (value: survival, "
            "creative, adventure, spectator), give (value: item like 'diamond' "
            "or 'minecraft:oak_log', amount up to 64), or the admin actions op, "
            "deop, kick, ban, pardon, whitelist_add, whitelist_remove (not "
            "available to a voice-level agent). Returns the server's reply."
        ),
        "inputSchema": {"type": "object", "properties": {
            "player": {"type": "string"},
            "action": {"type": "string", "enum": [
                "gamemode", "give", "op", "deop", "kick", "ban", "pardon",
                "whitelist_add", "whitelist_remove"]},
            "value": {"type": "string"},
            "amount": {"type": "integer"}},
            "required": ["player", "action"]},
    },
    {
        "name": "minecraft_world",
        "description": (
            "The Minecraft world everyone shares: set the time (day, night, "
            "noon, midnight or ticks), the weather (clear, rain, thunder), or "
            "say a message in chat to every player."
        ),
        "inputSchema": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["time", "weather", "say"]},
            "value": {"type": "string"}},
            "required": ["action", "value"]},
    },
    {
        "name": "minecraft_command",
        "description": (
            "Run any Minecraft server console command (no leading slash) and "
            "return the server's reply — for anything the other minecraft_ "
            "tools do not cover (effects, difficulty, gamerules, spawnpoints, "
            "plugin commands). Not available to a voice-level agent."
        ),
        "inputSchema": {"type": "object", "properties": {
            "command": {"type": "string"}}, "required": ["command"]},
    },
    {
        "name": "minecraft_server",
        "description": (
            "Back up the Minecraft world now, or restart or stop the server "
            "(the add-on keeps running). Not available to a voice-level agent."
        ),
        "inputSchema": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["backup", "restart", "stop"]}},
            "required": ["action"]},
    },
    {
        "name": "minecraft_addons",
        "description": (
            "BRUH Minecraft's add-on browser (Modrinth, server-side only, so "
            "every player gets them — iPads through Geyser included). list: "
            "what kinds this server can load and what is installed in the "
            "active world. search: query plus optional kind (plugin, datapack, "
            "mod, resourcepack) — results carry a project id. install: "
            "project_id and kind, brings required dependencies, says whether a "
            "restart is needed. remove: project_id. Install and remove are not "
            "available to a voice-level agent."
        ),
        "inputSchema": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["list", "search", "install", "remove"]},
            "query": {"type": "string"},
            "kind": {"type": "string", "enum": ["plugin", "datapack", "mod", "resourcepack"]},
            "project_id": {"type": "string"}},
            "required": ["action"]},
    },
    {
        "name": "label_printer_status",
        "description": (
            "BRUH Print's label printer: which printer is attached, what stock "
            "is loaded in each roll (with the stock ids), the saved templates "
            "and the fields each one needs, and the last few labels. Read-only. "
            "Call it before print_label to name a template or stock that exists."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "print_label",
        "description": (
            "Print a label on BRUH Print. Either text (fitted as large as it "
            "will go; a line break starts a new line) with an optional stock id, "
            "or a saved template by name with its fields (date and time fill "
            "themselves in). copies defaults to 1; a voice-level agent prints "
            "at most 10. Returns how many printed and on which roll."
        ),
        "inputSchema": {"type": "object", "properties": {
            "text": {"type": "string"},
            "template": {"type": "string"},
            "fields": {"type": "object"},
            "stock": {"type": "string"},
            "copies": {"type": "integer"}}},
    },
    {
        "name": "bright_status",
        "description": (
            "BRight, the music light-show director: what it is doing now, the "
            "saved sets (parties) by name, and the tracks with a show ready "
            "(file path, whether analyzed). Read-only."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "bright_show",
        "description": (
            "Run BRight. action party: a saved set by name (party), or party "
            "mode over the music folder with no name. action track: one track's "
            "show (track = file path from bright_status). action stop: stop "
            "and put the room back, or call scene instead. media_player "
            "overrides the speaker; scene is the end scene."
        ),
        "inputSchema": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["party", "track", "stop"]},
            "party": {"type": "string"},
            "track": {"type": "string"},
            "media_player": {"type": "string"},
            "scene": {"type": "string"}},
            "required": ["action"]},
    },
    # Music Assistant — its own API, through the panel.
    {
        "name": "music_assistant_status",
        "description": (
            "Music Assistant, whole: whether brAIn can reach the server and as "
            "whom (role — 'service' can control and configure players; 'admin' "
            "can also change providers and server settings), every player "
            "(id, name, provider, available, state, volume, what it is playing, "
            "group), the players worth clearing out (remembered but gone, or "
            "unavailable — with why), and every provider with its last error. "
            "Read-only. Start here before any other music_assistant tool."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "music_assistant_query",
        "description": (
            "Run one READ-ONLY Music Assistant API command and return its "
            "result, e.g. players/all, player_queues/items {queue_id, limit}, "
            "config/players/get {player_id}, config/providers, "
            "config/providers/get_entries {provider_domain}, "
            "music/tracks/library_items {limit, search}, music/browse {path}, "
            "logging/get. Commands that change something are refused here; "
            "use music_assistant_command."
        ),
        "inputSchema": {"type": "object", "properties": {
            "command": {"type": "string"},
            "args": {"type": "object", "description": "The command's arguments."}},
            "required": ["command"]},
    },
    {
        "name": "music_assistant_search",
        "description": (
            "Search Music Assistant (the library and every music provider) for "
            "tracks, albums, artists, playlists, radio stations, audiobooks or "
            "podcasts. Each result carries a uri to play with "
            "music_assistant_play. Read-only."
        ),
        "inputSchema": {"type": "object", "properties": {
            "query": {"type": "string"},
            "media_types": {"type": "array", "items": {"type": "string", "enum": [
                "artist", "album", "track", "playlist", "radio", "audiobook",
                "podcast"]}},
            "limit": {"type": "integer", "description": "Per type (default 10)."}},
            "required": ["query"]},
    },
    {
        "name": "music_assistant_command",
        "description": (
            "Run ANY Music Assistant API command — full control and "
            "administration: players/cmd/* (play, pause, volume_set, "
            "group_many, …), player_queues/* (play_media, shuffle, repeat, "
            "move_item, transfer, …), config/players/save {player_id, values} "
            "and config/players/remove {player_id}, "
            "players/create_group_player, config/providers/save/remove/reload, "
            "config/core/save, music/library/add_item, "
            "music/playlists/create_playlist, music/sync, … Arguments are the "
            "command's own, as in Music Assistant's API docs (its /api-docs "
            "page). Refused for a player that is a protected entity. Settings "
            "for providers and the server need an admin token "
            "(music_assistant_token); the refusal says so."
        ),
        "inputSchema": {"type": "object", "properties": {
            "command": {"type": "string"},
            "args": {"type": "object"}},
            "required": ["command"]},
    },
    {
        "name": "music_assistant_player",
        "description": (
            "One action on one Music Assistant player: play, pause, play_pause, "
            "stop, next, previous, power (value true/false), volume (0-100), "
            "volume_up, volume_down, mute (true/false), seek (seconds), group "
            "(value: the player to join), ungroup, shuffle (true/false), repeat "
            "(off/one/all), clear_queue, enable, disable, rename (value: the "
            "new name). Refused for a protected entity."
        ),
        "inputSchema": {"type": "object", "properties": {
            "player_id": {"type": "string"},
            "action": {"type": "string", "enum": [
                "play", "pause", "play_pause", "stop", "next", "previous",
                "power", "volume", "volume_up", "volume_down", "mute", "seek",
                "group", "ungroup", "shuffle", "repeat", "clear_queue",
                "enable", "disable", "rename"]},
            "value": {"description": "The action's value, where it takes one."}},
            "required": ["player_id", "action"]},
    },
    {
        "name": "music_assistant_play",
        "description": (
            "Play media on a Music Assistant player: a uri from "
            "music_assistant_search, a list of uris, or a name Music Assistant "
            "searches for. option: play (default), replace, next, "
            "replace_next or add. radio_mode keeps similar music going."
        ),
        "inputSchema": {"type": "object", "properties": {
            "player_id": {"type": "string"},
            "media": {"description": "A uri, a list of uris, or a name."},
            "option": {"type": "string",
                       "enum": ["play", "replace", "next", "replace_next", "add"]},
            "radio_mode": {"type": "boolean"}},
            "required": ["player_id", "media"]},
    },
    {
        "name": "music_assistant_remove_players",
        "description": (
            "Make Music Assistant forget players it should not have any more — "
            "stale ones it remembers but has not seen, or ones left unavailable "
            "(e.g. every AirCast/Chromecast bridge player from a provider you "
            "removed). This is what clears a player Home Assistant's registry "
            "tools cannot: the config lives in Music Assistant, and once it is "
            "gone Home Assistant drops the entity too. DRY RUN by default — "
            "lists what would go; call again with dry_run false to remove. "
            "stale_only (default true) never sweeps up a working player. Filter "
            "by player_ids and/or provider (instance id, domain or name). A "
            "player whose provider cannot remove players is reported as held; "
            "disable_if_held disables those instead."
        ),
        "inputSchema": {"type": "object", "properties": {
            "player_ids": {"type": "array", "items": {"type": "string"}},
            "provider": {"type": "string"},
            "stale_only": {"type": "boolean"},
            "dry_run": {"type": "boolean"},
            "disable_if_held": {"type": "boolean"}}},
    },
    # ESPHome — files here, builds on the dashboard, all through the panel.
    {
        "name": "esphome_list_devices",
        "description": (
            "List every ESPHome device configuration (/config/esphome): its "
            "node and friendly name, platform and board, the dashboard's view "
            "of it (address, online, deployed vs current firmware version, "
            "update available), the Home Assistant device it is and whether "
            "it carries a protected entity. Also says whether the ESPHome "
            "dashboard can be reached and why not, the discovered devices "
            "not yet adopted, and the keys (never values) in secrets.yaml. "
            "Read-only."
        ),
        "inputSchema": {"type": "object", "properties": {
            "refresh": {"type": "boolean",
                        "description": "Look for the dashboard again rather than "
                                       "using the route found a few minutes ago."}}},
    },
    {
        "name": "esphome_get_config",
        "description": (
            "Read one ESPHome device's YAML exactly as it is on disk, with its "
            "file modification time. secrets.yaml is never read out (its keys "
            "are listed instead). Read-only."
        ),
        "inputSchema": {"type": "object", "properties": {
            "configuration": {"type": "string",
                              "description": "The file name, e.g. porch-light.yaml"}},
            "required": ["configuration"]},
    },
    {
        "name": "esphome_write_config",
        "description": (
            "Save an ESPHome device's YAML (the whole file). The previous file "
            "is snapshotted into the edit journal first, so `brain undo` "
            "restores it. A file that does not parse is still saved and the "
            "answer says so. This changes nothing on the device until it is "
            "installed; run esphome_validate after writing."
        ),
        "inputSchema": {"type": "object", "properties": {
            "configuration": {"type": "string"},
            "content": {"type": "string", "description": "The complete YAML."},
            "create": {"type": "boolean",
                       "description": "True to create a new file (refused if it exists)."}},
            "required": ["configuration", "content"]},
    },
    {
        "name": "esphome_create_device",
        "description": (
            "Start a new ESPHome device file the way the dashboard's wizard "
            "does: a fresh API encryption key, OTA password and fallback "
            "hotspot, Wi-Fi from secrets.yaml. The name becomes the hostname "
            "(lowercase letters, digits, hyphens)."
        ),
        "inputSchema": {"type": "object", "properties": {
            "name": {"type": "string"},
            "platform": {"type": "string",
                         "enum": ["esp32", "esp8266", "rp2040", "bk72xx", "rtl87xx"]},
            "board": {"type": "string",
                      "description": "PlatformIO board id (empty for the usual one)."},
            "friendly_name": {"type": "string"}},
            "required": ["name"]},
    },
    {
        "name": "esphome_delete_device",
        "description": (
            "Move an ESPHome device file into the archive folder, the way the "
            "dashboard deletes one. Refused for a device carrying a protected "
            "entity."
        ),
        "inputSchema": {"type": "object", "properties": {
            "configuration": {"type": "string"}}, "required": ["configuration"]},
    },
    {
        "name": "esphome_validate",
        "description": (
            "Validate an ESPHome configuration with ESPHome itself (on the "
            "dashboard) and return its output and exit code. Changes nothing. "
            "Needs a reachable dashboard."
        ),
        "inputSchema": {"type": "object", "properties": {
            "configuration": {"type": "string"},
            "wait_seconds": {"type": "integer",
                             "description": "How long to wait for it (default 90)."}},
            "required": ["configuration"]},
    },
    {
        "name": "esphome_compile",
        "description": (
            "Compile an ESPHome device's firmware on the dashboard without "
            "installing it. Takes minutes; returns a job to follow with "
            "esphome_job if it has not finished within wait_seconds."
        ),
        "inputSchema": {"type": "object", "properties": {
            "configuration": {"type": "string"},
            "wait_seconds": {"type": "integer"}}, "required": ["configuration"]},
    },
    {
        "name": "esphome_install",
        "description": (
            "Compile and install firmware onto an ESPHome device — over the "
            "air by default (target 'OTA'), or to an address. This replaces "
            "the firmware the device runs and reboots it. Refused for a device "
            "carrying a protected entity. Returns a job to follow with "
            "esphome_job."
        ),
        "inputSchema": {"type": "object", "properties": {
            "configuration": {"type": "string"},
            "target": {"type": "string",
                       "description": "'OTA' (default) or the device's IP address."},
            "wait_seconds": {"type": "integer"}}, "required": ["configuration"]},
    },
    {
        "name": "esphome_update_firmware",
        "description": (
            "Install the firmware update Home Assistant says is waiting for "
            "an ESPHome device, through Home Assistant's own update entity. "
            "Use this when the dashboard cannot be reached directly; it only "
            "works while an update is actually waiting."
        ),
        "inputSchema": {"type": "object", "properties": {
            "configuration": {"type": "string"},
            "wait_seconds": {"type": "integer"}}, "required": ["configuration"]},
    },
    {
        "name": "esphome_clean",
        "description": "Delete an ESPHome device's build files on the dashboard.",
        "inputSchema": {"type": "object", "properties": {
            "configuration": {"type": "string"}}, "required": ["configuration"]},
    },
    {
        "name": "esphome_logs",
        "description": (
            "Read an ESPHome device's live log for a few seconds (default 20, "
            "at most 120) and return the lines. Connects to the device "
            "through the dashboard; changes nothing."
        ),
        "inputSchema": {"type": "object", "properties": {
            "configuration": {"type": "string"},
            "seconds": {"type": "integer"}}, "required": ["configuration"]},
    },
    {
        "name": "esphome_job",
        "description": (
            "Follow an ESPHome command (validate, compile, install, logs, "
            "clean) by its job id: its state, exit code and output lines "
            "after `since`. Read-only."
        ),
        "inputSchema": {"type": "object", "properties": {
            "job_id": {"type": "string"},
            "since": {"type": "integer",
                      "description": "Line number to continue from (the last `total`)."}},
            "required": ["job_id"]},
    },
    {
        "name": "esphome_set_secret",
        "description": (
            "Set one key in ESPHome's secrets.yaml (e.g. wifi_ssid, "
            "wifi_password). Only that line changes; the value is never "
            "read back."
        ),
        "inputSchema": {"type": "object", "properties": {
            "key": {"type": "string"}, "value": {"type": "string"}},
            "required": ["key", "value"]},
    },
    # ------------------------------------------------------------------
    # Entity & State Tools
    # ------------------------------------------------------------------
    {
        "name": "get_entity_state",
        "description": "Get the current state and attributes of a specific Home Assistant entity. Returns state, attributes, last_changed, and last_updated.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "The entity ID (e.g., 'light.living_room', 'sensor.temperature')"
                }
            },
            "required": ["entity_id"]
        }
    },
    {
        "name": "get_all_states",
        "description": "Get a summary of entity states in Home Assistant, filtered by domain and/or a name substring. Results are capped at 300 — always filter on large installations.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Optional domain filter (e.g., 'light', 'sensor', 'switch', 'automation')"
                },
                "name_filter": {
                    "type": "string",
                    "description": "Optional case-insensitive substring matched against entity_id and friendly name (e.g., 'kitchen')"
                }
            }
        }
    },
    # ------------------------------------------------------------------
    # Generic Service Call
    # ------------------------------------------------------------------
    {
        "name": "call_service",
        "description": (
            "Call any Home Assistant service. Use this for services not covered by "
            "the dedicated tools (control_light, control_climate, etc.). "
            "Pass domain, service name, and a data object with required fields.\n\n"
            "Common examples:\n"
            "- switch/turn_on: {\"entity_id\": \"switch.heater\"}\n"
            "- input_boolean/toggle: {\"entity_id\": \"input_boolean.guest_mode\"}\n"
            "- input_number/set_value: {\"entity_id\": \"input_number.target\", \"value\": 42}\n"
            "- input_select/select_option: {\"entity_id\": \"input_select.mode\", \"option\": \"away\"}\n"
            "- tts/speak: {\"entity_id\": \"tts.google\", \"media_player_entity_id\": \"media_player.kitchen\", \"message\": \"Hello\"}\n"
            "- number/set_value: {\"entity_id\": \"number.volume\", \"value\": 50}\n"
            "- button/press: {\"entity_id\": \"button.restart\"}\n"
            "- select/select_option: {\"entity_id\": \"select.mode\", \"option\": \"eco\"}\n"
            "- automation/trigger: {\"entity_id\": \"automation.morning_routine\"}\n"
            "\nThe brain domain also provides BRUH Power Tools — registry "
            "management services (create_area, rename_entity, add_label, "
            "disable_device, create_repair_issue, ...). Use get_registry to look "
            "up the ids they need, and set return_response true for the ones "
            "that return data (create_area/floor/label, "
            "delete_orphaned_entities, create_repair_issue).\n"
            "\nUse get_service_details to look up all available fields for any service."
            "\n\nPROTECTED ENTITIES: the homeowner may have named entities "
            "brAIn must not act on, and this call refuses any target that "
            "matches one — including an area or device that contains one. "
            "The refusal names the entity. Do not route around it with a "
            "shell command or by editing a YAML file: it is the homeowner's "
            "list, and those paths are not checked."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Service domain (e.g., 'light', 'switch', 'automation', 'climate', 'tts', 'input_boolean')"
                },
                "service": {
                    "type": "string",
                    "description": "Service name (e.g., 'turn_on', 'turn_off', 'toggle', 'trigger', 'set_value')"
                },
                "data": {
                    "type": "object",
                    "description": "Service data payload including entity_id and service-specific fields"
                },
                "return_response": {
                    "type": "boolean",
                    "description": "Set true for services that return response data (routes the call over the WebSocket API and returns the service response)"
                }
            },
            "required": ["domain", "service"]
        }
    },
    {
        "name": "get_registry",
        "description": (
            "List a Home Assistant registry: areas, floors, labels, devices, "
            "entities, integrations (config entries), or users. Returns the "
            "registry ids (area_id, floor_id, label_id, device_id, entity_id, "
            "config_entry_id, user_id) needed by the brain.* management services "
            "— the safe alternative to reading /config/.storage files. "
            "The full registry is retrieved and filtered server-side, then "
            "capped at 300 rows; use name_filter to narrow large results."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "registry": {
                    "type": "string",
                    "enum": ["areas", "floors", "labels", "devices", "entities", "integrations", "users"],
                    "description": "Which registry to list"
                },
                "name_filter": {
                    "type": "string",
                    "description": "Optional case-insensitive substring matched against any text field (name, id, manufacturer, ...)"
                }
            },
            "required": ["registry"]
        }
    },
    {
        "name": "list_dashboards",
        "description": "List Lovelace dashboards (url_path, title, mode). The default dashboard is not in the list — fetch it with get_dashboard and no url_path.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "include_resources": {
                    "type": "boolean",
                    "description": "Also list registered Lovelace resources (custom card modules). Default false."
                }
            }
        }
    },
    {
        "name": "get_dashboard",
        "description": (
            "Fetch a dashboard's full configuration as JSON (the default "
            "dashboard when url_path is omitted). To edit a dashboard: fetch "
            "with this tool, modify the JSON, then save the complete object "
            "with the brain.update_dashboard service — it backs up the "
            "previous config automatically, and brain.restore_dashboard "
            "undoes a bad edit. If the config is too large to return whole, "
            "the response lists the views — fetch each with view_index. "
            "Never read or edit .storage/lovelace files directly: they lag "
            "the real config for ~10s after saves."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url_path": {
                    "type": "string",
                    "description": "Dashboard url_path from list_dashboards; omit or pass \"default\" for the default dashboard (the same word brain.update_dashboard takes for it). The answer says which dashboard it actually read."
                },
                "view_index": {
                    "type": "integer",
                    "description": "Return only this view (0-based) — for dashboards too large to return whole"
                }
            }
        }
    },
    {
        "name": "get_service_details",
        "description": "Get the full service schema for a domain, showing all available services and their fields/parameters. Use this to discover what parameters a service accepts before calling it. Pass service to get just one schema (recommended for large domains like brain).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "The service domain to look up (e.g., 'light', 'climate', 'media_player', 'vacuum', 'notify')"
                },
                "service": {
                    "type": "string",
                    "description": "Optional: return only this service's schema instead of the whole domain"
                }
            },
            "required": ["domain"]
        }
    },
    # ------------------------------------------------------------------
    # Light Control
    # ------------------------------------------------------------------
    {
        "name": "control_light",
        "description": (
            "Control a light — turn on/off, set brightness, color, color temperature, and effects. "
            "Supports RGB, HS, XY, named colors, and Kelvin color temperature."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "The light entity ID (e.g., 'light.living_room', 'light.bedroom_strip')"
                },
                "action": {
                    "type": "string",
                    "enum": ["turn_on", "turn_off", "toggle"],
                    "description": "Action to perform"
                },
                "brightness": {
                    "type": "integer",
                    "description": "Brightness 0-255 (0=off, 255=max)"
                },
                "brightness_pct": {
                    "type": "integer",
                    "description": "Brightness as percentage 0-100"
                },
                "rgb_color": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "RGB color as [R, G, B] (0-255 each). Examples: [255,0,0]=red, [0,255,0]=green, [0,0,255]=blue, [255,165,0]=orange, [128,0,128]=purple"
                },
                "hs_color": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Hue/Saturation as [hue, saturation]. Hue: 0-360, Saturation: 0-100"
                },
                "xy_color": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "CIE xy color as [x, y] (0.0-1.0 each)"
                },
                "color_temp_kelvin": {
                    "type": "integer",
                    "description": "Color temperature in Kelvin (2000=warm/candlelight, 3000=soft white, 4000=neutral, 5000=daylight, 6500=cool)"
                },
                "color_name": {
                    "type": "string",
                    "description": "CSS3 color name (e.g., 'red', 'blue', 'green', 'purple', 'orange', 'pink', 'white', 'coral', 'gold')"
                },
                "effect": {
                    "type": "string",
                    "description": "Light effect name (device-specific, e.g., 'colorloop', 'random', 'rainbow', 'breathe', 'strobe')"
                },
                "transition": {
                    "type": "number",
                    "description": "Transition duration in seconds for the change"
                },
                "flash": {
                    "type": "string",
                    "enum": ["short", "long"],
                    "description": "Flash the light briefly"
                },
                "white": {
                    "type": "integer",
                    "description": "Set white channel value 0-255 (for RGBW lights)"
                }
            },
            "required": ["entity_id", "action"]
        }
    },
    # ------------------------------------------------------------------
    # Climate / Thermostat Control
    # ------------------------------------------------------------------
    {
        "name": "control_climate",
        "description": (
            "Control a thermostat or HVAC system — set temperature, mode, fan, preset, humidity, and swing."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "The climate entity ID (e.g., 'climate.living_room', 'climate.ecobee')"
                },
                "action": {
                    "type": "string",
                    "enum": ["set_temperature", "set_hvac_mode", "set_fan_mode", "set_preset_mode", "set_humidity", "set_swing_mode", "turn_on", "turn_off"],
                    "description": "Action to perform"
                },
                "temperature": {
                    "type": "number",
                    "description": "Target temperature (in system units — °F or °C)"
                },
                "target_temp_high": {
                    "type": "number",
                    "description": "Upper target for auto/heat_cool mode"
                },
                "target_temp_low": {
                    "type": "number",
                    "description": "Lower target for auto/heat_cool mode"
                },
                "hvac_mode": {
                    "type": "string",
                    "enum": ["off", "heat", "cool", "heat_cool", "auto", "dry", "fan_only"],
                    "description": "HVAC operating mode"
                },
                "fan_mode": {
                    "type": "string",
                    "description": "Fan mode (e.g., 'auto', 'low', 'medium', 'high', 'on', 'off')"
                },
                "preset_mode": {
                    "type": "string",
                    "description": "Preset mode (e.g., 'away', 'home', 'sleep', 'eco', 'boost', 'comfort')"
                },
                "humidity": {
                    "type": "integer",
                    "description": "Target humidity percentage (0-100)"
                },
                "swing_mode": {
                    "type": "string",
                    "description": "Swing mode (e.g., 'off', 'on', 'vertical', 'horizontal', 'both')"
                }
            },
            "required": ["entity_id", "action"]
        }
    },
    # ------------------------------------------------------------------
    # Media Player Control
    # ------------------------------------------------------------------
    {
        "name": "control_media_player",
        "description": (
            "Control a media player — play, pause, volume, source, play specific media, shuffle, repeat."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "The media player entity ID (e.g., 'media_player.living_room', 'media_player.sonos')"
                },
                "action": {
                    "type": "string",
                    "enum": [
                        "turn_on", "turn_off", "toggle",
                        "play", "pause", "stop", "play_pause",
                        "next", "previous",
                        "set_volume", "volume_up", "volume_down",
                        "volume_mute", "volume_unmute",
                        "select_source", "play_media", "seek",
                        "set_shuffle", "set_repeat", "clear_playlist"
                    ],
                    "description": "Action to perform"
                },
                "volume_level": {
                    "type": "number",
                    "description": "Volume level 0.0-1.0 (for set_volume)"
                },
                "source": {
                    "type": "string",
                    "description": "Input source name (for select_source, e.g., 'Spotify', 'TV', 'Bluetooth')"
                },
                "media_content_id": {
                    "type": "string",
                    "description": "Media content ID/URL (for play_media)"
                },
                "media_content_type": {
                    "type": "string",
                    "description": "Media type (for play_media: 'music', 'video', 'playlist', 'channel', 'tvshow', 'image')"
                },
                "seek_position": {
                    "type": "number",
                    "description": "Seek position in seconds (for seek)"
                },
                "shuffle": {
                    "type": "boolean",
                    "description": "Enable/disable shuffle (for set_shuffle)"
                },
                "repeat": {
                    "type": "string",
                    "enum": ["off", "all", "one"],
                    "description": "Repeat mode (for set_repeat)"
                }
            },
            "required": ["entity_id", "action"]
        }
    },
    # ------------------------------------------------------------------
    # Cover / Blind Control
    # ------------------------------------------------------------------
    {
        "name": "control_cover",
        "description": (
            "Control a cover, blind, shade, or garage door — open, close, stop, "
            "set position (0=closed, 100=open), and set tilt."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "The cover entity ID (e.g., 'cover.garage_door', 'cover.living_room_blinds')"
                },
                "action": {
                    "type": "string",
                    "enum": ["open", "close", "stop", "toggle", "set_position", "set_tilt"],
                    "description": "Action to perform"
                },
                "position": {
                    "type": "integer",
                    "description": "Cover position 0-100 (0=fully closed, 100=fully open)"
                },
                "tilt_position": {
                    "type": "integer",
                    "description": "Tilt position 0-100 (0=closed, 100=fully open)"
                }
            },
            "required": ["entity_id", "action"]
        }
    },
    # ------------------------------------------------------------------
    # Fan Control
    # ------------------------------------------------------------------
    {
        "name": "control_fan",
        "description": "Control a fan — on/off, speed percentage, preset mode, direction, and oscillation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "The fan entity ID (e.g., 'fan.bedroom', 'fan.ceiling')"
                },
                "action": {
                    "type": "string",
                    "enum": ["turn_on", "turn_off", "toggle", "set_percentage", "set_preset_mode", "set_direction", "oscillate"],
                    "description": "Action to perform"
                },
                "percentage": {
                    "type": "integer",
                    "description": "Fan speed percentage 0-100 (for turn_on or set_percentage)"
                },
                "preset_mode": {
                    "type": "string",
                    "description": "Preset mode (e.g., 'auto', 'nature', 'sleep', 'baby')"
                },
                "direction": {
                    "type": "string",
                    "enum": ["forward", "reverse"],
                    "description": "Fan direction"
                },
                "oscillating": {
                    "type": "boolean",
                    "description": "Enable or disable oscillation"
                }
            },
            "required": ["entity_id", "action"]
        }
    },
    # ------------------------------------------------------------------
    # Switch / Toggle Control
    # ------------------------------------------------------------------
    {
        "name": "control_switch",
        "description": "Control a switch, input_boolean, or similar on/off entity.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "The entity ID (e.g., 'switch.heater', 'input_boolean.guest_mode')"
                },
                "action": {
                    "type": "string",
                    "enum": ["turn_on", "turn_off", "toggle"],
                    "description": "Action to perform"
                }
            },
            "required": ["entity_id", "action"]
        }
    },
    # ------------------------------------------------------------------
    # Lock Control
    # ------------------------------------------------------------------
    {
        "name": "control_lock",
        "description": "Control a smart lock — lock, unlock, or open (if supported). Optionally provide an access code.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "The lock entity ID (e.g., 'lock.front_door')"
                },
                "action": {
                    "type": "string",
                    "enum": ["lock", "unlock", "open"],
                    "description": "Action to perform"
                },
                "code": {
                    "type": "string",
                    "description": "Optional access code"
                }
            },
            "required": ["entity_id", "action"]
        }
    },
    # ------------------------------------------------------------------
    # Alarm Control
    # ------------------------------------------------------------------
    {
        "name": "control_alarm",
        "description": "Control an alarm panel — arm (away/home/night/vacation), disarm, or trigger.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "The alarm entity ID (e.g., 'alarm_control_panel.home')"
                },
                "action": {
                    "type": "string",
                    "enum": ["arm_away", "arm_home", "arm_night", "arm_vacation", "arm_custom", "disarm", "trigger"],
                    "description": "Action to perform"
                },
                "code": {
                    "type": "string",
                    "description": "Alarm code (required for most arm/disarm actions)"
                }
            },
            "required": ["entity_id", "action"]
        }
    },
    # ------------------------------------------------------------------
    # Vacuum Control
    # ------------------------------------------------------------------
    {
        "name": "control_vacuum",
        "description": "Control a robot vacuum — start, stop, pause, return home, locate, spot clean, set fan speed.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "The vacuum entity ID (e.g., 'vacuum.roborock')"
                },
                "action": {
                    "type": "string",
                    "enum": ["start", "stop", "pause", "return_home", "locate", "clean_spot", "send_command", "set_fan_speed"],
                    "description": "Action to perform"
                },
                "command": {
                    "type": "string",
                    "description": "For send_command: the command name. For set_fan_speed: the speed (e.g., 'quiet', 'standard', 'turbo', 'max')"
                },
                "params": {
                    "type": "object",
                    "description": "For send_command: optional command parameters"
                }
            },
            "required": ["entity_id", "action"]
        }
    },
    # ------------------------------------------------------------------
    # Notification
    # ------------------------------------------------------------------
    {
        "name": "send_notification",
        "description": (
            "Send a notification via Home Assistant. "
            "Without a target, creates a persistent notification in the HA UI. "
            "With a target, sends to that notify service (e.g., mobile app, Slack, email)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The notification message"
                },
                "title": {
                    "type": "string",
                    "description": "Optional notification title"
                },
                "target": {
                    "type": "string",
                    "description": "Notify service target (e.g., 'mobile_app_phone', 'slack', 'email'). Omit for persistent notification."
                },
                "data": {
                    "type": "object",
                    "description": "Extra data (e.g., {\"image\": \"/local/cam.jpg\"}, {\"push\": {\"sound\": \"default\"}})"
                }
            },
            "required": ["message"]
        }
    },
    # ------------------------------------------------------------------
    # Scene & Script
    # ------------------------------------------------------------------
    {
        "name": "activate_scene",
        "description": "Activate a scene in Home Assistant. Scenes apply a saved set of states to multiple entities at once.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "The scene entity ID (e.g., 'scene.movie_night', 'scene.goodnight')"
                },
                "transition": {
                    "type": "number",
                    "description": "Transition time in seconds for the scene change"
                }
            },
            "required": ["entity_id"]
        }
    },
    {
        "name": "run_script",
        "description": "Run a Home Assistant script with optional input variables.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "The script entity ID (e.g., 'script.morning_routine')"
                },
                "variables": {
                    "type": "object",
                    "description": "Optional variables to pass to the script (e.g., {\"room\": \"bedroom\", \"brightness\": 80})"
                }
            },
            "required": ["entity_id"]
        }
    },
    # ------------------------------------------------------------------
    # Camera Vision
    # ------------------------------------------------------------------
    {
        "name": "get_camera_snapshot",
        "description": (
            "Take a snapshot from a camera and SEE it. Returns the current "
            "image so you can describe what's visible, check on things, or "
            "verify a state visually (e.g. 'is the garage door actually closed?')."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "The camera entity ID (e.g., 'camera.driveway')"
                },
                "max_dim": {
                    "type": "integer",
                    "description": "Max image dimension in pixels, 256-1920 (default 1024). Use smaller for quick checks."
                }
            },
            "required": ["entity_id"]
        }
    },
    # ------------------------------------------------------------------
    # Automation Tools
    # ------------------------------------------------------------------
    {
        "name": "get_automations",
        "description": "List all automations with their current state (on/off), friendly name, and last triggered time.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_automation_trace",
        "description": "Get state info and recent execution traces for a specific automation. Returns last_triggered time, current state, and stored trace data when available. Useful for debugging why an automation did or didn't fire.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "automation_id": {
                    "type": "string",
                    "description": "The automation entity ID (e.g., 'automation.turn_on_lights')"
                }
            },
            "required": ["automation_id"]
        }
    },
    # ------------------------------------------------------------------
    # System Tools
    # ------------------------------------------------------------------
    {
        "name": "get_ha_config",
        "description": "Get Home Assistant configuration including location, unit system, timezone, version, and component list.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_services",
        "description": "List all available Home Assistant service domains and their services.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_device_registry",
        "description": "Get a count summary of entities grouped by domain (total entities and a per-domain tally). NOTE: this is derived from entity states, not the HA device registry. For area/room groupings use get_areas.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_areas",
        "description": "List all Home Assistant areas (rooms) and the entity_ids assigned to each. Use this to resolve room-based requests like 'turn off the kitchen lights' to concrete entity_ids before calling a control tool.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_logbook",
        "description": "Get recent logbook entries from Home Assistant. Shows state changes and events.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "hours": {
                    "type": "number",
                    "description": "How many hours of history to retrieve (default: 1, max: 24)"
                },
                "entity_id": {
                    "type": "string",
                    "description": "Optional entity ID to filter logbook entries"
                }
            }
        }
    },
    {
        "name": "get_history",
        "description": (
            "Get recent state-change history for ONE entity (up to 7 days, from "
            "the recorder). Includes min/max for numeric sensors. Use this for "
            "'when did the garage last open' or 'how warm was it this morning'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "The entity ID to fetch history for"
                },
                "hours": {
                    "type": "number",
                    "description": "How many hours back (1-168, default 24)"
                }
            },
            "required": ["entity_id"]
        }
    },
    {
        "name": "get_baseline",
        "description": (
            "What is NORMAL for one numeric entity — its usual reading for each "
            "hour of the week and how much it usually varies, measured from a "
            "month of this house's own history. Use it before calling anything "
            "unusual: it is the difference between 'that looks high' and '4.2 "
            "times its normal variation for a Tuesday morning'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "The entity ID to look up"
                }
            },
            "required": ["entity_id"]
        }
    },
    {
        "name": "explain_change",
        "description": (
            "Why an entity is the way it is: its recent changes and what caused "
            "each one — an automation (named), a script, a scene, a person, a "
            "voice command, or brAIn itself. A state says WHAT; this says WHO. "
            "Use it for 'why did the hall light come on', 'why is the heating "
            "running', and before blaming an automation for anything."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "The entity ID to explain"
                },
                "hours": {
                    "type": "number",
                    "description": ("How many hours back, default 24. The panel caps how "
                                    "long one window may be; ask about an "
                                    "earlier day by asking about it, not by "
                                    "widening the window.")
                }
            },
            "required": ["entity_id"]
        }
    },
    {
        "name": "get_house_model",
        "description": (
            "What brAIn has measured about this house and what it is still "
            "collecting: the wake/settle rhythm, per-entity baselines, each "
            "room's heat model, how often closures are open, appliance power "
            "shapes, hand-driven habits, and last week's energy. Each answers "
            "with a state (not_started / collecting / ready / unavailable / "
            "stale), how far along it is, and one sentence. Read it before "
            "calling a house quiet or a reading normal — a measurement that "
            "has not been made yet says nothing, which is not the same as "
            "saying nothing is wrong."
        ),
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "what_is_normal",
        "description": (
            "What one numeric entity normally reads, how far from that it is "
            "RIGHT NOW in its own spreads, and which way it has been heading "
            "over the month. The first thing to call before saying a reading "
            "is high, low or odd: a threshold you would guess is the same one "
            "for a freezer and a water meter, and this is measured from this "
            "house. `get_baseline` has the hour-of-week detail."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"entity_id": {"type": "string",
                                         "description": "The entity ID"}},
            "required": ["entity_id"]
        }
    },
    {
        "name": "room_physics",
        "description": (
            "How fast a room loses heat and how fast it warms, measured per "
            "room from a month of nights: the loss rate, the time constant, "
            "the gain with the heating on, and how long the coldest night's "
            "climb took. For pre-heat timing, 'is a window open', setback "
            "costs and freeze risk — questions a threshold cannot answer "
            "because every house and every room differs by an order of "
            "magnitude."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"area": {"type": "string",
                                    "description": "The area name or id"}},
            "required": ["area"]
        }
    },
    {
        "name": "appliance_status",
        "description": (
            "Whether a machine on a power sensor is idle, running, or "
            "finished-and-waiting, by thresholds measured from ITS OWN power "
            "shape rather than a wattage somebody typed. 'Is the dishwasher "
            "done' and 'has the washing been taken out' — the second is a "
            "question no power reading can answer, and the tool says so."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"entity_id": {"type": "string",
                                         "description": "The power sensor"}},
            "required": ["entity_id"]
        }
    },
    {
        "name": "house_rhythm",
        "description": (
            "When this house gets up and settles for the night — weekdays "
            "and weekends measured apart, with the spread — from the first "
            "and last thing a person did each day. For anything scheduled "
            "'in the morning' or 'at bedtime': 07:00 is early on a Sunday "
            "and late on a Tuesday in the same house."
        ),
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "door_habits",
        "description": (
            "How much of each hour of the week a door, window, lock, cover "
            "or garage is USUALLY open in this house, time-weighted over the "
            "weeks watched. 'Is it odd that the back door is open at 23:40' "
            "has a different answer in a house that shuts it every night and "
            "one that airs the kitchen all summer."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"entity_id": {"type": "string",
                                         "description": "The closure's entity ID"}},
            "required": ["entity_id"]
        }
    },
    {
        "name": "habits",
        "description": (
            "What a person does with this entity BY HAND often enough to be "
            "a habit — which days, at what time, how reliably, and whether "
            "it is still happening — plus which automations they keep "
            "undoing about it and whether something already automates it. "
            "The evidence behind 'you seem to do this every evening; want "
            "an automation for it'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"entity_id": {"type": "string",
                                         "description": "The entity ID"}},
            "required": ["entity_id"]
        }
    },
    {
        "name": "simulate_automation",
        "description": (
            "Replay an automation config over the last N days of recorded "
            "history — calling nothing — to see when it WOULD have fired, "
            "and grade each firing against what a person actually did in "
            "that window (agreed, contradicted, nothing). The sanity check "
            "to run on any automation before proposing it. Only time, "
            "state, numeric_state and template triggers can be replayed; "
            "anything else is refused whole rather than counted wrongly."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "config": {"type": "object",
                           "description": "A Home Assistant automation object: trigger(s), condition(s), action(s)"},
                "days": {"type": "integer", "description": "How many days back (1–28, default 7)"}
            },
            "required": ["config"]
        }
    },
    {
        "name": "recall",
        "description": (
            "What brAIn remembers about something: ranked facts with who "
            "taught each one and when. Ask by subject — an entity id, "
            "`area:<id>`, `person:<id>` or `house` — or by a few words. Read "
            "it before contradicting the homeowner about their own house: a "
            "`correction` is them saying brAIn had it wrong, and an "
            "`exception:` predicate is a rule they have told to stand down."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "A few words to match"},
                "subject": {"type": "string", "description": "An entity id, area:<id>, person:<id> or house"},
                "limit": {"type": "integer", "description": "At most this many (default 10)"}
            }
        }
    },
    {
        "name": "get_findings",
        "description": (
            "What brAIn has found wrong with this house and is waiting on the "
            "homeowner about: the Findings tab, as rows — each with what is "
            "wrong, the detail, what to do, the entity, who raised it and "
            "what the look before it was shown concluded. Use it for 'what "
            "needs attention', 'is anything broken', 'what should I do "
            "today', and before reporting a problem the house already "
            "knows about. Read-only; it changes nothing and settles nothing."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": ("Which rows: 'open' (default — waiting on a "
                                    "person, the tab's own list), 'held' "
                                    "(looked at and judged not worth showing), "
                                    "or 'all'.")
                },
                "limit": {
                    "type": "number",
                    "description": "Most rows to return (1-200, default 50)"
                }
            }
        }
    },
    {
        "name": "get_health",
        "description": (
            "Whether brAIn itself is working, in its own words: the health "
            "verdict (ok / degraded / failed) with the sentence and the "
            "switch for the worst thing found, whether it is signed in, what "
            "the usage sensors last said, and which of its background jobs "
            "are running. Use it when somebody asks whether brAIn is OK, why "
            "the usage figure is missing, or why nothing has run. Read-only."
        ),
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "get_activity",
        "description": (
            "What changed in the house recently, with a cause on every row, plus "
            "the times a person undid something an automation had just done. Use "
            "it for 'what happened last night', 'what has brAIn been doing', and "
            "for finding the automations this house is fighting with."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "hours": {
                    "type": "number",
                    "description": ("How many hours back, default 24. The panel caps how "
                                    "long one window may be; ask about an "
                                    "earlier day by asking about it, not by "
                                    "widening the window.")
                },
                "cause": {
                    "type": "string",
                    "description": (
                        "Only rows with this cause: brain, automation, script, "
                        "scene, voice, person, unattributed"
                    )
                },
                "limit": {
                    "type": "number",
                    "description": "Most rows to return (1-1000, default 200)"
                }
            }
        }
    },
    {
        "name": "get_statistics",
        "description": (
            "Get long-term statistics (hourly/daily mean, min, max) for a numeric "
            "sensor — survives recorder purging, so it answers 'how cold did it "
            "get last week/month'. Only works for sensors with a state_class."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "The sensor entity ID (e.g., 'sensor.outdoor_temperature')"
                },
                "period": {
                    "type": "string",
                    "enum": ["5minute", "hour", "day", "week", "month"],
                    "description": "Aggregation bucket (default 'hour')"
                },
                "days": {
                    "type": "number",
                    "description": "How many days back (1-365, default 7)"
                }
            },
            "required": ["entity_id"]
        }
    },
    {
        "name": "get_weather_forecast",
        "description": (
            "Get the weather forecast (daily, hourly, or twice_daily) for a "
            "weather entity. Use this for 'what's the weather tomorrow / this "
            "week' — current conditions come from get_entity_state instead."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "The weather entity ID (e.g., 'weather.home')"
                },
                "forecast_type": {
                    "type": "string",
                    "enum": ["daily", "hourly", "twice_daily"],
                    "description": "Forecast granularity (default 'daily')"
                }
            },
            "required": ["entity_id"]
        }
    },
    {
        "name": "get_error_log",
        "description": "Get the last 100 lines of Home Assistant logs from the Supervisor journal. Useful for diagnosing integration issues, failed automations, and system errors.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "render_template",
        "description": "Render a Jinja2 template in Home Assistant. Useful for testing template sensors, evaluating conditions, and computing values.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "template": {
                    "type": "string",
                    "description": "The Jinja2 template string to render (e.g., '{{ states(\"sensor.temperature\") }}')"
                }
            },
            "required": ["template"]
        }
    },
    {
        "name": "fire_event",
        "description": "Fire a custom event in Home Assistant. Can be used to trigger automations that listen for specific events.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "event_type": {
                    "type": "string",
                    "description": "The event type to fire (e.g., 'custom_event')"
                },
                "event_data": {
                    "type": "object",
                    "description": "Optional event data payload"
                }
            },
            "required": ["event_type"]
        }
    },
    {
        "name": "get_supervisor_info",
        "description": "Get Home Assistant Supervisor system information including core version, host details, and add-on count.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "remember_fact",
        "description": (
            "Remember a durable fact about this household for future "
            "conversations — a preference, correction, entity nickname, or "
            "pattern (e.g. \"the family calls the office lamp 'the "
            "beacon'\", \"always leave the porch light on at night\"). Do "
            "NOT store transient states, one-off commands, or secrets."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "fact": {
                    "type": "string",
                    "description": "The durable fact to remember, phrased as one short standalone sentence."
                },
                "subject": {
                    "type": "string",
                    "description": "What the fact is about: an entity id, area:<id>, person:<id> or house"
                },
                "person": {
                    "type": "string",
                    "description": "The person this preference belongs to, if it is theirs and not the house's"
                },
                "confidence": {
                    "type": "string",
                    "enum": ["high", "medium", "low"],
                    "description": "How certain the fact is (default 'high' — the user stated it directly)."
                }
            },
            "required": ["fact"]
        }
    },
    {
        "name": "reload_config",
        "description": "Reload a specific Home Assistant configuration area after making YAML changes. Valid targets: automations, scripts, scenes, groups, input_booleans, input_numbers, input_selects, input_texts, input_datetimes, timers, counters, core, all.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "What to reload: automations, scripts, scenes, groups, input_booleans, input_numbers, input_selects, input_texts, input_datetimes, timers, counters, core, all"
                }
            },
            "required": ["target"]
        }
    },
    {
        "name": "offer_resolutions",
        "description": (
            "Offer the homeowner the ways the finding you are discussing "
            "could end, as buttons under your message. Use it once you have "
            "looked into the problem and can name what would actually "
            "settle it. Each option's label is BOTH the button and what "
            "gets recorded, so write it in the voice of its kind: 'done' is "
            "something they have already done (\"Replaced the CR2032\"), "
            "'todo' is work to put on their list (\"Replace the CR2032 in "
            "the garage sensor\"), 'wrong' is a fact about the house that "
            "means this was never a problem (\"That cupboard is never "
            "opened\"). 'advice' is the fourth kind and is not an ending: "
            "its label is what you would tell them to DO about it, specific "
            "to this house (\"Power-cycle the Tuya hub in the garage — the "
            "other three valves on it are answering\"), and pressing it "
            "replaces the generic 'What you'd need to do' on the card with "
            "that sentence while the finding stays open. Offer only endings "
            "your own investigation supports, and leave out any you cannot "
            "justify — two honest options beat four. This changes nothing "
            "by itself: nothing is settled until they press, and you are not "
            "told whether they did. It works only inside a finding "
            "discussion."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "options": {
                    "type": "array",
                    "maxItems": 4,
                    "description": "Up to 4 ways this could end, best first.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {
                                "type": "string",
                                "description": "What the button says, and what gets recorded. One short line, in the voice of its kind."
                            },
                            "kind": {
                                "type": "string",
                                "enum": ["done", "todo", "wrong", "advice"],
                                "description": "done = they have already done this, and it goes into memory as a fix. todo = work for their to-do list, written as an instruction. wrong = brAIn has misread the house, and the label is the correction. advice = not an ending: the label becomes the card's 'What you'd need to do', specific to this house, and the finding stays open."
                            }
                        },
                        "required": ["label", "kind"]
                    }
                }
            },
            "required": ["options"]
        }
    },
]


# ============================================================================
# Tool Call Router
# ============================================================================

# Single source of truth mapping tool name -> implementation function name.
# Arguments from the MCP request are matched to the function's parameters by
# name (every implementation's signature mirrors its inputSchema), so adding
# a tool is: write the function, add its schema to TOOLS, add one line here.
# Names (not references) keep the lookup late-bound, so tests can patch
# implementations on the module.
TOOL_IMPLEMENTATIONS = {
    # Core tools
    "get_entity_state": "get_entity_state",
    "get_all_states": "get_all_states",
    "call_service": "call_service",
    "get_service_details": "get_service_details",
    "get_registry": "get_registry",
    "list_dashboards": "list_dashboards",
    "get_dashboard": "get_dashboard",
    # Domain-specific device control
    "control_light": "control_light",
    "control_climate": "control_climate",
    "control_media_player": "control_media_player",
    "control_cover": "control_cover",
    "control_fan": "control_fan",
    "control_switch": "control_switch",
    "control_lock": "control_lock",
    "control_alarm": "control_alarm",
    "control_vacuum": "control_vacuum",
    "send_notification": "send_notification",
    "activate_scene": "activate_scene",
    "run_script": "run_script",
    # Vision
    "get_camera_snapshot": "get_camera_snapshot",
    # System tools
    "get_automations": "get_automations",
    "get_automation_trace": "get_automation_trace",
    "get_ha_config": "get_config",
    "get_services": "get_services",
    "get_device_registry": "get_device_registry",
    "get_areas": "get_areas",
    "get_logbook": "get_logbook",
    "get_history": "get_history",
    "explain_change": "explain_change",
    "get_baseline": "get_baseline",
    "get_activity": "get_activity",
    "get_house_model": "get_house_model",
    # The measurements as tools (2.2): every store the checks read,
    # readable by every run, over the panel's own routes.
    "what_is_normal": "what_is_normal",
    "room_physics": "room_physics",
    "appliance_status": "appliance_status",
    "house_rhythm": "house_rhythm",
    "door_habits": "door_habits",
    "habits": "habits",
    "simulate_automation": "simulate_automation",
    "recall": "recall",
    "get_findings": "get_findings",
    "get_health": "get_health",
    "get_statistics": "get_statistics",
    "get_weather_forecast": "get_weather_forecast",
    "get_error_log": "get_error_log",
    "render_template": "render_template",
    "fire_event": "fire_event",
    "get_supervisor_info": "get_supervisor_info",
    "reload_config": "reload_config",
    # Memory / learning
    "remember_fact": "remember_fact",
    # Talking to the person who is reading
    "offer_resolutions": "offer_resolutions",
    # ESPHome devices
    "esphome_list_devices": "esphome_list_devices",
    "esphome_get_config": "esphome_get_config",
    "esphome_write_config": "esphome_write_config",
    "esphome_create_device": "esphome_create_device",
    "esphome_delete_device": "esphome_delete_device",
    "esphome_validate": "esphome_validate",
    "esphome_compile": "esphome_compile",
    "esphome_install": "esphome_install",
    "esphome_update_firmware": "esphome_update_firmware",
    "esphome_clean": "esphome_clean",
    "esphome_logs": "esphome_logs",
    "esphome_job": "esphome_job",
    "esphome_set_secret": "esphome_set_secret",
    # Music Assistant
    "music_assistant_status": "music_assistant_status",
    "music_assistant_query": "music_assistant_query",
    "music_assistant_search": "music_assistant_search",
    "music_assistant_command": "music_assistant_command",
    "music_assistant_player": "music_assistant_player",
    "music_assistant_play": "music_assistant_play",
    "music_assistant_remove_players": "music_assistant_remove_players",
    "minecraft_status": "minecraft_status",
    "minecraft_teleport": "minecraft_teleport",
    "minecraft_player": "minecraft_player",
    "minecraft_world": "minecraft_world",
    "minecraft_command": "minecraft_command",
    "minecraft_server": "minecraft_server",
    "minecraft_addons": "minecraft_addons",
    "label_printer_status": "label_printer_status",
    "print_label": "print_label",
    "bright_status": "bright_status",
    "bright_show": "bright_show",
}


# Argument contracts derived from the schemas themselves: the inputSchema is
# the single source of truth for which arguments a tool accepts/requires.
_TOOL_SPECS = {
    schema["name"]: (
        set(schema.get("inputSchema", {}).get("properties", {})),
        list(schema.get("inputSchema", {}).get("required", [])),
    )
    for schema in TOOLS
}


# The voice channel's second half. The per-tool checks above
# (`_entity_exposed` in get_entity_state, get_history, get_statistics,
# call_service, get_all_states) cover the tools voice uses every day; they
# did not cover the tools that reach the same entities some other way — a
# template can read any state, the logbook and activity list the whole
# house, and brAIn's own read tools (what is normal, why did this change,
# habits, findings) answer about any entity named. So a voice agent told
# "that sensor is not exposed" could be talked round it with "use brAIn".
# One gate, at the dispatcher, so a tool added later is covered by being a
# tool: refused outright if it reads house-wide, allowed only for exposed
# entities if it is about one, and a template only when every entity it
# names is exposed and it names them literally.
VOICE_REFUSED_TOOLS = frozenset({
    "get_registry", "get_device_registry", "list_dashboards", "get_dashboard",
    "get_automations", "get_automation_trace", "get_activity",
    "get_house_model", "room_physics", "simulate_automation", "get_findings",
    "get_health", "get_error_log", "fire_event", "get_supervisor_info",
    "reload_config", "offer_resolutions",
})
VOICE_REFUSED_PREFIXES = ("esphome_",)
# Tools about ONE entity: allowed only when it is named and exposed.
VOICE_ENTITY_TOOLS = frozenset({
    "get_baseline", "explain_change", "what_is_normal", "appliance_status",
    "door_habits", "habits", "get_camera_snapshot", "get_weather_forecast",
    "get_logbook",
})
VOICE_WIDER = (" This voice agent only reaches what Home Assistant exposes to "
               "Assist; its access can be raised in the brAIn agent's settings. "
               "Tell the user that; do not try another way.")
_TEMPLATE_ID_RE = re.compile(r"\b([a-z_]+\.[a-z0-9_]+)\b")
# A template that reaches entities without naming them: enumerating a
# domain or the whole state machine, expanding a group, walking an area,
# device, label, floor or integration, or looking an id up from a variable.
_TEMPLATE_DYNAMIC_RE = re.compile(
    r"states\s*(\||\[|\(\s*\)|\.\s*[a-z_]+\s*(?![.\w]))"
    r"|\bexpand\s*\("
    r"|\b(area|device|label|floor|integration)_entities\s*\("
    r"|\b(states|is_state|state_attr|is_state_attr|has_value|state_translated)"
    r"\s*\(\s*[^'\"\s)]")


def _template_refusal(template):
    text = str(template or "")
    if _TEMPLATE_DYNAMIC_RE.search(text):
        return ("this template reaches entities without naming them, and "
                "voice may only read the entities exposed to it — name each "
                "entity id in quotes")
    if _exposure() is None:
        return ("Home Assistant's exposure settings could not be read, and "
                "voice may only read what is exposed to it")
    for eid in _TEMPLATE_ID_RE.findall(text):
        domain = eid.split(".", 1)[0]
        if domain in _TEMPLATE_NOT_ENTITY:
            continue
        if not _entity_exposed(eid):
            return UNEXPOSED_READ.format(eid=eid)
    return None


# Dotted names in a template that are not entity ids: filters, attribute
# access on loop variables and the like never start with these.
_TEMPLATE_NOT_ENTITY = frozenset({
    "states", "state", "trigger", "this", "now", "ns", "loop", "self",
    "value", "value_json", "item", "x", "e", "s", "a", "attr", "attributes",
})


def _voice_refusal(name, kwargs):
    """Why a voice agent limited to exposed entities may not make this call."""
    if not EXPOSED_ONLY:
        return None
    if name in VOICE_REFUSED_TOOLS or name.startswith(VOICE_REFUSED_PREFIXES):
        return (f"{name} reads across the whole house, including entities not "
                "exposed to voice assistants." + VOICE_WIDER)
    if name == "render_template":
        why = _template_refusal(kwargs.get("template"))
        return (why + "." + VOICE_WIDER) if why else None
    if name in VOICE_ENTITY_TOOLS:
        eid = str(kwargs.get("entity_id") or "").strip()
        if not eid:
            return (f"{name} without an entity id reads the whole house; "
                    "name an exposed entity." + VOICE_WIDER)
        if not _entity_exposed(eid):
            return UNEXPOSED_READ.format(eid=eid) + VOICE_WIDER
    return None


def handle_tool_call(name, arguments):
    """Dispatch a tool call.

    Arguments are filtered/validated against the tool's inputSchema, then
    passed as keyword args to the implementation (looked up late via
    globals() so tests can patch implementations on the module).
    """
    fn_name = TOOL_IMPLEMENTATIONS.get(name)
    spec = _TOOL_SPECS.get(name)
    if fn_name is None or spec is None:
        return {"error": f"Unknown tool: {name}"}
    allowed, required = spec
    kwargs = {k: v for k, v in (arguments or {}).items() if k in allowed}
    missing = [p for p in required if p not in kwargs]
    if missing:
        return {"error": f"Missing required argument(s) for {name}: {', '.join(missing)}"}
    refused = _voice_refusal(name, kwargs)
    if refused:
        return {"error": refused}
    try:
        return globals()[fn_name](**kwargs)
    except Exception as e:
        return {"error": str(e)}


def build_tool_response(result):
    """Build the MCP content payload for a tool result.

    Results are JSON text blocks, except when a tool returns an image
    envelope ({"_mcp_image": {"data": <b64>, "mimeType": ...}, ...}) —
    those become an MCP image content block plus a text block with any
    remaining metadata.
    """
    if isinstance(result, dict) and "_mcp_image" in result:
        image = result["_mcp_image"]
        meta = {k: v for k, v in result.items() if k != "_mcp_image"}
        content = [{
            "type": "image",
            "data": image.get("data", ""),
            "mimeType": image.get("mimeType", "image/jpeg"),
        }]
        if meta:
            content.append({
                "type": "text",
                "text": json.dumps(meta, indent=2, default=str),
            })
        return {"content": content}

    result_text = json.dumps(result, indent=2, default=str)
    response_obj = {
        "content": [{"type": "text", "text": result_text}],
    }
    if isinstance(result, dict) and "error" in result:
        response_obj["isError"] = True
    return response_obj


# ============================================================================
# MCP Protocol Implementation
# ============================================================================

def send_response(response_id, result):
    """Send a JSON-RPC response to stdout."""
    response = {
        "jsonrpc": "2.0",
        "id": response_id,
        "result": result,
    }
    msg = json.dumps(response)
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def send_error(response_id, code, message):
    """Send a JSON-RPC error response."""
    response = {
        "jsonrpc": "2.0",
        "id": response_id,
        "error": {"code": code, "message": message},
    }
    msg = json.dumps(response)
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def main():
    """Main MCP server loop - reads JSON-RPC from stdin, responds on stdout."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            send_error(None, -32700, "Parse error")
            continue

        req_id = request.get("id")
        method = request.get("method", "")
        params = request.get("params", {})

        if method == "initialize":
            send_response(req_id, {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {},
                },
                "serverInfo": {
                    "name": "home-assistant",
                    "version": "1.0.0",
                },
            })

        elif method == "notifications/initialized":
            # No response needed for notifications
            pass

        elif method == "resources/list":
            send_response(req_id, {"resources": []})

        elif method == "prompts/list":
            send_response(req_id, {"prompts": []})

        elif method == "tools/list":
            send_response(req_id, {"tools": TOOLS})

        elif method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            result = handle_tool_call(tool_name, arguments)
            send_response(req_id, build_tool_response(result))

        elif method == "ping":
            send_response(req_id, {})

        else:
            send_error(req_id, -32601, f"Method not found: {method}")


if __name__ == "__main__":
    main()
