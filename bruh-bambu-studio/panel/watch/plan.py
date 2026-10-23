"""When to look: the print's own G-code read once, turned into checkpoints.

Most prints that fail do it in a few places, and a person watching knows
where: the first layer; the first few millimetres, where a part that is
going to come loose comes loose; the layer where a wide base narrows to a
thin column; the first bridges and overhangs; a colour change; the moment a
part gets tall and narrow enough to wobble or be knocked over. Everything
between those is mostly the same layer printed again.

So the sliced file is read once (the same `Metadata/plate_N.gcode` the
printer runs), layer by layer: how much of the plate each layer covers, on a
2 mm grid of where filament was laid (the prime tower, the purge line and
the skirt left out — they are not the part), which features it prints, and
how many minutes are left when it starts. Each risky moment becomes a
candidate with a weight and a sentence that says why it matters, the
candidates are chosen greedily under a per-print budget with a minimum gap
between looks, and a long stretch with nothing chosen gets one look of its
own, because spaghetti does not wait for a bridge.

A print the add-on cannot read the file of (started from somewhere else,
a printer that would not hand the file over) gets the same shape from the
layer count alone: the first layer, a few millimetres up, and a spread of
looks through the rest. The plan says which it is.
"""
from __future__ import annotations

import io
import math
import re
import zipfile

CELL_MM = 2.0
# What is not the part.
NOT_PART = ("prime tower", "wipe tower", "custom", "skirt", "purge", "flush")
MAX_LINES = 8_000_000
MAX_GCODE_BYTES = 400 * 1024 * 1024
# The looks a print gets, by how careful somebody asked it to be. A look a
# trigger asks for (a sudden change, the printer's own camera) comes out of
# the same budget plus a little.
BUDGETS = {"low": 5, "medium": 8, "high": 13}
TRIGGER_EXTRA = 4
# No two planned looks closer than this.
MIN_GAP_LAYERS = 3
MIN_GAP_MIN = 3
# A stretch longer than this with nothing planned gets a look.
FILL_GAP_MIN = {"low": 120, "medium": 75, "high": 45}

WEIGHTS = {"first_layer": 1.0, "early": 0.75, "narrowing": 0.6, "colour": 0.5,
           "bridge": 0.5, "tall": 0.5, "overhang": 0.45, "support": 0.4,
           "taller": 0.35, "last": 0.55, "fill": 0.25, "spread": 0.3}

_LAYER_MARKS = ("; CHANGE_LAYER", ";LAYER_CHANGE")
_Z = re.compile(r"^;\s*Z_HEIGHT:\s*([\d.]+)|^;Z:([\d.]+)")
_FEATURE = re.compile(r"^;\s*(?:FEATURE|TYPE):\s*(.+?)\s*$")
_M73 = re.compile(r"^M73\s+P(\d+)\s+R(\d+)")
_TOOL = re.compile(r"^T(\d+)\s*(?:;.*)?$")


def _num(word: str) -> float | None:
    try:
        return float(word[1:])
    except ValueError:
        return None


