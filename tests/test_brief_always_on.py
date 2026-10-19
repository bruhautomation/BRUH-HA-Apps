#!/usr/bin/env python3
"""A light the owner labels "always on" was not left on overnight (#287).

The morning brief listed lights labelled "always on" among the lights left
on overnight, while its own sentence said they need nothing. The labels
reach the brief through the names map the last checks pass built (`_NAMES`,
registry label ids such as `always_on`) — no new fetch — and a light that
carries one is left out of the reasons and the list.
"""

import datetime
import importlib
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import brief  # noqa: E402

NOW = 1_700_000_000.0


def light(eid, hours_on, name):
    since = datetime.datetime.fromtimestamp(
        NOW - hours_on * 3600, datetime.timezone.utc).isoformat()
    return {"entity_id": eid, "state": "on", "last_changed": since,
            "attributes": {"friendly_name": name}}


class TestAlwaysOnIsNotLeftOn(unittest.TestCase):
    def test_a_labelled_light_is_not_left_on(self):
        states = [light("light.porch", 9, "Porch"),
                  light("light.kitchen", 9, "Kitchen")]
        got = brief.morning_facts(
            states, [], NOW,
            labels={"light.porch": ["always_on"]})
        self.assertEqual([r["name"] for r in got["left_on"]], ["Kitchen"])

    def test_the_label_is_read_in_whole_words_and_any_spelling(self):
        for spelled in ("always_on", "Always On", "always-on", "lights_always_on"):
            self.assertTrue(brief.always_on_label([spelled]), spelled)
        for spelled in ("always_online", "on_always", "", "evening"):
            self.assertFalse(brief.always_on_label([spelled]), spelled)

    def test_nothing_is_said_about_lights_when_none_remain(self):
        got = brief.morning_facts(
            [light("light.porch", 9, "Porch")], [], NOW,
            labels={"light.porch": ["always_on"]})
        reasons = brief.worth_saying({"morning": got})
        self.assertFalse(any("Left on" in r for r in reasons), reasons)

    def test_the_panel_hands_the_brief_the_labels_it_already_holds(self):
        server = importlib.import_module("server")
        saved = dict(server._NAMES)
        try:
            server._NAMES.clear()
            server._NAMES.update({
                "light.night": {"name": "Night light", "labels": ["always_on"]},
                "light.kitchen": {"name": "Kitchen"}})
            night = {"states": [light("light.night", 9, "Night light"),
                                light("light.kitchen", 9, "Kitchen")]}
            got = server._brief_morning(NOW, night)
        finally:
            server._NAMES.clear()
            server._NAMES.update(saved)
        self.assertEqual([r["entity_id"] for r in got["left_on"]],
                         ["light.kitchen"])


if __name__ == "__main__":
    unittest.main()
