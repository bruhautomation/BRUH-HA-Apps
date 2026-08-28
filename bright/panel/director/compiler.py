"""THE compiler: show script + light map + analysis → the cue timeline.

Both director tiers emit the same script language; this is the only code
that knows how a scene becomes packets. Its obligations:

* Waveforms carry the beats. A pulsing scene sends one SetWaveform per
  fixture per 8 beats — the bulb generates the motion, the network only
  carries scene changes and hits.
* Every LIFX cue ships pre-serialized (base64 bytes; the conductor stamps
  the live sequence number) with a lead of half that bulb's probed RTT.
* Aux (HA-path) cues lead by that entity's MEASURED service latency from
  the Lab, so a laser "hits" a drop by having been commanded early.
* The 20 msgs/s/device ceiling is enforced HERE: a script that would
  exceed it fails to compile, loudly — never a runtime surprise in a dark
  room full of guests.

Scripts speak effects
---------------------
A scene is a window with a palette, a base level and a list of EFFECTS
(`director/effects.py`). The compiler resolves each effect to actions and
renders actions to packets; it does not know what a chase is, and adding
one more effect type never touches this file.

Scripts written against the older vocabulary still compile. `motifs` are
translated into their effect equivalents on the way in (`_from_motif`),
because a script somebody wrote — or a show compiled last week and kept
— must not stop working when the vocabulary grows.
"""
from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path

from lifx import packets
from analyzer import library

from . import effects as fx
from . import palettes

HA_LATENCY_FILE = (Path(os.environ.get("BRIGHT_STATE", "/data"))
                   / "cache" / "ha-latency.json")
DEFAULT_HA_LEAD_MS = 350.0
DEFAULT_LIFX_LEAD_MS = 5.0
MAX_RATE_HZ = 18.0  # compile-time budget: under LIFX's 20 with margin

SHOW_VERSION = 2

_SHAPE_CODES = {
    "saw": packets.WAVEFORM_SAW,
    "sine": packets.WAVEFORM_SINE,
    "half_sine": packets.WAVEFORM_HALF_SINE,
    "triangle": packets.WAVEFORM_TRIANGLE,
    "pulse": packets.WAVEFORM_PULSE,
}


class CompileError(ValueError):
    pass


def _kelvin_for(saturation: float) -> int:
    return 3500 if saturation > 0.2 else 2700


def _hsbk(hue_deg: float, saturation: float, brightness: float) -> dict:
    return {
        "hue": int((hue_deg % 360.0) / 360.0 * 65535) & 0xFFFF,
        "saturation": int(max(0.0, min(1.0, saturation)) * 65535),
        "brightness": int(max(0.0, min(1.0, brightness)) * 65535),
        "kelvin": _kelvin_for(saturation),
    }


def _ha_leads() -> dict[str, float]:
    try:
        stored = json.loads(HA_LATENCY_FILE.read_text())
        return {entity: float(result.get("p50_ms", DEFAULT_HA_LEAD_MS))
                for entity, result in stored.items()}
    except (OSError, ValueError):
        return {}