def analyse(lines) -> dict:
    """Per-layer facts out of G-code lines.

    {layers: [{n, z, cells, features, tool_change, remaining_min}], base_cells,
    height, total_min}. `cells` is how many 2 mm squares of the plate the
    part covers on that layer.
    """
    layers: list[dict] = []
    cur = None
    cells: set = set()
    feature = ""
    x = y = None
    absolute_e = False
    last_e = 0.0
    tool = None
    total_min = None
    last_remaining = None
    for count, raw in enumerate(lines):
        if count > MAX_LINES:
            break
        line = raw.strip() if isinstance(raw, str) else raw.decode("ascii", "replace").strip()
        if not line:
            continue
        head = line[0]
        if head == ";":
            if line.startswith(_LAYER_MARKS):
                if cur is not None:
                    cur["cells"] = len(cells)
                    layers.append(cur)
                cur = {"n": len(layers) + 1, "z": None, "cells": 0, "features": set(),
                       "tool_change": False, "remaining_min": last_remaining}
                cells = set()
                continue
            m = _Z.match(line)
            if m and cur is not None and cur["z"] is None:
                cur["z"] = float(m.group(1) or m.group(2))
                continue
            m = _FEATURE.match(line)
            if m:
                feature = m.group(1).lower()
                if cur is not None:
                    cur["features"].add(feature)
            continue
        if head == "M":
            if line.startswith("M83"):
                absolute_e = False
            elif line.startswith("M82"):
                absolute_e = True
            else:
                m = _M73.match(line)
                if m:
                    last_remaining = int(m.group(2))
                    if total_min is None:
                        total_min = int(m.group(2))
            continue
        if head == "T":
            m = _TOOL.match(line)
            if m:
                n = int(m.group(1))
                if n < 64:
                    if tool is not None and n != tool and cur is not None:
                        cur["tool_change"] = True
                    tool = n
            continue
        if head != "G" or not (line.startswith(("G0 ", "G1 ", "G2 ", "G3 "))):
            if line.startswith("G92"):
                for word in line.split():
                    if word[0] == "E":
                        last_e = _num(word) or 0.0
            continue
        nx = ny = e = None
        for word in line.split(";", 1)[0].split()[1:]:
            key = word[0]
            if key == "X":
                nx = _num(word)
            elif key == "Y":
                ny = _num(word)
            elif key == "E":
                e = _num(word)
        extruded = False
        if e is not None:
            if absolute_e:
                extruded = e > last_e + 1e-5
                last_e = e
            else:
                extruded = e > 1e-5
        tx = nx if nx is not None else x
        ty = ny if ny is not None else y
        if (extruded and cur is not None and tx is not None and ty is not None
                and x is not None and y is not None and not any(n in feature for n in NOT_PART)):
            length = math.hypot(tx - x, ty - y)
            steps = max(1, int(length / CELL_MM))
            for i in range(steps + 1):
                f = i / steps
                cells.add((int((x + (tx - x) * f) // CELL_MM), int((y + (ty - y) * f) // CELL_MM)))
        x, y = tx, ty
    if cur is not None:
        cur["cells"] = len(cells)
        layers.append(cur)
    # Numbered as the printer numbers them (its `layer_num`), so a
    # checkpoint at layer 48 is reached when the printer says 48.
    heights = [l["z"] for l in layers if l["z"] is not None]
    return {"layers": layers, "base_cells": layers[0]["cells"] if layers else 0,
            "height": max(heights) if heights else None, "total_min": total_min}


def read_plate(source, plate: int = 1) -> dict | None:
    """Analyse plate N's G-code inside a sliced 3MF (a path or a file object)."""
    try:
        with zipfile.ZipFile(source) as archive:
            name = f"Metadata/plate_{max(1, int(plate))}.gcode"
            if name not in archive.namelist():
                gcodes = sorted(n for n in archive.namelist() if n.endswith(".gcode"))
                if not gcodes:
                    return None
                name = gcodes[0]
            if archive.getinfo(name).file_size > MAX_GCODE_BYTES:
                return None
            with archive.open(name) as member:
                return analyse(io.TextIOWrapper(member, encoding="ascii", errors="replace"))
    except (zipfile.BadZipFile, KeyError, EOFError, ValueError):
        return None


def _area_cm2(cells: int) -> float:
    return round(cells * CELL_MM * CELL_MM / 100, 1)


def candidates(facts: dict) -> list[dict]:
    """Every risky moment in the print, with a weight and a sentence."""
    layers = facts.get("layers") or []
    if not layers:
        return []
    out: list[dict] = []
    total = len(layers)

    def add(kind: str, at: int, reason: str, weight: float | None = None):
        at = max(2, min(total, at))
        out.append({"layer": at, "kind": kind, "reason": reason,
                    "weight": WEIGHTS[kind] if weight is None else weight,
                    "remaining_min": layers[at - 1].get("remaining_min")})

    add("first_layer", 2, "The first layer is down — most failed prints fail here: " +
                          "not sticking, bare patches, a nozzle too high or too low.")
    early = next((l["n"] for l in layers if (l["z"] or 0) >= 1.6), min(total, 8))
    if early > 3:
        add("early", early, "A couple of millimetres up: a part that is going to come " +
                            "loose from the plate usually has by now.")
    base = facts.get("base_cells") or layers[0]["cells"]
    seen: dict[str, int] = {}
    for prev, layer in zip(layers, layers[1:]):
        n = layer["n"]
        if prev["cells"] >= 12 and layer["cells"] < 0.45 * prev["cells"] and n > 3:
            add("narrowing", n + 2,
                f"The print narrows sharply at layer {n} (from {_area_cm2(prev['cells'])} " +
                f"to {_area_cm2(layer['cells'])} cm²): thin parts start here.",
                WEIGHTS["narrowing"] + (0.1 if layer["cells"] < 0.2 * prev["cells"] else 0))
        for word, kind, sentence in (
                ("bridge", "bridge", "Bridges start at layer {n}: filament spanning thin air " +
                                     "can droop or tangle."),
                ("overhang", "overhang", "Overhangs start at layer {n}: edges printed over " +
                                         "nothing can curl up."),
                ("support", "support", "Supports start at layer {n}.")):
            has = any(word in f for f in layer["features"])
            if has and n - seen.get(kind, -99) > 6 and n > 2:
                add(kind, n + 2, sentence.format(n=n))
            if has:
                seen[kind] = n
    changes = [l["n"] for l in layers if l["tool_change"]]
    if changes:
        if len(changes) > 0.3 * total:
            add("colour", changes[0] + 1, f"Colour changes from layer {changes[0]} on, most layers: " +
                                          "a blob from a purge or a missed change shows early.")
        else:
            for n in changes:
                add("colour", n + 1, f"Filament changes at layer {n}: a blob or a missed " +
                                     "change shows right after.")
    if base:
        side = math.sqrt(base * CELL_MM * CELL_MM)
        tall = next((l for l in layers if (l["z"] or 0) >= max(20.0, 2.5 * side)), None)
        if tall:
            add("tall", tall["n"], f"From {tall['z']:g} mm up the part is tall for its base " +
                                   f"({_area_cm2(base)} cm²): it can wobble or be knocked over.")
            step = tall["z"] * 1.5
            for layer in layers[tall["n"]:]:
                if (layer["z"] or 0) >= step:
                    add("taller", layer["n"], f"{layer['z']:g} mm up on a {_area_cm2(base)} cm² base.")
                    step = layer["z"] * 1.5
    if total > 6:
        add("last", total, "The last layers: the print is nearly done.")
    return out


def choose(found: list[dict], total_layers: int, sensitivity: str = "medium",
           total_min: int | None = None) -> list[dict]:
    """The checkpoints a print gets: the riskiest first, spread out, in budget."""
    budget = BUDGETS.get(sensitivity, BUDGETS["medium"])
    chosen: list[dict] = []

    def clash(c: dict) -> dict | None:
        for other in chosen:
            if abs(other["layer"] - c["layer"]) < MIN_GAP_LAYERS:
                return other
            a, b = other.get("remaining_min"), c.get("remaining_min")
            if a is not None and b is not None and abs(a - b) < MIN_GAP_MIN \
                    and {other["kind"], c["kind"]} != {"first_layer", "early"}:
                return other
        return None

    for c in sorted(found, key=lambda c: (-c["weight"], c["layer"])):
        if c["layer"] > total_layers:
            continue
        near = clash(c)
        if near is not None:
            # Too close to a look already chosen: when that look comes at or
            # after this moment it covers it too, and is told so.
            if (c["kind"] != near["kind"] and near["layer"] >= c["layer"]
                    and len(near.setdefault("also", [])) < 2):
                near["also"].append(c["reason"])
            continue
        if len(chosen) >= budget:
            continue
        chosen.append(dict(c))
    chosen.sort(key=lambda c: c["layer"])
    gap = FILL_GAP_MIN.get(sensitivity, 75)
    if total_min:
        fills = []
        marks = [(0, total_min)] + [(c["layer"], c.get("remaining_min")) for c in chosen
                                     if c.get("remaining_min") is not None] + [(total_layers, 0)]
        for (la, ra), (lb, rb) in zip(marks, marks[1:]):
            if ra is None or rb is None or ra - rb <= gap or lb - la < 2 * MIN_GAP_LAYERS:
                continue
            pieces = int((ra - rb) // gap)
            for k in range(1, pieces + 1):
                layer = la + round((lb - la) * k / (pieces + 1))
                fills.append({"layer": layer, "kind": "fill", "weight": WEIGHTS["fill"],
                              "reason": "A long stretch with nothing else to look at: a " +
                                        "routine look for spaghetti or a part come loose.",
                              "remaining_min": round(ra - (ra - rb) * k / (pieces + 1))})
        for f in fills:
            if len(chosen) >= budget:
                break
            if clash(f) is None:
                chosen.append(f)
        chosen.sort(key=lambda c: c["layer"])
    return chosen


def from_gcode(facts: dict, sensitivity: str = "medium") -> dict:
    layers = facts.get("layers") or []
    points = choose(candidates(facts), len(layers), sensitivity, facts.get("total_min"))
    return {"source": "gcode", "total_layers": len(layers), "height": facts.get("height"),
            "base_cm2": _area_cm2(facts.get("base_cells") or 0),
            "total_min": facts.get("total_min"), "checkpoints": points}


def estimated(total_layers: int | None, sensitivity: str = "medium") -> dict:
    """The plan for a print whose file could not be read: from its layer count."""
    total = int(total_layers or 0)
    budget = BUDGETS.get(sensitivity, BUDGETS["medium"])
    points = [{"layer": 2, "kind": "first_layer", "weight": WEIGHTS["first_layer"],
               "reason": "The first layer is down — most failed prints fail here."}]
    if total >= 12:
        points.append({"layer": min(8, total // 3), "kind": "early", "weight": WEIGHTS["early"],
                       "reason": "A few millimetres up: a part that will come loose usually has by now."})
    if total >= 20:
        spread = max(1, budget - len(points) - 1)
        for k in range(1, spread + 1):
            layer = round(total * k / (spread + 1))
            if all(abs(layer - p["layer"]) >= MIN_GAP_LAYERS for p in points):
                points.append({"layer": layer, "kind": "spread", "weight": WEIGHTS["spread"],
                               "reason": f"About {round(100 * layer / total)}% through: a routine look."})
        points.append({"layer": total, "kind": "last", "weight": WEIGHTS["last"],
                       "reason": "The last layers: the print is nearly done."})
    points.sort(key=lambda c: c["layer"])
    return {"source": "estimate", "total_layers": total or None, "height": None,
            "base_cm2": None, "total_min": None, "checkpoints": points}
