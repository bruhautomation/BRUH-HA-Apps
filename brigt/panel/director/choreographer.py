"""The algorithmic director: analysis + light map → a show script.

Deterministic on purpose — same track, same map, same script — so a show
someone liked on Friday is the show they get on Saturday, and a test can
assert the whole output. This tier is also the FLOOR: whatever the Claude
tier produces is validated against the same schema, and any failure lands
back here, so a show always compiles.
"""
from __future__ import annotations

from . import palettes

SCRIPT_VERSION = 1


def _mood(kind: str) -> str:
    return {
        "intro": "arrive", "quiet": "hold", "mid": "roll",
        "peak": "lift", "outro": "land",
    }.get(kind, "roll")


def _motifs_for(kind: str, roles_present: set[str]) -> list[dict]:
    """What moves during a section of this energy, given who is on stage."""
    motifs: list[dict] = []
    pulsing = [r for r in ("lamp", "downlight", "strip")
               if r in roles_present]
    if "candle" in roles_present:
        motifs.append({"type": "breathe", "roles": ["candle"],
                       "period_beats": 16, "depth": 0.15})
    if kind in ("mid", "peak") and pulsing:
        motifs.append({"type": "beat_pulse", "roles": pulsing,
                       "shape": "sine", "beats": 1})
    if kind == "peak":
        if "strip" in roles_present or len(pulsing) >= 3:
            motifs.append({"type": "sweep",
                           "roles": pulsing or ["lamp"],
                           "axis": "x", "period_beats": 8})
        for switch_role in ("party", "laser"):
            if switch_role in roles_present:
                motifs.append({"type": "aux_on", "roles": [switch_role]})
    elif kind == "mid" and "party" in roles_present:
        motifs.append({"type": "aux_on", "roles": ["party"]})
    if kind in ("intro", "quiet", "outro") and pulsing:
        motifs.append({"type": "breathe", "roles": pulsing,
                       "period_beats": 8, "depth": 0.10})
    return motifs


def write_script(analysis: dict, fixtures: list[dict]) -> dict:
    roles_present = {f["role"] for f in fixtures}
    seed = int((analysis.get("hash") or "0")[:8] or "0", 16)
    palette_name, palette = palettes.pick_palette(
        float(analysis.get("brightness", 0.5)), seed)

    scenes = []
    for section in analysis.get("sections") or []:
        base, depth = palettes.SECTION_LEVELS.get(
            section["kind"], palettes.SECTION_LEVELS["mid"])
        motifs = _motifs_for(section["kind"], roles_present)
        for motif in motifs:
            if motif["type"] == "beat_pulse":
                motif["depth"] = depth
        scenes.append({
            "start": float(section["start"]),
            "end": float(section["end"]),
            "mood": _mood(section["kind"]),
            "kind": section["kind"],
            "palette": palette,
            "brightness": base,
            "motifs": motifs,
        })

    features = []
    for drop in analysis.get("drops") or []:
        hit_roles = [r for r in ("laser", "party", "strip", "lamp",
                                 "downlight") if r in roles_present]
        features.append({
            "t": float(drop["t"]),
            "type": "drop_hit",
            "roles": hit_roles or ["lamp"],
            "strength": float(drop.get("strength", 0.8)),
            "blackout_before_ms": 400,
        })

    return {
        "version": SCRIPT_VERSION,
        "tier": "algorithmic",
        "track_hash": analysis.get("hash"),
        "palette_name": palette_name,
        "scenes": scenes,
        "features": features,
    }


def validate_script(script: dict) -> list[str]:
    """Why a script is unusable, or an empty list. The Claude tier's output
    goes through here; anything listed sends that track to this tier
    instead. Checks shape and vocabulary — taste can't be validated."""
    problems: list[str] = []
    if not isinstance(script, dict):
        return ["script is not an object"]
    scenes = script.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        problems.append("no scenes")
        scenes = []
    last_end = 0.0
    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            problems.append(f"scene {i} is not an object")
            continue
        try:
            start, end = float(scene["start"]), float(scene["end"])
            if end <= start:
                problems.append(f"scene {i} ends before it starts")
            if start < last_end - 1.0:
                problems.append(f"scene {i} overlaps the previous one")
            last_end = end
        except (KeyError, TypeError, ValueError):
            problems.append(f"scene {i} has no usable start/end")
        palette = scene.get("palette")
        if (not isinstance(palette, list) or not palette
                or not all(isinstance(p, (list, tuple)) and len(p) == 2
                           for p in palette)):
            problems.append(f"scene {i} has no palette of [hue, sat] pairs")
        try:
            if not 0.0 <= float(scene.get("brightness", -1)) <= 1.0:
                problems.append(f"scene {i} brightness outside 0..1")
        except (TypeError, ValueError):
            problems.append(f"scene {i} brightness is not a number")
        for j, motif in enumerate(scene.get("motifs") or []):
            if (not isinstance(motif, dict)
                    or motif.get("type") not in palettes.MOTIF_TYPES):
                problems.append(f"scene {i} motif {j}: unknown type")
            elif not motif.get("roles"):
                problems.append(f"scene {i} motif {j}: no roles")
    for k, feature in enumerate(script.get("features") or []):
        if not isinstance(feature, dict):
            problems.append(f"feature {k} is not an object")
            continue
        if feature.get("type") not in palettes.FEATURE_TYPES:
            problems.append(f"feature {k}: unknown type")
        try:
            float(feature["t"])
        except (KeyError, TypeError, ValueError):
            problems.append(f"feature {k}: no usable time")
    return problems