class _Cues:
    """Accumulates cues; owns serialization and lead stamping."""

    def __init__(self, source: int, ha_leads: dict[str, float]) -> None:
        self.source = source
        self.ha_leads = ha_leads
        self.cues: list[dict] = []

    def lifx(self, fixture: dict, t: float, packet: bytes, desc: str,
             resend: bool = False) -> None:
        lead = ((fixture.get("rtt") or {}).get("p50_ms")
                or DEFAULT_LIFX_LEAD_MS * 2) / 2.0
        self.cues.append({
            "t": round(t, 4),
            "ch": "lifx",
            "serial": fixture["serial"],
            "lead_ms": round(lead, 2),
            "resend": resend,
            "payload_b64": base64.b64encode(packet).decode(),
            "desc": desc,
        })

    def set_color(self, fixture: dict, t: float, hue: float, sat: float,
                  brightness: float, duration_ms: int, desc: str,
                  resend: bool = True) -> None:
        color = _hsbk(hue, sat, brightness)
        self.lifx(fixture, t,
                  packets.set_color(color["hue"], color["saturation"],
                                    color["brightness"], color["kelvin"],
                                    duration_ms, target=bytes.fromhex(
                                        fixture["serial"]),
                                    source=self.source),
                  desc, resend=resend)

    def waveform(self, fixture: dict, t: float, hue: float, sat: float,
                 brightness: float, period_ms: int, cycles: float,
                 desc: str, shape: int = packets.WAVEFORM_SINE,
                 skew_ratio: int = 0,
                 channels: tuple = fx.ALL_CHANNELS) -> None:
        """One waveform, on the bulb.

        A routine that moves every channel is `SetWaveform`, which is what
        every effect sent before a mask existed; one that moves a subset
        is `SetWaveformOptional`, the same engine told which channels to
        leave alone. The default is the whole colour, so nothing that was
        already compiled changes shape — an effect gets the narrower
        message only by asking for it.
        """
        color = _hsbk(hue, sat, brightness)
        target = bytes.fromhex(fixture["serial"])
        if tuple(channels) == tuple(fx.ALL_CHANNELS):
            packet = packets.set_waveform(
                transient=True, hue=color["hue"],
                saturation=color["saturation"],
                brightness=color["brightness"], kelvin=color["kelvin"],
                period_ms=period_ms, cycles=cycles, waveform=shape,
                skew_ratio=skew_ratio, target=target, source=self.source)
        else:
            packet = packets.set_waveform_optional(
                transient=True, hue=color["hue"],
                saturation=color["saturation"],
                brightness=color["brightness"], kelvin=color["kelvin"],
                period_ms=period_ms, cycles=cycles, waveform=shape,
                skew_ratio=skew_ratio,
                set_hue="h" in channels, set_saturation="s" in channels,
                set_brightness="b" in channels,
                target=target, source=self.source)
        self.lifx(fixture, t, packet, desc)

    def ha(self, fixture: dict, t: float, service: str, desc: str) -> None:
        entity = fixture["entity_id"]
        self.cues.append({
            "t": round(t, 4),
            "ch": "ha",
            "service": service,
            "data": {"entity_id": entity},
            "lead_ms": round(self.ha_leads.get(entity, DEFAULT_HA_LEAD_MS), 1),
            "desc": desc,
        })


def render_actions(actions: list[dict], out: _Cues) -> None:
    """Actions → packets. The only place the two vocabularies meet."""
    for action in actions:
        fixture = action["fixture"]
        if action["kind"] == "set":
            out.set_color(fixture, action["t"], action["hue"], action["sat"],
                          action["bri"], action["fade_ms"], action["desc"],
                          resend=bool(action.get("resend")))
        elif action["kind"] == "wave":
            # A PULSE's duty cycle is LIFX's skew_ratio, an i16 where 0 is
            # an even square: 0.5 duty is 0, and either side of it walks
            # toward the ends of the range.
            skew = int((action["duty"] - 0.5) * 2 * 32767) if \
                action["shape"] == "pulse" else 0
            out.waveform(fixture, action["t"], action["hue"], action["sat"],
                         action["bri"], action["period_ms"], action["cycles"],
                         action["desc"],
                         shape=_SHAPE_CODES.get(action["shape"],
                                                packets.WAVEFORM_SINE),
                         skew_ratio=max(-32768, min(32767, skew)),
                         channels=action.get("channels", fx.ALL_CHANNELS))
        elif action["kind"] == "aux":
            out.ha(fixture, action["t"],
                   "homeassistant.turn_on" if action["on"]
                   else "homeassistant.turn_off", action["desc"])


