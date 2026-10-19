"""Parts designed with brAIn: one folder each under /share/bambu/designs.

    designs/<id>/part.json          the conversation, versions, prints, state
    designs/<id>/v<n>/design.py     the script brAIn wrote for version n
    designs/<id>/v<n>/report.json   what the build found
    designs/<id>/v<n>/<name>.3mf    ... .stl, .step, bodies/<Body>.stl

On the share, so the STEP and 3MF are reachable over Samba and from Bambu
Studio's own Open dialog as well as from the Design tab. A version is never
edited after it is built: going back to one makes it current, and the next
change becomes a new version on top, so nothing is lost by trying an idea.
"""
from __future__ import annotations

import os
import re
import threading
import time
import uuid
from pathlib import Path

import bambu_atomic
import library

DESIGNS = "designs"
MAX_MESSAGES = 200
ID = re.compile(r"^[a-z0-9-]{4,60}$")
_LOCK = threading.RLock()


def root() -> Path:
    return library.ROOT / DESIGNS


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:30]
    return slug or "part"


def folder(part_id: str) -> Path:
    """A part's folder. The id arrives off the wire, so it is checked for
    shape AND the result is normalised and held under the designs folder —
    the second is the form a path check can be read in (brAIn's
    `transcript_path` makes the same pair for the same reason)."""
    if not ID.match(str(part_id or "")):
        raise ValueError("No such part.")
    base = os.path.normpath(os.path.realpath(root()))
    candidate = os.path.normpath(os.path.join(base, part_id))
    if not candidate.startswith(base + os.sep):
        raise ValueError("No such part.")
    return Path(candidate)


def load(part_id: str) -> dict:
    data = bambu_atomic.read_json(folder(part_id) / "part.json", None)
    if not isinstance(data, dict):
        raise LookupError("No such part.")
    return data


def save(part: dict) -> dict:
    with _LOCK:
        part["updated"] = time.time()
        part["messages"] = part.get("messages", [])[-MAX_MESSAGES:]
        bambu_atomic.write_json(folder(part["id"]) / "part.json", part)
    return part


def create(name: str) -> dict:
    name = str(name or "").strip()[:80] or "New part"
    part_id = f"{_slug(name)}-{uuid.uuid4().hex[:6]}"
    folder(part_id).mkdir(parents=True, exist_ok=False)
    now = time.time()
    return save({"id": part_id, "name": name, "created": now, "updated": now,
                 "session_id": "", "current": None, "versions": [], "messages": [],
                 "print_settings": None, "prints": [], "state": "idle",
                 "state_detail": "", "error": ""})


def listing() -> list[dict]:
    if not root().is_dir():
        return []
    out = []
    for path in root().glob("*/part.json"):
        part = bambu_atomic.read_json(path, None)
        if not isinstance(part, dict):
            continue
        current = version(part, part.get("current"))
        out.append({"id": part["id"], "name": part.get("name"), "updated": part.get("updated"),
                    "versions": len(part.get("versions", [])), "current": part.get("current"),
                    "state": part.get("state"), "prints": len(part.get("prints", [])),
                    "size_mm": (current or {}).get("size_mm"),
                    "thumbnail": (folder(part["id"]) / "thumb.png").is_file()})
    out.sort(key=lambda p: p.get("updated") or 0, reverse=True)
    return out


def version(part: dict, n) -> dict | None:
    for row in part.get("versions", []):
        if row.get("n") == n:
            return row
    return None


def version_dir(part_id: str, n: int) -> Path:
    return folder(part_id) / f"v{int(n)}"


def next_version(part: dict) -> int:
    return max([v.get("n", 0) for v in part.get("versions", [])] + [0]) + 1


def say(part: dict, role: str, text: str, **extra) -> None:
    part.setdefault("messages", []).append(
        {"role": role, "text": str(text or "")[:8000], "at": time.time(), **extra})


def file_in(part_id: str, n: int, relative: str) -> Path:
    """A built file of one version, never anything outside it."""
    base = os.path.normpath(os.path.realpath(version_dir(part_id, n)))
    path = os.path.normpath(os.path.realpath(os.path.join(base, relative)))
    if not path.startswith(base + os.sep) or not os.path.isfile(path):
        raise LookupError("No such file.")
    return Path(path)
