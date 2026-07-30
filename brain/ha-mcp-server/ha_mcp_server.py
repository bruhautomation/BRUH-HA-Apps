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
import sys
import time
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


def _service_denied(domain, service):
    """True if calling domain.service is forbidden for this channel."""
    target = f"{domain}.{service}".lower()
    for pattern in DENIED_SERVICES:
        if pattern == target or pattern == f"{domain.lower()}.*" or pattern == "*":
            return True
    return False


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
    payload = data or {}
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
    if isinstance(result, list):
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


def get_dashboard(url_path=None, view_index=None):
    """Fetch a dashboard's configuration (default dashboard when url_path
    is omitted). Pair with brain.update_dashboard to edit: fetch,
    modify the JSON, save — the service backs up the old config
    automatically.

    Large dashboards are retrievable in full through view_index: when the
    whole config exceeds MAX_DASHBOARD_BYTES the response is a view
    summary, and each view can then be fetched individually. Never read
    /config/.storage instead — it lags actual state for ~10s after a save
    (HA's delayed writes) and must never be treated as a source of truth.
    """
    try:
        result = _ws_command({"type": "lovelace/config", "url_path": url_path or None},
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
            if url_path:
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
            return {
                "url_path": url_path or "default",
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
            "url_path": url_path or "default",
            "view_index": view_index,
            "view_count": len(views),
            "view": views[view_index],
        }

    payload = {"url_path": url_path or "default", "config": result}
    if len(json.dumps(payload)) > MAX_DASHBOARD_BYTES:
        return {
            "url_path": url_path or "default",
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
    """Fire a Home Assistant event."""
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


def remember_fact(fact, confidence="high"):
    """Queue a durable household fact for the memory consolidator.

    Appends one JSONL record to a fresh inbox file (one file per call —
    lock-free by construction). The brain memory consolidator later merges
    pending records into /config/.brain/memory/memory.md.
    """
    if not isinstance(fact, str) or not fact.strip():
        return {"error": "fact must be a non-empty string"}
    if confidence not in ("high", "medium", "low"):
        confidence = "high"

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


# ============================================================================
# MCP Tool Definitions
# ============================================================================

TOOLS = [
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
                    "description": "Dashboard url_path from list_dashboards; omit for the default dashboard"
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
    "get_statistics": "get_statistics",
    "get_weather_forecast": "get_weather_forecast",
    "get_error_log": "get_error_log",
    "render_template": "render_template",
    "fire_event": "fire_event",
    "get_supervisor_info": "get_supervisor_info",
    "reload_config": "reload_config",
    # Memory / learning
    "remember_fact": "remember_fact",
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