# ---------------------------------------------------------------------------
# The older vocabulary, translated
# ---------------------------------------------------------------------------
def _from_motif(motif: dict, depth_default: float) -> dict | None:
    """A v1 `motif` as the effect it always meant.

    Kept because scripts are files people edit and shows are artifacts
    people keep: a vocabulary that grows must not invalidate what was
    written against it.
    """
    roles = [r for r in (motif.get("roles") or []) if isinstance(r, str)]
    kind = motif.get("type")
    if kind == "beat_pulse":
        return {"type": "pulse", "name": "beat pulse", "select": {"roles": roles},
                "params": {"every_beats": motif.get("beats", 1),
                           "depth": motif.get("depth", depth_default),
                           "shape": motif.get("shape", "sine")}}
    if kind == "sweep":
        return {"type": "sweep", "name": "sweep", "select": {"roles": roles},
                "order": "x" if motif.get("axis", "x") == "x" else "y",
                "params": {"period_beats": motif.get("period_beats", 8)}}
    if kind == "breathe":
        return {"type": "breathe", "name": "breathe", "select": {"roles": roles},
                "params": {"period_beats": motif.get("period_beats", 16),
                           "depth": motif.get("depth", 0.15)}}
    if kind == "aux_on":
        return {"type": "aux", "name": "aux on", "select": {"roles": roles},
                "params": {"state": "on"}}
    return None


def _from_feature(feature: dict) -> dict | None:
    """A v1 `feature` (a moment) as an effect at a moment."""
    roles = [r for r in (feature.get("roles") or []) if isinstance(r, str)]
    if feature.get("type") == "drop_hit":
        return {"type": "stab", "name": "drop hit", "select": {"roles": roles},
                "params": {"strength": feature.get("strength", 0.8),
                           "blackout_before_ms":
                               feature.get("blackout_before_ms", 400)}}
    if feature.get("type") == "lyric_moment":
        return {"type": "stab", "name": "lyric moment", "select": {"roles": roles},
                "respect_roles": True,
                "params": {"strength": 0.4, "blackout_before_ms": 0,
                           "hold_ms": 900, "white": False, "shape": "half_sine"}}
    return None


# ---------------------------------------------------------------------------
# Compile
# ---------------------------------------------------------------------------
def scene_effects(scene: dict) -> list[dict]:
    """Everything a scene asks for, as clean effects, in running order.

    The base wash comes first and can be turned off (`"base": false`) by
    a scene that means to leave the room where the last one left it — a
    hand-written script's way of writing a cross-section fade.
    """
    _, depth_default = palettes.SECTION_LEVELS.get(
        scene.get("kind", "mid"), palettes.SECTION_LEVELS["mid"])
    out: list[dict] = []
    if scene.get("base", True):
        out.append(fx.clean_effect({
            "type": "wash",
            "name": f"scene {scene.get('mood') or scene.get('kind') or ''}".strip(),
            "params": {"brightness": scene.get("brightness", 0.5),
                       "fade_ms": scene.get("base_fade_ms", 900)},
        }))
    for motif in scene.get("motifs") or []:
        if not isinstance(motif, dict):
            continue
        translated = _from_motif(motif, depth_default)
        if translated is not None:
            out.append(fx.clean_effect(translated))
    for effect in scene.get("effects") or []:
        out.append(fx.clean_effect(effect))
    return out


def _routine_clash(rendered: list[dict], routines: dict) -> str | None:
    """The name of an already-placed bulb routine this one overlaps, if
    any. One name is enough — the point is to say what is being replaced,
    not to enumerate every fixture it happens on."""
    for action in rendered:
        if action["kind"] != "wave":
            continue
        start = action["t"]
        end = start + action["period_ms"] / 1000.0 * action["cycles"]
        for other_start, other_end, name in routines.get(
                action["fixture"]["id"], []):
            if start < other_end - 1e-6 and other_start < end - 1e-6:
                return name
    return None


