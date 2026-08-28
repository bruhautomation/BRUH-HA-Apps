"""The effect vocabulary: what a light can be asked to *do*, as data.

An effect is the unit both directors write in and the unit a person builds
in the Effects tab. It names a type, the fixtures it owns, the window it
runs in, how it lines up with the beat, and a handful of typed parameters
— and nothing else. It carries no packets, no entity ids and no wire
budget, because those are the compiler's and it must be possible to edit
one by hand in a text file without knowing any of them.

One rendering, two consumers
----------------------------
Every effect renders to a list of ACTIONS — "this fixture, at this
moment, becomes this colour over this fade", or "this fixture runs this
waveform for this many cycles". The compiler turns actions into packets;
`simulate()` turns the same actions into frames for the preview. That is
deliberate: a preview drawn from a second implementation of what an
effect does is a preview of the second implementation. Here the picture
and the packets come from the same list.

Selection is explicit and narrow
--------------------------------
`select` resolves to fixtures by id, role or zone, and everything it does
not name is not touched by that effect — a chase across three kitchen
bulbs leaves the lounge exactly as the scene left it. That is the whole
point of building effects rather than scenes: most of the room is usually
meant to stay still.

Roles still cap what a fixture will do (a candle does not strobe) because
that is what makes an automatic show tasteful. An effect that means it
can say `respect_roles: false` and own the fixture outright.
"""
from __future__ import annotations

import hashlib
import math
from typing import Any, Callable

from . import palettes

# Waveform shapes, by the name a person writes. Mapped to LIFX's numbers
# in the compiler — this module never sees a packet.
SHAPES = ("sine", "triangle", "pulse", "saw", "half_sine")

# Where in its cycle each shape is BRIGHTEST, as a fraction of the period.
#
# This table is why the beat pulse used to miss the beat. A LIFX waveform
# runs between the bulb's current colour and the packet's, starting at the
# current one — so a sine anchored on the beat is at its DIMMEST on the
# beat and peaks halfway to the next one. The one effect whose entire job
# was "the beat" was landing on the off-beat, in every show, since the
# first release. It is not a subtle thing to see once you know: the room
# answers a four-to-the-floor kick exactly out of phase with it.
#
# So a wave that means to peak at a moment starts `peak_phase * period`
# BEFORE it, and every shape knows its own number.
PEAK_PHASE = {"sine": 0.5, "half_sine": 0.5, "triangle": 0.5,
              "saw": 1.0, "pulse": 0.0}


def peak_shift(shape: str, period_s: float) -> float:
    """How far ahead of the beat a wave of this shape has to start."""
    return PEAK_PHASE.get(shape, 0.5) * max(0.0, float(period_s))


ORDERS = ("x", "-x", "y", "-y", "center_out", "edges_in", "snake",
          "zone", "listed", "random")

# The effects that follow what the song is PLAYING rather than when it
# hits. They render to nothing at all when the analysis carries no music
# — which is correct, and indistinguishable from broken unless somebody
# says so out loud. The compiler checks this set to put a reason on the
# effect's own row rather than leaving a silent zero there.
NEEDS_MUSIC = frozenset({"melody", "harmony"})

# `level` needs the loudness envelope instead, which is a different
# requirement with a different remedy: every analysis BRight has ever
# written carries `features`, so a track that cannot drive a level effect
# is one with no analysis at all rather than an out-of-date one.
NEEDS_ENERGY = frozenset({"level"})

# `accent` follows the analyzer's ranked drum hits. A track analysed
# before BRight ranked them has none, which is a third missing thing with
# a third remedy — and one more effect that would otherwise render an
# unexplained nothing.
NEEDS_HITS = frozenset({"accent"})

ALIGNMENTS = ("beat", "downbeat", "bar", "time")

# What an effect that names neither does. These are shipped to the panel in
# the catalog, because the editor has to open an effect at the value the
# compiler would have used — offering any other default turns "open it and
# press Apply" into a change to the show.
DEFAULT_ORDER = "x"
DEFAULT_ALIGN = "beat"


# A rendering that would put thousands of steps on the wire is a mistake
# in the script, not an instruction. Every stepping effect stops here and
# says so in `notes`, rather than compiling to something the rate check
# refuses later with no idea which effect did it.
MAX_STEPS = 512


class EffectError(ValueError):
    """An effect that cannot be understood, with a person-readable why."""


# ---------------------------------------------------------------------------
# Parameter kinds
# ---------------------------------------------------------------------------
def _num(low: float, high: float, default: float, *, integer: bool = False):
    return {"kind": "int" if integer else "number", "min": low, "max": high,
            "default": default}


def _choice(options: tuple[str, ...], default: str):
    return {"kind": "choice", "options": list(options), "default": default}


def _flag(default: bool):
    return {"kind": "bool", "default": default}


