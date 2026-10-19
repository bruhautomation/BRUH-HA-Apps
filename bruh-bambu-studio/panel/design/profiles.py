"""Which Bambu Studio profiles slice a part for a given printer and filament.

Bambu Studio ships its system profiles as JSON under
resources/profiles/BBL/{machine,process,filament}, each one a few keys on
top of a parent named in `inherits`. The command line is handed whole
settings files, so a profile is FLATTENED here — parent first, child over
it — and the part's own settings (what brAIn recommended, as the person
left them) are written over the process profile under the keys Bambu
Studio itself uses.

Nothing here is guessed from a name when the files can answer: a process
or filament profile is chosen among the ones whose own
`compatible_printers` lists the printer, so a profile for another machine
is never offered.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

import installer

MACHINE_NAMES = {
    "X1C": "Bambu Lab X1 Carbon", "X1": "Bambu Lab X1", "X1E": "Bambu Lab X1E",
    "P1S": "Bambu Lab P1S", "P1P": "Bambu Lab P1P", "P2S": "Bambu Lab P2S",
    "A1": "Bambu Lab A1", "A1 mini": "Bambu Lab A1 mini", "H2D": "Bambu Lab H2D",
    "H2S": "Bambu Lab H2S",
}
PATTERN_KEYS = {"grid": "grid", "gyroid": "gyroid", "cubic": "cubic",
                "honeycomb": "honeycomb", "line": "line", "triangles": "triangles"}
BRIM_KEYS = {"none": "no_brim", "auto": "auto_brim", "outer": "outer_only"}
MAX_DEPTH = 12


def _base() -> Path | None:
    root = installer.resources()
    return root / "profiles" / "BBL" if root else None


@lru_cache(maxsize=8)
def _index(base: str, kind: str) -> dict:
    """{profile name: path} for one kind, read off each file's own `name`."""
    out = {}
    folder = Path(base) / kind
    for path in folder.glob("*.json"):
        try:
            name = json.loads(path.read_text()).get("name") or path.stem
        except (OSError, ValueError):
            continue
        out[str(name)] = str(path)
    return out


def flatten(kind: str, name: str) -> dict:
    base = _base()
    if base is None:
        raise LookupError("Bambu Studio is not installed yet, so it has no profiles.")
    index = _index(str(base), kind)
    chain = []
    current = name
    for _ in range(MAX_DEPTH):
        path = index.get(current)
        if path is None:
            raise LookupError(f"No {kind} profile called {current!r}.")
        data = json.loads(Path(path).read_text())
        chain.append(data)
        current = data.get("inherits")
        if not current:
            break
    merged: dict = {}
    for data in reversed(chain):
        merged.update(data)
    merged["name"] = name
    merged["inherits"] = ""
    merged["from"] = "User"
    return merged


def _leaf(kind: str) -> list[str]:
    base = _base()
    if base is None:
        return []
    out = []
    for name, path in _index(str(base), kind).items():
        try:
            data = json.loads(Path(path).read_text())
        except (OSError, ValueError):
            continue
        if str(data.get("instantiation", "true")).lower() == "true":
            out.append(name)
    return sorted(out)


def _compatible(kind: str, machine: str) -> list[tuple[str, dict]]:
    out = []
    for name in _leaf(kind):
        try:
            flat = flatten(kind, name)
        except (LookupError, OSError, ValueError):
            continue
        printers = flat.get("compatible_printers") or []
        if machine in printers:
            out.append((name, flat))
    return out


def machine_for(model: str, nozzle: str = "0.4") -> str:
    prefix = MACHINE_NAMES.get(str(model or ""))
    if not prefix:
        raise LookupError("Set this printer's model on the Printers tab so the right "
                          "slicer profile can be chosen.")
    name = f"{prefix} {nozzle} nozzle"
    if name not in _leaf("machine"):
        raise LookupError(f"Bambu Studio has no {name!r} profile.")
    return name


