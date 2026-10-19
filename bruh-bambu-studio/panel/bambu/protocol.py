"""What a Bambu Lab printer says over MQTT, and what it is told.

Pure functions, no network: the shapes here are the printer's own (topic
`device/<serial>/report` in, `device/<serial>/request` out, as Bambu Studio
and every LAN-mode client speak them), and keeping them apart from the
socket is what lets the tests drive every command and every report without
a printer on the desk.

Two facts decide most of this file.

* A P1 or A1 sends DELTAS. After the `pushall` that opens a session it
  reports only the fields that moved, so a status is the running merge of
  every report since, never the last one alone — reading the last one is a
  printer whose nozzle temperature vanishes the moment its bed warms up.
* `gcode_state` is the only word the printer has for what it is doing, and
  it is upper-case and terse (IDLE, PREPARE, RUNNING, PAUSE, FINISH,
  FAILED, SLICING). It is passed through lower-cased rather than translated
  into a vocabulary of ours, because a state we had not heard of yet would
  otherwise be reported as one we had.
"""
from __future__ import annotations

import json
import re

# print_speed's levels, by the names Bambu Studio shows.
SPEEDS = {"silent": 1, "standard": 2, "sport": 3, "ludicrous": 4}
SPEED_NAMES = {v: k for k, v in SPEEDS.items()}

# Hard ceilings on a temperature somebody (or a misheard voice command)
# asks for. Above the hottest nozzle and bed any Bambu printer ships with,
# and well below what would damage one: a target here is refused, never
# clamped, because "set the bed to 600" clamped to 120 is a bed nobody
# asked to be hot.
MAX_NOZZLE_C = 300
MAX_BED_C = 120

# A gcode line is the one free-text command, so it is checked: one or more
# lines of ASCII G/M/T codes. Anything that is not G-code shaped is refused
# before it reaches a machine with a hot end.
GCODE_LINE = re.compile(r"^\s*(;.*|[GMT]\d+(\.\d+)?([ \t]+[A-Z][-+]?[0-9.]*)*\s*(;.*)?)?$")
MAX_GCODE_LINES = 32

ACTIVE_STATES = {"prepare", "running", "pause", "slicing"}


def deep_merge(base: dict, update: dict) -> dict:
    """Merge a delta report into the running status, in place.

    Lists replace rather than merge: the AMS tray list and the HMS error
    list are each sent whole when they change.
    """
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def request(payload: dict, sequence: int) -> str:
    """One request, with the sequence id the printer echoes back."""
    body = json.loads(json.dumps(payload))
    for section in body.values():
        if isinstance(section, dict):
            section["sequence_id"] = str(sequence)
    return json.dumps(body)


def pushall() -> dict:
    return {"pushing": {"command": "pushall", "version": 1, "push_target": 1}}


def simple(command: str) -> dict:
    """pause, resume and stop."""
    if command not in ("pause", "resume", "stop"):
        raise ValueError(f"unknown print command {command!r}")
    return {"print": {"command": command, "param": ""}}


def speed(level) -> dict:
    name = str(level).strip().lower()
    if name.isdigit() and int(name) in SPEED_NAMES:
        value = int(name)
    elif name in SPEEDS:
        value = SPEEDS[name]
    else:
        raise ValueError("Speed is silent, standard, sport or ludicrous.")
    return {"print": {"command": "print_speed", "param": str(value)}}


def light(on: bool, node: str = "chamber_light") -> dict:
    return {"system": {"command": "ledctrl", "led_node": node,
                       "led_mode": "on" if on else "off",
                       "led_on_time": 500, "led_off_time": 500,
                       "loop_times": 0, "interval_time": 0}}


def gcode(lines: str) -> dict:
    text = str(lines or "").replace("\r", "")
    rows = [r.strip().upper() for r in text.split("\n") if r.strip()]
    if not rows:
        raise ValueError("No G-code given.")
    if len(rows) > MAX_GCODE_LINES:
        raise ValueError(f"At most {MAX_GCODE_LINES} lines of G-code at once.")
    for row in rows:
        if not row.isascii() or not GCODE_LINE.match(row):
            raise ValueError(f"Not a G-code line: {row[:60]!r}")
    return {"print": {"command": "gcode_line", "param": "\n".join(rows) + "\n"}}


