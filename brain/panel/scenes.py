"""Four moods for a room, composed from the lights the room has.

*"Design my evening for the living room."* Scenes are the thing everybody
means to set up and nobody does, because doing it by hand means opening
each bulb, picking a colour temperature that will look wrong beside the
next one, saving four of them and then writing the schedule. What makes
it possible to do *for* somebody is that the answer is deterministic: the
registries already say which lights the room has and what each of them can
be told, and a mood is a level and a warmth.

**This is not BRight, and the docs must not compare the two.** BRight
choreographs a show against a piece of music, in tenths of a second, on
bulbs it drives over the LAN. This writes four ordinary Home Assistant
scenes and one ordinary automation, and Home Assistant runs them. They
share no code and no vocabulary, and describing this as "BRight for every
day" would tell somebody it needs LIFX bulbs and a speaker.

**What a light can be told is read, never assumed** (`capability`). Four
answers, in the order a mood wants them:

* **colour temperature** where the bulb takes one — a scene of whites is a
  colour-temperature scene, and kelvin is the control that means it.
* **colour** where it does not: an RGB approximation of the same kelvin,
  because a bulb that can only be told a colour still has a warm end.
* **brightness** where there is neither.
* **on or off** where there is not even that — and the card says so, so a
  room of cheap bulbs is a set of scenes that still works rather than an
  empty card.

A light whose modes cannot be read at all falls to the last of those
rather than being dropped: an unreadable capability is *"I could not
tell"*, and the honest thing to do with it is the thing that works
everywhere.

**`brightness`, not `brightness_pct`.** A scene's entity dict is a *state*
that Home Assistant reproduces, not a service call — `light`'s
`reproduce_state` reads `brightness` (0–255), `color_temp_kelvin` and
`rgb_color`, and a `brightness_pct` in a scene is an attribute nothing
reads. It would store, load, reload and apply, and every light would come
on at whatever level it was already at. That is the shape of failure this
file exists to avoid, so the percentage is the vocabulary of the *card*
and the byte is the vocabulary of the file.

**A protected light is dropped from the config and listed as skipped**,
asked at the producer as well as the writer — `playbooks.py`'s
arrangement, for its reason: a card offering something the writer will
refuse is a wasted no, and showing it is how you see that brAIn knows the
bulb is there and knows it may not set it.

**And nothing here decides anything.** It composes and it names; the store
dedupes, the panel renders and a person answers. The same split
`baselines.py`, `closures.py` and `thermal.py` keep.
"""
from __future__ import annotations

import re

from checks._util import House

# The four moods, in the order a day happens. Each is a warmth and a
# level, and both are deliberately plain numbers rather than a model's
# choice: a scene that came out different every time it was offered would
# be one nobody could reason about.
MOODS = ("morning", "day", "evening", "night")

# Kelvin and brightness per mood. Morning is cooler than day on purpose —
# it is the one that has to wake somebody up — and night is the only one
# that turns most of the room off.
LEVELS = {
    "morning": {"kelvin": 5000, "pct": 80},
    "day": {"kelvin": 4000, "pct": 100},
    "evening": {"kelvin": 2400, "pct": 45},
    "night": {"kelvin": 2000, "pct": 10},
}
DEFAULT_NAMES = {
    "morning": "Morning", "day": "Day",
    "evening": "Evening", "night": "Night",
}

# At night, only a light that is *for* the night stays on. Matched on the
# name, which is the one thing a person chose — there is no attribute for
# "this is the one I leave on", and inventing a rule from the wattage
# would be a guess about somebody's furniture.
NIGHT_WORDS = ("night", "bedside", "hall", "landing")

# Below this an area is not a room with lighting in it, and four scenes
# over one bulb is four ways of saying the same thing.
MIN_LIGHTS = 2
# And past this a "room" is a floor: the card would not fit and the moods
# would be about a building.
MAX_LIGHTS = 40

# Colour modes, as Home Assistant spells them.
COLOUR_MODES = frozenset({"hs", "xy", "rgb", "rgbw", "rgbww"})
TEMP_MODES = frozenset({"color_temp"})
DIM_MODES = frozenset({"brightness", "white"})

SOURCE = "scene"
ID_PREFIX = "brain_scene_"

# Naming the four is the one optional Claude run, and it is the one thing
# a model is better at than a table. A failure leaves the plain names.
NAME_TIMEOUT_S = 90
NAME_MAX_TURNS = 2
SYSTEM = """You name four lighting scenes for one room in a house.

You are given the room and the four moods in order: morning, day, evening,
night. Answer with FOUR lines and nothing else — one name per line, in
that order, each under 24 characters, each a name a person would use out
loud about their own home. No numbering, no quotes, no explanation.

They are shown beside the room's name, so do not repeat it."""


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text or "").lower()).strip("_")


