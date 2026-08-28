"""The algorithmic director: analysis + light map → a show script.

Deterministic on purpose — same track, same map, same script — so a show
someone liked on Friday is the show they get on Saturday, and a test can
assert the whole output. This tier is also the FLOOR: whatever the Claude
tier produces is validated against the same schema, and any failure lands
back here, so a show always compiles.

Four layers, on different lights
--------------------------------
The first version of this file gave each SECTION a texture and ran it end
to end: a pulse and a colour cycle for every verse, a chase for every
chorus. A four-minute track therefore changed about eight times, and
inside a section nothing moved but the same swell on the same bulbs. It
is a mood-lighting engine that happens to know where the chorus is, and
from a sofa it reads exactly as what it is — a bunch of fading lights.

What a show is actually made of is four layers with different time
constants, and the thing that makes it read as musical is that they are
SEPARATE:

* **ground** — the room's colour, moving with the harmony. Seconds-long.
  The only layer that is allowed to feel like fading.
* **pulse** — the beat, as a strike rather than a swell.
* **hits** — the kick and the snare, as different instruments on
  different lights, landing on the drums the analyzer actually heard
  rather than on the beat grid.
* **voice** — the melody, tracking real pitch. This is the layer that
  makes a room feel like it is playing along, and the previous version
  deliberately kept it out of every chorus.

A fixture belongs to exactly one layer at a time, and that is not a
style rule — a LIFX bulb runs ONE waveform at a time, so two rhythmic
layers on one bulb is the second cancelling the first. The arrangement
is what makes the layering audible AND what makes it work.

A layer arriving is itself an event
-----------------------------------
A chorus does not hit because it is brighter. It hits because the strip
joins the kick and the lamps stop washing and start following the tune.
`_entrances` places a stab on exactly that: the lights of a layer that
was not running in the previous section, on the downbeat where it
starts.

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

# Which layers a section of each energy runs, in the order they claim
# lights. The ORDER is the taste: a chorus hands its lights to the drums
# first and its leftovers to the ground, a verse does the opposite,
# because a verse with a snare on every light and nothing carrying the
# tune is a chorus that arrived early.
LAYER_PLAN = {
    "intro": ("ground", "voice", "pulse"),
    "quiet": ("ground", "voice", "pulse"),
    "mid":   ("voice", "ground", "kick", "pulse"),
    "peak":  ("kick", "snare", "voice", "pulse", "ground"),
    "outro": ("ground", "voice", "pulse"),
}

# The layers that strike rather than swell. Every section must land at
# least one of these on at least one light — a room with no beat anywhere
# is the single loudest way a show stops following the music, and it used
# to be the DEFAULT for every intro, quiet and outro section.
RHYTHMIC_LAYERS = frozenset({"pulse", "kick", "snare"})

# The roles the guarantee below may reach for. Bulbs only — a beat on a
# party-light smart plug is a relay clicking twice a second.
_BEAT_ROLES = ("lamp", "downlight", "strip", "candle")

# How many layers may share one kind of light by splitting its fixtures.
#
# Rooms do not come with five kinds of light. Most have "some lamps", and
# a layer model that only assigns whole ROLES gives such a room one layer
# and calls the rest impossible — which is how a chorus ends up as a
# single effect on every bulb again. Splitting is what a person does with
# six lamps and four ideas, so it is what this does: the kick takes the
# left pair, the snare the right pair, the tune what is left.
#
# Capped because a split is also a cost — every layer past the first
# makes the room's picture smaller — and floored at one fixture, because
# a layer with none is a layer that silently did not happen.
MAX_SHARERS = 4

# Which roles each layer will take, best first. A role is claimed by at
# most one layer per section — that is the rule that keeps two bulb-side
# routines off one bulb, and it is enforced by construction here rather
# than checked afterwards.
LAYER_ROLES = {
    "ground": ("candle", "strip", "downlight", "lamp"),
    "voice":  ("lamp", "downlight", "strip"),
    "kick":   ("strip", "downlight", "lamp"),
    "snare":  ("downlight", "lamp", "strip"),
    "pulse":  ("lamp", "downlight", "strip"),
}


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


def plan_layers(kind: str, fixtures: list[dict]) -> dict[str, dict]:
    """layer -> the lights it drives in a section of this energy.

    Two passes, and the order of them is the whole design. First every
    layer tries to claim a WHOLE role, because selecting by role is what
    survives somebody adding a bulb next month — an automatic show that
    named ids would quietly stop covering a light the day it was mapped.
    Only when a layer has nowhere left to go does it split a role it
    shares, and then it says so by naming ids, which is the honest
    encoding of "these four of the six".

    Rooms are small and layers are many, so most of this function is
    about what to DROP. A room with one kind of light and one bulb gets
    one layer, and the plan's order decides which — which is why a
    chorus lists its drums first: if only one thing can happen in a
    chorus, it should be the kick.
    """
    by_role: dict[str, list[dict]] = {}
    for fixture in fixtures:
        by_role.setdefault(fixture.get("role"), []).append(fixture)
    # Left to right, so a split is a split of the ROOM and two adjacent
    # lamps end up on the same layer rather than across it.
    for group in by_role.values():
        group.sort(key=lambda f: (float(f.get("x", 0.5)), f.get("id", "")))

    plan = LAYER_PLAN.get(kind, LAYER_PLAN["mid"])
    wanted: dict[str, list[str]] = {}
    order: list[tuple[str, str]] = []
    for layer in plan:
        for role in LAYER_ROLES[layer]:
            group = by_role.get(role) or []
            sharers = len(wanted.get(role, ()))
            if not group or sharers >= min(MAX_SHARERS, len(group)):
                continue
            wanted.setdefault(role, []).append(layer)
            order.append((layer, role))
            break

    # The beat guarantee: some light, in every section, is striking on
    # the grid. The plan above is taste and taste can strand the pulse —
    # a candles-only room has no role in LAYER_ROLES["pulse"] at all, and
    # a one-lamp room gives the lamp to the ground and calls the rest
    # impossible. If no rhythmic layer landed, the pulse first tries to
    # SHARE the roomiest bulb role, and in a room too small to share it
    # takes a role outright from its last (lowest-priority) claimant —
    # because if only one thing can happen, it should be the beat.
    if not any(layer in RHYTHMIC_LAYERS for layer, _ in order):
        def _room(role: str) -> int:
            return len(by_role.get(role) or [])
        candidates = [r for r in _BEAT_ROLES if _room(r)]
        shareable = [r for r in candidates
                     if len(wanted.get(r, ())) < min(MAX_SHARERS, _room(r))]
        if shareable:
            role = max(shareable, key=_room)
            wanted.setdefault(role, []).append("pulse")
            order.append(("pulse", role))
        elif candidates:
            role = max(candidates, key=_room)
            victim = wanted[role][-1]
            wanted[role][-1] = "pulse"
            order[order.index((victim, role))] = ("pulse", role)

    out: dict[str, dict] = {}
    for layer, role in order:
        sharing = wanted[role]
        group = by_role[role]
        if len(sharing) == 1:
            out[layer] = {"select": {"roles": [role]}, "size": len(group),
                          "role": role}
            continue
        index = sharing.index(layer)
        # Contiguous slices, so with five lamps and two layers the kick
        # gets the left three and the snare the right two rather than
        # the remainder landing wherever integer division puts it.
        start = index * len(group) // len(sharing)
        end = (index + 1) * len(group) // len(sharing)
        mine = group[start:end] or [group[min(index, len(group) - 1)]]
        out[layer] = {"select": {"ids": [f["id"] for f in mine]},
                      "size": len(mine), "role": role}
    return out


def _layer_effects(layer: str, spec: dict, kind: str,
                   seed: int, zones: bool, depth: float,
                   has_music: bool, has_hits: bool,
                   section_hits: dict | None = None) -> list[dict]:
    """One layer, as the effect that carries it in a section of this
    energy. Returns a list because a layer may be silent here."""
    select = spec["select"]
    size = spec["size"]

    if layer == "ground":
        if has_music and kind != "peak":
            # The chords, not the section map: the room's colour turns
            # over when the harmony does, which is the difference
            # between a show that follows the song and one that follows
            # its outline.
            return [{"type": "harmony", "name": "chord colour",
                     "select": select,
                     "params": {"brightness": 0.5 if kind in ("mid", "peak")
                                else 0.4,
                                "fade_ms": 1600, "spread": "single"}}]
        if kind in ("intro", "outro"):
            # Colour that travels while the level does not. It layers
            # cleanly over a wash because a wash is made of `set`s.
            return [{"type": "colour_drift", "name": "ground colour",
                     "select": select,
                     "params": {"period_beats": 24,
                                "span": 55 if kind == "intro" else -45,
                                "shape": "sine"}}]
        return [{"type": "breathe", "name": "ground breath", "select": select,
                 "params": {"period_beats": 16 if kind == "quiet" else 8,
                            "depth": 0.12}}]

    if layer == "voice":
        if not has_music:
            return []
        # The tune belongs in the chorus too. Keeping it out was the
        # previous version's rule and it was wrong: a chorus IS the part
        # of the song people know the melody of, and a room that stops
        # following it exactly there is a room that stops playing along
        # when it matters most. What makes it work in a peak is that it
        # owns its own lights — it is not a third thing fighting for the
        # bulbs the drums are on.
        return [{"type": "melody", "name": "the tune", "select": select,
                 "params": {"hue_spread": 0.45 if kind in ("quiet", "intro")
                            else 0.7,
                            "brightness": 0.75 if kind != "peak" else 0.9,
                            "fade_ms": 90, "min_strength": 0.3,
                            "voices": 1, "hold": True}}]

    if layer in ("kick", "snare"):
        band = "low" if layer == "kick" else "mid"
        if not has_hits or not (section_hits or {}).get(band, True):
            # Fall back to the grid — a worse answer and still a real
            # one. Two cases, one shape: an analysis with no ranked
            # drums at all, and a SECTION whose window holds no hits of
            # this band above the accent's own threshold. The choice
            # used to be made once for the whole track, so a verse whose
            # kick sat under the accent floor ran an accent that
            # rendered zero actions — a whole section with no rhythm
            # anywhere, which is the loudest way a show stops following
            # the music. The snare's offset puts it on the backbeat
            # (beats 2 and 4): without it the grid fallback landed the
            # snare on 1 and 3, in unison with every other kick.
            return [{"type": "hit", "name": f"{layer} (on the grid)",
                     "select": select,
                     "params": {"every_beats": 1 if layer == "kick" else 2,
                                "offset_beats": 0 if layer == "kick" else 1,
                                "peak": 0.95, "floor": 0.15,
                                "cycles_per_cue": 8}}]
        return [{"type": "accent", "name": layer, "select": select,
                 "params": {"band": band,
                            "min_strength": 0.3 if kind == "peak" else 0.45,
                            "min_gap_beats": 0.5 if layer == "kick" else 1,
                            "peak": 1.0 if kind == "peak" else 0.85,
                            "floor": 0.1, "decay_beats": 0.7,
                            "follow_strength": True, "white": False}}]

    if layer == "pulse":
        # A chase and a theater alternation are in the harsh set, and
        # `resolve_fixtures` keeps roles that do not pulse (candles) out
        # of the harsh set — so handing either to a candle role compiles
        # an effect that drives zero lights. `size` counts the map, not
        # the cast that will survive that filter; a role that does not
        # pulse takes the `hit` below, which candles are allowed to run.
        pulses = palettes.ROLE_RULES.get(spec.get("role"), {}) \
            .get("pulses", True)
        if pulses and kind == "peak" and size >= 3:
            # Three or more of one kind of light and the beat can TRAVEL
            # rather than blink in place. Below three a chase is a
            # flicker, which is why this is a count and not a preference.
            return [{"type": "chase", "name": "beat chase", "select": select,
                     "order": _chase_order(seed, zones),
                     "params": {"step_beats": 0.5,
                                "width": max(1, size // 3),
                                "bounce": bool(seed % 2), "background": 0.12,
                                "brightness": 1.0, "fade_ms": 80}}]
        if pulses and size == 2 and kind == "peak":
            return [{"type": "theater", "name": "beat alternation",
                     "select": select,
                     "params": {"step_beats": 1, "groups": 2,
                                "background": 0.15}}]
        return [{"type": "hit", "name": "the beat", "select": select,
                 "params": {"every_beats": 1, "peak": min(1.0, 0.6 + depth),
                            "floor": max(0.05, 0.35 - depth * 0.4),
                            "cycles_per_cue": 8}}]
    return []


def _effects_for(kind: str, roles: set, seed: int, zones: bool,
                 depth: float, has_music: bool, has_hits: bool,
                 layers: dict, section_hits: dict | None = None) -> list[dict]:
    """Everything that happens during a section of this energy.

    A wash goes down first and covers the WHOLE room, because a layer
    only claims one role and everything else would otherwise hold
    whatever the last section left it at. It is made of `set` actions,
    so every routine above it layers cleanly.

    Its brightness is SECTION_LEVELS' base — the same figure the scene
    carries and the Claude tier is briefed on. It used to be a pair of
    constants here (0.8 for the calm kinds, 0.55 for the loud ones),
    which stacked on top of the compiler's own base wash: two full-room
    washes per scene, the second silently overriding the first, and the
    override ran the dynamics BACKWARDS — quiet sections grounded out
    brighter than choruses. The scenes this file writes now say
    `"base": false`, because this wash IS their base.
    """
    base, _ = palettes.SECTION_LEVELS.get(kind, palettes.SECTION_LEVELS["mid"])
    effects: list[dict] = [{
        "type": "wash", "name": "scene colour", "select": {},
        "params": {"brightness": base,
                   "spread": "cycle",
                   "fade_ms": 1200 if kind in ("intro", "quiet", "outro")
                   else 500}}]

    for layer, spec in layers.items():
        effects.extend(_layer_effects(layer, spec, kind, seed, zones,
                                      depth, has_music, has_hits,
                                      section_hits))

    # Switches are stateful: nothing turns one off except another cue,
    # so every section states which way its switches should be, not just
    # the ones that turn something on. "On at the first chorus" used to
    # be the only cue a party light ever got — it then burned through
    # every breakdown and outro until the show-end sweep. A redundant
    # off (the light is already off) is one idempotent HA call per
    # section, which is what stateful outputs cost.
    for switch_role in ("party", "laser"):
        if switch_role not in roles:
            continue
        on = kind == "peak" if switch_role == "laser" \
            else kind in ("mid", "peak")
        effects.append({"type": "aux",
                        "name": f"{switch_role} {'on' if on else 'off'}",
                        "select": {"roles": [switch_role]},
                        "params": {"state": "on" if on else "off"}})
    return effects


def _entrances(sections: list[dict], plans: list[dict], beat_s: float,
               roles_present: set) -> list[dict]:
    """A stab on the lights of a layer that has just arrived.

    This is the whole of "a layer entering is an event". A chorus does
    not land because it is brighter than the verse — it lands because
    something new starts happening, on lights that were doing something
    else a moment ago. Restricted to the layers a listener can name
    (the drums and the tune) and to sections that are LOUDER than the
    one before, because a layer arriving as a song calms down is the
    arrangement thinning out and wants no announcement.
    """
    out: list[dict] = []
    for index, (section, layers) in enumerate(zip(sections, plans)):
        if index == 0:
            continue
        before = plans[index - 1]
        if float(section.get("energy", 0)) <= float(
                sections[index - 1].get("energy", 0)):
            continue
        ids: list[str] = []
        roles: list[str] = []
        for layer in ("kick", "snare", "voice"):
            spec = layers.get(layer)
            if spec is None or (before.get(layer) or {}).get(
                    "select") == spec["select"]:
                continue
            ids.extend(spec["select"].get("ids") or [])
            roles.extend(spec["select"].get("roles") or [])
        if not ids and not roles:
            continue
        select: dict = {}
        if ids:
            select["ids"] = sorted(set(ids))
        if roles:
            select["roles"] = sorted(set(roles))
        out.append({
            "t": float(section["start"]),
            "effect": {"type": "stab", "name": "layer enters",
                       "select": select,
                       "params": {"strength": 0.7,
                                  "blackout_before_ms": 220,
                                  "hold_ms": 320, "white": False}}})
    return out


def write_script(analysis: dict, fixtures: list[dict]) -> dict:
    roles_present = {f["role"] for f in fixtures}
    zones = any((f.get("zone") or "").strip() for f in fixtures)
    movers = [r for r in _MOVERS if r in roles_present]
    seed = int((analysis.get("hash") or "0")[:8] or "0", 16)
    musical = analysis.get("music") or {}
    has_music = bool(musical.get("notes") or musical.get("chords"))
    has_hits = bool(analysis.get("hits"))
    palette_name, palette = palettes.pick_palette(
        float(analysis.get("brightness", 0.5)), seed)

    sections = [s for s in (analysis.get("sections") or [])
                if isinstance(s, dict)]
    plans = [plan_layers(s["kind"], fixtures) for s in sections]

    hits = [h for h in (analysis.get("hits") or []) if isinstance(h, dict)]

    scenes = []
    for section, layers in zip(sections, plans):
        base, depth = palettes.SECTION_LEVELS.get(
            section["kind"], palettes.SECTION_LEVELS["mid"])
        # Which drum bands this SECTION actually holds, above the
        # threshold the accent effect itself will apply — the per-track
        # `has_hits` answers a different question, and answering the
        # per-section one with it is how a verse ran an accent that
        # rendered nothing.
        min_strength = 0.3 if section["kind"] == "peak" else 0.45
        window_hits = {
            band: any(float(section["start"]) <= float(h.get("t", -1.0))
                      < float(section["end"])
                      and h.get("band") == band
                      and float(h.get("strength", 0.0)) >= min_strength
                      for h in hits)
            for band in ("low", "mid")}
        scenes.append({
            "start": float(section["start"]),
            "end": float(section["end"]),
            "mood": _mood(section["kind"]),
            "kind": section["kind"],
            "palette": palette,
            "brightness": base,
            # The "scene colour" wash below carries this base itself;
            # without this flag the compiler prepends a second full-room
            # wash and the two double every scene boundary's packet
            # burst while only one of them can win.
            "base": False,
            "effects": _effects_for(section["kind"], roles_present,
                                    seed, zones, depth, has_music, has_hits,
                                    layers, window_hits),
        })

    # Moments: the build into a drop and the hit itself. The build is a
    # separate effect with its own window rather than part of the scene,
    # because tension crosses section boundaries — it starts inside the
    # section before the drop and ends on it.
    beat_s = _beat_seconds(analysis)
    moments = _entrances(sections, plans, beat_s, roles_present)
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
        # The drop is the WHOLE room: every light off in the last breath
        # before it, every light on when it lands. It used to stab a few
        # roles at the drop's own strength, which read as one more accent
        # — a drop that only moves some of the lights is a drop the room
        # can miss. An empty select is every bulb, `respect_roles` off
        # means the candles come too, and the strength floor keeps a
        # timidly-detected drop from landing as a flicker.
        moments.append({
            "t": at,
            "effect": {"type": "stab", "name": "drop hit",
                       "select": {},
                       "respect_roles": False,
                       "params": {"strength": max(0.85,
                                                  float(drop.get("strength",
                                                                 0.8))),
                                  "blackout_before_ms": 400, "hold_ms": 500}}})
        if "party" in roles_present or "laser" in roles_present:
            moments.append({
                "t": at,
                "effect": {"type": "aux", "name": "drop aux",
                           "select": {"roles": [r for r in ("party", "laser")
                                                if r in roles_present]},
                           "params": {"state": "on"}}})

    # There is no separate accent pass any more. It used to place six
    # stabs a song on the strongest on-beat hits — restraint, when the
    # only tool was a stab that owned every mover in the room. The
    # `accent` effect is that idea done properly: every drum the
    # analyzer heard, at the strength it heard it, on the lights that
    # layer owns and nothing else. Six a song was never the taste; it
    # was the budget.

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
