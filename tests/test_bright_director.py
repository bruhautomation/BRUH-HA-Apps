#!/usr/bin/env python3
"""BRight's director: the light map, the algorithmic choreographer, the
script validator (the Claude tier's gate), and THE compiler."""

import base64
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
PANEL_DIR = os.path.join(BASE_DIR, "bright", "panel")
if PANEL_DIR not in sys.path:
    sys.path.append(PANEL_DIR)

from director import build, choreographer, compiler, palettes  # noqa: E402
from lifx import packets  # noqa: E402
from stores import light_map  # noqa: E402


def analysis_fixture(minutes: float = 3.0, bpm: float = 120.0) -> dict:
    beats = [round(60.0 / bpm * i, 2)
             for i in range(1, int(minutes * bpm) + 1)]
    duration = minutes * 60
    third = duration / 3
    return {
        "hash": "ab" * 20,
        "bpm": bpm,
        "beats": beats,
        "downbeats": beats[::4],
        "onsets": beats,
        "brightness": 0.6,
        "tags": {"title": "Fixture Track", "duration": duration},
        "sections": [
            {"start": 0.0, "end": third, "kind": "intro", "energy": 0.2},
            {"start": third, "end": 2 * third, "kind": "peak", "energy": 0.9},
            {"start": 2 * third, "end": duration, "kind": "outro",
             "energy": 0.2},
        ],
        "drops": [{"t": third, "strength": 0.9}],
        "file": "/media/music/fixture.mp3",
    }


FIXTURES = [
    {"id": "lifx-d073d5000001", "kind": "lifx", "serial": "d073d5000001",
     "label": "Left lamp", "role": "lamp", "zone": "living", "x": 0.1,
     "y": 0.5, "rtt": {"p50_ms": 6.0}},
    {"id": "lifx-d073d5000002", "kind": "lifx", "serial": "d073d5000002",
     "label": "Right lamp", "role": "lamp", "zone": "living", "x": 0.9,
     "y": 0.5},
    {"id": "lifx-d073d5000003", "kind": "lifx", "serial": "d073d5000003",
     "label": "Mantel candle", "role": "candle", "zone": "living", "x": 0.5,
     "y": 0.2},
    {"id": "switch.laser", "kind": "ha", "entity_id": "switch.laser",
     "label": "laser", "role": "laser", "zone": "living", "x": 0.5, "y": 0.9},
]


class TestChoreographer(unittest.TestCase):
    def test_deterministic(self):
        analysis = analysis_fixture()
        first = choreographer.write_script(analysis, FIXTURES)
        second = choreographer.write_script(analysis, FIXTURES)
        self.assertEqual(first, second)

    def test_scenes_cover_the_sections(self):
        script = choreographer.write_script(analysis_fixture(), FIXTURES)
        self.assertEqual(3, len(script["scenes"]))
        self.assertEqual("lift", script["scenes"][1]["mood"])

    def test_a_drop_gets_a_build_into_it_and_a_hit_on_it(self):
        script = choreographer.write_script(analysis_fixture(), FIXTURES)
        drop_t = analysis_fixture()["drops"][0]["t"]
        kinds = {m["effect"]["type"] for m in script["moments"]}
        self.assertIn("build", kinds)
        self.assertIn("stab", kinds)
        build = next(m for m in script["moments"]
                     if m["effect"]["type"] == "build")
        # The build ends ON the drop and starts before it — tension is
        # the part that crosses the section boundary.
        self.assertAlmostEqual(drop_t, build["effect"]["end"], places=3)
        self.assertLess(build["t"], drop_t)
        hit = next(m for m in script["moments"]
                   if m["effect"]["type"] == "stab")
        self.assertIn("laser", hit["effect"]["select"]["roles"])

    def test_candles_never_pulse(self):
        script = choreographer.write_script(analysis_fixture(), FIXTURES)
        for scene in script["scenes"]:
            for effect in scene["effects"]:
                if effect["type"] in ("pulse", "chase", "strobe", "theater"):
                    self.assertNotIn(
                        "candle", effect.get("select", {}).get("roles", []))

    def test_the_chase_reads_the_map(self):
        """Order is a map question, and the map is what answers it."""
        many = FIXTURES + [
            {"id": f"lifx-d07000000{i}", "kind": "lifx",
             "serial": f"d07000000{i}0", "label": f"Lamp {i}", "role": "lamp",
             "zone": "", "x": i / 10.0, "y": 0.5} for i in range(3, 7)]
        script = choreographer.write_script(analysis_fixture(), many)
        peak = next(s for s in script["scenes"] if s["kind"] == "peak")
        chase = next(e for e in peak["effects"] if e["type"] == "chase")
        self.assertIn(chase["order"], ("x", "-x", "center_out", "snake",
                                       "zone"))

    def test_two_lights_answer_each_other_instead_of_chasing(self):
        """A chase across two bulbs is a flicker. The room's size is a
        creative constraint, not a parameter to ignore."""
        script = choreographer.write_script(analysis_fixture(), FIXTURES)
        peak = next(s for s in script["scenes"] if s["kind"] == "peak")
        types = {e["type"] for e in peak["effects"]}
        self.assertIn("theater", types)
        self.assertNotIn("chase", types)

    def test_its_own_output_validates(self):
        script = choreographer.write_script(analysis_fixture(), FIXTURES)
        self.assertEqual([], choreographer.validate_script(script))


