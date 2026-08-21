"""The algorithmic director: analysis + light map → a show script.

Deterministic on purpose — same track, same map, same script — so a show
someone liked on Friday is the show they get on Saturday, and a test can
assert the whole output. This tier is also the FLOOR: whatever the Claude
tier produces is validated against the same schema, and any failure lands
back here, so a show always compiles.

It writes EFFECTS, and it writes them off the map
-------------------------------------------------
Everything this tier emits is an ordinary effect instance — the same
objects the Effects tab builds and the same ones a person can edit in the
script afterwards. There is no private vocabulary the automatic show can
use and a hand-written one cannot, which is the whole reason "automatic
but completely editable" is true rather than aspirational.

Where a light *is* decides what it does. A chase needs an order and the
map is what supplies it: left to right across the room, out from the
middle, or reading-order through the zones when the map has them. With
one or two lights a chase is a flicker, so it takes a different shape
below three — the map is not decoration.
"""
from __future__ import annotations

from . import palettes

SCRIPT_VERSION = 2

# Roles that carry motion, in the order a scene reaches for them.
_MOVERS = ("lamp", "downlight", "strip")

# How far ahead of a drop the build starts, in beats. Four bars: long
# enough to be felt as tension, short enough that the section it borrows
# from still reads as itself.
BUILD_BEATS = 16


def _mood(kind: str) -> str:
    return {
        "intro": "arrive", "quiet": "hold", "mid": "roll",
        "peak": "lift", "outro": "land",
    }.get(kind, "roll")


def _chase_order(seed: int, zones: bool) -> str:
    """Which way a chase travels. Seeded so it is stable per track, and
    varied so two songs in a row do not run the identical pattern."""
    if zones:
        return "zone"
    return ("x", "-x", "center_out", "snake")[seed % 4]