# ---------------------------------------------------------------------------
# What a bulb can be told
# ---------------------------------------------------------------------------

def capability(state: dict | None) -> str:
    """`"colour_temp"`, `"colour"`, `"brightness"` or `"onoff"`.

    Colour temperature is preferred over colour where a bulb has both:
    these are scenes of whites, and kelvin is the control that says so —
    an RGB approximation of 2400K on a bulb that could have taken the
    number is a worse answer written more precisely.
    """
    attrs = (state or {}).get("attributes") or {}
    raw = attrs.get("supported_color_modes")
    modes = {str(m).strip().lower() for m in (raw or []) if m}
    if modes & TEMP_MODES:
        return "colour_temp"
    if modes & COLOUR_MODES:
        return "colour"
    if modes & DIM_MODES:
        return "brightness"
    # `onoff`, `unknown`, and an attribute that could not be read at all.
    # The last of those is "I could not tell", and the honest thing to do
    # with it is the setting that works on every bulb ever made.
    return "onoff"


def kelvin_to_rgb(kelvin: int) -> tuple[int, int, int]:
    """A Planckian approximation, for the bulbs that cannot take a kelvin.

    Deterministic and testable, which is the whole reason it is here
    rather than in the panel: the same warmth has to reach an RGB bulb and
    a colour-temperature one, and two implementations of "what does 2400K
    look like" would put two different whites in one room.
    """
    temp = max(1000, min(int(kelvin), 40000)) / 100.0
    if temp <= 66:
        red = 255.0
        green = 99.4708025861 * _log(temp) - 161.1195681661
    else:
        red = 329.698727446 * ((temp - 60) ** -0.1332047592)
        green = 288.1221695283 * ((temp - 60) ** -0.0755148492)
    if temp >= 66:
        blue = 255.0
    elif temp <= 19:
        blue = 0.0
    else:
        blue = 138.5177312231 * _log(temp - 10) - 305.0447927307
    return tuple(max(0, min(255, int(round(c)))) for c in (red, green, blue))


def _log(value: float) -> float:
    import math  # noqa: PLC0415 — two call sites, on a path walked a
    # handful of times per proposal

    return math.log(max(value, 1e-6))


def rgb_to_hsv(rgb: tuple[int, int, int]) -> tuple[int, float, float]:
    """`(hue 0-360, saturation 0-1, value 0-1)`.

    The swatch on the card is drawn from HSV because that is what a bulb
    holds — the same contract BRight's preview keeps, for the same reason:
    a picture converted from something the house does not use is a picture
    of the conversion.
    """
    import colorsys  # noqa: PLC0415 — one call site

    h, s, v = colorsys.rgb_to_hsv(*(c / 255.0 for c in rgb))
    return int(round(h * 360)) % 360, round(s, 3), round(v, 3)


# ---------------------------------------------------------------------------
# Composing the four
# ---------------------------------------------------------------------------

def is_nightlight(name: str) -> bool:
    words = re.split(r"[^a-z0-9]+", str(name or "").lower())
    return any(w in words for w in NIGHT_WORDS)


def _settings(mood: str, cap: str, on: bool) -> dict:
    """One light's entry in one scene."""
    if not on:
        return {"state": "off"}
    level = LEVELS[mood]
    out: dict = {"state": "on"}
    if cap == "onoff":
        return out
    # 0-255, because a scene is a STATE Home Assistant reproduces and
    # `light`'s reproduce_state reads `brightness`. See the module
    # docstring: `brightness_pct` here is an attribute nothing reads.
    out["brightness"] = max(1, min(255, round(level["pct"] * 255 / 100)))
    if cap == "colour_temp":
        out["color_temp_kelvin"] = level["kelvin"]
    elif cap == "colour":
        out["rgb_color"] = list(kelvin_to_rgb(level["kelvin"]))
    return out


def _swatch(mood: str, cap: str, on: bool) -> dict:
    """What the card draws for one light in one scene."""
    level = LEVELS[mood]
    if not on:
        return {"on": False, "h": 0, "s": 0.0, "v": 0.0}
    hue, sat, _v = rgb_to_hsv(kelvin_to_rgb(level["kelvin"]))
    if cap == "onoff":
        # Nothing about warmth is true of a bulb that only switches, so
        # the swatch says so rather than drawing a colour it will not be.
        return {"on": True, "h": 0, "s": 0.0, "v": 1.0}
    if cap == "brightness":
        return {"on": True, "h": 0, "s": 0.0, "v": level["pct"] / 100}
    return {"on": True, "h": hue, "s": sat, "v": level["pct"] / 100}


