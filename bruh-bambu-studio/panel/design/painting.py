"""Which filament each body of a designed part prints in.

A design built since 0.1.4 is one object with a part per body, and its
Metadata/model_settings.config names each part's filament (cad/mf3.py).
Printing decides which AMS tray each body comes from; the trays used, in
order, are the filaments the slicer is handed, so each part's number is
rewritten to its tray's place in that list. An older version's 3MF has no
such file and prints in one filament.
"""
from __future__ import annotations

import shutil
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

SETTINGS = "Metadata/model_settings.config"


def bodies(path: Path) -> list[str] | None:
    """The body names in a design 3MF, or None for one with no per-part filaments."""
    try:
        with zipfile.ZipFile(path) as archive:
            root = ET.fromstring(archive.read(SETTINGS))
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError):
        return None
    names = []
    for part in root.iter("part"):
        name = next((m.get("value") for m in part.findall("metadata") if m.get("key") == "name"), None)
        if name:
            names.append(name)
    return names or None


def plan(slots: dict) -> tuple[list, dict]:
    """{body: slot} -> (slots in filament order, {body: 1-based filament}).

    A slot is an AMS tray number, or "external" for the spool on the back.
    """
    order: list = []
    filament = {}
    for body, slot in slots.items():
        if slot not in order:
            order.append(slot)
        filament[body] = order.index(slot) + 1
    return order, filament


def retarget(source: Path, target: Path, filament: dict) -> None:
    """Copy `source` to `target` with each part's filament set from `filament`."""
    with zipfile.ZipFile(source) as archive:
        root = ET.fromstring(archive.read(SETTINGS))
        for obj in root.iter("object"):
            first = None
            for part in obj.findall("part"):
                meta = {m.get("key"): m for m in part.findall("metadata")}
                name = meta["name"].get("value") if "name" in meta else None
                number = str(filament.get(name, 1))
                first = first or number
                if "extruder" in meta:
                    meta["extruder"].set("value", number)
                else:
                    ET.SubElement(part, "metadata", key="extruder", value=number)
            for m in obj.findall("metadata"):
                if m.get("key") == "extruder" and first:
                    m.set("value", first)
        text = ET.tostring(root, encoding="unicode")
        target.parent.mkdir(parents=True, exist_ok=True)
        scratch = target.with_name(target.name + ".part")
        with zipfile.ZipFile(scratch, "w", zipfile.ZIP_DEFLATED) as out:
            for item in archive.infolist():
                if item.filename == SETTINGS:
                    out.writestr(SETTINGS, '<?xml version="1.0" encoding="UTF-8"?>\n' + text)
                else:
                    with archive.open(item) as src, out.open(item.filename, "w") as dst:
                        shutil.copyfileobj(src, dst)
    scratch.replace(target)