# ---------------------------------------------------------------------------
# The catalog
# ---------------------------------------------------------------------------
# Every entry: what it is for in one line, which channel it drives, and its
# parameters with ranges. The UI builds its whole form from this, so a new
# effect is a catalog entry plus a render function — never a new form.
CATALOG: dict[str, dict[str, Any]] = {
    "wash": {
        "label": "Wash",
        "blurb": "Hold a colour. The still ground everything else moves against.",
        "channel": "light",
        "params": {
            "brightness": _num(0, 1, 0.6),
            "spread": _choice(("cycle", "single", "gradient"), "cycle"),
            "fade_ms": _num(0, 10000, 800, integer=True),
        },
    },
    "fade": {
        "label": "Fade",
        "blurb": "Travel from one level to another across the whole window — "
                 "the section transition that reads as intent rather than a cut.",
        "channel": "light",
        "params": {
            "from_brightness": _num(0, 1, 0.2),
            "to_brightness": _num(0, 1, 0.9),
            "curve": _choice(("linear", "ease_in", "ease_out", "ease_in_out"),
                             "linear"),
            "steps": _num(2, 64, 8, integer=True),
            "hue_shift": _num(-360, 360, 0),
        },
    },
    "build": {
        "label": "Build",
        "blurb": "Tension: climb in stages, optionally lighting up one more "
                 "fixture per stage, so the drop has somewhere to land.",
        "channel": "light",
        "params": {
            "from_brightness": _num(0, 1, 0.15),
            "to_brightness": _num(0, 1, 1.0),
            "step_beats": _num(0.25, 16, 1),
            "stagger": _flag(True),
            "curve": _choice(("linear", "ease_in", "ease_out", "exp"), "exp"),
            "saturate": _flag(False),
        },
    },
    "pulse": {
        "label": "Beat pulse",
        "blurb": "The beat itself. One packet carries eight beats of motion — "
                 "the bulb keeps time locally, so the network cannot smear it.",
        "channel": "light",
        "params": {
            "every_beats": _num(0.25, 8, 1),
            "depth": _num(0, 1, 0.35),
            "shape": _choice(SHAPES, "sine"),
            "duty": _num(0, 1, 0.5),
            "cycles_per_cue": _num(1, 32, 8, integer=True),
            "stagger_beats": _num(0, 8, 0),
        },
    },
    "strobe": {
        "label": "Strobe",
        "blurb": "Hard flashing for a short burst. Costs one packet per "
                 "fixture however fast it runs, because the bulb does the "
                 "flashing.",
        "channel": "light",
        "params": {
            "hz": _num(1, 20, 8),
            "beats": _num(0.5, 32, 4),
            "duty": _num(0.05, 0.95, 0.35),
            "brightness": _num(0, 1, 1.0),
            "desaturate": _flag(True),
        },
    },
    "chase": {
        "label": "Chase",
        "blurb": "Jump between bulbs in order — the effect the light map "
                 "exists for. Width and bounce turn it into a runner, a "
                 "comet or a ping-pong.",
        "channel": "light",
        "params": {
            "step_beats": _num(0.125, 8, 0.5),
            "width": _num(1, 8, 1, integer=True),
            "bounce": _flag(False),
            "background": _num(0, 1, 0.08),
            "brightness": _num(0, 1, 1.0),
            "fade_ms": _num(0, 2000, 90, integer=True),
            "colour_step": _flag(False),
        },
    },
    "sweep": {
        "label": "Sweep",
        "blurb": "One wave travelling across the room: same motion on every "
                 "fixture, phase-shifted by where it stands.",
        "channel": "light",
        "params": {
            "period_beats": _num(1, 32, 8),
            "depth": _num(0, 1, 0.45),
            "shape": _choice(SHAPES, "sine"),
            "repeats": _num(1, 64, 4, integer=True),
        },
    },
    "breathe": {
        "label": "Breathe",
        "blurb": "Slow rise and fall under everything else. What a candle "
                 "does, and the only motion a quiet section usually wants.",
        "channel": "light",
        "params": {
            "period_beats": _num(2, 64, 16),
            "depth": _num(0, 1, 0.15),
        },
    },
    "sparkle": {
        "label": "Sparkle",
        "blurb": "A few random fixtures catch the light each beat. Reads as "
                 "texture, not as a pattern.",
        "channel": "light",
        "params": {
            "every_beats": _num(0.25, 8, 1),
            "count": _num(1, 12, 2, integer=True),
            "brightness": _num(0, 1, 1.0),
            "decay_ms": _num(50, 4000, 320, integer=True),
            "seed": _num(0, 9999, 0, integer=True),
        },
    },
    "colour_cycle": {
        "label": "Colour cycle",
        "blurb": "Rotate the palette through the fixtures. Motion without "
                 "brightness — the one that works when the room is already bright.",
        "channel": "light",
        "params": {
            "every_beats": _num(0.5, 32, 4),
            "rotate": _num(1, 8, 1, integer=True),
            "fade_ms": _num(0, 4000, 320, integer=True),
            "brightness": _num(0, 1, 0.85),
        },
    },
    "rainbow": {
        "label": "Rainbow",
        "blurb": "Hue spread across the room, turning slowly. Ignores the "
                 "palette on purpose — this one is its own colour scheme.",
        "channel": "light",
        "params": {
            "period_beats": _num(2, 64, 16),
            "spread_deg": _num(0, 360, 240),
            "saturation": _num(0, 1, 0.9),
            "brightness": _num(0, 1, 0.8),
            "steps_per_period": _num(2, 32, 8, integer=True),
        },
    },
    "theater": {
        "label": "Theater chase",
        "blurb": "Alternating groups, on and off against each other. Two "
                 "halves of a room answering one another.",
        "channel": "light",
        "params": {
            "step_beats": _num(0.25, 8, 1),
            "groups": _num(2, 6, 2, integer=True),
            "background": _num(0, 1, 0.1),
            "brightness": _num(0, 1, 1.0),
            "fade_ms": _num(0, 2000, 80, integer=True),
        },
    },
    "stab": {
        "label": "Stab",
        "blurb": "One hit, at one moment. The drop, the downbeat back in, the "
                 "line in the chorus that deserves an answer.",
        "channel": "light",
        "params": {
            "strength": _num(0, 1, 0.9),
            "blackout_before_ms": _num(0, 4000, 400, integer=True),
            "hold_ms": _num(60, 4000, 500, integer=True),
            "white": _flag(True),
            "shape": _choice(SHAPES, "pulse"),
        },
    },
    "blackout": {
        "label": "Blackout",
        "blurb": "Take the selected lights down. Silence is a lighting cue.",
        "channel": "light",
        "params": {
            "level": _num(0, 0.5, 0.02),
            "fade_ms": _num(0, 6000, 500, integer=True),
        },
    },
    "melody": {
        "label": "Melody",
        "blurb": "Follow the tune. Each note the analyzer heard lands on the "
                 "next light along, and the colour comes from the note "
                 "itself — a rising line walks across the room and climbs "
                 "the palette with it. The one effect that answers what is "
                 "being played rather than when.",
        "channel": "light",
        "params": {
            # How far around the palette a note's pitch moves the colour.
            # Full is the vivid reading (an octave crosses the whole
            # palette); low values keep a scene's colour and let the
            # melody move only the brightness.
            "follow": _choice(("pitch", "step"), "pitch"),
            "hue_spread": _num(0, 1, 0.6),
            "brightness": _num(0, 1, 0.85),
            "fade_ms": _num(0, 2000, 90, integer=True),
            "hold": _flag(True),
            "min_strength": _num(0, 1, 0.25),
            "voices": _num(1, 6, 1, integer=True),
        },
    },
    "harmony": {
        "label": "Harmony",
        "blurb": "The palette follows the chords. On every harmony change "
                 "the selection crossfades to that chord's colour, so the "
                 "room turns over with the song rather than with its "
                 "sections — slow, wide, and the ground other effects move "
                 "against.",
        "channel": "light",
        "params": {
            "brightness": _num(0, 1, 0.5),
            "fade_ms": _num(0, 6000, 1200, integer=True),
            "spread": _choice(("cycle", "single", "gradient"), "single"),
            "minor_shift": _num(-180, 180, -25),
        },
    },
    "colour_drift": {
        "label": "Colour drift",
        "blurb": "The colour travels and the brightness never moves — the "
                 "bulb walks its hue around the wheel on its own. The one "
                 "kind of motion a candle can join, and the ground a whole "
                 "quiet section can sit on without a single flicker.",
        "channel": "light",
        "params": {
            "period_beats": _num(1, 64, 16),
            "span": _num(-360, 360, 70),
            "shape": _choice(SHAPES, "sine"),
        },
    },
    "saturate": {
        "label": "Colour swell",
        "blurb": "Saturation breathes: the room washes out toward white and "
                 "back, or deepens into colour, with the level untouched. A "
                 "chorus lifting without getting brighter.",
        "channel": "light",
        "params": {
            "period_beats": _num(1, 64, 8),
            "to_saturation": _num(0, 1, 0.1),
            "shape": _choice(SHAPES, "sine"),
        },
    },
    "level": {
        "label": "Level",
        "blurb": "Brightness follows how loud the song actually IS, moment "
                 "to moment — not the beat grid, the audio itself. Pick a "
                 "band and the lights breathe with the kick, the vocal or "
                 "the shimmer. The one effect whose shape is the waveform.",
        "channel": "light",
        "params": {
            "band": _choice(("energy", "low", "mid", "high"), "energy"),
            "floor": _num(0, 1, 0.12),
            "ceiling": _num(0, 1, 1.0),
            "step_beats": _num(0.25, 8, 1),
            "gamma": _num(0.25, 4, 1.0),
            "fade_ms": _num(0, 2000, 140, integer=True),
        },
    },
    "hit": {
        "label": "Hit",
        "blurb": "A drum hit: full brightness the instant the beat lands, "
                 "then a decay to the ground before the next one. This is "
                 "what makes a light read as an instrument rather than as "
                 "a dimmer being turned — a pulse swells, a hit STRIKES.",
        "channel": "light",
        "params": {
            "every_beats": _num(0.25, 8, 1),
            # A uniform shift of every strike, in beats — what puts a
            # backbeat instrument on 2 and 4 while the kick holds 1 and
            # 3. `stagger_beats` cannot say this: it is per-fixture.
            "offset_beats": _num(0, 8, 0),
            "peak": _num(0, 1, 1.0),
            "floor": _num(0, 1, 0.1),
            "cycles_per_cue": _num(1, 32, 8, integer=True),
            "stagger_beats": _num(0, 8, 0),
            "attack_ms": _num(0, 400, 0, integer=True),
            "white": _flag(False),
        },
    },
    "accent": {
        "label": "Accent",
        "blurb": "A hit on every drum the analyzer actually heard, at the "
                 "strength it heard it — the kick on one set of lights and "
                 "the snare on another. Follows the record, not the grid, "
                 "so it lands on the fills the beat grid knows nothing about.",
        "channel": "light",
        "params": {
            "band": _choice(("any", "low", "mid"), "any"),
            "min_strength": _num(0, 1, 0.35),
            "min_gap_beats": _num(0, 8, 1),
            "peak": _num(0, 1, 1.0),
            "floor": _num(0, 1, 0.08),
            "decay_beats": _num(0.1, 4, 0.75),
            "follow_strength": _flag(True),
            "white": _flag(False),
        },
    },
    "aux": {
        "label": "Aux switch",
        "blurb": "Party lights and lasers: on, off, or flashed on the beat. "
                 "These ride Home Assistant, so their cues are sent early by "
                 "the latency the Lab measured.",
        "channel": "switch",
        "params": {
            "state": _choice(("on", "off", "flash"), "on"),
            "flash_beats": _num(1, 32, 4),
            "flashes": _num(1, 16, 4, integer=True),
        },
    },
}

# Which roles an effect will refuse to drive when `respect_roles` is on.
# Two rules, both about taste rather than hardware: a candle is ambience
# and a switch cannot be dimmed, so nothing that fades or flickers goes
# near either by default.
#
# `melody` is on the list and `harmony` is deliberately not, which is the
# whole distinction between them: a melody lands a note every few hundred
# milliseconds with a 90ms fade, and that is flickering however musical
# its reason — a candle asked to follow a tune is a candle strobing. A
# harmony crossfades over a bar or two, which is exactly what a candle
# SHOULD do, and is why the automatic director gives it the candles on
# purpose.
_HARSH = {"strobe", "chase", "sparkle", "stab", "theater", "melody"}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def _clamped(spec: dict, raw: Any) -> Any:
    kind = spec["kind"]
    if kind == "bool":
        if isinstance(raw, str):
            return raw.strip().lower() in ("1", "true", "yes", "on")
        return bool(raw)
    if kind == "choice":
        value = str(raw)
        return value if value in spec["options"] else spec["default"]
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return spec["default"]
    if math.isnan(value) or math.isinf(value):
        return spec["default"]
    value = min(spec["max"], max(spec["min"], value))
    return int(round(value)) if kind == "int" else value