def process_for(machine: str, layer_height: float | None) -> str:
    options = _compatible("process", machine)
    if not options:
        raise LookupError(f"No process profile in Bambu Studio fits {machine}.")
    want = layer_height or 0.2

    def score(item):
        name, flat = item
        try:
            lh = float(flat.get("layer_height") or 0.2)
        except ValueError:
            lh = 0.2
        return (abs(lh - want), 0 if "Standard" in name else 1, name)

    return min(options, key=score)[0]


def filament_for(machine: str, material: str) -> str:
    material = str(material or "PLA").upper()
    options = []
    for name, flat in _compatible("filament", machine):
        kind = flat.get("filament_type")
        kind = kind[0] if isinstance(kind, list) and kind else kind
        if str(kind or "").upper() == material:
            options.append(name)
    if not options:
        raise LookupError(f"No {material} filament profile in Bambu Studio fits {machine}.")

    def rank(name):
        return (0 if name.startswith(f"Bambu {material} Basic") else
                1 if name.startswith("Bambu") else 2 if name.startswith("Generic") else 3, name)

    return min(options, key=rank)


def apply(process: dict, settings: dict | None) -> dict:
    """The part's settings over a flattened process profile."""
    s = settings or {}
    out = dict(process)
    if "layer_height" in s:
        out["layer_height"] = f"{s['layer_height']:g}"
    if "walls" in s:
        out["wall_loops"] = str(s["walls"])
    if "infill_percent" in s:
        out["sparse_infill_density"] = f"{s['infill_percent']}%"
    if s.get("infill_pattern") in PATTERN_KEYS:
        out["sparse_infill_pattern"] = PATTERN_KEYS[s["infill_pattern"]]
    if "supports" in s:
        out["enable_support"] = "0" if s["supports"] == "none" else "1"
        if s["supports"] != "none":
            out["support_type"] = "tree(auto)" if s["supports"] == "tree" else "normal(auto)"
    if s.get("brim") in BRIM_KEYS:
        out["brim_type"] = BRIM_KEYS[s["brim"]]
    if "top_layers" in s:
        out["top_shell_layers"] = str(s["top_layers"])
    if "bottom_layers" in s:
        out["bottom_shell_layers"] = str(s["bottom_layers"])
    out["name"] = f"{process.get('name', 'process')} (BRUH Bambu)"
    return out


def coloured(filament: dict, colour: str) -> dict:
    """A flattened filament profile carrying the tray's colour, so the
    slicer's preview and the printer's job show the colour it really is."""
    text = str(colour or "").strip()
    if len(text) == 7 and text.startswith("#"):
        try:
            int(text[1:], 16)
        except ValueError:
            return filament
        return {**filament, "filament_colour": [text.upper()]}
    return filament


def prepare(model: str, settings: dict | None, outdir: Path,
            filaments: list[dict] | None = None) -> dict:
    """Write the settings files for one print; return their paths and names.

    `filaments` is one {"material", "colour"} per filament the part prints
    in, in filament order; with none, the part's own material is the one.
    """
    machine = machine_for(model)
    material = (settings or {}).get("material") or "PLA"
    wanted = filaments or [{"material": material, "colour": ""}]
    process = process_for(machine, (settings or {}).get("layer_height"))
    names = [filament_for(machine, f.get("material") or material) for f in wanted]
    outdir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for key, data in (("machine", flatten("machine", machine)),
                      ("process", apply(flatten("process", process), settings))):
        path = outdir / f"{key}.json"
        path.write_text(json.dumps(data, indent=1))
        paths[key] = str(path)
    paths["filaments"] = []
    for i, (name, f) in enumerate(zip(names, wanted), start=1):
        path = outdir / ("filament.json" if len(names) == 1 else f"filament_{i}.json")
        path.write_text(json.dumps(coloured(flatten("filament", name), f.get("colour")), indent=1))
        paths["filaments"].append(str(path))
    paths["filament"] = paths["filaments"][0]
    return {"machine": machine, "process": process, "filament": " + ".join(dict.fromkeys(names)),
            "filament_names": names, "material": wanted[0].get("material") or material,
            "paths": paths, "dir": os.fspath(outdir)}