def temperature(target: str, celsius) -> dict:
    """A target for the nozzle or the bed, as the G-code Bambu Studio sends."""
    try:
        value = int(round(float(celsius)))
    except (TypeError, ValueError):
        raise ValueError("Give the temperature as a number of °C.") from None
    which = str(target or "").strip().lower()
    if which in ("nozzle", "hotend", "extruder"):
        if not 0 <= value <= MAX_NOZZLE_C:
            raise ValueError(f"A nozzle target is 0–{MAX_NOZZLE_C} °C.")
        return gcode(f"M104 S{value}")
    if which in ("bed", "plate", "heatbed"):
        if not 0 <= value <= MAX_BED_C:
            raise ValueError(f"A bed target is 0–{MAX_BED_C} °C.")
        return gcode(f"M140 S{value}")
    raise ValueError("Temperature target is nozzle or bed.")


def project_file(name: str, plate: int, *, use_ams: bool,
                 ams_mapping: list[int] | None, timelapse: bool,
                 bed_leveling: bool, flow_cali: bool,
                 vibration_cali: bool, subtask: str = "") -> dict:
    """Start a sliced .3mf already on the printer's storage.

    `param` names the plate's G-code INSIDE the archive; the archive itself
    is the url. Plates are 1-based, as Bambu Studio numbers them.
    """
    plate = max(1, int(plate or 1))
    return {"print": {
        "command": "project_file",
        "param": f"Metadata/plate_{plate}.gcode",
        "url": f"file:///sdcard/{name}",
        "subtask_name": subtask or re.sub(r"(\.gcode)?\.3mf$", "", name),
        "project_id": "0", "profile_id": "0", "task_id": "0",
        "subtask_id": "0", "md5": "",
        "bed_type": "auto",
        "timelapse": bool(timelapse),
        "bed_leveling": bool(bed_leveling),
        "flow_cali": bool(flow_cali),
        "vibration_cali": bool(vibration_cali),
        "layer_inspect": False,
        "use_ams": bool(use_ams),
        "ams_mapping": list(ams_mapping or [0]),
    }}


def _num(value):
    try:
        return round(float(value), 1)
    except (TypeError, ValueError):
        return None


def _tray_colour(raw) -> str:
    text = str(raw or "")
    return f"#{text[:6]}" if re.fullmatch(r"[0-9A-Fa-f]{6,8}", text) else ""


def summarise(status: dict) -> dict:
    """The merged report trimmed to what a person, a sensor or brAIn reads.

    A field the printer has not sent is None, never 0: a nozzle at 0 °C and
    a nozzle nobody has heard about are different claims.
    """
    p = status.get("print") if isinstance(status.get("print"), dict) else {}
    state = str(p.get("gcode_state") or "").strip().lower() or None
    lights = {str(item.get("node")): item.get("mode") == "on"
              for item in p.get("lights_report") or [] if isinstance(item, dict)}
    trays = []
    ams = p.get("ams") if isinstance(p.get("ams"), dict) else {}
    for unit in ams.get("ams") or []:
        if not isinstance(unit, dict):
            continue
        for tray in unit.get("tray") or []:
            if not isinstance(tray, dict) or not tray.get("tray_type"):
                continue
            trays.append({
                "slot": int(unit.get("id", 0)) * 4 + int(tray.get("id", 0)),
                "type": str(tray.get("tray_type")),
                "colour": _tray_colour(tray.get("tray_color")),
                "remaining": tray.get("remain") if isinstance(tray.get("remain"), int)
                and tray.get("remain") >= 0 else None,
            })
    hms = [h for h in p.get("hms") or [] if isinstance(h, dict)]
    error = p.get("print_error")
    remaining = p.get("mc_remaining_time")
    return {
        "state": state,
        "printing": state in ACTIVE_STATES,
        "progress": p.get("mc_percent") if isinstance(p.get("mc_percent"), int) else None,
        "remaining_min": remaining if isinstance(remaining, int) else None,
        "layer": p.get("layer_num"),
        "total_layers": p.get("total_layer_num"),
        "file": p.get("subtask_name") or p.get("gcode_file") or None,
        "nozzle_c": _num(p.get("nozzle_temper")),
        "nozzle_target_c": _num(p.get("nozzle_target_temper")),
        "bed_c": _num(p.get("bed_temper")),
        "bed_target_c": _num(p.get("bed_target_temper")),
        "chamber_c": _num(p.get("chamber_temper")),
        "speed": SPEED_NAMES.get(p.get("spd_lvl")),
        "chamber_light": lights.get("chamber_light"),
        "ams": trays,
        "error_code": error if isinstance(error, int) and error else None,
        "hms_count": len(hms),
        "wifi": p.get("wifi_signal") or None,
    }
