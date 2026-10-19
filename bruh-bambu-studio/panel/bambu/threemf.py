"""What is inside a .3mf: is it sliced, which plates, how long, how much.

A Bambu project and a Bambu print job are both .3mf archives. The
difference that matters is whether `Metadata/plate_N.gcode` is in it — the
printer prints that file and nothing else, so an unsliced project sent to
it is a print that never starts. Everything here reads the zip and never
the model, so it is cheap enough to run on every file in the library.
"""
from __future__ import annotations

import json
import re
import zipfile
import xml.etree.ElementTree as ET

PLATE_GCODE = re.compile(r"^Metadata/plate_(\d+)\.gcode$")
# What an archive may hold before we stop trusting it to be a print job.
MAX_ENTRIES = 5000


def inspect(path: str) -> dict:
    """{sliced, project, plates, filaments, seconds, grams} — empty answers as None.

    `project` is a Bambu Studio project, which carries the printer and
    process it is set up for; a 3MF from anywhere else is a bare model and
    has to be given profiles before it can be sliced."""
    out = {"sliced": False, "project": False, "plates": [], "filaments": None,
           "seconds": None, "grams": None}
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) > MAX_ENTRIES:
                return out
            plates = sorted(int(m.group(1)) for n in names
                            if (m := PLATE_GCODE.match(n)))
            out["plates"] = plates
            out["sliced"] = bool(plates)
            out["project"] = "Metadata/project_settings.config" in names
            if "Metadata/slice_info.config" in names:
                _slice_info(archive.read("Metadata/slice_info.config"), out)
            if out["filaments"] is None and plates:
                info = f"Metadata/plate_{plates[0]}.json"
                if info in names:
                    try:
                        data = json.loads(archive.read(info))
                        ids = data.get("filament_ids") or data.get("filament_colors")
                        if isinstance(ids, list):
                            out["filaments"] = len(ids)
                    except ValueError:
                        pass  # a plate description we cannot read counts nothing
    except (OSError, zipfile.BadZipFile):
        return out
    return out


def _slice_info(raw: bytes, out: dict) -> None:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return
    seconds = grams = 0.0
    filaments = set()
    for plate in root.iter("plate"):
        for meta in plate.iter("metadata"):
            key, value = meta.get("key"), meta.get("value")
            try:
                if key == "prediction":
                    seconds += float(value)
                elif key == "weight":
                    grams += float(value)
            except (TypeError, ValueError):
                continue
        for filament in plate.iter("filament"):
            filaments.add(filament.get("id"))
    out["seconds"] = int(seconds) or None
    out["grams"] = round(grams, 1) or None
    if filaments:
        out["filaments"] = len(filaments)


def ams_mapping(info: dict) -> list[int]:
    """Filament n from AMS slot n, which is what Bambu Studio sends when
    nobody has re-mapped anything. A print that wants other slots names
    them."""
    count = info.get("filaments") or 1
    return list(range(max(1, min(int(count), 16))))
