"""What an acting tool call would touch, resolved in code.

The action gate (`gate.py`) decides allow / ask / deny, and the one thing
it must never do is decide from text a tool returned. So what it is shown
about a proposed call is built HERE, from the call's own arguments and from
the registries, never from anything a model read:

* the **calls** the tool will make — the MCP server's routing, written down
  as a table (`calls_for`) rather than reconstructed from a description;
* the **entities** they reach — named in the payload (the same walk the
  MCP chokepoint makes, `payload_entities`, held equal to it by a test),
  and **expanded** through what a call reaches indirectly: a scene's or a
  script's members, an area's or a device's entities, a group's members;
* for each, its domain, its area's NAME (an admin-set registry field), its
  current state **only when the state is from a closed vocabulary** (a
  light's `on`, a cover's `open`, a number) — a free-text state, an input
  text, a sensor reporting a sentence, is shown as hidden, because a state
  is somebody else's text too — and whether it is protected, exposed to
  Assist, or a tripwire.

What is NOT here, deliberately: friendly names, attributes, tool results.
A friendly name is set by an integration, and an integration is the most
obvious place a hostile string comes from; the gate matches the person's
words against registry area names and entity ids, which is what a person
names when they ask for something.

Pure over a `View` the server builds, so the suite drives every expansion
without a Home Assistant behind it. Stdlib only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

MCP_PREFIX = "mcp__home-assistant__"

# The MCP tools the gate stands in front of: every acting tool on
# `engine.ANALYST_DENIED`, less the ones that change nothing in a house
# (`offer_resolutions` puts buttons on a screen; `send_notification` sends a
# message; `render_template` and `get_camera_snapshot` read). The hook keeps
# its own copy of this set because it must answer without the panel, and a
# test holds the two equal.
GATED_MCP = frozenset({
    "call_service", "control_light", "control_climate",
    "control_media_player", "control_cover", "control_fan", "control_switch",
    "control_lock", "control_alarm", "control_vacuum", "activate_scene",
    "run_script", "reload_config", "fire_event", "remember_fact",
    "bright_show", "print_label", "minecraft_addons", "minecraft_command",
    "minecraft_player", "minecraft_server", "minecraft_teleport",
    "minecraft_world", "music_assistant_command", "music_assistant_play",
    "music_assistant_player", "music_assistant_remove_players",
    "esphome_clean", "esphome_compile", "esphome_create_device",
    "esphome_delete_device", "esphome_install", "esphome_set_secret",
    "esphome_update_firmware", "esphome_write_config",
    "set_device_class", "show_switch_as", "stop_showing_switch_as",
    "set_sensor_display",
})
# Built-in tools the gate reads only while a change contract is in force:
# under one, a file edit outside its files is off the contract and a shell
# command is read-only. Outside a contract the terminal is somebody's
# shell, and gating every `ls` behind a model would be a gate nobody keeps.
CONTRACT_BUILTINS = frozenset({"Bash", "Write", "Edit", "MultiEdit",
                               "NotebookEdit"})

_ENTITY_KEYS = frozenset({"entity_id", "entity_ids", "entities",
                          "snapshot_entities", "group_members"})
_ENTITY_TOKEN_RE = re.compile(r"^[a-z_][a-z0-9_]*\.[a-z0-9_]+$")
SCOPE_KEYS = ("area_id", "device_id", "label_id", "floor_id")
SCAN_DEPTH = 12
MAX_ENTITIES = 60

# The containers whose members a call reaches without naming them.
CONTAINER_DOMAINS = frozenset({"scene", "script", "automation", "group"})

# States from a closed vocabulary, which may be shown. Anything else that
# is not a number is somebody's text and is shown as hidden.
CLOSED_STATES = frozenset({
    "on", "off", "open", "closed", "opening", "closing", "stopped",
    "locked", "unlocked", "locking", "unlocking", "jammed", "home",
    "not_home", "playing", "paused", "idle", "standby", "buffering",
    "heat", "cool", "auto", "dry", "fan_only", "heat_cool", "disarmed",
    "armed_home", "armed_away", "armed_night", "armed_vacation",
    "armed_custom_bypass", "arming", "pending", "triggered", "cleaning",
    "docked", "returning", "error", "unavailable", "unknown", "above_horizon",
    "below_horizon", "detected", "clear",
})

# control_* actions → service names, the MCP server's own routing.
_CONTROL = {
    "control_light": ("light", {"on": "turn_on", "off": "turn_off",
                                "toggle": "toggle"}),
    "control_fan": ("fan", {"on": "turn_on", "off": "turn_off",
                            "toggle": "toggle", "set_percentage":
                            "set_percentage", "set_preset_mode":
                            "set_preset_mode", "set_direction":
                            "set_direction", "oscillate": "oscillate"}),
    "control_cover": ("cover", {"open": "open_cover", "close": "close_cover",
                                "stop": "stop_cover", "toggle": "toggle",
                                "set_position": "set_cover_position",
                                "set_tilt": "set_cover_tilt_position"}),
    "control_lock": ("lock", {"lock": "lock", "unlock": "unlock",
                              "open": "open"}),
    "control_alarm": ("alarm_control_panel", {
        "arm_away": "alarm_arm_away", "arm_home": "alarm_arm_home",
        "arm_night": "alarm_arm_night", "arm_vacation": "alarm_arm_vacation",
        "arm_custom": "alarm_arm_custom_bypass", "disarm": "alarm_disarm",
        "trigger": "alarm_trigger"}),
    "control_vacuum": ("vacuum", {"return_home": "return_to_base"}),
    "control_climate": ("climate", {"off": "turn_off", "on": "turn_on",
                                    "set_temperature": "set_temperature",
                                    "set_hvac_mode": "set_hvac_mode",
                                    "set_fan_mode": "set_fan_mode",
                                    "set_preset_mode": "set_preset_mode",
                                    "set_humidity": "set_humidity",
                                    "set_swing_mode": "set_swing_mode"}),
    "control_media_player": ("media_player", {
        "play": "media_play", "pause": "media_pause", "stop": "media_stop",
        "play_pause": "media_play_pause", "next": "media_next_track",
        "previous": "media_previous_track", "volume_unmute": "volume_mute",
        "set_volume": "volume_set"}),
}

# What may pass with no model: one entity, put somewhere it can be put
# straight back from, in a room the person named. A switch is deliberately
# absent — it drives an appliance, and "turn off the kitchen" reaching a
# freezer's plug is exactly the mistake a model should be asked about.
FAST_PATH = {
    "light": {"turn_on", "turn_off", "toggle"},
    "fan": {"turn_on", "turn_off", "toggle", "set_percentage",
            "oscillate", "set_direction", "set_preset_mode"},
    "media_player": {"media_play", "media_pause", "media_stop",
                     "volume_set", "volume_up", "volume_down", "volume_mute",
                     "media_next_track", "media_previous_track", "turn_on",
                     "turn_off"},
    "climate": {"set_temperature", "set_fan_mode", "set_preset_mode",
                "set_humidity", "set_swing_mode"},
    "cover": {"close_cover", "stop_cover", "set_cover_tilt_position"},
    "input_boolean": {"turn_on", "turn_off", "toggle"},
}
# Covers whose opening opens the house; never reversible-by-default.
SECURITY_COVER_CLASSES = frozenset({"garage", "door", "gate"})


@dataclass
class View:
    """What the server knows about the house, for one decision."""

    states: dict = field(default_factory=dict)          # eid → state row
    entity_area: dict = field(default_factory=dict)     # eid → area id
    area_names: dict = field(default_factory=dict)      # area id → name
    area_entities: dict = field(default_factory=dict)   # area id → [eid]
    device_entities: dict = field(default_factory=dict)  # device id → [eid]
    members: dict = field(default_factory=dict)         # container → [eid]
    protected: list = field(default_factory=list)       # patterns
    exposed: set | None = None                          # None: not asked
    honeytokens: set = field(default_factory=set)


def tool_kind(full: str) -> tuple[str, str]:
    """('mcp', short) | ('builtin', name) | ('other', name)."""
    full = str(full or "")
    if full.startswith(MCP_PREFIX):
        return "mcp", full[len(MCP_PREFIX):]
    if full in CONTRACT_BUILTINS or full in ("WebFetch", "WebSearch", "Read",
                                             "Glob", "Grep"):
        return "builtin", full
    return "other", full


def is_gated(full: str, under_contract: bool) -> bool:
    kind, short = tool_kind(full)
    if kind == "mcp":
        return short in GATED_MCP
    return under_contract and kind == "builtin" and short in CONTRACT_BUILTINS


def _entity_key(key) -> bool:
    key = str(key).lower()
    return (key in _ENTITY_KEYS or key.endswith("_entity_id")
            or key.endswith("_entity_ids"))


def _entity_values(value) -> list[str]:
    if isinstance(value, str):
        return [x.strip() for x in value.split(",") if x.strip()]
    if isinstance(value, (list, tuple)):
        out = []
        for item in value:
            if isinstance(item, str):
                out.extend(x.strip() for x in item.split(",") if x.strip())
        return out
    if isinstance(value, dict):
        return [str(k).strip() for k in value if str(k).strip()]
    return []


def _dedupe(items) -> list:
    seen: set = set()
    return [i for i in items if not (i in seen or seen.add(i))]


def payload_entities(payload) -> tuple[list[str], list[str]]:
    """(named, loose) — `ha_mcp_server._payload_entities`, the same walk.

    Written twice because the panel cannot import the MCP server at run
    time (it is a different process with a different path), and held equal
    by a test that drives both over the same payloads.
    """
    named: list[str] = []
    loose: list[str] = []

    def walk(node, depth):
        if depth > SCAN_DEPTH:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                if _entity_key(key):
                    named.extend(_entity_values(value))
                    if isinstance(value, dict):
                        walk(list(value.values()), depth + 1)
                    continue
                if isinstance(key, str) and _ENTITY_TOKEN_RE.match(
                        key.strip().lower()):
                    loose.append(key.strip())
                walk(value, depth + 1)
        elif isinstance(node, (list, tuple)):
            for item in node:
                walk(item, depth + 1)
        elif isinstance(node, str):
            for part in node.split(","):
                token = part.strip()
                if _ENTITY_TOKEN_RE.match(token.lower()):
                    loose.append(token)

    walk(payload if isinstance(payload, (dict, list)) else {}, 0)
    named = _dedupe(named)
    lowered = {n.lower() for n in named}
    return named, _dedupe(t for t in loose if t.lower() not in lowered)


def calls_for(short: str, args: dict) -> list[dict]:
    """The `{domain, service, data}` calls an MCP tool will make."""
    args = args if isinstance(args, dict) else {}
    if short == "call_service":
        data = args.get("data") if isinstance(args.get("data"), dict) else {}
        return [{"domain": str(args.get("domain") or ""),
                 "service": str(args.get("service") or ""), "data": data}]
    if short in _CONTROL:
        domain, table = _CONTROL[short]
        action = str(args.get("action") or "")
        service = table.get(action) or action
        data = {k: v for k, v in args.items() if k not in ("action",)}
        return [{"domain": domain, "service": service, "data": data}]
    if short == "control_switch":
        eid = str(args.get("entity_id") or "")
        domain = eid.split(".", 1)[0] if "." in eid else "switch"
        action = str(args.get("action") or "")
        service = {"on": "turn_on", "off": "turn_off"}.get(action, action)
        return [{"domain": domain, "service": service,
                 "data": {"entity_id": eid}}]
    if short == "activate_scene":
        return [{"domain": "scene", "service": "turn_on",
                 "data": {"entity_id": args.get("entity_id")}}]
    if short == "run_script":
        return [{"domain": "script", "service": "turn_on",
                 "data": {"entity_id": args.get("entity_id"),
                          "variables": args.get("variables") or {}}}]
    if short == "reload_config":
        return [{"domain": str(args.get("target") or "config"),
                 "service": "reload", "data": {}}]
    if short == "fire_event":
        return [{"domain": "event", "service": str(args.get("event_type")
                                                   or ""),
                 "data": args.get("event_data") or {}}]
    if short == "remember_fact":
        return [{"domain": "memory", "service": "remember",
                 "data": {"fact": args.get("fact"),
                          "subject": args.get("subject")}}]
    # Another add-on's tool: the call is the tool and its arguments.
    return [{"domain": short.split("_", 1)[0], "service": short, "data": args}]


def shown_state(row) -> str:
    """A state, or `(not shown)` when it is not from a closed vocabulary."""
    if not isinstance(row, dict) or "state" not in row:
        return "(could not read)"
    state = str(row.get("state"))
    if state in CLOSED_STATES:
        return state
    try:
        float(state)
        return state[:16]
    except ValueError:
        return "(not shown)"


def _is_protected(eid: str, patterns) -> bool:
    eid = eid.lower()
    for raw in patterns or []:
        pat = str(raw).strip().lower()
        if not pat:
            continue
        if pat == "*" or pat == eid:
            return True
        if pat.endswith(".*") and eid.startswith(pat[:-1]):
            return True
    return False


def resolve(full_tool: str, args: dict, view: View) -> dict:
    """The consequence set: calls, entities (expanded), what is unresolved."""
    kind, short = tool_kind(full_tool)
    out: dict = {"tool": short, "kind": kind, "calls": [], "entities": [],
                 "unresolved": [], "scopes": []}
    if kind != "mcp":
        return out
    calls = calls_for(short, args)
    seen: dict[str, dict] = {}

    def add(eid: str, via: str):
        eid = str(eid).strip().lower()
        if not _ENTITY_TOKEN_RE.match(eid) or eid in seen:
            return
        if len(seen) >= MAX_ENTITIES:
            out["unresolved"].append("more entities than the gate lists")
            return
        area = view.entity_area.get(eid) or ""
        state = view.states.get(eid)
        seen[eid] = {
            "entity_id": eid, "domain": eid.split(".", 1)[0],
            "area": view.area_names.get(area, area) if area else "",
            "state": shown_state(state),
            "device_class": str(((state or {}).get("attributes") or {})
                                .get("device_class") or "")[:32],
            "protected": _is_protected(eid, view.protected),
            "exposed": (None if view.exposed is None else eid in view.exposed),
            "tripwire": eid in view.honeytokens,
            "via": via,
        }

    for call in calls:
        data = call.get("data") if isinstance(call.get("data"), dict) else {}
        out["calls"].append({
            "domain": call["domain"], "service": call["service"],
            "data": _shown_data(data)})
        named, loose = payload_entities(data)
        for eid in named:
            add(eid, "named")
        for eid in loose:
            add(eid, "named in the data")
        for scope_block in (data, data.get("target") if isinstance(
                data.get("target"), dict) else {}):
            for key in SCOPE_KEYS:
                value = scope_block.get(key)
                for sid in _entity_values(value) if value else []:
                    out["scopes"].append(f"{key}:{sid}")
                    if key == "area_id" and sid in view.area_entities:
                        for eid in view.area_entities[sid]:
                            add(eid, f"in area {view.area_names.get(sid, sid)}")
                    elif key == "device_id" and sid in view.device_entities:
                        for eid in view.device_entities[sid]:
                            add(eid, f"on device {sid}")
                    else:
                        out["unresolved"].append(
                            f"{key.replace('_id', '')} {sid} could not be "
                            "resolved to entities")
        # A bare `script.<name>` service runs that script.
        if call["domain"] == "script" and call["service"] not in (
                "turn_on", "turn_off", "toggle", "reload"):
            add(f"script.{call['service']}", "the script this runs")
    # Expand containers: what a scene, a script, an automation or a group
    # reaches without naming it.
    for eid in list(seen):
        if seen[eid]["domain"] in CONTAINER_DOMAINS:
            members = view.members.get(eid)
            if members is None:
                out["unresolved"].append(f"what {eid} reaches could not be "
                                         "read")
                continue
            for member in members:
                add(member, f"reached through {eid}")
    out["entities"] = list(seen.values())
    return out


MAX_SHOWN_VALUE = 60


def _shown_data(data: dict) -> dict:
    """The call's data with every string capped — the assistant chose it,
    and a long string is how text it read would ride into the gate."""
    out = {}
    for key, value in list(data.items())[:12]:
        if isinstance(value, str):
            out[str(key)[:40]] = value[:MAX_SHOWN_VALUE]
        elif isinstance(value, (int, float, bool)) or value is None:
            out[str(key)[:40]] = value
        elif isinstance(value, list):
            out[str(key)[:40]] = [v[:MAX_SHOWN_VALUE] if isinstance(v, str)
                                  else v for v in value[:10]
                                  if isinstance(v, (str, int, float, bool))]
        else:
            out[str(key)[:40]] = "(an object)"
    return out


def fast_path(cons: dict, words: list[str]) -> str:
    """Why this may pass with no model, or "".

    One call, one entity, a service that can be put straight back, nothing
    protected or a tripwire, nothing unresolved — and the person's own words
    name the room it is in. All six, or the model is asked.
    """
    if len(cons.get("calls") or []) != 1 or cons.get("unresolved") \
            or cons.get("scopes"):
        return ""
    ents = cons.get("entities") or []
    if len(ents) != 1:
        return ""
    ent = ents[0]
    call = cons["calls"][0]
    if ent["protected"] or ent["tripwire"] or ent["exposed"] is False:
        return ""
    if call["domain"] != ent["domain"]:
        return ""
    if call["service"] not in FAST_PATH.get(ent["domain"], ()):
        return ""
    if ent["domain"] == "cover" and ent["device_class"] in \
            SECURITY_COVER_CLASSES:
        return ""
    area = str(ent.get("area") or "").strip().lower()
    if not area:
        return ""
    said = " ".join(str(w) for w in words or []).lower()
    said = re.sub(r"[^a-z0-9 ]+", " ", said)
    room = re.sub(r"[^a-z0-9 ]+", " ", area).strip()
    if room and re.search(rf"\b{re.escape(room)}\b", said):
        return f"one {ent['domain']} in the {area}, which you named"
    return ""


__all__ = ["CONTRACT_BUILTINS", "FAST_PATH", "GATED_MCP", "MCP_PREFIX",
           "View", "calls_for", "fast_path", "is_gated", "payload_entities",
           "resolve", "shown_state", "tool_kind"]
