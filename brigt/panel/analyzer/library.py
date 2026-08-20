"""The music library: what is in the folder, and what has been analyzed.

Track identity is a content hash (size + first megabyte), not the path —
renaming a file must not cost its analysis, and two copies of one track
are one analysis. Everything derived lives under /data/shows/<hash>/.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

import atomic_write

SHOWS_DIR = Path(os.environ.get("BRIGT_STATE", "/data")) / "shows"

AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wav"}

_HASH_RE = re.compile(r"^[0-9a-f]{40}$")


def track_hash(path: Path) -> str:
    """sha1 of (size, first 1MB). Fast enough to hash a folder on every
    scan, stable across renames, and collision-proof enough for a music
    library."""
    digest = hashlib.sha1()
    stat = path.stat()
    digest.update(str(stat.st_size).encode())
    with open(path, "rb") as handle:
        digest.update(handle.read(1024 * 1024))
    return digest.hexdigest()


def _track_dir(hash_hex: str) -> Path:
    if not _HASH_RE.fullmatch(hash_hex):
        raise ValueError(f"not a track hash: {hash_hex!r}")
    return SHOWS_DIR / hash_hex


def analysis_path(hash_hex: str) -> Path:
    return _track_dir(hash_hex) / "analysis.json"


def load_analysis(hash_hex: str) -> dict | None:
    try:
        return json.loads(analysis_path(hash_hex).read_text())
    except (OSError, ValueError):
        return None


def save_analysis(hash_hex: str, analysis: dict) -> None:
    atomic_write.write_json(analysis_path(hash_hex), analysis)


def scan(folder: Path) -> list[dict]:
    """Every audio file under `folder`, with its hash and analysis state."""
    tracks = []
    folder = Path(folder)
    if not folder.is_dir():
        return tracks
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in AUDIO_EXTENSIONS:
            continue
        try:
            hash_hex = track_hash(path)
        except OSError:
            continue
        analysis = load_analysis(hash_hex)
        entry = {
            "file": str(path),
            "name": path.stem,
            "hash": hash_hex,
            "analyzed": analysis is not None,
        }
        if analysis:
            entry["summary"] = {
                "bpm": analysis.get("bpm"),
                "duration": (analysis.get("tags") or {}).get("duration"),
                "sections": len(analysis.get("sections") or []),
                "drops": len(analysis.get("drops") or []),
                "lyrics": bool((analysis.get("lyrics") or {}).get("synced")),
            }
        tracks.append(entry)
    return tracks