def script_actions(script: dict, fixtures: list[dict],
                   analysis: dict) -> dict:
    """A whole script, walked once, as actions.

    The same move `effects.py` makes for a single effect, at the scale of a
    show: this is the ONLY place that knows how a script becomes actions,
    and both consumers hang off it — `compile_show` renders the list to
    packets, `preview.py` simulates it into frames. A preview that walked
    the script itself would be a second answer to "what does this show do",
    and the two would drift the first time a moment's default changed.

    Returns the actions in the order they were rendered (which is what
    `used_aux` below is counting on), the per-effect breakdown, and the
    duration everything was laid out against.
    """
    if not fixtures:
        raise CompileError("the light map has no reachable fixtures")
    musical = analysis.get("music") or {}
    grid = fx.Grid(analysis.get("beats"), analysis.get("downbeats"),
                   analysis.get("bpm"),
                   notes=musical.get("notes"), chords=musical.get("chords"),
                   energy=analysis.get("features"),
                   hits=analysis.get("hits"))
    # Via duration_of, never the tag directly: a VBR header without a
    # Xing frame reports a length wrong by whole multiples, the show is
    # laid out over this number, and the conductor sleeps out its tail
    # after the last cue — so a lying header parked the party queue for
    # the difference, on top of drawing a 26-minute waveform.
    duration = library.duration_of(analysis)

    actions: list[dict] = []
    breakdown: list[dict] = []
    # fixture id -> [(start, end, effect name)] of bulb-side routines
    # already placed, so a later one can say what it is interrupting.
    routines: dict[str, list] = {}

    def _run(effect: dict, window: tuple[float, float], palette: list,
             base: float, where: str) -> None:
        try:
            rendered = fx.actions_for(effect, fixtures, grid, window=window,
                                      palette=palette, base_brightness=base)
        except fx.EffectError as exc:
            raise CompileError(f"{where}: {exc}") from None
        actions.extend(rendered)
        entry = {"where": where, "type": effect["type"],
                 "name": effect.get("name"), **fx.summarise(rendered)}
        # An effect that follows the music and found none renders to
        # nothing, which is right — and reads exactly like a broken
        # effect. The reason goes on the effect's own row, because that
        # is where somebody is looking when they wonder why the melody
        # they added does not appear in the preview.
        # Two bulb-side routines on one fixture in one window is the
        # second cancelling the first, because a bulb runs one waveform at
        # a time. Reported on the effect's own row rather than refused:
        # the overlap may be deliberate (a stab is MEANT to interrupt a
        # pulse on the drop), and a compiler that refused it would be
        # refusing a real technique.
        if effect["type"] in fx.BULB_ROUTINES:
            clash = _routine_clash(rendered, routines)
            if clash:
                entry["note"] = (
                    f"a bulb runs one waveform at a time, and "
                    f"{clash} is already running one on some of these "
                    f"lights here — the later effect replaces it rather "
                    f"than layering with it")
            for action in rendered:
                if action["kind"] == "wave":
                    routines.setdefault(action["fixture"]["id"], []).append(
                        (action["t"],
                         action["t"] + action["period_ms"] / 1000.0
                         * action["cycles"],
                         effect.get("name") or effect["type"]))
        # An effect that names lights the map does not have. This is the
        # one silence that is nobody's analysis being out of date and
        # nothing to do with the music: the selection matched no fixture,
        # so the effect was never going to do anything. It compiled, it
        # saved, it played, and the room stayed exactly as it was — and
        # the only trace anywhere was a `0 lights` on a list nobody
        # reads. Checked FIRST, because it explains the zero better than
        # any of the reasons below it.
        if not rendered and not fx.resolve_fixtures(effect, fixtures):
            named = effect.get("select") or {}
            wanted = ", ".join(
                str(value) for key in ("ids", "roles", "zones")
                for value in (named.get(key) or []))
            entry["note"] = (
                f"this effect drives no lights: nothing on the map matches "
                f"{wanted or 'its selection'} — check the names against the "
                f"Light Map, or widen the selection")
        elif (not rendered and effect["type"] in fx.NEEDS_MUSIC
                and not grid.has_music):
            entry["note"] = ("this track was analysed before BRight could "
                             "hear melody and harmony — re-run Analyze on "
                             "the Library tab, then compile again")
        elif (not rendered and effect["type"] in fx.NEEDS_ENERGY
                and not grid.has_energy):
            # A different missing thing with a different remedy: every
            # analysis carries the loudness envelope, so this is a track
            # with no analysis rather than an out-of-date one.
            entry["note"] = ("this effect follows the song's loudness and "
                             "this track has no analysis to read it from — "
                             "analyse it on the Library tab")
        elif (not rendered and effect["type"] in fx.NEEDS_HITS
                and not grid.has_hits):
            entry["note"] = ("this effect lands on the drum hits the "
                             "analyzer ranked, and this track was analysed "
                             "before it ranked them — re-run Analyze on the "
                             "Library tab, then compile again")
        elif not rendered and effect["type"] in fx.NEEDS_HITS:
            # The track HAS ranked hits — this effect's window just holds
            # none that clear its own filters. Without the note, a verse
            # whose accent goes silent is pixel-identical to a broken
            # effect, and the track-wide check above cannot see it.
            band = (effect.get("params") or {}).get("band") or "any"
            entry["note"] = (
                f"no {'ranked' if band == 'any' else band} drum hits above "
                f"this effect's min_strength inside its window — it renders "
                f"nothing here; lower min_strength, widen the band, or use "
                f"a `hit` on the beat grid instead")
        breakdown.append(entry)

    for index, scene in enumerate(script.get("scenes") or []):
        if not isinstance(scene, dict):
            raise CompileError(f"scene {index} is not an object")
        try:
            window = (float(scene["start"]), float(scene["end"]))
        except (KeyError, TypeError, ValueError):
            raise CompileError(f"scene {index} has no usable start/end") from None
        palette = scene.get("palette") or [[40, 0.6]]
        base = float(scene.get("brightness", 0.5))
        label = scene.get("mood") or scene.get("kind") or f"scene {index}"
        for effect in scene_effects(scene):
            _run(effect, window, palette, base, f"scene {index} ({label})")

    # Moments: an effect pinned to a time rather than to a section. Both
    # the old `features` list and the new `moments` one land here.
    moments: list[tuple[float, dict]] = []
    for feature in script.get("features") or []:
        if not isinstance(feature, dict):
            continue
        translated = _from_feature(feature)
        if translated is None:
            continue
        try:
            moments.append((float(feature["t"]), translated))
        except (KeyError, TypeError, ValueError):
            raise CompileError("a feature has no usable time") from None
    beats_list = analysis.get("beats") or []
    for moment in script.get("moments") or []:
        if not isinstance(moment, dict):
            continue
        effect = moment.get("effect") if isinstance(moment.get("effect"), dict) \
            else moment
        try:
            at = float(moment.get("t", effect.get("start", 0.0)))
        except (TypeError, ValueError):
            raise CompileError("a moment has no usable time") from None
        # `"snap": "beat"` moves the moment onto the nearest analyzed
        # beat. It exists for times that arrive APPROXIMATE — a model
        # reading "the hit around 41 seconds", a person typing one — and
        # a stab 80ms off the beat reads as a mistake where one ON it
        # reads as intent. Written times that are already exact (the
        # choreographer's, which come from the analysis itself) simply
        # don't ask.
        if moment.get("snap") == "beat" and beats_list:
            at = float(min(beats_list, key=lambda b: abs(float(b) - at)))
        moments.append((at, effect))

    default_palette = ((script.get("scenes") or [{}])[0] or {}).get(
        "palette") or [[40, 0.6]]
    for at, raw in moments:
        effect = fx.clean_effect(raw)
        effect["start"] = at
        effect.setdefault("end", at + float(
            effect["params"].get("hold_ms", 800)) / 1000.0 + 1.0)
        _run(effect, (at, effect["end"]), effect.get("palette")
             or _palette_at(script, at) or default_palette, 0.5,
             f"moment {at:.1f}s")

    # Aux lights end the show off. They are switches: nothing else turns
    # them back off, and a laser left on after the music stops is the one
    # failure a guest actually notices.
    #
    # It is an ordinary aux action rather than a direct `out.ha` so that the
    # returned list is the WHOLE show — the preview draws the laser going
    # out at the end because the show really does end that way, and a tail
    # written straight to the cues would have been invisible to it.
    used_aux: set[str] = set()
    for action in actions:
        if action["kind"] != "aux":
            continue
        if action["on"]:
            used_aux.add(action["fixture"]["entity_id"])
        else:
            used_aux.discard(action["fixture"]["entity_id"])
    for fixture in fixtures:
        if (palettes.ROLE_RULES.get(fixture.get("role"), {}).get("switch")
                and fixture.get("entity_id") in used_aux):
            actions.append(fx.aux_action(fixture, duration, False, "show end"))

    return {"actions": actions, "effects": breakdown, "duration_s": duration,
            "grid": grid}