def _house(snap) -> House:
    """A `House` from a snapshot, or the one it already is.

    `conditions.build` takes a snapshot and builds one; so does this, so
    the two producers read the registries the same way — and a test may
    hand a `House` straight in.
    """
    return snap if isinstance(snap, House) else House(snap)


def lights_in(snap, area: str, patterns: list[str] | None = None) -> tuple:
    """`(lights, skipped)` for one area, each light with its capability.

    A protected light is **skipped and named**, never silently dropped —
    `playbooks.py`'s rule, and the reason is the same: seeing that brAIn
    knows the bulb is there is the point of showing it.
    """
    import automation_writer  # noqa: PLC0415 — panel-local

    house = _house(snap)
    patterns = list(patterns or [])
    wanted = _slug(area)
    lights, skipped = [], []
    for eid, state in sorted((house.states or {}).items()):
        if not eid.startswith("light."):
            continue
        if _slug(house.area_of(eid)) != wanted:
            continue
        row = {"entity_id": eid, "name": house.name(eid),
               "capability": capability(state)}
        if automation_writer.is_protected(eid, patterns):
            skipped.append({**row, "reason": "protected"})
            continue
        lights.append(row)
    return lights, skipped


def compose(area: str, lights: list[dict],
            names: dict[str, str] | None = None) -> list[dict]:
    """Four scene entries for one room. Deterministic, top to bottom."""
    names = names or {}
    nightlights = [light for light in lights
                   if is_nightlight(light["name"]) or is_nightlight(
                       light["entity_id"].split(".", 1)[-1])]
    out = []
    for mood in MOODS:
        # At night only a light that is for the night stays on — and if
        # the room has none, the whole room goes off, which is what
        # "night" means in a room with no nightlight in it.
        on_at_night = {light["entity_id"] for light in nightlights}
        entities = {}
        for light in lights:
            on = mood != "night" or light["entity_id"] in on_at_night
            entities[light["entity_id"]] = _settings(mood, light["capability"],
                                                     on)
        label = str(names.get(mood) or DEFAULT_NAMES[mood]).strip()[:40]
        out.append({
            "id": f"{ID_PREFIX}{_slug(area)}_{mood}",
            "name": f"{label} — {area}",
            "entities": entities,
            # Read by the card and by nothing else. It is not part of the
            # scene, so it is stripped before the file is written.
            "mood": mood,
        })
    return out


def strip(entries: list[dict]) -> list[dict]:
    """The scenes as they go into `scenes.yaml`, without the card's key."""
    return [{k: v for k, v in e.items() if k != "mood"} for e in entries]


def preview(entries: list[dict], lights: list[dict]) -> list[dict]:
    """Swatches: one row per mood, one colour per light.

    HSV, converted to CSS on the client and nowhere else — the one
    conversion the panel does, because these ARE bulb colours.
    """
    caps = {light["entity_id"]: light["capability"] for light in lights}
    out = []
    for entry in entries:
        mood = entry.get("mood") or ""
        out.append({
            "mood": mood,
            "name": entry["name"],
            "lights": [
                {"entity_id": light["entity_id"], "name": light["name"],
                 "capability": light["capability"],
                 **_swatch(mood, caps.get(light["entity_id"], "onoff"),
                           (entry["entities"].get(light["entity_id"]) or {})
                           .get("state") == "on")}
                for light in lights],
        })
    return out


# ---------------------------------------------------------------------------
# The proposal
# ---------------------------------------------------------------------------

def _cap_sentence(lights: list[dict]) -> str:
    counts: dict[str, int] = {}
    for light in lights:
        counts[light["capability"]] = counts.get(light["capability"], 0) + 1
    words = {"colour_temp": "take a colour temperature",
             "colour": "take a colour but not a temperature",
             "brightness": "dim but have no colour",
             "onoff": "only switch on and off"}
    parts = [f"{counts[k]} {words[k]}" for k in
             ("colour_temp", "colour", "brightness", "onoff") if counts.get(k)]
    return "; ".join(parts)