class TestScriptValidator(unittest.TestCase):
    """The gate every Claude-authored script passes or dies at."""

    def test_rejects_free_text(self):
        self.assertTrue(choreographer.validate_script("a poem about lights"))

    def test_rejects_missing_scenes(self):
        self.assertTrue(choreographer.validate_script({"features": []}))

    def test_rejects_unknown_motifs(self):
        """The v1 vocabulary is still validated — scripts are files people
        keep, and a show compiled last year must still be readable."""
        script = choreographer.write_script(analysis_fixture(), FIXTURES)
        script["scenes"][0]["motifs"] = [
            {"type": "hyperdrive", "roles": ["lamp"]}]
        problems = choreographer.validate_script(script)
        self.assertTrue(any("unknown type" in p for p in problems))

    def test_rejects_an_unknown_effect_type(self):
        script = choreographer.write_script(analysis_fixture(), FIXTURES)
        script["scenes"][0]["effects"].append(
            {"type": "hyperdrive", "select": {"roles": ["lamp"]}})
        problems = choreographer.validate_script(script)
        self.assertTrue(any("hyperdrive" in p for p in problems), problems)

    def test_rejects_an_unusable_moment(self):
        script = choreographer.write_script(analysis_fixture(), FIXTURES)
        script["moments"].append({"t": "whenever",
                                  "effect": {"type": "stab"}})
        self.assertTrue(choreographer.validate_script(script))

    def test_rejects_a_scene_that_ends_before_it_starts(self):
        script = choreographer.write_script(analysis_fixture(), FIXTURES)
        script["scenes"][0]["end"] = -5
        self.assertTrue(choreographer.validate_script(script))

    def test_rejects_brightness_out_of_range(self):
        script = choreographer.write_script(analysis_fixture(), FIXTURES)
        script["scenes"][0]["brightness"] = 7
        self.assertTrue(choreographer.validate_script(script))


class TestCompiler(unittest.TestCase):
    def _show(self, analysis=None):
        analysis = analysis or analysis_fixture()
        script = choreographer.write_script(analysis, FIXTURES)
        return compiler.compile_show(script, FIXTURES, analysis, source=7)

    def test_budget_is_enforced_at_compile_time(self):
        show = self._show()
        self.assertLess(show["stats"]["peak_per_device_hz"],
                        compiler.MAX_RATE_HZ)

    def test_pulses_are_waveforms_anchored_on_beats(self):
        show = self._show()
        analysis = analysis_fixture()
        beat_set = {round(b, 4) for b in analysis["beats"]}
        pulses = [c for c in show["cues"]
                  if c["ch"] == "lifx" and c["desc"].startswith("beat pulse")]
        self.assertTrue(pulses)
        for cue in pulses:
            self.assertIn(round(cue["t"], 4), beat_set,
                          f"pulse at {cue['t']} is not on a beat")
            payload = base64.b64decode(cue["payload_b64"])
            self.assertEqual(packets.SET_WAVEFORM,
                             packets.parse_header(payload)["type"])

    def test_the_laser_leads_by_its_measured_latency(self):
        with tempfile.TemporaryDirectory() as tmp:
            latency_file = Path(tmp) / "ha-latency.json"
            latency_file.write_text(
                '{"switch.laser": {"p50_ms": 280.0}}')
            original = compiler.HA_LATENCY_FILE
            compiler.HA_LATENCY_FILE = latency_file
            try:
                show = self._show()
            finally:
                compiler.HA_LATENCY_FILE = original
        laser_cues = [c for c in show["cues"] if c["ch"] == "ha"]
        self.assertTrue(laser_cues)
        self.assertEqual(280.0, laser_cues[0]["lead_ms"])

    def test_the_drop_gets_a_blackout_then_a_hit(self):
        show = self._show()
        drop_t = analysis_fixture()["drops"][0]["t"]
        # Every cue names the effect that asked for it, which is how a
        # 900-cue timeline is readable at all — and how this test asks
        # about the drop rather than about a moment in time.
        blackouts = [c for c in show["cues"]
                     if c["desc"] == "drop hit \u00b7 pre-stab dip"]
        hits = [c for c in show["cues"] if c["desc"] == "drop hit \u00b7 stab"]
        self.assertTrue(blackouts and hits)
        self.assertAlmostEqual(drop_t - 0.4, blackouts[0]["t"], places=3)
        self.assertAlmostEqual(drop_t, hits[0]["t"], places=3)

    def test_candles_stay_dim(self):
        show = self._show()
        candle_cues = [c for c in show["cues"]
                       if c.get("serial") == "d073d5000003"
                       and c["desc"].startswith("scene")]
        cap = palettes.ROLE_RULES["candle"]["max_brightness"]
        for cue in candle_cues:
            payload = base64.b64decode(cue["payload_b64"])
            header = packets.parse_header(payload)
            import struct
            (_r, _h, _s, brightness, _k, _d) = struct.unpack(
                "<BHHHHI", header["payload"])
            self.assertLessEqual(brightness, int(cap * 65535) + 1)

    def test_no_fixtures_is_a_clear_refusal(self):
        analysis = analysis_fixture()
        script = choreographer.write_script(analysis, FIXTURES)
        with self.assertRaises(compiler.CompileError):
            compiler.compile_show(script, [], analysis, source=7)

    def test_an_overdense_script_fails_loudly(self):
        """A script that would flood a bulb must die at compile time."""
        analysis = analysis_fixture(bpm=200.0)
        one = [FIXTURES[0]]
        script = {
            "version": 1, "tier": "algorithmic",
            "track_hash": analysis["hash"], "palette_name": "club",
            "scenes": [{
                "start": 0.0, "end": 30.0, "mood": "flood",
                "palette": [[200, 0.9]], "brightness": 0.9,
                # Forty sweeps stacked on one fixture = a waveform per
                # anchor per motif, all anchored together — far over budget.
                "motifs": [{"type": "sweep", "roles": ["lamp"],
                            "axis": "x", "period_beats": 1}] * 40,
            }],
            "features": [],
        }
        with self.assertRaises(compiler.CompileError):
            compiler.compile_show(script, one, analysis, source=7)


class TestLightMapStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._file = light_map.MAP_FILE
        light_map.MAP_FILE = Path(self.tmp.name) / "light-map.json"

    def tearDown(self):
        light_map.MAP_FILE = self._file
        self.tmp.cleanup()

    def test_round_trip_and_validation(self):
        light_map.upsert({"kind": "lifx", "serial": "d073d5aabbcc",
                          "role": "strip", "label": "Shelf", "x": 0.2, "y": 0.3})
        light_map.upsert({"kind": "ha", "entity_id": "switch.disco",
                          "role": "party"})
        fixtures = light_map.load()["fixtures"]
        self.assertEqual(2, len(fixtures))
        for bad in (
            {"kind": "lifx", "serial": "nope", "role": "lamp"},
            {"kind": "ha", "entity_id": "../etc", "role": "party"},
            {"kind": "lifx", "serial": "d073d5aabbcc", "role": "discoball"},
            {"kind": "hue", "serial": "d073d5aabbcc", "role": "lamp"},
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    light_map.upsert(bad)

    def test_discovery_merge_never_overwrites_placement(self):
        light_map.upsert({"kind": "lifx", "serial": "d073d5aabbcc",
                          "role": "candle", "label": "Mantel",
                          "x": 0.9, "y": 0.9})
        added = light_map.merge_lifx({
            "d073d5aabbcc": {"label": "LIFX Bulb"},
            "d073d5ddeeff": {"label": "New bulb"},
        })
        self.assertEqual(1, added)
        by_id = {f["id"]: f for f in light_map.load()["fixtures"]}
        kept = by_id["lifx-d073d5aabbcc"]
        self.assertEqual(("candle", 0.9, "Mantel"),
                         (kept["role"], kept["x"], kept["label"]))
        self.assertEqual("lamp", by_id["lifx-d073d5ddeeff"]["role"])

    def test_reachability_filter(self):
        light_map.upsert({"kind": "lifx", "serial": "d073d5aabbcc",
                          "role": "lamp"})
        light_map.upsert({"kind": "lifx", "serial": "d073d5001122",
                          "role": "lamp"})
        reachable = light_map.lifx_fixtures(
            {"d073d5aabbcc": {"rtt": {"p50_ms": 4.0}}})
        self.assertEqual(1, len(reachable))
        self.assertEqual(4.0, reachable[0]["rtt"]["p50_ms"])


class TestBuild(unittest.TestCase):
    def test_strict_claude_mode_fails_rather_than_downgrades(self):
        def broken_writer(analysis, fixtures):
            return "not a script"

        with tempfile.TemporaryDirectory() as tmp:
            from analyzer import library
            original = library.SHOWS_DIR
            library.SHOWS_DIR = Path(tmp)
            light_original = light_map.MAP_FILE
            light_map.MAP_FILE = Path(tmp) / "light-map.json"
            try:
                analysis = analysis_fixture()
                library.save_analysis(analysis["hash"], analysis)
                light_map.upsert({"kind": "lifx", "serial": "d073d5000001",
                                  "role": "lamp"})
                devices = {"d073d5000001": {"serial": "d073d5000001",
                                            "ip": "10.0.0.7"}}
                with self.assertRaises(ValueError):
                    build.build_show(analysis["hash"], devices, 7,
                                     director_mode="claude",
                                     script_writer=broken_writer)
                # auto mode: same broken writer lands on the floor.
                show = build.build_show(analysis["hash"], devices, 7,
                                        director_mode="auto",
                                        script_writer=broken_writer)
                self.assertEqual("algorithmic", show["tier"])
            finally:
                library.SHOWS_DIR = original
                light_map.MAP_FILE = light_original


if __name__ == "__main__":
    unittest.main()
