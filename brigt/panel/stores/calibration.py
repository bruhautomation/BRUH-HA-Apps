"""Per-media-player latency profiles.

A profile is a set of measured runs plus the derived answer playback
actually uses (`offset_ms`, the median). Runs accumulate — the spread
between them is the honest error bar, and a new speaker session that
measures differently shows up as spread before it shows up as a broken
show. A manual fine-tune is stored as an adjustment on top of the
measured offset, never instead of it: re-measuring must not silently
discard a nudge, and nudging must not overwrite a measurement.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import atomic_write

CALIBRATION_DIR = Path(os.environ.get("BRIGT_STATE", "/data")) / "calibration"

MAX_RUNS = 12


def _path(entity_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", entity_id)
    return CALIBRATION_DIR / f"{safe}.json"


def load(entity_id: str) -> dict:
    try:
        return json.loads(_path(entity_id).read_text())
    except (OSError, ValueError):
        return {"entity_id": entity_id, "runs": [], "adjust_ms": 0}


def _derive(profile: dict) -> dict:
    offsets = sorted(run["offset_ms"] for run in profile["runs"])
    if offsets:
        median = offsets[len(offsets) // 2]
        profile["offset_ms"] = median
        profile["spread_ms"] = round(offsets[-1] - offsets[0], 1)
    profile["effective_offset_ms"] = round(
        profile.get("offset_ms", 0) + profile.get("adjust_ms", 0), 1)
    return profile


def add_run(entity_id: str, offset_ms: float, *, method: str,
            confidence: float | None = None,
            position_attr: dict | None = None) -> dict:
    profile = load(entity_id)
    run = {
        "offset_ms": round(float(offset_ms), 1),
        "method": method,
        "measured_at": time.time(),
    }
    if confidence is not None:
        run["confidence"] = confidence
    profile["runs"] = (profile.get("runs") or [])[-(MAX_RUNS - 1):] + [run]
    if position_attr is not None:
        profile["position_attr"] = position_attr
    profile = _derive(profile)
    atomic_write.write_json(_path(entity_id), profile, indent=2)
    return profile


def set_adjust(entity_id: str, adjust_ms: float) -> dict:
    """The fine-tune slider: a delta on top of the measured offset."""
    profile = load(entity_id)
    profile["adjust_ms"] = round(float(adjust_ms), 1)
    profile = _derive(profile)
    atomic_write.write_json(_path(entity_id), profile, indent=2)
    return profile


def all_profiles() -> list[dict]:
    profiles = []
    try:
        for path in sorted(CALIBRATION_DIR.glob("*.json")):
            try:
                profiles.append(json.loads(path.read_text()))
            except (OSError, ValueError):
                continue
    except OSError:
        pass
    return profiles


def best_entity() -> str | None:
    """The most recently calibrated player — party mode's default."""
    newest, newest_at = None, 0.0
    for profile in all_profiles():
        for run in profile.get("runs", []):
            if run.get("measured_at", 0) > newest_at:
                newest, newest_at = profile.get("entity_id"), run["measured_at"]
    return newest
