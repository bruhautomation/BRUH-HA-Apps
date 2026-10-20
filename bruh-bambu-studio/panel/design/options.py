"""Every print option, in one place: what it is called, what it may be, and
the Bambu Studio key it is written under.

Three readers, one table. brAIn's schema is built from it (so brAIn can ask
for exactly what the slicer will take), the panel's print dialogs are built
from it (`/api/print/options`), and `profiles.apply` writes it over the
process profile. A value outside its range or list is dropped — the
profile's own value stands — never clamped and never passed through, because
an enum value Bambu Studio does not know is a slice that ends "the file
carries a setting value it rejects".

SLICE options change the G-code and are written into the process (or the
filament) profile; START options are what the printer is told when the job
starts. The enum values on the right are Bambu Studio's own
(src/libslic3r/PrintConfig.cpp's key maps), checked against its source.
"""
from __future__ import annotations

# key: (label, group, kind, spec, profile key, help)
#   kind "float"/"int": spec = (lo, hi, step)
#   kind "enum": spec = {choice: profile value}
#   kind "bool": spec = None (written "1"/"0")
SLICE = {
    "layer_height": ("Layer height (mm)", "Quality", "float", (0.06, 0.32, 0.02), "layer_height",
                     "Thinner is smoother and slower; 0.2 is the everyday choice, 0.12 for fine detail, 0.28 for fast drafts."),
    "first_layer_height": ("First layer (mm)", "Quality", "float", (0.1, 0.35, 0.02),
                           "initial_layer_print_height", "A thicker first layer sticks better."),
    "walls": ("Walls", "Strength", "int", (1, 10, 1), "wall_loops",
              "Perimeters around every layer: the biggest single lever on strength."),
    "top_layers": ("Top layers", "Strength", "int", (0, 20, 1), "top_shell_layers", ""),
    "bottom_layers": ("Bottom layers", "Strength", "int", (0, 20, 1), "bottom_shell_layers", ""),
    "infill_percent": ("Infill (%)", "Strength", "int", (0, 100, 1), "sparse_infill_density",
                       "15 % for most parts, 25–40 % for load, 100 % only when it must be solid."),
    "infill_pattern": ("Infill pattern", "Strength", "enum", {
        "grid": "grid", "gyroid": "gyroid", "cubic": "cubic", "honeycomb": "honeycomb",
        "line": "line", "triangles": "triangles", "adaptive cubic": "adaptivecubic",
        "lightning": "lightning", "zig-zag": "zig-zag", "rectilinear": "zig-zag",
        "concentric": "concentric", "aligned rectilinear": "alignedrectilinear"},
        "sparse_infill_pattern",
        "Gyroid is strong in every direction; lightning only holds up top surfaces. "
        "At 100 % infill only rectilinear, concentric or aligned rectilinear work."),
    "wall_generator": ("Wall generator", "Quality", "enum", {"classic": "classic", "arachne": "arachne"},
                       "wall_generator", "Arachne varies line width for thin features."),
    "seam": ("Seam", "Quality", "enum", {"aligned": "aligned", "nearest": "nearest", "back": "back",
                                          "random": "random"}, "seam_position",
             "Where each layer starts: back hides it, random scatters it."),
    "ironing": ("Ironing", "Quality", "enum", {"none": "no ironing", "top": "top", "topmost": "topmost",
                                                "all solid": "solid"}, "ironing_type",
                "A smooth top surface, at the cost of time."),
    "supports": ("Supports", "Support", "enum", {"none": None, "normal": "normal(auto)", "tree": "tree(auto)"},
                 "support_type", "Tree supports are easier to remove and use less filament."),
    "support_angle": ("Support overhang angle (°)", "Support", "int", (0, 90, 1),
                      "support_threshold_angle", "Overhangs steeper than this get support; 0 is the profile's own."),
    "support_build_plate_only": ("Support only from the plate", "Support", "bool", None,
                                 "support_on_build_plate_only", "No support standing on the part itself."),
    "brim": ("Brim", "Adhesion", "enum", {"none": "no_brim", "auto": "auto_brim", "outer": "outer_only",
                                          "inner": "inner_only", "outer and inner": "outer_and_inner",
                                          "mouse ears": "brim_ears"}, "brim_type",
             "A brim keeps tall or small-footprint parts from lifting."),
    "brim_width": ("Brim width (mm)", "Adhesion", "float", (0, 20, 0.5), "brim_width", ""),
    "skirt_loops": ("Skirt loops", "Adhesion", "int", (0, 10, 1), "skirt_loops", ""),
    "print_sequence": ("Print order", "Layout", "enum", {"by layer": "by layer", "by object": "by object"},
                       "print_sequence",
                       "By object finishes each part before the next (fewer strings, but parts must clear the toolhead)."),
    "prime_tower": ("Prime tower", "Multi-colour", "bool", None, "enable_prime_tower",
                    "Purges each colour change on a tower beside the part; off only for one colour."),
    "flush_into_infill": ("Flush into infill", "Multi-colour", "bool", None, "flush_into_infill",
                          "Purge colour changes into the part's infill instead of waste."),
    "flush_into_objects": ("Flush into objects", "Multi-colour", "bool", None, "flush_into_objects",
                           "Purge into whole objects marked as sacrificial."),
    "vase": ("Spiral vase", "Special", "bool", None, "spiral_mode",
             "One continuous wall, no top, no infill: vases and lamp shades."),
    "fuzzy_skin": ("Fuzzy skin", "Special", "enum", {"none": "none", "outside": "external", "all": "all"},
                   "fuzzy_skin", "A textured outer surface."),
    "nozzle_temp": ("Nozzle temperature (°C)", "Temperature", "int", (170, 300, 5), "nozzle_temperature",
                    "Overrides the filament profile; 0 or empty keeps it."),
}
# The only sparse patterns Bambu Studio slices at 100 % density: its
# validate() refuses any pattern that is not also a top_surface_pattern
# value ("grid doesn't work at 100% density", exit -18).
SOLID_PATTERNS = ("zig-zag", "concentric", "monotonic", "monotonicline", "globalmonotonicline",
                  "alignedrectilinear", "hilbertcurve", "archimedeanchords", "octagramspiral")