def compile_show(script: dict, fixtures: list[dict], analysis: dict,
                 source: int) -> dict:
    """Render the script. Raises CompileError on an impossible ask."""
    walked = script_actions(script, fixtures, analysis)
    duration = walked["duration_s"]
    breakdown = walked["effects"]

    out = _Cues(source, _ha_leads())
    render_actions(walked["actions"], out)

    cues = sorted(out.cues, key=lambda c: c["t"] - c.get("lead_ms", 0) / 1000.0)
    peak, worst_serial = _peak_rate(cues)
    if peak > MAX_RATE_HZ:
        raise CompileError(
            f"compiled to {peak:.0f} msgs/s at one device "
            f"({worst_serial}) — over the budget of {MAX_RATE_HZ:.0f}/s "
            f"(LIFX ceiling is 20). Something is stepping too fast: raise "
            f"an effect's step_beats, narrow its selection, or drop one of "
            f"the effects stacked on that light.")

    return {
        "version": SHOW_VERSION,
        "track_hash": script.get("track_hash") or analysis.get("hash"),
        "tier": script.get("tier", "algorithmic"),
        "palette_name": script.get("palette_name"),
        "compiled_at": time.time(),
        "duration_s": duration,
        "cues": cues,
        "effects": breakdown,
        "stats": {
            "cues": len(cues),
            "lifx_cues": sum(1 for c in cues if c["ch"] == "lifx"),
            "ha_cues": sum(1 for c in cues if c["ch"] == "ha"),
            "peak_per_device_hz": round(peak, 2),
            "fixtures": len(fixtures),
            "effects": len(breakdown),
        },
    }


