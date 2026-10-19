"""Models and print jobs under /share/bambu.

/share rather than /data, so Samba, the File Editor and Bambu Studio's own
Open dialog all reach the same folder: drop an STL in from a laptop, open it
in the slicer in the sidebar, print the result from an automation.

Every name that arrives off the wire is resolved and checked to be inside
the library before anything opens it — a `..` in an uploaded file's name is
the classic way out of a folder.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

from bambu import threemf

ROOT = Path(os.environ.get("BAMBU_LIBRARY", "/share/bambu"))
SLICED = "sliced"
DESIGNS = "designs"
# What the add-on writes for itself: a slice made on the way to a print, and
# every version of every designed part with its per-body meshes. The Files
# list is what somebody brought in, so these stay out of it; a designed part
# appears there once, as its current version (server.h_files).
WORKING = (SLICED, DESIGNS)
SUFFIXES = (".3mf", ".stl", ".step", ".stp", ".obj", ".amf")
MAX_UPLOAD = 512 * 1024 * 1024
NAME = re.compile(r"^[^/\\\x00]{1,160}$")


def ensure() -> None:
    (ROOT / SLICED).mkdir(parents=True, exist_ok=True)


def path_of(relative: str) -> Path:
    """An existing-or-not path inside the library, or ValueError."""
    rel = str(relative or "").strip().lstrip("/")
    if not rel or "\x00" in rel:
        raise ValueError("No file named.")
    # realpath so a link cannot lead out; normpath + the prefix check is
    # the form a path check is read in.
    root = os.path.normpath(os.path.realpath(ROOT))
    candidate = os.path.normpath(os.path.realpath(os.path.join(root, rel)))
    if not candidate.startswith(root + os.sep):
        raise ValueError("That file is outside the Bambu library.")
    return Path(candidate)


def relative(path: Path) -> str:
    return os.path.relpath(os.path.realpath(path), os.path.realpath(ROOT))


def listing(working: bool = False) -> list[dict]:
    """The model files in the library; `working` adds the add-on's own."""
    if not ROOT.is_dir():
        return []
    out = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        top = path.relative_to(ROOT).parts[0]
        if not working and top in WORKING:
            continue
        name = path.name.lower()
        if not name.endswith(SUFFIXES):
            continue
        stat = path.stat()
        row = {"path": relative(path), "name": path.name, "size": stat.st_size,
               "modified": int(stat.st_mtime)}
        if name.endswith(".3mf"):
            row.update(threemf.inspect(str(path)))
        else:
            row.update(sliced=False, project=False)
        out.append(row)
    out.sort(key=lambda r: r["modified"], reverse=True)
    return out


def safe_upload_name(name: str) -> str:
    base = os.path.basename(str(name or "").replace("\\", "/")).strip()
    if not NAME.match(base) or base.startswith(".") or not base.lower().endswith(SUFFIXES):
        raise ValueError("Upload a .3mf, .stl, .step, .obj or .amf file.")
    return base


def unique(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.name, ""
    for ext in (".gcode.3mf",) + SUFFIXES:
        if path.name.lower().endswith(ext):
            stem, suffix = path.name[: -len(ext)], path.name[-len(ext):]
            break
    return path.with_name(f"{stem}-{time.strftime('%Y%m%d-%H%M%S')}{suffix}")