SOLID_FALLBACK = "zig-zag"
# Written into the filament profile rather than the process one.
FILAMENT_KEYS = {"nozzle_temp"}

PLATES = {
    "auto": ("Whatever is on the printer", None, "auto"),
    "textured_pei": ("Textured PEI", "Textured PEI Plate", "textured_plate"),
    "smooth_pei": ("Smooth PEI / High Temp", "High Temp Plate", "hot_plate"),
    "cool": ("Cool Plate", "Cool Plate", "cool_plate"),
    "engineering": ("Engineering Plate", "Engineering Plate", "eng_plate"),
}
SPEEDS = ("silent", "standard", "sport", "ludicrous")

START = {
    "plate_type": ("Build plate", "enum", tuple(PLATES), "auto",
                   "The plate the job is sliced and started for; auto takes the printer's."),
    "speed": ("Speed after it starts", "enum", SPEEDS, "standard", "Silent is quieter, sport faster."),
    "bed_leveling": ("Bed levelling", "bool", None, True, ""),
    "flow_cali": ("Flow calibration", "bool", None, False, "X1 and P2S: measure the flow before printing."),
    "vibration_cali": ("Vibration compensation", "bool", None, True, ""),
    "layer_inspect": ("First-layer inspection", "bool", None, False, "X1: lidar checks the first layer."),
    "timelapse": ("Timelapse", "bool", None, False, ""),
    "copies": ("Copies", "int", (1, 50), 1, "How many of it, arranged on the plate."),
}


def clean_slice(raw) -> dict:
    """The slice options in `raw` that are sane, in their canonical form."""
    out: dict = {}
    if not isinstance(raw, dict):
        return out
    for key, (_label, _group, kind, spec, _pkey, _help) in SLICE.items():
        if key not in raw or raw[key] is None or raw[key] == "":
            continue
        value = raw[key]
        if kind in ("float", "int"):
            try:
                number = float(value) if kind == "float" else int(round(float(value)))
            except (TypeError, ValueError):
                continue
            if isinstance(value, bool):
                continue
            lo, hi, _step = spec
            if lo <= number <= hi:
                out[key] = number
        elif kind == "enum":
            word = str(value).strip().lower().replace("_", " ")
            if word in spec:
                out[key] = word
        elif kind == "bool":
            if isinstance(value, bool):
                out[key] = value
            elif str(value).lower() in ("true", "1", "yes", "on"):
                out[key] = True
            elif str(value).lower() in ("false", "0", "no", "off"):
                out[key] = False
    if out.get("nozzle_temp") == 0:
        out.pop("nozzle_temp")
    if out.get("infill_percent") == 100 and out.get("infill_pattern") and \
            SLICE["infill_pattern"][3][out["infill_pattern"]] not in SOLID_PATTERNS:
        out["infill_pattern"] = "rectilinear"
    return out


def _percent(value) -> float | None:
    try:
        return float(str(value).strip().rstrip("%"))
    except (TypeError, ValueError):
        return None


def _flag(value) -> bool:
    return str(value).strip().lower() in ("1", "true")


def reconcile(process: dict) -> tuple[dict, list[str]]:
    """The final process profile made consistent the way Bambu Studio's own
    validate() (PrintConfig.cpp) demands, so a slice never ends on exit -18
    over a combination: brAIn's settings over the profile's defaults can
    each be valid and still disagree (100 % infill over the profile's grid).

    Returns the corrected profile and one sentence per change.
    """
    out = dict(process)
    notes: list[str] = []
    density = _percent(out.get("sparse_infill_density"))
    pattern = str(out.get("sparse_infill_pattern") or "")
    if density is not None and abs(density - 100) < 1e-6 and pattern and pattern not in SOLID_PATTERNS:
        out["sparse_infill_pattern"] = SOLID_FALLBACK
        notes.append(f"{pattern} infill cannot print at 100 %, so it is rectilinear.")
    if _flag(out.get("spiral_mode")):
        wanted = {"wall_loops": "1", "sparse_infill_density": "0%", "top_shell_layers": "0",
                  "enable_support": "0", "enforce_support_layers": "0"}
        changed = [k for k, v in wanted.items() if str(out.get(k, v)) != v]
        out.update(wanted)
        if changed:
            notes.append("Spiral vase: one wall, no infill, no top layers, no supports.")
    for key in ("top_shell_layers", "bottom_shell_layers", "wall_loops"):
        try:
            if int(float(out.get(key, 0))) < 0:
                out[key] = "0"
        except (TypeError, ValueError):
            pass
    return out, notes


