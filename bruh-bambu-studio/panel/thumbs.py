"""Pictures of files: in the library, and on a printer's own storage.

A 3MF that Bambu Studio wrote carries its own picture of each plate
(`Metadata/plate_N.png`), so that is read out of the zip. A bare mesh (STL,
OBJ, STEP, a 3MF with no picture) is drawn once by cad/thumb.py in the CAD
virtualenv and kept. A file on the printer is read where it lies — the zip's
directory and the one picture, a few kilobytes over FTPS — and kept too.

Every picture is cached under /data/thumbs, keyed by what would change it
(the path, size and time for a library file; the name and size on a
printer), and a file with no picture is remembered as having none, so the
list never asks again.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import threading
import zipfile
from pathlib import Path

CACHE = Path(os.environ.get("BAMBU_THUMBS", "/data/thumbs"))
CAD_PYTHON = Path(os.environ.get("BAMBU_CAD_PYTHON", "/opt/cad/bin/python"))
CAD_DIR = Path(os.environ.get("BAMBU_CAD_DIR", "/opt/bruh-bambu/cad"))
RENDER_TIMEOUT = 90
MAX_RENDER_BYTES = 200 * 1024 * 1024
MESHES = (".stl", ".obj", ".amf", ".3mf", ".step", ".stp")
NONE = b""
# Printer pictures are cached under this generation: an older release could
# remember a read that went wrong as "no picture", and those are not trusted.
PRINTER_CACHE = "printer2"
# One storage session per printer at a time: a list of jobs asks for every
# picture at once, and a printer's FTPS server serves one session well and
# refuses or stalls the rest.
_PRINTER_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_LOCK = threading.Lock()


def _printer_lock(serial: str) -> threading.Lock:
    with _LOCKS_LOCK:
        return _PRINTER_LOCKS.setdefault(str(serial), threading.Lock())


def png_member(names: list[str], plate: int = 1) -> str | None:
    """The best picture inside a 3MF, by the names Bambu Studio writes."""
    wanted = [f"Metadata/plate_{plate}.png", f"Metadata/plate_{plate}_small.png",
              "Metadata/plate_1.png", "Auxiliaries/.thumbnails/thumbnail_middle.png",
              "Auxiliaries/.thumbnails/thumbnail_3mf.png", "Metadata/thumbnail.png"]
    present = set(names)
    for name in wanted:
        if name in present:
            return name
    for name in sorted(names):
        low = name.lower()
        if low.startswith("metadata/plate_") and low.endswith(".png") and "no_light" not in low:
            return name
    return None


def from_zip(handle, plate: int = 1, *, quiet: bool = True) -> bytes | None:
    """The picture out of an open 3MF (a path or a file object), or None.

    `quiet=False` lets a read error through, for a file read over the
    network: "could not reach it" must not be remembered as "has none".
    """
    try:
        with zipfile.ZipFile(handle) as archive:
            member = png_member(archive.namelist(), plate)
            if member is None:
                return None
            info = archive.getinfo(member)
            if info.file_size > 8 * 1024 * 1024:
                return None
            data = archive.read(member)
    except (zipfile.BadZipFile, KeyError, EOFError, ValueError):
        return None
    except OSError:
        if quiet:
            return None
        raise
    return data if data.startswith(b"\x89PNG") else None


def _key(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:24]


def _cached(path: Path):
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return data


def _store(path: Path, data: bytes) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        scratch = path.with_name(path.name + ".tmp")
        scratch.write_bytes(data)
        os.replace(scratch, path)
    except OSError:
        pass  # a picture that cannot be cached is drawn again next time


def render(model: Path, out: Path) -> bool:
    if not CAD_PYTHON.is_file() or not (CAD_DIR / "thumb.py").is_file():
        return False
    try:
        if model.stat().st_size > MAX_RENDER_BYTES:
            return False
        out.parent.mkdir(parents=True, exist_ok=True)
        done = subprocess.run([str(CAD_PYTHON), str(CAD_DIR / "thumb.py"), str(model), str(out), "256"],
                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=RENDER_TIMEOUT, env={
                                  "PATH": "/usr/bin:/bin", "HOME": str(out.parent)})
    except (OSError, subprocess.TimeoutExpired):
        return False
    return done.returncode == 0 and out.is_file()


def library(path: Path, plate: int = 1) -> bytes | None:
    """A library file's picture, or None when it has none."""
    try:
        stat = path.stat()
    except OSError:
        return None
    lower = path.name.lower()
    cache = CACHE / "library" / f"{_key(path, stat.st_size, int(stat.st_mtime), plate)}.png"
    hit = _cached(cache)
    if hit is not None:
        return hit or None
    data = from_zip(str(path), plate) if lower.endswith(".3mf") else None
    if data is None and lower.endswith(MESHES):
        scratch = cache.with_name(cache.name + ".render.png")
        if render(path, scratch):
            data = _cached(scratch)
            scratch.unlink(missing_ok=True)
    _store(cache, data or NONE)
    return data


def printer(serial: str, name: str, size: int, open_storage) -> bytes | None:
    """A file on a printer's storage, read in place. `open_storage()` is a
    context manager yielding a bambu.ftps.Storage."""
    cache = CACHE / PRINTER_CACHE / _key(serial) / f"{_key(name, size)}.png"
    hit = _cached(cache)
    if hit is not None:
        return hit or None
    if not name.lower().endswith(".3mf") or not size:
        _store(cache, NONE)
        return None
    from bambu.ftps import RemoteFile
    with _printer_lock(serial):
        hit = _cached(cache)  # another request may have read it meanwhile
        if hit is not None:
            return hit or None
        with open_storage() as storage:
            remote = RemoteFile(storage, name, size)
            data = from_zip(remote, quiet=False)
            if remote.error is not None:
                raise OSError(f"Could not read {name} on the printer: {remote.error}")
    _store(cache, data or NONE)
    return data