def areas_with_lights(snap, patterns: list[str] | None = None) -> list[dict]:
    """Every area brAIn could compose scenes for, and how many lights each
    has.

    The picker's own list, so a room with one bulb is never offered and
    then refused: a control that hands somebody a choice its own rule
    forbids is a control that teaches people to distrust it.
    """
    house = _house(snap)
    counts: dict[str, int] = {}
    for eid in house.states or {}:
        if not eid.startswith("light."):
            continue
        area = house.area_of(eid)
        if area:
            counts[area] = counts.get(area, 0) + 1
    out = []
    for area in sorted(counts):
        lights, skipped = lights_in(house, area, patterns)
        if len(lights) >= MIN_LIGHTS:
            out.append({"area": area, "lights": len(lights),
                        "skipped": len(skipped)})
    return out


def build(snap, area: str, patterns: list[str] | None = None,
          names: dict[str, str] | None = None) -> dict:
    """One scene proposal for one area, or one carrying `refused`.

    Never raises: an area somebody typed always gets an answer, and
    *"there is one light in there"* is one of them.
    """
    house = _house(snap)
    lights, skipped = lights_in(house, area, patterns)
    out = {
        "kind": "scene",
        "source": SOURCE,
        "title": f"Four scenes for the {area}",
        "area": area,
    }
    if len(lights) < MIN_LIGHTS:
        out["refused"] = (
            f"the {area} has "
            f"{'only one light' if len(lights) == 1 else 'no lights'} brAIn "
            f"can set{' (the rest are protected)' if skipped else ''}, and "
            "four scenes over one bulb is four ways of saying the same "
            "thing.")
        return out
    if len(lights) > MAX_LIGHTS:
        out["refused"] = (
            f"the {area} has {len(lights)} lights in it, which is a floor "
            "rather than a room — brAIn would be composing moods for a "
            "building. Split it into areas and ask again.")
        return out

    entries = compose(area, lights, names)
    out["config"] = strip(entries)
    out["scene"] = {
        "area": area,
        "lights": lights,
        "skipped": skipped,
        "preview": preview(entries, lights),
        "moods": list(MOODS),
    }
    out["why"] = why_for(area, lights, skipped)
    return out


def why_for(area: str, lights: list[dict], skipped: list[dict]) -> str:
    caps = _cap_sentence(lights)
    night = [light["name"] for light in lights
             if is_nightlight(light["name"])
             or is_nightlight(light["entity_id"].split(".", 1)[-1])]
    lines = [
        f"Composed from the {len(lights)} lights the {area} has: {caps}. "
        "Morning is cool and bright, day is neutral and full, evening is "
        "warm and dimmed.",
    ]
    lines.append(
        f"At night only {', '.join(night)} stays on." if night
        else "The room has nothing named like a nightlight, so night turns "
             "all of it off.")
    if skipped:
        lines.append(
            f"{', '.join(s['name'] for s in skipped)} "
            f"{'is' if len(skipped) == 1 else 'are'} on your protected "
            "entities list and left out.")
    return " ".join(lines)


# ---------------------------------------------------------------------------
# Naming them — the one optional Claude run
# ---------------------------------------------------------------------------

def name_prompt(area: str) -> str:
    return (f"Room: {area}\nMoods, in order: "
            + ", ".join(MOODS)
            + "\n\nFour names, one per line.")


def read_names(text: str) -> dict[str, str]:
    """Four lines into four names, or `{}` if it is not four usable lines.

    All four or none: three good names and one that came back as *"4."* is
    a set with a hole in it, and the plain names are a perfectly good
    answer. A model's line is stripped of the numbering and the quotes it
    was told not to use, because that is cheaper than losing the set over
    punctuation.
    """
    lines = []
    for raw in str(text or "").splitlines():
        line = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", raw).strip()
        line = line.strip("\"'").strip()
        if line:
            lines.append(line[:40])
    if len(lines) != len(MOODS):
        return {}
    # And they have to be four DIFFERENT names. Home Assistant derives a
    # scene's entity id from its name, so two moods called the same thing
    # are one `scene.wind_down` with two definitions fighting over it —
    # `apply`'s duplicate check reads the file rather than the batch, the
    # accept path waits for an id it finds, and the schedule walks the
    # room through three moods and a repeat. Same "all four or none" this
    # function already keeps: the plain names are a good answer.
    if len({_slug(line) for line in lines}) != len(MOODS):
        return {}
    return dict(zip(MOODS, lines))


# ---------------------------------------------------------------------------
# The schedule — offered only once the scenes are really there
# ---------------------------------------------------------------------------

