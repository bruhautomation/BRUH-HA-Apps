#!/usr/bin/env python3
"""A finding about several things carries all of them, and its sentence is
never cut off (#437).

A dashboard finding ended "the scene “…”, the select…" and an automation's
"and 7 more.…": the detail listed what was missing inline, long names took
it past the store's cap or the card's three lines, and the rest of the list
was nowhere a person could reach. Now a check that lists things keeps its
inline list inside a budget, carries the WHOLE list as `items`, and the
case hands the card every item by the name a person reads, for the card's
count line and its Show all.
"""

import re
import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "brain" / "panel"))
sys.path.insert(0, str(TESTS_DIR))

import cases  # noqa: E402
import checks  # noqa: E402
import findings_store  # noqa: E402
from test_house_checks import NOW, house  # noqa: E402

LONG = [f"select.upstairs_hallway_ceiling_light_scene_mode_number_{i}"
        for i in range(9)] + [
    f"scene.evening_in_the_living_room_with_the_curtains_drawn_{i}"
    for i in range(6)]


def dash(title, *entities):
    return {"url_path": title.lower(), "title": title, "config": {
        "views": [{"cards": [{"type": "entities", "entities": list(entities)}]}]}}


def assert_whole(test, detail):
    test.assertLessEqual(len(detail), findings_store.MAX_DETAIL, detail)
    test.assertFalse(detail.endswith("…"), detail[-60:])
    test.assertNotIn(".…", detail)
    # Every name in the sentence is whole: nothing ends inside a quote.
    test.assertEqual(detail.count("“"), detail.count("”"), detail)


class TestADashboardRowCarriesEveryMissingEntity(unittest.TestCase):
    def test_long_names_on_many_dashboards(self):
        snap = house()
        snap["dashboards"] = [dash(f"Upstairs dashboard number {i}", *LONG)
                              for i in range(9)]
        [row] = checks.run_all(snap, NOW, only=["org.dashboard_dead_ref"])[
            "findings"]
        assert_whole(self, row["detail"])
        self.assertEqual(sorted(row["items"]), sorted(LONG))


class TestAnAutomationRowCarriesEveryMissingEntity(unittest.TestCase):
    def test_an_automation_naming_many_dead_entities(self):
        snap = house()
        snap["automations"][0]["actions"] += [
            {"action": "scene.turn_on", "target": {"entity_id": e}}
            for e in LONG]
        rows = checks.run_all(snap, NOW, only=["auto.dead_ref"])["findings"]
        self.assertEqual(len(rows), 1)
        assert_whole(self, rows[0]["detail"])
        self.assertEqual(sorted(rows[0]["items"]), sorted(LONG))


class TestTheCaseNamesEveryItem(unittest.TestCase):
    def test_item_labels_by_the_name_a_person_reads(self):
        old = findings_store.DISPLAY_NAMES
        findings_store.DISPLAY_NAMES = lambda: {"light.porch": "Porch light"}
        try:
            row = {"ts": 1, "status": "open", "text": "Some are missing",
                   "detail": "Missing: 3.", "source": "check:auto.dead_ref",
                   "items": ["light.porch", "scene.before_movie",
                             "select.hall_mode"]}
            case = cases._from_finding(row, {})
        finally:
            findings_store.DISPLAY_NAMES = old
        self.assertEqual(case["item_labels"], [
            "Porch light", "the scene “before movie”",
            "the select “hall mode”"])
        self.assertEqual(case["items_noun"], "entities")
        for label in case["item_labels"]:
            self.assertIsNone(re.match(r"^[a-z_]+\.[a-z0-9_]+$", label))

    def test_a_row_about_one_thing_carries_no_list(self):
        case = cases._from_finding({"ts": 1, "status": "open", "text": "x",
                                    "source": "check:a.b"}, {})
        self.assertNotIn("item_labels", case)


if __name__ == "__main__":
    unittest.main()
