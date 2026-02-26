#!/usr/bin/env python3
"""
Home Assistant MCP Server for BRUH Claude Terminal

Provides Claude Code with real-time access to Home Assistant via the
Model Context Protocol (MCP). This server exposes HA entity states,
service calls, automation traces, device registry, area registry,
and log access as MCP tools.

Runs as a stdio-based MCP server that Claude Code launches automatically.
"""

import asyncio
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


def ha_api_request(endpoint, method="GET", data=None):
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

    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        return {"error": f"HTTP {e.code}: {e.reason}", "details": error_body}
    except Exception as e:
        return {"error": str(e)}


# ============================================================================
# MCP Tool Implementations
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


def get_all_states(domain=None):
    """Get states of all entities, optionally filtered by domain."""
    result = ha_api_request("/api/states")
    if isinstance(result, list):
        if domain:
            result = [e for e in result if e.get("entity_id", "").startswith(f"{domain}.")]
        return [
            {
                "entity_id": e.get("entity_id"),
                "state": e.get("state"),
                "friendly_name": e.get("attributes", {}).get("friendly_name", ""),
            }
            for e in result
        ]
    return result


def call_service(domain, service, data=None):
    """Call a Home Assistant service."""
    payload = data or {}
    result = ha_api_request(f"/api/services/{domain}/{service}", method="POST", data=payload)
    return result


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
    """Get recent traces for an automation."""
    result = ha_api_request(f"/api/trace/automation/{automation_id}")
    return result


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
    """Get device registry via websocket-compatible endpoint."""
    # Use the template endpoint to extract device info
    result = ha_api_request(
        "/api/template",
        method="POST",
        data={"template": "{{ states | map(attribute='entity_id') | list | length }} entities total"}
    )
    # Fallback: get areas and devices from states
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
    start = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    endpoint = f"/api/logbook/{start}"
    if entity_id:
        endpoint += f"?entity={entity_id}"
    result = ha_api_request(endpoint)
    if isinstance(result, list):
        return result[:50]  # Limit to 50 entries
    return result


def get_error_log():
    """Get the Home Assistant error log."""
    result = ha_api_request("/api/error_log")
    if isinstance(result, str):
        lines = result.strip().split("\n")
        return "\n".join(lines[-100:])  # Last 100 lines
    return result


def render_template(template_str):
    """Render a Jinja2 template in Home Assistant."""
    result = ha_api_request(
        "/api/template",
        method="POST",
        data={"template": template_str}
    )
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
# MCP Protocol Implementation
# ============================================================================

TOOLS = [
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
        "description": "Get a summary of all entity states in Home Assistant, optionally filtered by domain (e.g., 'light', 'sensor', 'automation', 'switch', 'climate').",
        "inputSchema": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Optional domain filter (e.g., 'light', 'sensor', 'switch', 'automation')"
                }
            }
        }
    },
    {
        "name": "call_service",
        "description": "Call a Home Assistant service. Use this to control devices, trigger automations, and more. Examples: light/turn_on, automation/trigger, switch/toggle.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Service domain (e.g., 'light', 'switch', 'automation', 'climate')"
                },
                "service": {
                    "type": "string",
                    "description": "Service name (e.g., 'turn_on', 'turn_off', 'toggle', 'trigger')"
                },
                "data": {
                    "type": "object",
                    "description": "Optional service data (e.g., {\"entity_id\": \"light.living_room\", \"brightness\": 255})"
                }
            },
            "required": ["domain", "service"]
        }
    },
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
        "description": "Get recent execution traces for a specific automation. Useful for debugging why an automation did or didn't fire.",
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
        "description": "Get a summary of all devices and entity domains registered in Home Assistant.",
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
        "description": "Get the last 100 lines of the Home Assistant error log. Useful for diagnosing integration issues, failed automations, and system errors.",
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


def handle_tool_call(name, arguments):
    """Route a tool call to the appropriate function."""
    try:
        if name == "get_entity_state":
            return get_entity_state(arguments["entity_id"])
        elif name == "get_all_states":
            return get_all_states(arguments.get("domain"))
        elif name == "call_service":
            return call_service(arguments["domain"], arguments["service"], arguments.get("data"))
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

        elif method == "tools/list":
            send_response(req_id, {"tools": TOOLS})

        elif method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            result = handle_tool_call(tool_name, arguments)
            result_text = json.dumps(result, indent=2, default=str)
            send_response(req_id, {
                "content": [{"type": "text", "text": result_text}],
            })

        elif method == "ping":
            send_response(req_id, {})

        else:
            send_error(req_id, -32601, f"Method not found: {method}")


if __name__ == "__main__":
    main()
