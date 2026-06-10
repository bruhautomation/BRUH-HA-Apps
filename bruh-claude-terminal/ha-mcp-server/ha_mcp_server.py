#!/usr/bin/env python3
"""
Home Assistant MCP Server for BRUH Claude Terminal

Provides Claude Code with real-time access to Home Assistant via the
Model Context Protocol (MCP). This server exposes HA entity states,
service calls, device control, automation traces, area listings
(via the template engine), and log access as MCP tools.

Runs as a stdio-based MCP server that Claude Code launches automatically.
"""

import json
import os
import sys
import urllib.request
import urllib.error

# ============================================================================
# Configuration
# ============================================================================

SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
HA_BASE_URL = os.environ.get("HA_BASE_URL", "http://supervisor/core/api")
SUPERVISOR_API_URL = os.environ.get("SUPERVISOR_API_URL", "http://supervisor")


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
            needle = name_filter.lower()
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


def call_service(domain, service, data=None):
    """Call a Home Assistant service."""
    payload = data or {}
    result = ha_api_request(f"/api/services/{domain}/{service}", method="POST", data=payload)
    return result


def get_service_details(domain):
    """Get detailed service schemas for a domain."""
    result = ha_api_request("/api/services")
    if isinstance(result, list):
        for svc in result:
            if svc.get("domain") == domain:
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
    hours = max(0.1, min(hours or 1, 24))  # Clamp between 0.1 and 24
    start = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    endpoint = f"/api/logbook/{start}"
    if entity_id:
        endpoint += f"?entity={entity_id}"
    result = ha_api_request(endpoint)
    if isinstance(result, list):
        return result[:50]  # Limit to 50 entries
    return result


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
        return "\n".join(lines[-100:])  # Last 100 lines

    # Fallback: legacy HA Core REST endpoint (works if log file exists)
    if isinstance(result, dict) and "error" in result:
        result = ha_api_request("/api/error_log")
        if isinstance(result, str) and result.strip():
            lines = result.strip().split("\n")
            return "\n".join(lines[-100:])

    if isinstance(result, dict) and "error" in result:
        return {
            "error": "Could not retrieve logs from Supervisor or HA Core. "
                     "Check Settings > System > Logs in the HA UI instead.",
            "details": result.get("details", ""),
        }
    return result or {"error": "No log data available."}


