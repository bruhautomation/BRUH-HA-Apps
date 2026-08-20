#!/usr/bin/env python3
"""The effect library: saved effects that shows use, and Claude reads.

A preset store existed before this and was invisible to the one thing
most able to use it. BRight would hold a dozen effects somebody spent an
evening getting right, and then ask Claude to write a show from a blank
page — so every show started from nothing, and no show could be better
than the last one. That is the opposite of what a library is for.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "bright" / "panel"
if str(PANEL_DIR) not in sys.path:
    sys.path.append(str(PANEL_DIR))

CHASE = {
    "type": "chase", "name": "kitchen chase",
    "select": {"zones": ["kitchen"]},
    "order": "x",
    "params": {"step_beats": 0.5, "width": 2, "brightness": 0.9},
}


class LibraryCase(unittest.TestCase):
    def setUp(self):
        from stores import effect_presets
        self.presets = effect_presets
        self.tmp = tempfile.TemporaryDirectory()
        self._file = effect_presets.PRESETS_FILE
        effect_presets.PRESETS_FILE = Path(self.tmp.name) / "presets.json"

    def tearDown(self):
        self.presets.PRESETS_FILE = self._file
        self.tmp.cleanup()


class TestUsingASavedEffect(LibraryCase):
    def test_a_script_can_name_one(self):
        self.presets.save("kitchen chase", CHASE)
        script = {"scenes": [{"start": 0, "end": 30,
                              "effects": [{"use": "kitchen chase"}]}]}
        out = self.presets.expand_script(script)
        effect = out["scenes"][0]["effects"][0]
        self.assertEqual("chase", effect["type"])
        self.assertEqual({"zones": ["kitchen"]}, effect["select"])
        self.assertEqual(0.5, effect["params"]["step_beats"])
        self.assertNotIn("use", effect, "expanded, not referenced")

    def test_overriding_a_parameter_keeps_the_others(self):
        """Changing the speed of a saved chase must not silently drop the
        rest of it, which is exactly what a wholesale replace would do."""
        self.presets.save("kitchen chase", CHASE)
        out = self.presets.expand_script({"scenes": [{
            "effects": [{"use": "kitchen chase",
                         "params": {"step_beats": 2}}]}]})
        params = out["scenes"][0]["effects"][0]["params"]
        self.assertEqual(2, params["step_beats"], "the override landed")
        self.assertEqual(2, params["width"], "and the rest survived")
        self.assertEqual(0.9, params["brightness"])

    def test_the_selection_can_be_overridden_too(self):
        self.presets.save("kitchen chase", CHASE)
        out = self.presets.expand_script({"scenes": [{
            "effects": [{"use": "kitchen chase",
                         "select": {"roles": ["lamp"]}}]}]})
        self.assertEqual({"roles": ["lamp"]},
                         out["scenes"][0]["effects"][0]["select"])

    def test_a_moment_can_name_one(self):
        self.presets.save("kitchen chase", CHASE)
        out = self.presets.expand_script(
            {"moments": [{"t": 70.0, "effect": {"use": "kitchen chase"}}]})
        self.assertEqual("chase", out["moments"][0]["effect"]["type"])

    def test_an_unknown_name_says_what_the_library_holds(self):
        self.presets.save("kitchen chase", CHASE)
        with self.assertRaises(self.presets.UnknownPreset) as caught:
            self.presets.expand_script(
                {"scenes": [{"effects": [{"use": "hallway sweep"}]}]})
        message = str(caught.exception)
        self.assertIn("hallway sweep", message)
        self.assertIn("kitchen chase", message,
                      "naming what IS there is most of the fix")

    def test_expansion_does_not_touch_the_script_it_was_given(self):
        """The caller's script is theirs. Expansion happens on a copy
        because a failed compile must leave the editor holding what the
        person typed, not a half-expanded version of it."""
        self.presets.save("kitchen chase", CHASE)
        script = {"scenes": [{"effects": [{"use": "kitchen chase"}]}]}
        self.presets.expand_script(script)
        self.assertEqual({"use": "kitchen chase"},
                         script["scenes"][0]["effects"][0])

    def test_an_ordinary_effect_passes_through_untouched(self):
        plain = {"type": "wash", "params": {"brightness": 0.4}}
        out = self.presets.expand_script({"scenes": [{"effects": [plain]}]})
        self.assertEqual(plain, out["scenes"][0]["effects"][0])

    def test_a_saved_show_holds_the_effect_not_the_name(self):
        """The invariant the whole design turns on.

        A show that stored the NAME would change when somebody edited the
        library — silently, and usually the night after they edited it.
        The library is a place to copy from, not a layer a saved show
        depends on.
        """
        self.presets.save("kitchen chase", CHASE)
        expanded = self.presets.expand_script(
            {"scenes": [{"effects": [{"use": "kitchen chase"}]}]})
        self.presets.save("kitchen chase",
                          {**CHASE, "params": {"step_beats": 4}})
        # The already-expanded script is unaffected by the later edit.
        self.assertEqual(
            0.5, expanded["scenes"][0]["effects"][0]["params"]["step_beats"])


class TestTheLibraryIsReadable(LibraryCase):
    def test_an_empty_library_still_says_what_it_is_for(self):
        text = self.presets.describe()
        self.assertIn("none yet", text)
        self.assertIn("saved to the library", text)

    def test_a_saved_effect_is_described_not_just_named(self):
        """"kitchen chase" is not a name a model can reason about; "a
        chase across the kitchen zone, half a beat a step" is."""
        self.presets.save("kitchen chase", CHASE, note="looks great at 120bpm")
        text = self.presets.describe()
        self.assertIn("kitchen chase", text)
        self.assertIn("chase", text)
        self.assertIn("kitchen", text, "the selection is part of the idea")
        self.assertIn("step_beats=0.5", text, "and so are the parameters")
        self.assertIn("120bpm", text, "the note somebody left")
        self.assertIn('"use"', text, "and how to reach for one")

    def test_a_selection_by_role_reads_as_a_role(self):
        self.presets.save("candle calm", {
            "type": "breathe", "select": {"roles": ["candle"]}, "params": {}})
        self.assertIn("role candle", self.presets.describe())

    def test_an_effect_that_names_nothing_says_every_light(self):
        self.presets.save("all up", {"type": "wash", "params": {}})
        self.assertIn("every light", self.presets.describe())


class TestTheLibraryReachesClaude(LibraryCase):
    """The gap this closes: the store existed and no prompt mentioned it."""

    def test_the_show_director_is_told_what_is_saved(self):
        from director import claude_director
        from test_bright_director import FIXTURES, analysis_fixture

        self.presets.save("kitchen chase", CHASE)
        brief = claude_director.digest(analysis_fixture(), FIXTURES)
        self.assertIn("kitchen chase", brief)
        self.assertIn("SAVED EFFECTS", brief)

    def test_the_effect_writer_is_told_too(self):
        from director import claude_director
        from test_bright_director import FIXTURES

        self.presets.save("kitchen chase", CHASE)
        prompt = claude_director._effect_prompt("something warm", FIXTURES)
        self.assertIn("kitchen chase", prompt)


if __name__ == "__main__":
    unittest.main()
