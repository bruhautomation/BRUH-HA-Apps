#!/usr/bin/env python3
"""One missing entity is one row, however many dashboards show it.

#341: a deleted scene shown on two dashboards was filed twice, one row per
dashboard, so the same fix had to be answered twice. The rows are grouped
by what is missing: one row naming every dashboard that shows it, its text
stable across passes (the dashboards it names are in the detail), and it
clears once the entity is back. Entities missing from exactly the same
dashboards share a row, so a rebuilt integration that renamed forty is
still one row and not forty.
"""

import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "brain" / "panel"))
sys.path.insert(0, str(TESTS_DIR))

import checks  # noqa: E402
from test_house_checks import NOW, house  # noqa: E402


def dash(title, *entities):
    return {"url_path": title.lower(), "title": title, "config": {
        "views": [{"cards": [{"type": "entities", "entities": list(entities)}]}]}}


def run(snap):
    return checks.run_all(snap, NOW, only=["org.dashboard_dead_ref"])["findings"]


class TestOneMissingEntityIsOneRow(unittest.TestCase):
    def test_a_scene_on_two_dashboards_is_one_row_naming_both(self):
        snap = house()
        snap["dashboards"] = [dash("Home", "light.kitchen", "scene.movie_night"),
                              dash("Lounge", "scene.movie_night")]
        [row] = run(snap)
        self.assertEqual(row["entity_id"], "scene.movie_night")
        self.assertIn("Home", row["detail"])
        self.assertIn("Lounge", row["detail"])
        self.assertEqual([e["entity"] for e in row["evidence"]],
                         ["scene.movie_night"])

    def test_the_text_does_not_move_when_another_dashboard_shows_it(self):
        snap = house()
        snap["dashboards"] = [dash("Home", "scene.movie_night")]
        [one] = run(snap)
        snap["dashboards"].append(dash("Lounge", "scene.movie_night"))
        [two] = run(snap)
        self.assertEqual(one["text"], two["text"])

    def test_it_clears_once_the_entity_is_back(self):
        snap = house()
        snap["dashboards"] = [dash("Home", "scene.movie_night"),
                              dash("Lounge", "scene.movie_night")]
        snap["states"]["scene.movie_night"] = {
            "state": "unknown", "attributes": {"friendly_name": "Movie night"}}
        self.assertEqual(run(snap), [])

    def test_missing_from_the_same_dashboards_is_still_one_row(self):
        snap = house()
        renamed = [f"sensor.old_{i}" for i in range(40)]
        snap["dashboards"] = [dash("Home", *renamed)]
        [row] = run(snap)
        self.assertEqual(row["entity_id"], "sensor.old_0")
        self.assertIn("32 more", row["detail"])

    def test_two_entities_on_different_dashboards_are_two_rows(self):
        snap = house()
        snap["dashboards"] = [dash("Home", "scene.movie_night"),
                              dash("Lounge", "switch.vanished")]
        self.assertEqual(sorted(r["entity_id"] for r in run(snap)),
                         ["scene.movie_night", "switch.vanished"])


if __name__ == "__main__":
    unittest.main()