def render_template(template_str):
    """Render a Jinja2 template in Home Assistant."""
    result = ha_api_request(
        "/api/template",
        method="POST",
        data={"template": template_str}
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
                }
            },
            "required": ["domain", "service"]
        }
    },
    {
        "name": "get_service_details",
        "description": "Get the full service schema for a domain, showing all available services and their fields/parameters. Use this to discover what parameters a service accepts before calling it.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "The service domain to look up (e.g., 'light', 'climate', 'media_player', 'vacuum', 'notify')"
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

def handle_tool_call(name, arguments):
    """Route a tool call to the appropriate function."""
    try:
        # Core tools
        if name == "get_entity_state":
            return get_entity_state(arguments["entity_id"])
        elif name == "get_all_states":
            return get_all_states(arguments.get("domain"), arguments.get("name_filter"))
        elif name == "call_service":
            return call_service(arguments["domain"], arguments["service"], arguments.get("data"))
        elif name == "get_service_details":
            return get_service_details(arguments["domain"])

        # Domain-specific device control
        elif name == "control_light":
            return control_light(
                entity_id=arguments["entity_id"],
                action=arguments["action"],
                brightness=arguments.get("brightness"),
                brightness_pct=arguments.get("brightness_pct"),
                rgb_color=arguments.get("rgb_color"),
                hs_color=arguments.get("hs_color"),
                xy_color=arguments.get("xy_color"),
                color_temp_kelvin=arguments.get("color_temp_kelvin"),
                color_name=arguments.get("color_name"),
                effect=arguments.get("effect"),
                transition=arguments.get("transition"),
                flash=arguments.get("flash"),
                white=arguments.get("white"),
            )
        elif name == "control_climate":
            return control_climate(
                entity_id=arguments["entity_id"],
                action=arguments["action"],
                temperature=arguments.get("temperature"),
                target_temp_high=arguments.get("target_temp_high"),
                target_temp_low=arguments.get("target_temp_low"),
                hvac_mode=arguments.get("hvac_mode"),
                fan_mode=arguments.get("fan_mode"),
                preset_mode=arguments.get("preset_mode"),
                humidity=arguments.get("humidity"),
                swing_mode=arguments.get("swing_mode"),
            )
        elif name == "control_media_player":
            return control_media_player(
                entity_id=arguments["entity_id"],
                action=arguments["action"],
                volume_level=arguments.get("volume_level"),
                source=arguments.get("source"),
                media_content_id=arguments.get("media_content_id"),
                media_content_type=arguments.get("media_content_type"),
                seek_position=arguments.get("seek_position"),
                shuffle=arguments.get("shuffle"),
                repeat=arguments.get("repeat"),
            )
        elif name == "control_cover":
            return control_cover(
                entity_id=arguments["entity_id"],
                action=arguments["action"],
                position=arguments.get("position"),
                tilt_position=arguments.get("tilt_position"),
            )
        elif name == "control_fan":
            return control_fan(
                entity_id=arguments["entity_id"],
                action=arguments["action"],
                percentage=arguments.get("percentage"),
                preset_mode=arguments.get("preset_mode"),
                direction=arguments.get("direction"),
                oscillating=arguments.get("oscillating"),
            )
        elif name == "control_switch":
            return control_switch(
                entity_id=arguments["entity_id"],
                action=arguments["action"],
            )
        elif name == "control_lock":
            return control_lock(
                entity_id=arguments["entity_id"],
                action=arguments["action"],
                code=arguments.get("code"),
            )
        elif name == "control_alarm":
            return control_alarm(
                entity_id=arguments["entity_id"],
                action=arguments["action"],
                code=arguments.get("code"),
            )
        elif name == "control_vacuum":
            return control_vacuum(
                entity_id=arguments["entity_id"],
                action=arguments["action"],
                command=arguments.get("command"),
                params=arguments.get("params"),
            )
        elif name == "send_notification":
            return send_notification(
                message=arguments["message"],
                title=arguments.get("title"),
                target=arguments.get("target"),
                data=arguments.get("data"),
            )
        elif name == "activate_scene":
            return activate_scene(
                entity_id=arguments["entity_id"],
                transition=arguments.get("transition"),
            )
        elif name == "run_script":
            return run_script(
                entity_id=arguments["entity_id"],
                variables=arguments.get("variables"),
            )

        # System tools
        elif name == "get_automations":
            return get_automations()
        elif name == "get_automation_trace":
            return get_automation_trace(arguments["automation_id"])
        elif name == "get_ha_config":
            return get_config()
        elif name == "get_services":
            return get_services()
        elif name == "get_device_registry":
            return get_device_registry()
        elif name == "get_areas":
            return get_areas()
        elif name == "get_logbook":
            return get_logbook(arguments.get("hours", 1), arguments.get("entity_id"))
        elif name == "get_error_log":
            return get_error_log()
        elif name == "render_template":
            return render_template(arguments["template"])
        elif name == "fire_event":
            return fire_event(arguments["event_type"], arguments.get("event_data"))
        elif name == "get_supervisor_info":
            return get_supervisor_info()
        elif name == "reload_config":
            return reload_config(arguments["target"])
        else:
            return {"error": f"Unknown tool: {name}"}
    except Exception as e:
        return {"error": str(e)}


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
            result_text = json.dumps(result, indent=2, default=str)
            is_error = isinstance(result, dict) and "error" in result
            response_obj = {
                "content": [{"type": "text", "text": result_text}],
            }
            if is_error:
                response_obj["isError"] = True
            send_response(req_id, response_obj)

        elif method == "ping":
            send_response(req_id, {})

        else:
            send_error(req_id, -32601, f"Method not found: {method}")


if __name__ == "__main__":
    main()