def clean_params(effect_type: str, raw: Any) -> dict:
    """Every parameter the type declares, filled and clamped.

    Missing is the default and out-of-range is the nearest legal value,
    never an error: this data is meant to be typed by hand into a file,
    and a show that refuses to compile over `depth: 1.2` would be a worse
    tool than one that reads it as 1.
    """
    spec = CATALOG[effect_type]["params"]
    given = raw if isinstance(raw, dict) else {}
    return {name: _clamped(rule, given.get(name, rule["default"]))
            for name, rule in spec.items()}


def clean_select(raw: Any) -> dict:
    """The fixture selection, as three optional lists.

    An empty selection means "every fixture this effect can drive" — the
    useful default for a scene-wide wash, and the one a hand-written
    script gets by leaving `select` out entirely.
    """
    given = raw if isinstance(raw, dict) else {}

    def _list(key: str) -> list[str]:
        values = given.get(key)
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list):
            return []
        return [str(v)[:80] for v in values if isinstance(v, (str, int))][:200]

    return {"ids": _list("ids"), "roles": _list("roles"),
            "zones": _list("zones"), "exclude": _list("exclude")}


def clean_effect(raw: Any) -> dict:
    """One effect instance off the wire or out of a hand-edited file."""
    if not isinstance(raw, dict):
        raise EffectError("an effect must be an object")
    effect_type = str(raw.get("type", ""))
    if effect_type not in CATALOG:
        known = ", ".join(sorted(CATALOG))
        raise EffectError(f"unknown effect type {effect_type!r} — known "
                          f"types are: {known}")
    effect: dict[str, Any] = {
        "type": effect_type,
        "select": clean_select(raw.get("select")),
        "order": (str(raw.get("order", DEFAULT_ORDER))
                  if str(raw.get("order", DEFAULT_ORDER)) in ORDERS
                  else DEFAULT_ORDER),
        "align": (str(raw.get("align", DEFAULT_ALIGN))
                  if str(raw.get("align", DEFAULT_ALIGN)) in ALIGNMENTS
                  else DEFAULT_ALIGN),
        "params": clean_params(effect_type, raw.get("params")),
        "respect_roles": bool(raw.get("respect_roles", True)),
    }
    if raw.get("name"):
        effect["name"] = str(raw["name"])[:64]
    for key in ("start", "end"):
        if raw.get(key) is not None:
            try:
                effect[key] = float(raw[key])
            except (TypeError, ValueError):
                raise EffectError(f"{key} must be a number of seconds") from None
    if "start" in effect and "end" in effect and effect["end"] <= effect["start"]:
        raise EffectError("an effect ends before it starts")
    palette = raw.get("palette")
    if isinstance(palette, list) and palette:
        cleaned = []
        for pair in palette:
            if isinstance(pair, (list, tuple)) and len(pair) == 2:
                try:
                    cleaned.append([float(pair[0]) % 360.0,
                                    min(1.0, max(0.0, float(pair[1])))])
                except (TypeError, ValueError):
                    continue
        if cleaned:
            effect["palette"] = cleaned
    return effect


def catalog_payload() -> list[dict]:
    """The whole vocabulary, for the builder UI to draw its forms from."""
    return [{"type": name, **{k: v for k, v in spec.items() if k != "params"},
             "params": [{"name": pname, **prule}
                        for pname, prule in spec["params"].items()]}
            for name, spec in CATALOG.items()]


# ---------------------------------------------------------------------------
# Selecting and ordering the cast
# ---------------------------------------------------------------------------
def _key(text) -> str:
    """A name as it should be compared: trimmed and case-folded."""
    return str(text or "").strip().casefold()


def _is_switch(fixture: dict) -> bool:
    return bool(palettes.ROLE_RULES.get(fixture.get("role"), {}).get("switch"))


def _stable_seed(text: str) -> int:
    return int(hashlib.sha1(text.encode()).hexdigest()[:8], 16)


def order_fixtures(fixtures: list[dict], order: str,
                   seed: int = 0) -> list[dict]:
    """Put the cast in the order the effect travels through them.

    This is what makes the light map worth filling in: `x` is left to
    right across the room, `center_out` starts in the middle, `snake`
    walks the rows the way you would read them. Every ordering is total
    and deterministic — a chase must look the same on Saturday as it did
    on Friday, so `random` is seeded, never `random.shuffle`.
    """
    listed = list(fixtures)
    if order == "listed":
        return listed
    if order == "random":
        return sorted(listed, key=lambda f: _stable_seed(f"{seed}:{f['id']}"))
    if order == "zone":
        return sorted(listed, key=lambda f: (f.get("zone") or "~",
                                             f.get("x", 0.5), f["id"]))
    if order == "snake":
        # Rows top to bottom, alternate rows right to left — reading order
        # for a room, which is what a "sweep the whole house" wants.
        rows: dict[int, list[dict]] = {}
        for fixture in listed:
            rows.setdefault(int(round(float(fixture.get("y", 0.5)) * 3)),
                            []).append(fixture)
        out: list[dict] = []
        for index, key in enumerate(sorted(rows)):
            row = sorted(rows[key], key=lambda f: (f.get("x", 0.5), f["id"]))
            out.extend(row if index % 2 == 0 else list(reversed(row)))
        return out
    if order in ("center_out", "edges_in"):
        by_distance = sorted(
            listed, key=lambda f: (abs(float(f.get("x", 0.5)) - 0.5), f["id"]))
        return by_distance if order == "center_out" else list(reversed(by_distance))
    axis = "y" if order in ("y", "-y") else "x"
    ascending = not order.startswith("-")
    ordered = sorted(listed, key=lambda f: (float(f.get(axis, 0.5)), f["id"]))
    return ordered if ascending else list(reversed(ordered))


def resolve_fixtures(effect: dict, fixtures: list[dict]) -> list[dict]:
    """The fixtures this effect drives, in the order it drives them.

    Everything not returned here is untouched by this effect — that is
    the contract the Effects tab is built on, and the reason a show can
    run a chase in the kitchen while the lounge holds a wash.
    """
    select = effect.get("select") or {}
    ids = set(select.get("ids") or [])
    roles = set(select.get("roles") or [])
    zones = set(select.get("zones") or [])
    exclude = set(select.get("exclude") or [])
    channel = CATALOG[effect["type"]]["channel"]

    # Roles and zones are matched loosely, ids exactly.
    #
    # A zone is a name a person typed into the map and then typed again,
    # from memory, into a script — or that a model read off the room
    # description and wrote back with different capitals. "Inner
    # Kitchen" and "inner kitchen" are one room, and an effect that
    # silently drives no lights because of a capital letter is the worst
    # kind of failure: it compiles, it saves, it plays, and nothing
    # happens. Ids are generated rather than typed, so they stay exact.
    roles = {_key(r) for r in roles}
    zones = {_key(z) for z in zones}

    chosen = []
    for fixture in fixtures:
        if fixture.get("id") in exclude:
            continue
        if _is_switch(fixture) != (channel == "switch"):
            continue
        if ids or roles or zones:
            if not (fixture.get("id") in ids
                    or _key(fixture.get("role")) in roles
                    or _key(fixture.get("zone")) in zones):
                continue
        if effect.get("respect_roles", True) and channel == "light":
            rules = palettes.ROLE_RULES.get(fixture.get("role"), {})
            if effect["type"] in _HARSH and not rules.get("pulses", True):
                continue
        chosen.append(fixture)
    seed = _stable_seed(effect.get("name") or effect["type"])
    return order_fixtures(chosen, effect.get("order", "x"), seed)


def _cap(fixture: dict, brightness: float, effect: dict) -> float:
    """Role brightness ceiling, unless the effect said it owns the fixture."""
    if not effect.get("respect_roles", True):
        return min(1.0, max(0.0, brightness))
    ceiling = palettes.ROLE_RULES.get(fixture.get("role"), {}).get(
        "max_brightness", 1.0)
    return min(ceiling, max(0.0, min(1.0, brightness)))