# The two the house has not measured. Midday and the early evening are not
# things `rhythm` can see (nobody's first press of the day is at noon), so
# they are stated as the guesses they are and the card says which two.
FIXED = {"day": "11:00:00", "evening": "18:30:00"}


def _clock(minutes: float) -> str:
    total = int(round(minutes)) % 1440
    return f"{total // 60:02d}:{total % 60:02d}:00"


def existing_scenes(snap, area: str) -> dict[str, str]:
    """`{mood: the name it was actually written under}`.

    A fact about the house rather than about the store, deliberately: the
    schedule is offered because the four moods exist, and somebody who
    copied the card's YAML in by hand has earned it exactly as much as
    somebody who pressed the button. The **name** is what comes back
    rather than the id, because the schedule turns on an entity id Home
    Assistant derived from that name — and if Claude named them, the
    default names are not what is in the file.
    """
    house = _house(snap)
    prefix = f"{ID_PREFIX}{_slug(area)}_"
    found: dict[str, str] = {}
    for cfg in house.snap.get("scenes") or []:
        if not isinstance(cfg, dict):
            continue
        cid = str(cfg.get("id") or "")
        name = str(cfg.get("name") or "").strip()
        if cid.startswith(prefix) and name:
            found[cid[len(prefix):]] = name
    return {m: found[m] for m in MOODS if m in found}


def schedule(snap, area: str, wake_minutes: float | None = None,
             settle_minutes: float | None = None) -> dict | None:
    """The automation that walks the room through its four scenes.

    An ordinary automation, through 1.44.0's path unchanged — so it gets a
    replay, a trial week and the same accept. Only offered once all four
    scenes exist, because a schedule naming a scene that is not there is
    an automation that errors at 07:00 every morning.
    """
    written = existing_scenes(snap, area)
    if len(written) != len(MOODS):
        return None
    times = {
        "morning": _clock(wake_minutes) if wake_minutes is not None else None,
        "day": FIXED["day"],
        "evening": FIXED["evening"],
        "night": _clock(settle_minutes) if settle_minutes is not None else None,
    }
    measured = [m for m in ("morning", "night") if times[m]]
    times["morning"] = times["morning"] or "07:00:00"
    times["night"] = times["night"] or "22:30:00"

    triggers, branches = [], []
    for mood in MOODS:
        triggers.append({"platform": "time", "at": times[mood], "id": mood})
        branches.append({
            "conditions": [{"condition": "trigger", "id": mood}],
            "sequence": [{
                "service": "scene.turn_on",
                # The name Home Assistant really has, slugged the way Core
                # slugs it — never the default, which a Claude-named set
                # is not.
                "target": {"entity_id": f"scene.{_slug(written[mood])}"},
            }],
        })
    config = {
        "trigger": triggers,
        "condition": [],
        "action": [{"choose": branches}],
        "mode": "single",
    }
    return {
        "kind": "automation",
        "source": SOURCE,
        "title": f"Move the {area} through its four scenes",
        "why": (
            f"The {area} has all four scenes now, and nothing moves between "
            f"them. Morning at {times['morning'][:5]} and night at "
            f"{times['night'][:5]} are "
            + ("measured — that is when this house actually gets up and "
               "settles"
               if len(measured) == 2 else
               "brAIn's own defaults, because it has not measured enough "
               "days yet")
            + f"; {times['day'][:5]} and {times['evening'][:5]} are fixed "
              "guesses you can change."),
        "config": config,
        "schedule": {"area": area, "times": times, "measured": measured,
                     "scenes": {m: written[m] for m in MOODS}},
    }


def scene_name(area: str, mood: str, label: str | None = None) -> str:
    """The name a scene is written under, and the one the schedule calls.

    One implementation, because the automation names an entity id derived
    from the scene's name — and a second answer to "what is this scene
    called" is a schedule that turns on nothing.
    """
    return f"{label or DEFAULT_NAMES[mood]} — {area}"


__all__ = [
    "COLOUR_MODES", "DEFAULT_NAMES", "DIM_MODES", "FIXED", "ID_PREFIX",
    "LEVELS", "MAX_LIGHTS", "MIN_LIGHTS", "MOODS", "NAME_MAX_TURNS",
    "areas_with_lights",
    "NAME_TIMEOUT_S", "NIGHT_WORDS", "SOURCE", "SYSTEM", "TEMP_MODES",
    "build", "capability", "compose", "existing_scenes", "is_nightlight",
    "kelvin_to_rgb", "lights_in", "name_prompt", "preview", "read_names",
    "rgb_to_hsv", "scene_name", "schedule", "strip", "why_for",
]