def _effects_for(kind: str, roles: set[str], movers: list[str],
                 mover_count: int, seed: int, zones: bool,
                 depth: float, has_music: bool = False) -> list[dict]:
    """What moves during a section of this energy, given who is on stage.

    Every branch here is a judgement about taste, and all of them are
    reversible: the result is a list of effects in the script, so a
    person who disagrees edits the line rather than the code.
    """
    effects: list[dict] = []
    if "candle" in roles:
        effects.append({
            "type": "breathe", "name": "candles", "select": {"roles": ["candle"]},
            "params": {"period_beats": 16, "depth": 0.12}})

    effects.extend(_musical_layers(kind, roles, movers, has_music))

    if not movers:
        return effects

    mover_select = {"roles": movers}

    if kind in ("intro", "outro"):
        effects.append({
            "type": "fade", "name": f"{kind} fade", "select": mover_select,
            "params": {
                "from_brightness": 0.12 if kind == "intro" else 0.45,
                "to_brightness": 0.45 if kind == "intro" else 0.08,
                "curve": "ease_in_out", "steps": 12}})
        return effects

    if kind == "quiet":
        effects.append({
            "type": "breathe", "name": "quiet breath", "select": mover_select,
            "params": {"period_beats": 8, "depth": 0.10}})
        return effects

    effects.append({
        "type": "pulse", "name": "beat pulse", "select": mover_select,
        "params": {"every_beats": 1, "depth": depth, "shape": "sine",
                   "cycles_per_cue": 8}})

    if kind == "mid":
        # Colour movement rather than brightness movement: the room is
        # already lit, and cycling the palette is what reads as motion
        # without turning a verse into a chorus.
        effects.append({
            "type": "colour_cycle", "name": "verse colours",
            "select": mover_select,
            "params": {"every_beats": 8, "rotate": 1, "fade_ms": 600,
                       "brightness": 0.6}})
        if "party" in roles:
            effects.append({"type": "aux", "name": "party lights",
                            "select": {"roles": ["party"]},
                            "params": {"state": "on"}})
        return effects

    # peak — the section that has earned everything.
    if mover_count >= 3:
        effects.append({
            "type": "chase", "name": "peak chase", "select": mover_select,
            "order": _chase_order(seed, zones),
            "params": {"step_beats": 0.5, "width": max(1, mover_count // 3),
                       "bounce": bool(seed % 2), "background": 0.12,
                       "brightness": 1.0, "fade_ms": 80}})
    else:
        # Two lights cannot chase — they flicker. They can answer each
        # other, which is the same idea at the size the room actually is.
        effects.append({
            "type": "theater", "name": "peak alternation",
            "select": mover_select,
            "params": {"step_beats": 1, "groups": 2, "background": 0.15}})
    if "strip" in roles:
        effects.append({
            "type": "sweep", "name": "strip sweep",
            "select": {"roles": ["strip"]}, "order": "x",
            "params": {"period_beats": 8, "depth": 0.4, "repeats": 8}})
    for switch_role in ("party", "laser"):
        if switch_role in roles:
            effects.append({"type": "aux", "name": f"{switch_role} on",
                            "select": {"roles": [switch_role]},
                            "params": {"state": "on"}})
    return effects


def _musical_layers(kind: str, roles: set, movers: list,
                    has_music: bool) -> list[dict]:
    """The two layers that follow what the song is PLAYING.

    Kept apart from the rhythmic effects above on purpose, because they
    answer a different question and belong on different lights. Harmony
    is the ground — slow, wide, on whatever is not carrying the beat, so
    the room's colour turns over with the chords instead of with the
    section map. Melody is a voice: one kind of light, one note at a
    time, following the tune.

    Where they are NOT placed is the taste in this function. Melody sits
    out the peaks: a chorus already has a chase across every mover and a
    stab on every accent, and a third thing competing for the same bulbs
    on eighth notes is not more musical, it is mush. The tune gets the
    verses and the quiet parts, which is where a person can hear it and
    where the lights have room to answer.

    A track with no musical analysis gets neither, rather than two
    effects that render to nothing — the compiler would explain the
    silence, but a show should not need explaining.
    """
    if not has_music:
        return []
    out: list[dict] = []
    ground = [r for r in ("candle", "strip") if r in roles] or movers
    if kind in ("intro", "quiet", "mid", "outro") and ground:
        out.append({
            "type": "harmony", "name": "chord colour",
            "select": {"roles": ground},
            "params": {"brightness": 0.45 if kind in ("intro", "outro")
                       else 0.55,
                       "fade_ms": 1600, "spread": "single"}})
    lead = next((r for r in ("lamp", "downlight", "strip") if r in roles),
                None)
    if kind in ("quiet", "mid") and lead:
        out.append({
            "type": "melody", "name": "the tune",
            "select": {"roles": [lead]},
            "params": {"hue_spread": 0.45 if kind == "quiet" else 0.65,
                       "brightness": 0.8, "fade_ms": 90,
                       "min_strength": 0.3, "voices": 1, "hold": True}})
    return out


def write_script(analysis: dict, fixtures: list[dict]) -> dict:
    roles_present = {f["role"] for f in fixtures}
    zones = any((f.get("zone") or "").strip() for f in fixtures)
    movers = [r for r in _MOVERS if r in roles_present]
    mover_count = sum(1 for f in fixtures if f["role"] in movers)
    seed = int((analysis.get("hash") or "0")[:8] or "0", 16)
    musical = analysis.get("music") or {}
    has_music = bool(musical.get("notes") or musical.get("chords"))
    palette_name, palette = palettes.pick_palette(
        float(analysis.get("brightness", 0.5)), seed)

    scenes = []
    for section in analysis.get("sections") or []:
        base, depth = palettes.SECTION_LEVELS.get(
            section["kind"], palettes.SECTION_LEVELS["mid"])
        scenes.append({
            "start": float(section["start"]),
            "end": float(section["end"]),
            "mood": _mood(section["kind"]),
            "kind": section["kind"],
            "palette": palette,
            "brightness": base,
            "effects": _effects_for(section["kind"], roles_present, movers,
                                    mover_count, seed, zones, depth,
                                    has_music),
        })

    # Moments: the build into a drop and the hit itself. The build is a
    # separate effect with its own window rather than part of the scene,
    # because tension crosses section boundaries — it starts inside the
    # section before the drop and ends on it.
    beat_s = _beat_seconds(analysis)
    moments = []
    for drop in analysis.get("drops") or []:
        at = float(drop["t"])
        if movers:
            moments.append({
                "t": max(0.0, at - BUILD_BEATS * beat_s),
                "effect": {
                    "type": "build", "name": "drop build",
                    "select": {"roles": movers},
                    "order": "center_out",
                    "start": max(0.0, at - BUILD_BEATS * beat_s),
                    "end": at,
                    "params": {"from_brightness": 0.15, "to_brightness": 0.95,
                               "step_beats": 1, "stagger": True,
                               "curve": "exp", "saturate": True}}})
        hit_roles = [r for r in ("laser", "party", "strip", "lamp", "downlight")
                     if r in roles_present]
        moments.append({
            "t": at,
            "effect": {"type": "stab", "name": "drop hit",
                       "select": {"roles": hit_roles or movers},
                       "params": {"strength": float(drop.get("strength", 0.8)),
                                  "blackout_before_ms": 400, "hold_ms": 500}}})
        if "party" in roles_present or "laser" in roles_present:
            moments.append({
                "t": at,
                "effect": {"type": "aux", "name": "drop aux",
                           "select": {"roles": [r for r in ("party", "laser")
                                                if r in roles_present]},
                           "params": {"state": "on"}}})

    # Accents between the drops: the strongest ON-BEAT hits get a stab of
    # their own, so the show answers the song's actual punches rather
    # than only its section boundaries. Restraint is the design: only
    # hits the analyzer ranked near the top, only in the loud half of the
    # song (a stab in a verse is a wrong number), at least eight beats
    # apart so they read as moments rather than a strobe, clear of the
    # drops (which already own their hits), and never more than six —
    # one intentional accent beats three busy ones.
    drop_times = [float(d["t"]) for d in analysis.get("drops") or []]
    loud = [s for s in analysis.get("sections") or []
            if float(s.get("energy", 0)) >= 0.6]
    hit_roles = [r for r in ("strip", "lamp", "downlight")
                 if r in roles_present]
    if hit_roles:
        placed: list[float] = []
        strongest = sorted((h for h in analysis.get("hits") or []
                            if h.get("on_beat") and h.get("strength", 0) >= 0.55),
                           key=lambda h: h["strength"], reverse=True)
        for hit in strongest:
            if len(placed) >= 6:
                break
            at = float(hit["t"])
            if not any(float(s["start"]) <= at < float(s["end"]) for s in loud):
                continue
            if any(abs(at - d) < 2.0 for d in drop_times):
                continue
            if any(abs(at - p) < 8 * beat_s for p in placed):
                continue
            placed.append(at)
            moments.append({
                "t": at,
                "effect": {"type": "stab", "name": "accent",
                           "select": {"roles": hit_roles},
                           "params": {"strength": round(
                               0.5 + 0.4 * float(hit["strength"]), 2),
                               "blackout_before_ms": 0,
                               "hold_ms": 260, "white": False}}})

    return {
        "version": SCRIPT_VERSION,
        "tier": "algorithmic",
        "track_hash": analysis.get("hash"),
        "palette_name": palette_name,
        "scenes": scenes,
        "moments": moments,
        "features": [],
    }


def _beat_seconds(analysis: dict) -> float:
    beats = analysis.get("beats") or []
    if len(beats) >= 2:
        gaps = sorted(b - a for a, b in zip(beats, beats[1:]))
        return gaps[len(gaps) // 2]
    bpm = float(analysis.get("bpm") or 0)
    return 60.0 / bpm if bpm else 0.5


def validate_script(script: dict) -> list[str]:
    """Why a script is unusable, or an empty list. The Claude tier's output
    goes through here; anything listed sends that track to this tier
    instead. Checks shape and vocabulary — taste can't be validated."""
    # Imported here rather than at module scope: the catalog imports the
    # palette rules, and a top-level import in both directions is a cycle
    # waiting for whichever module is loaded first.
    from . import effects as fx

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
        for j, effect in enumerate(scene.get("effects") or []):
            try:
                fx.clean_effect(effect)
            except fx.EffectError as exc:
                problems.append(f"scene {i} effect {j}: {exc}")
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
    for k, moment in enumerate(script.get("moments") or []):
        if not isinstance(moment, dict):
            problems.append(f"moment {k} is not an object")
            continue
        effect = moment.get("effect") if isinstance(moment.get("effect"), dict) \
            else moment
        try:
            float(moment.get("t", effect.get("start")))
        except (TypeError, ValueError):
            problems.append(f"moment {k}: no usable time")
        try:
            fx.clean_effect(effect)
        except fx.EffectError as exc:
            problems.append(f"moment {k}: {exc}")
    return problems
