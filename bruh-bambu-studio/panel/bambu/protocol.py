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
# project_file's bed_type: what the printer checks the plate against.
BED_TYPES = ("auto", "textured_plate", "hot_plate", "cool_plate", "eng_plate")

# What the printer is doing inside a state, by `stg_cur` (the same table
# Bambu Studio and Handy show the words from). A number not here is passed
# on as "stage N" rather than guessed.
STAGES = {
    0: "Printing", 1: "Auto bed levelling", 2: "Heatbed preheating",
    3: "Vibration compensation", 4: "Changing filament", 5: "M400 pause",
    6: "Paused: filament ran out", 7: "Heating the nozzle",
    8: "Calibrating extrusion", 9: "Scanning the bed surface",
    10: "Inspecting the first layer", 11: "Identifying the build plate",
    12: "Calibrating the micro lidar", 13: "Homing the toolhead",
    14: "Cleaning the nozzle tip", 15: "Checking the extruder temperature",
    16: "Paused by the user", 17: "Paused: the front cover fell",
    18: "Calibrating the micro lidar", 19: "Calibrating extrusion flow",
    20: "Paused: nozzle temperature fault", 21: "Paused: bed temperature fault",
    22: "Unloading filament", 23: "Paused: skipped step",
    24: "Loading filament", 25: "Calibrating motor noise",
    26: "Paused: the AMS was lost", 27: "Paused: heat-break fan too slow",
    28: "Paused: chamber temperature fault", 29: "Cooling the chamber",
    30: "Paused by G-code", 31: "Motor noise showoff",
    32: "Paused: filament over the nozzle", 33: "Paused: cutter fault",
    34: "Paused: first layer fault", 35: "Paused: nozzle clog",
}
# The models whose camera is an RTSPS stream on port 322; the rest (P1, A1)
# send JPEG frames on port 6000. ipcam.rtsp_url in a report overrides this.
RTSP_MODELS = {"X1C", "X1", "X1E", "P2S", "H2D", "H2S", "H2C"}


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


def ams_refresh(ams_id: int, slot_id: int) -> dict:
    """Ask the AMS to read a tray's RFID tag again (a Bambu spool's details)."""
    return {"print": {"command": "ams_get_rfid", "ams_id": int(ams_id), "slot_id": int(slot_id)}}


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
                 vibration_cali: bool, subtask: str = "", bed_type: str = "auto",
                 layer_inspect: bool = False) -> dict:
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
        "bed_type": bed_type if bed_type in BED_TYPES else "auto",
        "timelapse": bool(timelapse),
        "bed_leveling": bool(bed_leveling),
        "flow_cali": bool(flow_cali),
        "vibration_cali": bool(vibration_cali),
        "layer_inspect": bool(layer_inspect),
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


def _int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _fan(value):
    """A fan's speed as the printer sends it (0–15) in percent."""
    n = _int(value)
    return None if n is None else round(max(0, min(15, n)) / 15 * 100)


def _tray(tray: dict, slot: int) -> dict:
    remain = tray.get("remain")
    return {
        "slot": slot,
        "type": str(tray.get("tray_type")),
        "name": str(tray.get("tray_sub_brands") or "").strip() or None,
        "colour": _tray_colour(tray.get("tray_color")),
        "remaining": remain if isinstance(remain, int) and remain >= 0 else None,
        "nozzle_min_c": _int(tray.get("nozzle_temp_min")),
        "nozzle_max_c": _int(tray.get("nozzle_temp_max")),
    }


# 0500-0500-0001-0007, "MQTT Command verification failed": firmware with
# Bambu's authorization refuses an unsigned command from a LAN client unless
# Developer Mode is on. Its own text tells people to update Bambu Studio or
# Bambu Handy, which does nothing for a command from Home Assistant.
COMMAND_REFUSED_HMS = "0500_0500_0001_0007"
COMMAND_REFUSED = ("The printer refused the command: it takes commands from Home Assistant "
                   "only with Developer Mode on. Turn it on on the printer, under Settings › "
                   "LAN only mode › Developer mode, then try again.")
# Codes the panel can say more about than Bambu's own page does.
HMS_NOTES = {
    COMMAND_REFUSED_HMS: COMMAND_REFUSED + " The printer's own message about updating Bambu "
                         "Studio or Bambu Handy does not apply to this add-on.",
}