def _palette_at(script: dict, t: float) -> list | None:
    """The palette the scene covering `t` is wearing, so a moment that
    names no colours of its own belongs to the section it lands in."""
    for scene in script.get("scenes") or []:
        try:
            if float(scene["start"]) <= t < float(scene["end"]):
                return scene.get("palette")
        except (KeyError, TypeError, ValueError):
            continue
    return None


def compile_preview(effects: list[dict], fixtures: list[dict], *,
                    grid: fx.Grid, duration_s: float, palette: list,
                    base_brightness: float = 0.35,
                    source: int = 0) -> dict:
    """One or more effects, on the bench: actions, cues and frames.

    The Effects tab's whole answer in one call — the picture it animates,
    the packets it would send if you pressed "run it on the lights", and
    the rate figure that says whether that is allowed.
    """
    actions: list[dict] = []
    breakdown = []
    for raw in effects:
        effect = fx.clean_effect(raw)
        rendered = fx.actions_for(effect, fixtures, grid,
                                  window=(0.0, duration_s), palette=palette,
                                  base_brightness=base_brightness)
        actions.extend(rendered)
        breakdown.append({"type": effect["type"], "name": effect.get("name"),
                          **fx.summarise(rendered)})
    out = _Cues(source, _ha_leads())
    render_actions(actions, out)
    cues = sorted(out.cues, key=lambda c: c["t"])
    peak, worst = _peak_rate(cues)
    return {
        "cues": cues,
        "effects": breakdown,
        "peak_per_device_hz": round(peak, 2),
        "over_budget": peak > MAX_RATE_HZ,
        "busiest_device": worst,
        "actions": actions,
    }


def _peak_rate(cues: list[dict]) -> tuple[float, str | None]:
    worst = 0.0
    worst_serial = None
    by_device: dict[str, list[float]] = {}
    for cue in cues:
        if cue.get("ch") != "lifx":
            continue
        sends = 2 if cue.get("resend") else 1
        by_device.setdefault(cue["serial"], []).extend([cue["t"]] * sends)
    for serial, times in by_device.items():
        times.sort()
        for i in range(len(times)):
            j = i
            while j + 1 < len(times) and times[j + 1] - times[i] < 1.0:
                j += 1
            if float(j - i + 1) > worst:
                worst = float(j - i + 1)
                worst_serial = serial
    return worst, worst_serial
