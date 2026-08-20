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
"""
from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path

from lifx import packets
from . import palettes

HA_LATENCY_FILE = (Path(os.environ.get("BRIGHT_STATE", "/data"))
                   / "cache" / "ha-latency.json")
DEFAULT_HA_LEAD_MS = 350.0
DEFAULT_LIFX_LEAD_MS = 5.0
MAX_RATE_HZ = 18.0  # compile-time budget: under LIFX's 20 with margin

SHOW_VERSION = 1


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
                 skew_ratio: int = 0) -> None:
        color = _hsbk(hue, sat, brightness)
        self.lifx(fixture, t,
                  packets.set_waveform(
                      transient=True, hue=color["hue"],
                      saturation=color["saturation"],
                      brightness=color["brightness"], kelvin=color["kelvin"],
                      period_ms=period_ms, cycles=cycles, waveform=shape,
                      skew_ratio=skew_ratio,
                      target=bytes.fromhex(fixture["serial"]),
                      source=self.source),
                  desc)

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


def _beats_in(beats: list[float], start: float, end: float) -> list[float]:
    return [b for b in beats if start <= b < end]


def compile_show(script: dict, fixtures: list[dict], analysis: dict,
                 source: int) -> dict:
    """Render the script. Raises CompileError on an impossible ask."""
    if not fixtures:
        raise CompileError("the light map has no reachable fixtures")
    beats = analysis.get("beats") or []
    intervals = sorted(b - a for a, b in zip(beats, beats[1:])) or [0.5]
    beat_ms = int(intervals[len(intervals) // 2] * 1000)

    by_role: dict[str, list[dict]] = {}
    for fixture in fixtures:
        by_role.setdefault(fixture["role"], []).append(fixture)
    for role_fixtures in by_role.values():
        role_fixtures.sort(key=lambda f: (f.get("x", 0.5), f["id"]))

    out = _Cues(source, _ha_leads())
    aux_on: set[str] = set()

    for scene in script.get("scenes") or []:
        start, end = float(scene["start"]), float(scene["end"])
        palette = scene["palette"]
        base = float(scene.get("brightness", 0.5))
        scene_beats = _beats_in(beats, start, end)

        # Scene base: every color fixture gets a palette color, spread so
        # neighbours differ; roles cap their own brightness.
        spread = 0
        for role, role_fixtures in sorted(by_role.items()):
            rules = palettes.ROLE_RULES[role]
            if rules["switch"]:
                wanted_on = any(role in (m.get("roles") or [])
                                for m in scene.get("motifs") or []
                                if m["type"] == "aux_on")
                for fixture in role_fixtures:
                    entity = fixture["entity_id"]
                    if wanted_on and entity not in aux_on:
                        out.ha(fixture, start, "homeassistant.turn_on",
                               f"{role} on for {scene.get('mood')}")
                        aux_on.add(entity)
                    elif not wanted_on and entity in aux_on:
                        out.ha(fixture, start, "homeassistant.turn_off",
                               f"{role} off")
                        aux_on.discard(entity)
                continue
            for fixture in role_fixtures:
                hue, sat = palette[spread % len(palette)]
                spread += 1
                out.set_color(fixture, start, hue, sat,
                              min(base, rules["max_brightness"]),
                              duration_ms=900, desc=f"scene {scene.get('mood')}")

        # Motifs that ride waveforms.
        for motif in scene.get("motifs") or []:
            roles = [r for r in motif.get("roles") or []
                     if r in by_role and not palettes.ROLE_RULES[r]["switch"]]
            if motif["type"] == "beat_pulse":
                depth = float(motif.get("depth", 0.3))
                for role in roles:
                    if not palettes.ROLE_RULES[role]["pulses"]:
                        continue
                    for i, fixture in enumerate(by_role[role]):
                        hue, sat = palette[i % len(palette)]
                        for anchor in scene_beats[::8]:
                            out.waveform(
                                fixture, anchor, hue, sat,
                                min(base + depth,
                                    palettes.ROLE_RULES[role]["max_brightness"]),
                                period_ms=beat_ms, cycles=8.0,
                                desc="beat pulse x8")
            elif motif["type"] == "sweep":
                period_beats = int(motif.get("period_beats", 8))
                sweep_fixtures = [f for role in roles for f in by_role[role]]
                if not sweep_fixtures or not scene_beats:
                    continue
                period_s = beat_ms / 1000.0 * period_beats
                for i, fixture in enumerate(sweep_fixtures):
                    phase = (i / len(sweep_fixtures)) * period_s
                    hue, sat = palette[(i + 1) % len(palette)]
                    for anchor in scene_beats[::period_beats * 4]:
                        out.waveform(
                            fixture, anchor + phase, hue, sat,
                            min(base + 0.3, 1.0),
                            period_ms=int(period_s * 1000), cycles=4.0,
                            desc="sweep")
            elif motif["type"] == "breathe":
                period_beats = int(motif.get("period_beats", 16))
                depth = float(motif.get("depth", 0.15))
                for role in roles:
                    cap = palettes.ROLE_RULES[role]["max_brightness"]
                    for i, fixture in enumerate(by_role[role]):
                        hue, sat = palette[i % len(palette)]
                        period_ms = beat_ms * period_beats
                        length_s = end - start
                        cycles = max(1.0, length_s * 1000 / period_ms)
                        out.waveform(fixture, start, hue, sat,
                                     min(base + depth, cap),
                                     period_ms=period_ms, cycles=cycles,
                                     desc="breathe")

    # Features: the moments everything aims at.
    color_fixtures = [f for f in fixtures
                      if not palettes.ROLE_RULES[f["role"]]["switch"]]
    for feature in script.get("features") or []:
        t = float(feature["t"])
        if feature.get("type") == "drop_hit":
            blackout_s = float(feature.get("blackout_before_ms", 400)) / 1000.0
            strength = float(feature.get("strength", 0.8))
            for fixture in color_fixtures:
                out.set_color(fixture, t - blackout_s, 0, 0.0, 0.02,
                              duration_ms=int(blackout_s * 700),
                              desc="pre-drop blackout", resend=False)
                out.waveform(fixture, t, 0, 0.0,
                             min(1.0, 0.7 + strength * 0.3),
                             period_ms=max(120, beat_ms // 4), cycles=8.0,
                             desc="drop hit",
                             shape=packets.WAVEFORM_PULSE, skew_ratio=-20000)
            for fixture in fixtures:
                if palettes.ROLE_RULES[fixture["role"]]["switch"]:
                    if fixture["entity_id"] not in aux_on:
                        out.ha(fixture, t, "homeassistant.turn_on", "drop")
                        aux_on.add(fixture["entity_id"])
        elif feature.get("type") == "lyric_moment":
            for i, fixture in enumerate(color_fixtures):
                out.waveform(fixture, t, 45, 0.15, 1.0,
                             period_ms=900, cycles=1.0,
                             desc="lyric moment")

    # Aux lights end the show off.
    duration = float((analysis.get("tags") or {}).get("duration")
                     or (beats[-1] + 5 if beats else 60))
    for fixture in fixtures:
        if (palettes.ROLE_RULES[fixture["role"]]["switch"]
                and fixture["entity_id"] in aux_on):
            out.ha(fixture, duration, "homeassistant.turn_off", "show end")

    cues = sorted(out.cues, key=lambda c: c["t"] - c.get("lead_ms", 0) / 1000.0)
    peak = _peak_rate(cues)
    if peak > MAX_RATE_HZ:
        raise CompileError(
            f"compiled to {peak:.0f} msgs/s at some device — over the "
            f"budget of {MAX_RATE_HZ:.0f}/s (LIFX ceiling is 20). The "
            "script asks for more motion than the wire can carry.")

    return {
        "version": SHOW_VERSION,
        "track_hash": script.get("track_hash") or analysis.get("hash"),
        "tier": script.get("tier", "algorithmic"),
        "palette_name": script.get("palette_name"),
        "compiled_at": time.time(),
        "duration_s": duration,
        "cues": cues,
        "stats": {
            "cues": len(cues),
            "lifx_cues": sum(1 for c in cues if c["ch"] == "lifx"),
            "ha_cues": sum(1 for c in cues if c["ch"] == "ha"),
            "peak_per_device_hz": round(peak, 2),
            "fixtures": len(fixtures),
        },
    }


def _peak_rate(cues: list[dict]) -> float:
    worst = 0.0
    by_device: dict[str, list[float]] = {}
    for cue in cues:
        if cue.get("ch") != "lifx":
            continue
        sends = 2 if cue.get("resend") else 1
        by_device.setdefault(cue["serial"], []).extend([cue["t"]] * sends)
    for times in by_device.values():
        times.sort()
        for i in range(len(times)):
            j = i
            while j + 1 < len(times) and times[j + 1] - times[i] < 1.0:
                j += 1
            worst = max(worst, float(j - i + 1))
    return worst