def hms_code(entry: dict) -> str:
    """An HMS entry as the code Bambu's wiki is indexed by (XXXX_XXXX_XXXX_XXXX)."""
    attr, code = _int(entry.get("attr")) or 0, _int(entry.get("code")) or 0
    text = f"{attr:08X}{code:08X}"
    return "_".join(text[i:i + 4] for i in range(0, 16, 4))


def camera_kind(model: str, rtsp_url) -> str:
    """"rtsp", "jpeg", or "disabled" (a printer whose LAN live view is off)."""
    url = str(rtsp_url or "").strip().lower()
    if url == "disable":
        return "disabled"
    if url.startswith("rtsp"):
        return "rtsp"
    return "rtsp" if str(model or "") in RTSP_MODELS else "jpeg"


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
    units = []
    ams = p.get("ams") if isinstance(p.get("ams"), dict) else {}
    for unit in ams.get("ams") or []:
        if not isinstance(unit, dict):
            continue
        uid = _int(unit.get("id")) or 0
        units.append({"id": uid, "humidity": _int(unit.get("humidity")),
                      "temp_c": _num(unit.get("temp"))})
        for tray in unit.get("tray") or []:
            if not isinstance(tray, dict) or not tray.get("tray_type"):
                continue
            trays.append(_tray(tray, uid * 4 + (_int(tray.get("id")) or 0)))
    # tray_now is the slot feeding the nozzle: 254 the external spool, 255 none.
    now = _int(ams.get("tray_now"))
    active = "external" if now == 254 else now if now is not None and now < 64 else None
    vt = p.get("vt_tray") if isinstance(p.get("vt_tray"), dict) else {}
    external = _tray(vt, 254) if vt.get("tray_type") else None
    if external:
        external["slot"] = "external"
    hms = [h for h in p.get("hms") or [] if isinstance(h, dict)]
    error = p.get("print_error")
    remaining = p.get("mc_remaining_time")
    stage_n = _int(p.get("stg_cur"))
    if state in ("idle", "finish", "failed") or stage_n is None or stage_n < 0:
        stage = None
    else:
        stage = STAGES.get(stage_n, f"Stage {stage_n}")
    ipcam = p.get("ipcam") if isinstance(p.get("ipcam"), dict) else {}
    return {
        "state": state,
        "printing": state in ACTIVE_STATES,
        "stage": stage,
        "progress": p.get("mc_percent") if isinstance(p.get("mc_percent"), int) else None,
        "remaining_min": remaining if isinstance(remaining, int) else None,
        "layer": p.get("layer_num"),
        "total_layers": p.get("total_layer_num"),
        "file": p.get("subtask_name") or p.get("gcode_file") or None,
        "gcode_file": p.get("gcode_file") or None,
        "nozzle_c": _num(p.get("nozzle_temper")),
        "nozzle_target_c": _num(p.get("nozzle_target_temper")),
        "bed_c": _num(p.get("bed_temper")),
        "bed_target_c": _num(p.get("bed_target_temper")),
        "chamber_c": _num(p.get("chamber_temper")),
        "speed": SPEED_NAMES.get(p.get("spd_lvl")),
        "chamber_light": lights.get("chamber_light"),
        "ams": trays,
        "ams_units": units,
        "active_tray": active,
        "external_spool": external,
        "error_code": error if isinstance(error, int) and error else None,
        "hms_count": len(hms),
        "hms": [hms_code(h) for h in hms][:8],
        "hms_notes": {code: HMS_NOTES[code] for code in map(hms_code, hms) if code in HMS_NOTES},
        "wifi": p.get("wifi_signal") or None,
        "fans": {"part": _fan(p.get("cooling_fan_speed")), "aux": _fan(p.get("big_fan1_speed")),
                 "chamber": _fan(p.get("big_fan2_speed")),
                 "heatbreak": _fan(p.get("heatbreak_fan_speed"))},
        "nozzle_diameter": str(p.get("nozzle_diameter") or "") or None,
        "rtsp_url": ipcam.get("rtsp_url") or None,
        "sdcard": p.get("sdcard") if isinstance(p.get("sdcard"), bool) else None,
    }
