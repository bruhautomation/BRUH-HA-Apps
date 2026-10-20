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
from design import options

MACHINE_NAMES = {
    "X1C": "Bambu Lab X1 Carbon", "X1": "Bambu Lab X1", "X1E": "Bambu Lab X1E",
    "P1S": "Bambu Lab P1S", "P1P": "Bambu Lab P1P", "P2S": "Bambu Lab P2S",
    "A1": "Bambu Lab A1", "A1 mini": "Bambu Lab A1 mini", "H2D": "Bambu Lab H2D",
    "H2S": "Bambu Lab H2S",
}
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
        # Since 2.x a system profile keeps its G-code in template files it
        # names under "include" (Bambu Lab A1 0.4 nozzle template
        # machine_start_gcode, …). Bambu Studio's preset loader applies them
        # (PresetBundle.cpp, BBL_JSON_KEY_INCLUDES); the command line's own
        # loader does not, so a flattened profile has to carry them itself.
        for included in _includes(data):
            merged.update(_included(index, kind, included))
        merged.update({k: v for k, v in data.items() if k != INCLUDE})
    # A "User" profile names the system profile it came from in `inherits`,
    # and the CLI takes that as the system name it checks compatibility
    # with: a process is sliced only if its compatible_printers lists the
    # machine's system name (BambuStudio.cpp, CLI_PROCESS_NOT_COMPATIBLE).
    # An empty `inherits` made that name "" and every print exit -17.
    merged["name"] = name
    merged["inherits"] = name
    merged["from"] = "User"
    return merged


INCLUDE = "include"
# What a template file says about itself, not settings it brings.
_TEMPLATE_META = ("name", "instantiation", "inherits", "from", "type", "setting_id")


def _includes(data: dict) -> list[str]:
    value = data.get(INCLUDE)
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(v) for v in value if isinstance(v, str) and v]
    return []


def _included(index: dict, kind: str, name: str) -> dict:
    path = index.get(name)
    if path is None:
        raise LookupError(f"The {kind} profile needs {name!r}, which Bambu Studio's "
                          "profiles do not have.")
    data = json.loads(Path(path).read_text())
    return {k: v for k, v in data.items() if k not in _TEMPLATE_META and k != INCLUDE}


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
    """The part's settings over a flattened process profile (design/options.py)."""
    out, _notes = reconciled(process, settings)
    return out


def reconciled(process: dict, settings: dict | None) -> tuple[dict, list[str]]:
    """apply(), with the sentences saying what had to change to slice."""
    out = dict(process)
    out.update(options.process_values(settings or {}))
    out, notes = options.reconcile(out)
    out["name"] = f"{process.get('name', 'process')} (BRUH Bambu)"
    return out, notes


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
    process_data, adjusted = reconciled(flatten("process", process), settings)
    for key, data in (("machine", flatten("machine", machine)), ("process", process_data)):
        path = outdir / f"{key}.json"
        path.write_text(json.dumps(data, indent=1))
        paths[key] = str(path)
    paths["filaments"] = []
    for i, (name, f) in enumerate(zip(names, wanted), start=1):
        path = outdir / ("filament.json" if len(names) == 1 else f"filament_{i}.json")
        data = coloured(flatten("filament", name), f.get("colour"))
        data.update(options.filament_values(settings or {}))
        path.write_text(json.dumps(data, indent=1))
        paths["filaments"].append(str(path))
    paths["filament"] = paths["filaments"][0]
    return {"machine": machine, "process": process, "filament": " + ".join(dict.fromkeys(names)),
            "filament_names": names, "material": wanted[0].get("material") or material,
            "paths": paths, "dir": os.fspath(outdir), "adjusted": adjusted}


# Keys a system profile carries about itself, not settings a project holds.
_PROFILE_META = ("name", "inherits", "from", "instantiation", "setting_id", "type",
                 "compatible_printers", "compatible_printers_condition", "compatible_prints",
                 "compatible_prints_condition", "filament_id", "base_id")


def _studio_version() -> str | None:
    label = str((installer.installed() or {}).get("version") or "").lstrip("vV")
    parts = label.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        return label
    return None


def project_settings(model: str, settings: dict | None,
                     filaments: list[dict] | None = None) -> dict:
    """Metadata/project_settings.config for a part opened in Bambu Studio.

    A 3MF with no project config, or one whose `printer_model` is not a
    Bambu Lab machine, is loaded as geometry only under "The 3mf file has
    invalid config" (Plater.cpp, is_bbl_vendor_config). This is the config
    Bambu Studio itself writes: the printer's, the process with the part's
    settings over it, and one filament per colour, each list key holding
    one value per filament.
    """
    machine = machine_for(model)
    material = (settings or {}).get("material") or "PLA"
    wanted = filaments or [{"material": material, "colour": ""}]
    process = process_for(machine, (settings or {}).get("layer_height"))
    names = [filament_for(machine, f.get("material") or material) for f in wanted]
    out: dict = {}
    out.update(flatten("machine", machine))
    process_data, _notes = reconciled(flatten("process", process), settings)
    out.update(process_data)
    merged: dict = {}
    for name, f in zip(names, wanted):
        data = coloured(flatten("filament", name), f.get("colour"))
        data.update(options.filament_values(settings or {}))
        for key, value in data.items():
            if key in _PROFILE_META:
                continue
            if isinstance(value, list):
                merged.setdefault(key, []).extend(value)
            elif key not in merged:
                merged[key] = value
    out.update(merged)
    for key in _PROFILE_META:
        out.pop(key, None)
    out.update(name="project_settings", **{"from": "project"},
               printer_settings_id=machine, print_settings_id=process,
               filament_settings_id=names)
    version = _studio_version()
    if version:
        out["version"] = version
    return out