# ---------------------------------------------------------------------------
# The beat grid
# ---------------------------------------------------------------------------
class Grid:
    """The song, as the effects see it: its beats, and what it is playing.

    Every stepping effect asks this rather than the analysis, so an
    effect with `align: "time"` (no music, or a preview on the bench)
    works through exactly the same code as one locked to a track.

    `notes` and `chords` are the musical half, and they are optional for
    the same reason: an effect that follows the melody renders to nothing
    at all when there is no melody to follow, which is exactly what it
    should do on a bench preview and on a track analysed before BRight
    could hear harmony. They are read straight off `analysis["music"]`.
    """

    def __init__(self, beats: list[float] | None = None,
                 downbeats: list[float] | None = None,
                 bpm: float | None = None,
                 notes: list[dict] | None = None,
                 chords: list[dict] | None = None,
                 energy: dict | None = None,
                 hits: list[dict] | None = None) -> None:
        self.notes = list(notes or [])
        self._range: tuple[int, int] | None = None
        self.chords = list(chords or [])
        # The analyzer's ranked drum hits, each with which band won it.
        # This is the layer a light show is actually made of and the one
        # nothing but a handful of stabs had ever read: a kick and a
        # snare are different instruments and belong on different
        # fixtures, which is what `band` is for.
        self.hits = sorted((h for h in (hits or [])
                            if isinstance(h, dict) and "t" in h),
                           key=lambda h: float(h["t"]))
        # The loudness envelope the analyzer already measures at 20Hz and
        # which, until `level` existed, was read only to find where the
        # sections and drops are. It is the song's actual shape, instant
        # by instant, and nothing was following it.
        self.energy = energy or {}
        self.beats = sorted(float(b) for b in (beats or []))
        self.downbeats = sorted(float(b) for b in (downbeats or []))
        if len(self.beats) >= 2:
            gaps = sorted(b - a for a, b in zip(self.beats, self.beats[1:]))
            self.beat_s = gaps[len(gaps) // 2]
        elif bpm:
            self.beat_s = 60.0 / max(1.0, float(bpm))
        else:
            self.beat_s = 0.5

    @property
    def beat_ms(self) -> int:
        return max(20, int(round(self.beat_s * 1000)))

    def loudness(self, band: str, start: float, end: float) -> float:
        """Mean level of one band over a window, 0..1.

        Averaged rather than sampled: the envelope is 20Hz and a light
        cue is not, so a point sample would catch whichever 50ms happened
        to line up and jitter between steps that should have read as one
        gesture.
        """
        series = self.energy.get(band) or []
        hop = float(self.energy.get("hop_s") or 0.05)
        if not series or hop <= 0 or end <= start:
            return 0.0
        lo = max(0, int(start / hop))
        hi = min(len(series), max(lo + 1, int(end / hop)))
        if lo >= len(series):
            return 0.0
        window = series[lo:hi]
        return max(0.0, min(1.0, sum(window) / len(window)))

    @property
    def has_energy(self) -> bool:
        return bool(self.energy.get("energy"))

    @property
    def has_hits(self) -> bool:
        return bool(self.hits)

    @property
    def note_range(self) -> tuple[int, int]:
        """The lowest and highest note in the WHOLE track.

        Whole track, not the window, and that is the point: a light
        chosen by pitch has to mean the same thing in the verse as in
        the chorus, or the same note walks to a different place in the
        room every section and the room stops meaning anything.
        """
        if self._range is None:
            pitches = [int(n["m"]) for n in self.notes if "m" in n]
            self._range = ((min(pitches), max(pitches)) if pitches
                           else (60, 72))
        return self._range

    def hits_in(self, start: float, end: float, *, band: str = "any",
                min_strength: float = 0.0,
                min_gap_s: float = 0.0) -> list[dict]:
        """The drum hits inside a window, filtered the way a light is.

        `band` picks the instrument — "low" is the kick, "mid" the snare
        and everything with body above it, "any" both. A hit analysed
        before BRight recorded which band won carries no `band` at all
        and is kept by every filter: an older analysis should render a
        plainer show, never an empty one.

        `min_gap_s` is the taste knob and the reason this is a method
        rather than a comprehension. Drums are dense — a snare and its
        ghost note 90ms later are one gesture to an ear and two flashes
        to a room — so the strongest hit in each cluster wins and the
        rest are dropped, which is what makes an accent read as an
        accent rather than as flicker.
        """
        inside = [h for h in self.hits
                  if start - 1e-6 <= float(h["t"]) < end
                  and float(h.get("strength", 0)) >= min_strength
                  and (band == "any" or not h.get("band")
                       or h.get("band") == band)]
        if min_gap_s > 0:
            kept: list[dict] = []
            for hit in sorted(inside, key=lambda h: -float(
                    h.get("strength", 0))):
                if all(abs(float(hit["t"]) - float(k["t"])) >= min_gap_s
                       for k in kept):
                    kept.append(hit)
            inside = sorted(kept, key=lambda h: float(h["t"]))
        return inside[:MAX_STEPS]

    @property
    def has_music(self) -> bool:
        """Does this song carry harmony or a melodic line at all?

        False for a track analysed before BRight could hear either, which
        is the case that has to be *said* rather than rendered as an empty
        effect nobody can explain.
        """
        return bool(self.notes or self.chords)

    def ticks(self, start: float, end: float, every_beats: float,
              align: str = "beat") -> list[float]:
        """The moments an effect steps on, inside its own window."""
        if end <= start:
            return []
        every = max(0.05, float(every_beats))
        if align == "time" or not self.beats:
            step = every * self.beat_s
            count = min(MAX_STEPS, int((end - start) / step) + 1)
            return [start + i * step for i in range(count)]
        # Bar and downbeat alignment pick WHERE the stepping starts, not
        # what a step is: `every_beats` is in beats everywhere a caller
        # does arithmetic with it (period_ms, cycles_per_cue). Striding
        # the downbeat list itself by `every` counted bars instead, so an
        # every-8-beats hit anchored every 32 beats and each 8-beat
        # packet was followed by 24 beats of silence.
        inside = [b for b in self.beats if start - 1e-6 <= b < end]
        if align in ("downbeat", "bar") and self.downbeats:
            first = next((d for d in self.downbeats
                          if start - 1e-6 <= d < end), None)
            if first is not None:
                inside = [b for b in inside if b >= first - 1e-6]
        if not inside:
            step = every * self.beat_s
            count = min(MAX_STEPS, int((end - start) / step) + 1)
            return [start + i * step for i in range(count)]
        if every >= 1:
            stride = max(1, int(round(every)))
            return inside[::stride][:MAX_STEPS]
        # Sub-beat stepping: subdivide each beat interval evenly, which is
        # what a half- or quarter-beat chase means and what a beat list on
        # its own cannot express.
        divisions = max(1, int(round(1.0 / every)))
        out: list[float] = []
        for index, beat in enumerate(inside):
            nxt = inside[index + 1] if index + 1 < len(inside) else beat + self.beat_s
            span = (nxt - beat) / divisions
            out.extend(beat + i * span for i in range(divisions))
            if len(out) >= MAX_STEPS:
                break
        return out[:MAX_STEPS]

    def notes_in(self, start: float, end: float,
                 min_strength: float = 0.0) -> list[dict]:
        """The melodic notes inside a window, quietest ones dropped.

        Capped like every other stepping source: a busy lead line can
        carry six notes a second, and a window that asked for all of them
        would put a packet on the wire per note per fixture. The cap
        keeps the LOUDEST notes and puts them back in time order, because
        a melody thinned by dropping its accents is not the melody.
        """
        inside = [n for n in self.notes
                  if start - 1e-6 <= float(n.get("t", 0)) < end
                  and float(n.get("s", 0)) >= min_strength]
        if len(inside) > MAX_STEPS:
            inside = sorted(inside, key=lambda n: -float(n.get("s", 0)))
            inside = sorted(inside[:MAX_STEPS], key=lambda n: float(n["t"]))
        return inside

    def chords_in(self, start: float, end: float) -> list[dict]:
        """The harmony changes inside a window, plus the chord already
        sounding when it opened — a scene that starts mid-chord has a
        colour, and starting black until the next change would be reading
        the list rather than the music."""
        inside = [c for c in self.chords
                  if start - 1e-6 <= float(c.get("t", 0)) < end]
        before = [c for c in self.chords if float(c.get("t", 0)) < start]
        if before:
            opening = dict(before[-1])
            opening["t"] = start
            inside.insert(0, opening)
        return inside[:MAX_STEPS]


# ---------------------------------------------------------------------------
# Actions — the one rendering
# ---------------------------------------------------------------------------
def _set(fixture: dict, t: float, hue: float, sat: float, bri: float,
         fade_ms: int, desc: str, resend: bool = False) -> dict:
    return {"kind": "set", "fixture": fixture, "t": round(float(t), 4),
            "hue": float(hue) % 360.0, "sat": min(1.0, max(0.0, float(sat))),
            "bri": min(1.0, max(0.0, float(bri))),
            "fade_ms": max(0, int(fade_ms)), "desc": desc, "resend": resend}


# Which channels a waveform is allowed to move. All three is what
# `SetWaveform` does and therefore what every effect did before this
# existed — which is why an audit found thirteen of seventeen effects
# showing nothing but the palette's three colours and only two moving
# brightness through more than two levels. A mask rides to the bulb as
# `SetWaveformOptional`, and it is the difference between colour that
# moves and colour that flickers.
ALL_CHANNELS = ("h", "s", "b")

# The effects the BULB runs, rather than ones we step from here.
#
# A LIFX bulb runs exactly ONE waveform at a time: sending a second is how
# you end the first (`packets.halt_waveform` is built on precisely that).
# So two of these on the same fixture in the same window is not a layered
# effect, it is the later one cancelling the earlier — and from across a
# room that reads as an effect that mysteriously does nothing. They layer
# happily with everything that steps (`set` actions) and with each other
# on DIFFERENT fixtures; the director is told this in its brief and the
# compiler warns when a script does it anyway.
BULB_ROUTINES = frozenset({"pulse", "strobe", "breathe", "sweep", "stab",
                           "colour_drift", "saturate", "hit", "accent"})


def _wave(fixture: dict, t: float, hue: float, sat: float, bri: float,
          period_ms: int, cycles: float, shape: str, duty: float,
          desc: str, channels: tuple = ALL_CHANNELS) -> dict:
    return {"kind": "wave", "fixture": fixture, "t": round(float(t), 4),
            "hue": float(hue) % 360.0, "sat": min(1.0, max(0.0, float(sat))),
            "bri": min(1.0, max(0.0, float(bri))),
            "period_ms": max(20, int(period_ms)), "cycles": float(cycles),
            "shape": shape if shape in SHAPES else "sine",
            "duty": min(1.0, max(0.0, float(duty))), "desc": desc,
            "channels": tuple(c for c in ALL_CHANNELS if c in channels)
                        or ALL_CHANNELS}


def _aux(fixture: dict, t: float, on: bool, desc: str) -> dict:
    return {"kind": "aux", "fixture": fixture, "t": round(float(t), 4),
            "on": bool(on), "desc": desc}


def _curve(name: str, position: float) -> float:
    position = min(1.0, max(0.0, position))
    if name == "ease_in":
        return position * position
    if name == "ease_out":
        return 1.0 - (1.0 - position) ** 2
    if name == "ease_in_out":
        return 0.5 - 0.5 * math.cos(math.pi * position)
    if name == "exp":
        return (math.exp(3.0 * position) - 1.0) / (math.exp(3.0) - 1.0)
    return position


def _colour(palette: list, index: int) -> tuple[float, float]:
    if not palette:
        return 40.0, 0.6
    hue, sat = palette[index % len(palette)]
    return float(hue), float(sat)


# Each renderer takes the same arguments and appends to `out`. Signature is
# uniform so `RENDERERS` can be a plain dict — an effect type is a catalog
# entry plus one of these, and nothing else anywhere.
Renderer = Callable[..., None]


def _r_wash(out, effect, cast, grid, ctx) -> None:
    p = effect["params"]
    palette = ctx["palette"]
    for index, fixture in enumerate(cast):
        if p["spread"] == "single":
            hue, sat = _colour(palette, 0)
        elif p["spread"] == "gradient" and len(cast) > 1:
            span = (len(palette) - 1) * index / (len(cast) - 1)
            low, high = int(span), min(len(palette) - 1, int(span) + 1)
            blend = span - low
            hue = _colour(palette, low)[0] * (1 - blend) + _colour(palette, high)[0] * blend
            sat = _colour(palette, low)[1] * (1 - blend) + _colour(palette, high)[1] * blend
        else:
            hue, sat = _colour(palette, index)
        out.append(_set(fixture, ctx["start"], hue, sat,
                        _cap(fixture, p["brightness"], effect),
                        int(p["fade_ms"]), "wash", resend=True))


def _r_fade(out, effect, cast, grid, ctx) -> None:
    p = effect["params"]
    steps = int(p["steps"])
    span = ctx["end"] - ctx["start"]
    step_s = span / max(1, steps)
    fade_ms = int(step_s * 1000)
    for index, fixture in enumerate(cast):
        hue, sat = _colour(ctx["palette"], index)
        for step in range(steps + 1):
            position = step / steps
            level = (p["from_brightness"]
                     + (p["to_brightness"] - p["from_brightness"])
                     * _curve(p["curve"], position))
            out.append(_set(fixture, ctx["start"] + step * step_s,
                            hue + p["hue_shift"] * position, sat,
                            _cap(fixture, level, effect), fade_ms, "fade"))


def _r_build(out, effect, cast, grid, ctx) -> None:
    p = effect["params"]
    ticks = grid.ticks(ctx["start"], ctx["end"], p["step_beats"],
                       effect.get("align", "beat"))
    if not ticks:
        return
    fade_ms = int(p["step_beats"] * grid.beat_s * 1000)
    for step, tick in enumerate(ticks):
        position = step / max(1, len(ticks) - 1)
        level = (p["from_brightness"]
                 + (p["to_brightness"] - p["from_brightness"])
                 * _curve(p["curve"], position))
        # Staggered: the build lights one more fixture each stage, which
        # is the version that reads as a room filling up rather than as a
        # dimmer being turned.
        lit = cast if not p["stagger"] else cast[:max(
            1, int(round(len(cast) * (position ** 0.7))))]
        for index, fixture in enumerate(lit):
            hue, sat = _colour(ctx["palette"], index)
            if p["saturate"]:
                sat = min(1.0, sat + 0.3 * position)
            out.append(_set(fixture, tick, hue, sat,
                            _cap(fixture, level, effect), fade_ms, "build"))


def _r_pulse(out, effect, cast, grid, ctx) -> None:
    p = effect["params"]
    cycles = int(p["cycles_per_cue"])
    period_ms = int(p["every_beats"] * grid.beat_ms)
    # One cue carries `cycles` beats of motion, so the wire only sees a
    # packet every `cycles` beats however busy the effect looks.
    anchors = grid.ticks(ctx["start"], ctx["end"],
                         p["every_beats"] * cycles, effect.get("align", "beat"))
    # The wave has to START before the beat so it PEAKS on it. A sine
    # anchored on the beat is at the bulb's current level there and
    # brightest halfway to the next one — which is what the beat pulse
    # did in every show BRight has ever compiled. See PEAK_PHASE.
    lead = peak_shift(p["shape"], period_ms / 1000.0)
    for index, fixture in enumerate(cast):
        hue, sat = _colour(ctx["palette"], index)
        offset = index * p["stagger_beats"] * grid.beat_s
        peak = _cap(fixture, ctx["base"] + p["depth"], effect)
        for anchor in anchors:
            at = anchor + offset - lead
            # An anchor whose lead-in would start before the song does is
            # dropped rather than clamped: clamping moves the peak off
            # the beat again, quietly, for the one cue nobody is
            # watching for it.
            if at < 0:
                continue
            out.append(_wave(fixture, at, hue, sat, peak,
                             period_ms, cycles, p["shape"], p["duty"],
                             f"pulse x{cycles}"))


def _r_strobe(out, effect, cast, grid, ctx) -> None:
    p = effect["params"]
    period_ms = int(1000.0 / max(1.0, p["hz"]))
    length_s = min(p["beats"] * grid.beat_s, ctx["end"] - ctx["start"])
    cycles = max(1.0, length_s * 1000.0 / period_ms)
    for index, fixture in enumerate(cast):
        hue, sat = _colour(ctx["palette"], index)
        if p["desaturate"]:
            hue, sat = 0.0, 0.0
        out.append(_wave(fixture, ctx["start"], hue, sat,
                         _cap(fixture, p["brightness"], effect),
                         period_ms, cycles, "pulse", p["duty"], "strobe"))


def _r_chase(out, effect, cast, grid, ctx) -> None:
    p = effect["params"]
    if not cast:
        return
    ticks = grid.ticks(ctx["start"], ctx["end"], p["step_beats"],
                       effect.get("align", "beat"))
    width = min(int(p["width"]), len(cast))
    count = len(cast)
    span = max(1, count - width + 1)
    for step, tick in enumerate(ticks):
        if p["bounce"] and span > 1:
            # Ping-pong: walk up the room and back down it, without
            # repeating either end (which would read as a stutter).
            cycle = max(1, 2 * span - 2)
            phase = step % cycle
            head = phase if phase < span else cycle - phase
        else:
            head = step % span
        lit = {id(f) for f in cast[head:head + width]}
        for index, fixture in enumerate(cast):
            on = id(fixture) in lit
            hue, sat = _colour(ctx["palette"],
                               step if p["colour_step"] else index)
            level = p["brightness"] if on else p["background"]
            out.append(_set(fixture, tick, hue, sat,
                            _cap(fixture, level, effect), int(p["fade_ms"]),
                            "chase"))


def _r_sweep(out, effect, cast, grid, ctx) -> None:
    p = effect["params"]
    if not cast:
        return
    period_s = p["period_beats"] * grid.beat_s
    repeats = min(int(p["repeats"]),
                  max(1, int((ctx["end"] - ctx["start"]) / max(0.1, period_s))))
    for index, fixture in enumerate(cast):
        phase = (index / len(cast)) * period_s
        hue, sat = _colour(ctx["palette"], index)
        start = ctx["start"] + phase
        if start >= ctx["end"]:
            continue
        out.append(_wave(fixture, start, hue, sat,
                         _cap(fixture, ctx["base"] + p["depth"], effect),
                         int(period_s * 1000), float(repeats), p["shape"],
                         0.5, "sweep"))


def _r_breathe(out, effect, cast, grid, ctx) -> None:
    p = effect["params"]
    period_ms = int(p["period_beats"] * grid.beat_ms)
    cycles = max(1.0, (ctx["end"] - ctx["start"]) * 1000.0 / max(1, period_ms))
    for index, fixture in enumerate(cast):
        hue, sat = _colour(ctx["palette"], index)
        out.append(_wave(fixture, ctx["start"], hue, sat,
                         _cap(fixture, ctx["base"] + p["depth"], effect),
                         period_ms, cycles, "sine", 0.5, "breathe"))


def _r_sparkle(out, effect, cast, grid, ctx) -> None:
    p = effect["params"]
    if not cast:
        return
    ticks = grid.ticks(ctx["start"], ctx["end"], p["every_beats"],
                       effect.get("align", "beat"))
    seed = int(p["seed"]) or _stable_seed(effect.get("name") or "sparkle")
    for step, tick in enumerate(ticks):
        # Deterministic "randomness": the same script sparkles the same
        # way every night, which is what makes a show a show.
        picks = sorted(range(len(cast)),
                       key=lambda i: _stable_seed(f"{seed}:{step}:{i}"))
        for index in picks[:int(p["count"])]:
            fixture = cast[index]
            hue, sat = _colour(ctx["palette"], index + step)
            out.append(_set(fixture, tick, hue, sat,
                            _cap(fixture, p["brightness"], effect), 60,
                            "sparkle"))
            out.append(_set(fixture, tick + p["decay_ms"] / 1000.0, hue, sat,
                            _cap(fixture, ctx["base"], effect),
                            int(p["decay_ms"]), "sparkle decay"))


def _r_colour_cycle(out, effect, cast, grid, ctx) -> None:
    p = effect["params"]
    ticks = grid.ticks(ctx["start"], ctx["end"], p["every_beats"],
                       effect.get("align", "beat"))
    for step, tick in enumerate(ticks):
        for index, fixture in enumerate(cast):
            hue, sat = _colour(ctx["palette"], index + step * int(p["rotate"]))
            out.append(_set(fixture, tick, hue, sat,
                            _cap(fixture, p["brightness"], effect),
                            int(p["fade_ms"]), "colour cycle"))


def _r_rainbow(out, effect, cast, grid, ctx) -> None:
    p = effect["params"]
    if not cast:
        return
    period_s = p["period_beats"] * grid.beat_s
    steps = int(p["steps_per_period"])
    step_s = period_s / max(1, steps)
    total = min(MAX_STEPS, int((ctx["end"] - ctx["start"]) / max(0.05, step_s)) + 1)
    for step in range(total):
        t = ctx["start"] + step * step_s
        turn = 360.0 * (step / max(1, steps))
        for index, fixture in enumerate(cast):
            hue = turn + p["spread_deg"] * (index / max(1, len(cast)))
            out.append(_set(fixture, t, hue, p["saturation"],
                            _cap(fixture, p["brightness"], effect),
                            int(step_s * 1000), "rainbow"))


def _r_theater(out, effect, cast, grid, ctx) -> None:
    p = effect["params"]
    groups = int(p["groups"])
    ticks = grid.ticks(ctx["start"], ctx["end"], p["step_beats"],
                       effect.get("align", "beat"))
    for step, tick in enumerate(ticks):
        live = step % groups
        for index, fixture in enumerate(cast):
            on = index % groups == live
            hue, sat = _colour(ctx["palette"], index)
            out.append(_set(fixture, tick, hue, sat,
                            _cap(fixture, p["brightness"] if on
                                 else p["background"], effect),
                            int(p["fade_ms"]), "theater"))


def _r_stab(out, effect, cast, grid, ctx) -> None:
    p = effect["params"]
    blackout_s = p["blackout_before_ms"] / 1000.0
    for index, fixture in enumerate(cast):
        hue, sat = (0.0, 0.0) if p["white"] else _colour(ctx["palette"], index)
        if blackout_s > 0:
            out.append(_set(fixture, ctx["start"] - blackout_s, hue, sat, 0.02,
                            int(blackout_s * 700), "pre-stab dip"))
        out.append(_wave(fixture, ctx["start"], hue, sat,
                         _cap(fixture, 0.7 + 0.3 * p["strength"], effect),
                         int(p["hold_ms"]), 1.0, p["shape"], 0.2, "stab"))
        if blackout_s > 0:
            # The wave is transient — the bulb returns to its "current"
            # colour when it ends, and the dip above IS that colour. A
            # stab with no dip lands back where the scene had the light;
            # one with a dip used to land back at 2% and sit there until
            # some other effect happened to name the bulb — on a
            # whole-room drop, that was most of the room going dark for
            # the rest of the section. Hand the light back to the scene:
            # its palette colour at the scene's own base level.
            scene_hue, scene_sat = _colour(ctx["palette"], index)
            out.append(_set(fixture,
                            ctx["start"] + p["hold_ms"] / 1000.0,
                            scene_hue, scene_sat,
                            _cap(fixture, ctx["base"], effect),
                            400, "back to the scene"))


def _r_blackout(out, effect, cast, grid, ctx) -> None:
    p = effect["params"]
    for fixture in cast:
        out.append(_set(fixture, ctx["start"], 0.0, 0.0, p["level"],
                        int(p["fade_ms"]), "blackout", resend=True))


def _envelope(out, fixture, t, hue, sat, peak, floor, period_s, cycles,
              attack_ms, desc) -> None:
    """One instrument-shaped strike: instant attack, linear decay.

    Two actions, and the pair is the whole idea. A `set` puts the fixture
    AT the peak with no fade, and the waveform then travels from there
    toward the floor — so the bulb's brightest instant is the moment the
    packet lands, which is what an attack is. Every other rhythmic effect
    BRight had travelled the other way: a sine from the current level up
    to a target, brightest halfway to the next beat, which is a swell.
    Swells are what "a bunch of fading lights" means.

    `saw` is the only shape that does this, and that is not a preference
    — it is the only one of LIFX's five that is monotone across a cycle.
    Sine, triangle and half-sine all come back up inside the cycle, so
    they duck rather than decay. `pulse` is a square and has no decay at
    all. So `shape` is not a parameter here: there is one answer.

    The `set` carries no fade because the waveform reads the bulb's
    CURRENT colour as its starting point — a fade still in flight would
    start the decay from somewhere between the two, and the strike would
    lose exactly the attack it exists for.
    """
    out.append(_set(fixture, t, hue, sat, peak, int(attack_ms), desc))
    out.append(_wave(fixture, t, hue, sat, floor,
                     int(period_s * 1000), cycles, "saw", 0.5, desc))


def _r_hit(out, effect, cast, grid, ctx) -> None:
    p = effect["params"]
    cycles = int(p["cycles_per_cue"])
    period_s = p["every_beats"] * grid.beat_s
    anchors = grid.ticks(ctx["start"], ctx["end"],
                         p["every_beats"] * cycles, effect.get("align", "beat"))
    phase = p["offset_beats"] * grid.beat_s
    for index, fixture in enumerate(cast):
        hue, sat = (0.0, 0.0) if p["white"] else _colour(ctx["palette"], index)
        offset = phase + index * p["stagger_beats"] * grid.beat_s
        peak = _cap(fixture, p["peak"], effect)
        floor = _cap(fixture, min(p["floor"], p["peak"]), effect)
        for anchor in anchors:
            # No peak-phase shift, deliberately: this wave travels DOWN,
            # so its brightest instant is where it starts. Shifting it
            # early — the fix the beat pulse needs — would land the
            # strike before the beat.
            _envelope(out, fixture, anchor + offset, hue, sat, peak, floor,
                      period_s, cycles, p["attack_ms"], f"hit x{cycles}")


def _r_accent(out, effect, cast, grid, ctx) -> None:
    p = effect["params"]
    hits = grid.hits_in(ctx["start"], ctx["end"], band=p["band"],
                        min_strength=p["min_strength"],
                        min_gap_s=p["min_gap_beats"] * grid.beat_s)
    period_s = p["decay_beats"] * grid.beat_s
    for hit in hits:
        strength = float(hit.get("strength", 1.0)) if p["follow_strength"] else 1.0
        for index, fixture in enumerate(cast):
            hue, sat = (0.0, 0.0) if p["white"] \
                else _colour(ctx["palette"], index)
            # The analyzer ranked these against the track's own loudest
            # hit, so a quiet one really is quieter and the room should
            # say so. Half the range is the strength's, half is floor:
            # an accent at 0.4 that rendered at 0.4 brightness would be
            # invisible beside a scene already sitting at 0.55.
            peak = _cap(fixture, p["peak"] * (0.55 + 0.45 * strength), effect)
            floor = _cap(fixture, min(p["floor"], peak), effect)
            _envelope(out, fixture, float(hit["t"]), hue, sat, peak, floor,
                      period_s, 1.0, 0, "accent")


def _r_aux(out, effect, cast, grid, ctx) -> None:
    p = effect["params"]
    if p["state"] in ("on", "off"):
        for fixture in cast:
            out.append(_aux(fixture, ctx["start"], p["state"] == "on",
                            f"aux {p['state']}"))
        return
    step_s = p["flash_beats"] * grid.beat_s
    for flash in range(int(p["flashes"])):
        at = ctx["start"] + flash * 2 * step_s
        if at >= ctx["end"]:
            break
        for fixture in cast:
            out.append(_aux(fixture, at, True, "aux flash on"))
            out.append(_aux(fixture, min(ctx["end"], at + step_s), False,
                            "aux flash off"))


def _r_melody(out, effect, cast, grid, ctx) -> None:
    """One note, one light, the colour taken from the pitch.

    The mapping is deliberately musical rather than decorative: the
    pitch CLASS picks the colour (so the same note is always the same
    colour, and a phrase that returns home looks like it did), and the
    palette is what it picks from — a melody effect in a warm scene stays
    warm, because a show whose colours are chosen by the tune and not by
    the scene is a show with no scenes.

    `voices` is how many lights a note takes; the rest of the selection
    keeps whatever the scene left it, which is what makes this layer over
    a wash instead of replacing it.
    """
    p = effect["params"]
    palette = ctx["palette"]
    notes = grid.notes_in(ctx["start"], ctx["end"], p["min_strength"])
    if not notes or not cast:
        # Nothing to follow is not an error: a track analysed before
        # BRight could hear melody, or an instrumental break with no
        # melodic line in it, both render to silence rather than to a
        # guess. `notes` in the summary is what tells the editor why.
        return
    voices = max(1, min(len(cast), int(p["voices"])))
    spread = p["hue_spread"]
    # Where a note goes.
    #
    # `step` is what this always did: the next light along, per note, in
    # a loop. It travels, but it travels the same way whatever the tune
    # does — a run up the scale and a run back down look identical, and
    # a held note that repeats keeps marching.
    #
    # `pitch` is the one worth having. The light is chosen by where the
    # note sits in the track's own range, so a rising phrase really is a
    # run of light across the room and a falling one runs back. Against
    # the WHOLE track's range, never the window's, or the same note
    # lands somewhere different in every section.
    by_pitch = p["follow"] == "pitch"
    low_note, high_note = grid.note_range
    note_span = max(1, high_note - low_note)
    span = max(1, len(palette) - 1) if palette else 1
    for index, note in enumerate(notes):
        at = float(note["t"])
        # Pitch class → a position around the palette. The palette is
        # walked rather than the hue wheel so the scene's colours are what
        # a note can be; `hue_spread` fades that toward the scene's first
        # colour, which is how "follow the tune in brightness only" is
        # spelled without a second parameter.
        position = float(note.get("pc", 0)) / 12.0
        hue, sat = _colour(palette, int(round(position * span)))
        home_hue, home_sat = _colour(palette, 0)
        hue = home_hue + (hue - home_hue) * spread
        sat = home_sat + (sat - home_sat) * spread
        level = p["brightness"] * (0.45 + 0.55 * float(note.get("s", 1.0)))
        if by_pitch:
            place = (int(note.get("m", low_note)) - low_note) / note_span
            seat = int(round(min(1.0, max(0.0, place)) * (len(cast) - 1)))
        else:
            seat = index * voices
        for voice in range(voices):
            fixture = cast[(seat + voice) % len(cast)]
            out.append(_set(fixture, at, hue, sat, level, int(p["fade_ms"]),
                            effect["name"]))
        if not p["hold"]:
            # Let the note end where the note ends, rather than holding
            # until the next one. A staccato line reads as staccato.
            tail = at + max(0.05, float(note.get("d", 0.2)))
            if tail < ctx["end"]:
                for voice in range(voices):
                    fixture = cast[(index * voices + voice) % len(cast)]
                    out.append(_set(fixture, tail, hue, sat,
                                    level * 0.15, int(p["fade_ms"]),
                                    effect["name"]))


def _r_harmony(out, effect, cast, grid, ctx) -> None:
    """The room turns over when the chord does.

    A long crossfade on purpose: harmony changes every bar or two and a
    fast one would read as a cut. Minor chords are shifted around the
    wheel by `minor_shift`, which is the one piece of synaesthesia here
    and earns its place — a minor chord landing a little cooler than the
    major beside it is the difference between a palette that follows the
    song and one that merely changes.
    """
    p = effect["params"]
    palette = ctx["palette"]
    changes = grid.chords_in(ctx["start"], ctx["end"])
    if not changes or not cast:
        return
    span = max(1, len(palette) - 1) if palette else 1
    for change in changes:
        root = int(change.get("root", 0))
        hue, sat = _colour(palette, int(round(root / 12.0 * span)))
        if change.get("quality") == "min":
            hue += float(p["minor_shift"])
        at = float(change["t"])
        for index, fixture in enumerate(cast):
            if p["spread"] == "single":
                shade = 0.0
            elif p["spread"] == "gradient" and len(cast) > 1:
                shade = 18.0 * index / (len(cast) - 1)
            else:
                shade = 12.0 * (index % 3)
            out.append(_set(fixture, at, hue + shade, sat, p["brightness"],
                            int(p["fade_ms"]), effect["name"], resend=True))


def _optional_wave(out, effect, cast, grid, ctx, *, channel: str,
                   target) -> None:
    """One masked waveform per fixture, spanning the effect's window.

    Shared by the two effects that move colour without touching level,
    because the only thing that differs between them is which channel the
    bulb is told to walk and where to. Everything else — one packet per
    fixture for the whole window, the cycle count derived from the window
    rather than guessed, `transient` so the light returns to what the
    scene left it at — is identical, and writing it twice would be two
    answers to one question.
    """
    p = effect["params"]
    period_s = max(0.05, float(p["period_beats"]) * grid.beat_s)
    span_s = max(0.0, ctx["end"] - ctx["start"])
    cycles = max(1.0, round(span_s / period_s, 2))
    for index, fixture in enumerate(cast):
        hue, sat = _colour(ctx["palette"], index)
        bri = ctx["base"]
        aim_hue, aim_sat = target(hue, sat)
        out.append(_wave(fixture, ctx["start"], aim_hue, aim_sat, bri,
                         int(period_s * 1000), cycles, p["shape"], 0.5,
                         effect["name"], channels=(channel,)))


def _r_colour_drift(out, effect, cast, grid, ctx) -> None:
    span = float(effect["params"]["span"])
    _optional_wave(out, effect, cast, grid, ctx, channel="h",
                   target=lambda hue, sat: (hue + span, sat))


def _r_saturate(out, effect, cast, grid, ctx) -> None:
    aim = float(effect["params"]["to_saturation"])
    _optional_wave(out, effect, cast, grid, ctx, channel="s",
                   target=lambda hue, sat: (hue, aim))


def _r_level(out, effect, cast, grid, ctx) -> None:
    """The room breathing with the actual audio.

    Every other effect here modulates brightness between two values on a
    grid — an audit of the catalog found exactly two moving it through
    more than two levels, which is why a show could feel busy and still
    feel flat. This one has no levels at all: it reads the analyzer's own
    loudness envelope and maps it, so a swell swells and a breakdown
    drops away without anybody choosing a number for it.

    `gamma` is the shape of that mapping. Below 1 lifts the quiet parts
    (the room stays alive through a verse); above 1 pushes them down and
    keeps the top (only the loud moments read). It is the one control
    that turns this from a meter into a lighting choice.
    """
    p = effect["params"]
    if not grid.has_energy:
        return
    ticks = grid.ticks(ctx["start"], ctx["end"], p["step_beats"],
                       effect.get("align", DEFAULT_ALIGN))
    if not ticks:
        return
    floor, ceiling = p["floor"], p["ceiling"]
    gamma = max(0.05, float(p["gamma"]))
    palette = ctx["palette"]
    for index, at in enumerate(ticks):
        nxt = ticks[index + 1] if index + 1 < len(ticks) else ctx["end"]
        loud = grid.loudness(p["band"], at, nxt) ** gamma
        level = floor + (ceiling - floor) * loud
        for slot, fixture in enumerate(cast):
            hue, sat = _colour(palette, slot)
            out.append(_set(fixture, at, hue, sat, _cap(fixture, level, effect),
                            int(p["fade_ms"]), effect["name"]))


RENDERERS: dict[str, Renderer] = {
    "wash": _r_wash,
    "fade": _r_fade,
    "build": _r_build,
    "pulse": _r_pulse,
    "strobe": _r_strobe,
    "chase": _r_chase,
    "sweep": _r_sweep,
    "breathe": _r_breathe,
    "sparkle": _r_sparkle,
    "colour_cycle": _r_colour_cycle,
    "rainbow": _r_rainbow,
    "theater": _r_theater,
    "stab": _r_stab,
    "blackout": _r_blackout,
    "melody": _r_melody,
    "harmony": _r_harmony,
    "colour_drift": _r_colour_drift,
    "saturate": _r_saturate,
    "level": _r_level,
    "hit": _r_hit,
    "accent": _r_accent,
    "aux": _r_aux,
}

# Every catalog entry has to have a renderer and vice versa — the pair IS
# the effect, and a half of one is a type that validates and does nothing.
assert set(RENDERERS) == set(CATALOG), "effect catalog and renderers disagree"


def actions_for(effect: dict, fixtures: list[dict], grid: Grid, *,
                window: tuple[float, float], palette: list,
                base_brightness: float = 0.5) -> list[dict]:
    """One effect, rendered into actions. Never raises on a clean effect."""
    cast = resolve_fixtures(effect, fixtures)
    if not cast:
        return []
    start = float(effect.get("start", window[0]))
    end = float(effect.get("end", window[1]))
    if end <= start:
        return []
    ctx = {
        "start": start,
        "end": end,
        "palette": effect.get("palette") or palette or [[40, 0.6]],
        "base": min(1.0, max(0.0, float(base_brightness))),
    }
    out: list[dict] = []
    RENDERERS[effect["type"]](out, effect, cast, grid, ctx)
    # Every cue carries the name of the effect that asked for it. This is
    # the only thread from a packet in a compiled show back to the line in
    # the script a person wrote, and it is what makes a 900-cue timeline
    # readable at all.
    name = effect.get("name")
    if name:
        for action in out:
            action["desc"] = f"{name} · {action['desc']}"
    return [action for action in out if action["t"] >= -1.0]


# ---------------------------------------------------------------------------
# Simulation — the preview, from the same actions
# ---------------------------------------------------------------------------
def _wave_position(shape: str, phase: float, duty: float) -> float:
    """How far toward the waveform's colour the bulb is, 0..1.

    LIFX runs the waveform between the fixture's current colour and the
    one in the packet; this is that interpolation factor at a point in
    the cycle. It is an approximation of the firmware, not a copy of it —
    the preview's job is to show the shape of the motion.
    """
    phase = phase % 1.0
    if shape == "sine":
        return 0.5 - 0.5 * math.cos(2 * math.pi * phase)
    if shape == "half_sine":
        return math.sin(math.pi * phase)
    if shape == "triangle":
        return 2 * phase if phase < 0.5 else 2 * (1 - phase)
    if shape == "saw":
        return phase
    if shape == "pulse":
        return 1.0 if phase < max(0.02, duty) else 0.0
    return 0.5 - 0.5 * math.cos(2 * math.pi * phase)


def _lerp(a: float, b: float, k: float) -> float:
    return a + (b - a) * k


def _hue_lerp(a: float, b: float, k: float) -> float:
    """Around the wheel the short way — a fade from 350° to 10° passes
    through red, not through the entire spectrum."""
    delta = ((b - a + 180.0) % 360.0) - 180.0
    return (a + delta * k) % 360.0


def simulate(actions: list[dict], fixtures: list[dict], *,
             duration_s: float, fps: int = 15, start_s: float = 0.0,
             initial: tuple[float, float, float] = (30.0, 0.4, 0.05)) -> dict:
    """Sampled colours per fixture per frame — what the preview draws.

    Built from the same actions the compiler turns into packets, so a
    preview that looks wrong is an effect that is wrong, which is the
    only useful thing a preview can be.

    `start_s` is where the FRAMES begin, not where the show does: every
    action before it is still applied, at its own time, so the colours the
    first frame reports are the ones a light really is wearing three
    minutes in — mid-fade included. Scrubbing a four-minute show is what
    this is for. Sampling every fixture for every frame is the expensive
    half and a window skips it; applying the actions is cheap, and skipping
    THAT would mean previewing a show that began wherever you scrolled to,
    with every light still at its opening colour.
    """
    fps = max(4, min(30, int(fps)))
    start_s = max(0.0, float(start_s))
    first = int(start_s * fps)
    frames = max(1, min(1800, int(duration_s * fps) + 1))
    ids = [f["id"] for f in fixtures]
    index_of = {fixture_id: i for i, fixture_id in enumerate(ids)}

    # Per fixture: the colour it is moving from, the one it is moving to,
    # when the move started and how long it takes; plus any waveform
    # currently running on it.
    state = [{"from": initial, "to": initial, "t0": -1.0, "fade": 0.0,
              "wave": None} for _ in ids]
    pending = sorted(actions, key=lambda a: a["t"])
    cursor = 0
    out: list[list[list[float]]] = []

    for frame in range(first, first + frames):
        now = frame / fps
        while cursor < len(pending) and pending[cursor]["t"] <= now:
            action = pending[cursor]
            cursor += 1
            slot = index_of.get(action["fixture"]["id"])
            if slot is None:
                continue
            current = _sample(state[slot], action["t"])
            if action["kind"] == "set":
                state[slot] = {"from": current,
                               "to": (action["hue"], action["sat"], action["bri"]),
                               "t0": action["t"],
                               "fade": action["fade_ms"] / 1000.0,
                               "wave": None}
            elif action["kind"] == "wave":
                state[slot] = {
                    "from": current, "to": current, "t0": action["t"],
                    "fade": 0.0,
                    "wave": {"hue": action["hue"], "sat": action["sat"],
                             "bri": action["bri"],
                             "period": action["period_ms"] / 1000.0,
                             "cycles": action["cycles"],
                             "shape": action["shape"], "duty": action["duty"],
                             "channels": action.get("channels", ALL_CHANNELS),
                             "t0": action["t"]}}
            elif action["kind"] == "aux":
                state[slot] = {"from": current,
                               "to": (55.0, 0.5, 1.0 if action["on"] else 0.0),
                               "t0": action["t"], "fade": 0.15, "wave": None}
        out.append([[round(v[0], 1), round(v[1], 3), round(v[2], 3)]
                    for v in (_sample(slot_state, now) for slot_state in state)])

    return {
        "fps": fps,
        "start_s": round(first / fps, 3),
        "duration_s": round(frames / fps, 3),
        "fixtures": [{"id": f["id"], "label": f.get("label") or f["id"],
                      "role": f.get("role"), "x": f.get("x", 0.5),
                      "y": f.get("y", 0.5),
                      "switch": _is_switch(f)} for f in fixtures],
        "frames": out,
    }


def _sample(slot: dict, now: float) -> tuple[float, float, float]:
    base_from, base_to = slot["from"], slot["to"]
    if slot["fade"] > 0 and now < slot["t0"] + slot["fade"]:
        k = max(0.0, (now - slot["t0"]) / slot["fade"])
        base = (_hue_lerp(base_from[0], base_to[0], k),
                _lerp(base_from[1], base_to[1], k),
                _lerp(base_from[2], base_to[2], k))
    else:
        base = base_to
    wave = slot.get("wave")
    if not wave:
        return base
    elapsed = now - wave["t0"]
    if elapsed < 0 or elapsed > wave["period"] * wave["cycles"]:
        return base
    k = _wave_position(wave["shape"], elapsed / max(0.001, wave["period"]),
                       wave["duty"])
    # Only the channels the routine actually moves. A hue drift that the
    # preview drew as a brightness pulse would be a preview of a different
    # effect — the one thing this module exists to prevent.
    channels = wave.get("channels", ALL_CHANNELS)
    return (_hue_lerp(base[0], wave["hue"], k) if "h" in channels else base[0],
            _lerp(base[1], wave["sat"], k) if "s" in channels else base[1],
            _lerp(base[2], wave["bri"], k) if "b" in channels else base[2])


def summarise(actions: list[dict]) -> dict:
    """What an effect costs, before anybody runs it."""
    per_fixture: dict[str, int] = {}
    for action in actions:
        per_fixture[action["fixture"]["id"]] = (
            per_fixture.get(action["fixture"]["id"], 0) + 1)
    span = [a["t"] for a in actions]
    return {
        "actions": len(actions),
        "fixtures": len(per_fixture),
        # WHICH lights, not only how many. The editor draws one lane per
        # effect and has to say what it is on — "4 lights" beside a row
        # is the same non-answer as "all lights" was beside a selection.
        "fixture_ids": list(per_fixture),
        "busiest_fixture": max(per_fixture.values()) if per_fixture else 0,
        "first_t": round(min(span), 3) if span else 0.0,
        "last_t": round(max(span), 3) if span else 0.0,
    }


def aux_action(fixture: dict, t: float, on: bool, desc: str) -> dict:
    """An aux switch action, for a caller outside this module.

    The compiler ends a show by turning its switches off, and that tail has
    to be an action like every other so the preview can see it.
    """
    return _aux(fixture, t, on, desc)