def clean_start(raw) -> dict:
    out: dict = {}
    if not isinstance(raw, dict):
        return out
    for key, (_label, kind, spec, _default, _help) in START.items():
        if key not in raw or raw[key] is None or raw[key] == "":
            continue
        value = raw[key]
        if kind == "bool":
            if isinstance(value, bool):
                out[key] = value
            elif str(value).lower() in ("true", "1", "yes", "on", "false", "0", "no", "off"):
                out[key] = str(value).lower() in ("true", "1", "yes", "on")
        elif kind == "enum":
            word = str(value).strip().lower().replace(" ", "_").replace("-", "_")
            if word in spec:
                out[key] = word
        elif kind == "int":
            try:
                number = int(value)
            except (TypeError, ValueError):
                continue
            if not isinstance(value, bool) and spec[0] <= number <= spec[1]:
                out[key] = number
    return out


def process_values(settings: dict) -> dict:
    """{Bambu Studio process key: value} for the slice options in `settings`."""
    out: dict = {}
    s = clean_slice(settings)
    for key, value in s.items():
        _label, _group, kind, spec, pkey, _help = SLICE[key]
        if key in FILAMENT_KEYS:
            continue
        if key == "supports":
            out["enable_support"] = "0" if value == "none" else "1"
            if value != "none":
                out["support_type"] = spec[value]
            continue
        if key == "infill_percent":
            out[pkey] = f"{value}%"
        elif kind == "float":
            out[pkey] = f"{value:g}"
        elif kind == "int":
            if key == "support_angle" and value == 0:
                continue
            out[pkey] = str(value)
        elif kind == "bool":
            out[pkey] = "1" if value else "0"
        else:
            out[pkey] = spec[value]
    if s.get("vase"):
        # The slicer refuses a vase with anything a vase cannot have.
        out.update(wall_loops="1", sparse_infill_density="0%", top_shell_layers="0",
                   enable_support="0", enforce_support_layers="0")
    plate = PLATES.get(str(settings.get("plate_type") or ""))
    if plate and plate[1]:
        out["curr_bed_type"] = plate[1]
    return out


def filament_values(settings: dict) -> dict:
    s = clean_slice(settings)
    out = {}
    if "nozzle_temp" in s:
        out["nozzle_temperature"] = [str(s["nozzle_temp"])]
        out["nozzle_temperature_initial_layer"] = [str(s["nozzle_temp"])]
    return out


def schema_properties() -> dict:
    """JSON-schema properties for brAIn's print_settings."""
    props: dict = {}
    for key, (label, _group, kind, spec, _pkey, help_text) in SLICE.items():
        desc = f"{label}. {help_text}".strip()
        if kind == "float":
            props[key] = {"type": "number", "minimum": spec[0], "maximum": spec[1], "description": desc}
        elif kind == "int":
            props[key] = {"type": "integer", "minimum": spec[0], "maximum": spec[1], "description": desc}
        elif kind == "enum":
            props[key] = {"type": "string", "enum": list(spec), "description": desc}
        else:
            props[key] = {"type": "boolean", "description": desc}
    for key, (label, kind, spec, _default, help_text) in START.items():
        desc = f"{label}. {help_text}".strip()
        if kind == "enum":
            props[key] = {"type": "string", "enum": list(spec), "description": desc}
        elif kind == "int":
            props[key] = {"type": "integer", "minimum": spec[0], "maximum": spec[1], "description": desc}
        else:
            props[key] = {"type": "boolean", "description": desc}
    return props


def catalog() -> dict:
    """What the print dialogs build their forms from."""
    return {
        "slice": [{"key": k, "label": v[0], "group": v[1], "kind": v[2],
                   "choices": list(v[3]) if v[2] == "enum" else None,
                   "range": list(v[3]) if v[2] in ("float", "int") else None, "help": v[5]}
                  for k, v in SLICE.items()],
        "start": [{"key": k, "label": v[0], "kind": v[1],
                   "choices": list(v[2]) if v[1] == "enum" else None,
                   "range": list(v[2]) if v[1] == "int" else None, "default": v[3], "help": v[4]}
                  for k, v in START.items()],
        "plates": {k: v[0] for k, v in PLATES.items()},
    }


def mqtt_bed_type(plate_type) -> str:
    return PLATES.get(str(plate_type or "auto"), PLATES["auto"])[2]
