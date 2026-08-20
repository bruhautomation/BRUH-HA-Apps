"""The show preview: one walk, two consumers, and a window you can scrub.

What these are actually guarding:

* that `script_actions` and `compile_show` cannot drift — the preview is
  only trustworthy because it is the compiler's own walk, so the test is
  that the cues built from the extracted walk are the cues `compile_show`
  produces, on a real generated show rather than a toy one;
* that a window three minutes in reports what the lights are WEARING there,
  not what they wore at the start — the whole point of `start_s`, and the
  failure it prevents is a preview that silently previews the wrong show;
* that the strip and the window move when the show does.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bright" / "panel"))

from director import choreographer, compiler, preview  # noqa: E402
from director import effects as fx  # noqa: E402

from test_bright_director import analysis_fixture  # noqa: E402

FIXTURES = [
    {"id": "d1", "kind": "lifx", "serial": "d073d5000001", "ip": "10.0.0.11",
     "label": "Left", "role": "downlight", "zone": "lounge", "x": 0.1, "y": 0.2},
    {"id": "d2", "kind": "lifx", "serial": "d073d5000002", "ip": "10.0.0.12",
     "label": "Right", "role": "lamp", "zone": "lounge", "x": 0.9, "y": 0.2},
    {"id": "d3", "kind": "lifx", "serial": "d073d5000003", "ip": "10.0.0.13",
     "label": "Back", "role": "strip", "zone": "lounge", "x": 0.5, "y": 0.9},
    {"id": "d4", "kind": "lifx", "serial": "d073d5000004", "ip": "10.0.0.14",
     "label": "Candle", "role": "candle", "zone": "hall", "x": 0.2, "y": 0.8},
    {"id": "a1", "kind": "ha", "entity_id": "switch.laser", "label": "Laser",
     "role": "laser", "zone": "lounge", "x": 0.7, "y": 0.6},
]


def a_show():
    analysis = analysis_fixture()
    return choreographer.write_script(analysis, FIXTURES), analysis


class TestOneWalkTwoConsumers(unittest.TestCase):
    """`compile_show` must be `script_actions` plus `render_actions`."""

    def test_the_extracted_walk_builds_the_same_cues(self):
        script, analysis = a_show()
        show = compiler.compile_show(script, FIXTURES, analysis, source=42)

        walked = compiler.script_actions(script, FIXTURES, analysis)
        out = compiler._Cues(42, compiler._ha_leads())
        compiler.render_actions(walked["actions"], out)
        cues = sorted(out.cues,
                      key=lambda c: c["t"] - c.get("lead_ms", 0) / 1000.0)

        self.assertEqual(len(cues), len(show["cues"]))
        self.assertEqual(json.dumps(cues, sort_keys=True),
                         json.dumps(show["cues"], sort_keys=True))

    def test_the_walk_carries_the_show_ending_its_switches_off(self):
        # The aux tail used to be written straight to the cues, where the
        # preview could not see it — a laser that goes out at the end of
        # the show but stays lit in the picture of it.
        script, analysis = a_show()
        walked = compiler.script_actions(script, FIXTURES, analysis)
        tail = [a for a in walked["actions"]
                if a["kind"] == "aux" and a["desc"] == "show end"]
        self.assertTrue(tail, "no aux switch is turned off at the end")
        for action in tail:
            self.assertFalse(action["on"])
            self.assertAlmostEqual(action["t"], walked["duration_s"], places=3)

    def test_no_fixtures_is_the_same_refusal_compiling_gives(self):
        script, analysis = a_show()
        with self.assertRaises(compiler.CompileError):
            compiler.script_actions(script, [], analysis)


class TestTheWindowIsWhereYouScrubbedTo(unittest.TestCase):

    def test_a_window_reports_the_colours_of_its_own_moment(self):
        # The failure this prevents: a window that starts its simulation at
        # `start_s` rather than merely its FRAMES, so every light reads as
        # whatever it was at the top of the song.
        script, analysis = a_show()
        walked = compiler.script_actions(script, FIXTURES, analysis)
        whole = fx.simulate(walked["actions"], FIXTURES,
                            duration_s=walked["duration_s"], fps=15)
        window = preview.window(script, FIXTURES, analysis,
                                start_s=90.0, span_s=4.0)
        index = int(90.0 * whole["fps"])
        self.assertEqual(window["frames"][0], whole["frames"][index])

    def test_a_window_is_not_the_opening_frame(self):
        script, analysis = a_show()
        first = preview.window(script, FIXTURES, analysis, start_s=0.0,
                               span_s=2.0)
        later = preview.window(script, FIXTURES, analysis, start_s=90.0,
                               span_s=2.0)
        self.assertNotEqual(first["frames"][0], later["frames"][0])

    def test_past_the_end_lands_on_the_end(self):
        # A scrub bar dragged to its right-hand stop is a person looking at
        # the end of the show, not a bug to raise.
        script, analysis = a_show()
        window = preview.window(script, FIXTURES, analysis, start_s=99999.0)
        self.assertLessEqual(window["start_s"], window["track_duration_s"])
        self.assertTrue(window["frames"])

    def test_a_window_covers_the_span_it_promises(self):
        script, analysis = a_show()
        window = preview.window(script, FIXTURES, analysis, start_s=10.0,
                                span_s=6.0)
        self.assertAlmostEqual(window["start_s"], 10.0, places=1)
        self.assertAlmostEqual(window["span_s"], 6.0, places=1)
        self.assertGreaterEqual(len(window["frames"]),
                                int(6.0 * window["fps"]))
        self.assertEqual(len(window["frames"][0]), len(FIXTURES))


class TestTheStrip(unittest.TestCase):

    def test_the_overview_spans_the_whole_show(self):
        script, analysis = a_show()
        strip = preview.overview(script, FIXTURES, analysis, columns=120)
        self.assertEqual(len(strip["columns"]), 120)
        self.assertEqual(len(strip["columns"][0]), len(FIXTURES))
        self.assertGreater(strip["seconds_per_column"], 0)

    def test_a_visible_edit_moves_the_strip(self):
        # The editor's whole promise. An effect added to a quiet scene has
        # to show up — added to the drop it legitimately would not, because
        # the stab there owns those lights, and that is the show being
        # right rather than the preview being wrong.
        script, analysis = a_show()
        before = preview.overview(script, FIXTURES, analysis, columns=120)
        edited = json.loads(json.dumps(script))
        edited["scenes"][0].setdefault("effects", []).append({
            "type": "strobe", "name": "test strobe",
            "select": {"roles": ["downlight"]}, "params": {}})
        after = preview.overview(edited, FIXTURES, analysis, columns=120)
        self.assertNotEqual(before["columns"], after["columns"])

    def test_every_column_is_a_moment_that_happened(self):
        # Never an average: the mean of two colours is a colour the show
        # does not contain. Each column has to be a frame the simulation
        # really produced.
        script, analysis = a_show()
        walked = compiler.script_actions(script, FIXTURES, analysis)
        frames = fx.simulate(walked["actions"], FIXTURES,
                             duration_s=walked["duration_s"],
                             fps=preview.OVERVIEW_FPS)
        real = {json.dumps(frame) for frame in frames["frames"]}
        strip = preview.overview(script, FIXTURES, analysis, columns=120)
        for column in strip["columns"]:
            self.assertIn(json.dumps(column), real)


class TestTheTimeline(unittest.TestCase):

    def test_it_describes_the_scenes_the_script_holds(self):
        script, analysis = a_show()
        timeline = preview.timeline(script, analysis)
        self.assertEqual(len(timeline["scenes"]), len(script["scenes"]))
        for drawn, source in zip(timeline["scenes"], script["scenes"]):
            self.assertAlmostEqual(drawn["start"], source["start"], places=2)
            self.assertAlmostEqual(drawn["end"], source["end"], places=2)
            self.assertTrue(drawn["label"])

    def test_a_broken_scene_does_not_take_the_timeline_down(self):
        # The editor draws what IS there while somebody is halfway through
        # typing; the save is where a bad scene gets named and refused.
        script, analysis = a_show()
        script["scenes"].append({"mood": "half typed"})
        timeline = preview.timeline(script, analysis)
        self.assertEqual(len(timeline["scenes"]), len(script["scenes"]) - 1)

    def test_it_carries_the_bar_lines_an_edge_should_snap_to(self):
        script, analysis = a_show()
        timeline = preview.timeline(script, analysis)
        self.assertTrue(timeline["downbeats"])
        self.assertEqual(timeline["bpm"], analysis["bpm"])


class TestTheEditorsDefaults(unittest.TestCase):
    """The panel opens an effect at the compiler's defaults, or an edit
    that touches nothing still changes the show."""

    def test_the_defaults_are_what_clean_effect_applies(self):
        bare = fx.clean_effect({"type": "chase"})
        self.assertEqual(bare["order"], fx.DEFAULT_ORDER)
        self.assertEqual(bare["align"], fx.DEFAULT_ALIGN)

    def test_the_defaults_are_real_choices(self):
        self.assertIn(fx.DEFAULT_ORDER, fx.ORDERS)
        self.assertIn(fx.DEFAULT_ALIGN, fx.ALIGNMENTS)


if __name__ == "__main__":
    unittest.main()
