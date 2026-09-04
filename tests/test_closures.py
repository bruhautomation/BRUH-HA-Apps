"""What is normally open here, and the bedtime check that reads it.

A door being open is not wrong. It is wrong at half past eleven in a
house that always has it shut then, and it is nothing at all in one that
leaves it open all summer — so every case here is about the difference
between those two houses, and about the three ways this could claim to
know which one it is looking at when it does not.
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "brain", "panel"))

import baselines  # noqa: E402
import closures  # noqa: E402

UTC = dt.timezone.utc
MONDAY = dt.datetime(2026, 8, 3, tzinfo=UTC)      # a Monday, 00:00
NOW = (MONDAY + dt.timedelta(weeks=4)).timestamp()


def hw(when: dt.datetime) -> int:
    return baselines.hour_of_week(when.timestamp(), UTC)


class TestWhatCountsAsAClosure(unittest.TestCase):
    def test_the_things_that_can_be_left_open(self):
        for eid, attrs in (
            ("lock.front", {}),
            ("cover.garage", {"device_class": "garage"}),
            ("cover.blind", {}),
            ("binary_sensor.back", {"device_class": "door"}),
            ("binary_sensor.velux", {"device_class": "window"}),
        ):
            self.assertTrue(closures.is_closure(eid, attrs), eid)

    def test_a_motion_sensor_is_not_a_door(self):
        # The one classification mistake that would bury the row that
        # matters: a hall motion sensor is "on" every evening.
        for eid, attrs in (
            ("binary_sensor.hall_motion", {"device_class": "motion"}),
            ("binary_sensor.unlabelled", {}),
            ("switch.lamp", {}),
            ("sensor.temp", {"device_class": "door"}),
            ("light.kitchen", {}),
        ):
            self.assertFalse(closures.is_closure(eid, attrs), eid)

    def test_candidates_are_sorted_capped_and_alive(self):
        states = {f"binary_sensor.d{i:03d}": {
            "state": "off", "attributes": {"device_class": "door"}}
            for i in range(closures.MAX_ENTITIES + 20)}
        states["binary_sensor.gone"] = {
            "state": "unavailable", "attributes": {"device_class": "door"}}
        got = closures.candidates(states)
        self.assertEqual(len(got), closures.MAX_ENTITIES)
        self.assertEqual(got, sorted(got))
        self.assertNotIn("binary_sensor.gone", got)


class TestTheArithmetic(unittest.TestCase):
    def test_an_interval_is_charged_to_every_hour_it_crosses(self):
        # A door shut on Friday and opened on Monday is ONE interval
        # across sixty buckets. Charging it all to the hour it started in
        # is how a rarely-changing entity reports the week as unwatched.
        into: dict[int, float] = {}
        closures.spread_interval(
            MONDAY.timestamp(),
            (MONDAY + dt.timedelta(hours=3, minutes=30)).timestamp(),
            UTC, into)
        self.assertEqual({k: round(v / 3600, 2) for k, v in sorted(into.items())},
                         {0: 1.0, 1: 1.0, 2: 1.0, 3: 0.5})

    def test_a_backwards_interval_adds_nothing(self):
        into: dict[int, float] = {}
        closures.spread_interval(NOW, NOW - 100, UTC, into)
        self.assertEqual(into, {})

    def test_it_terminates_across_a_daylight_saving_boundary(self):
        # A clock that does not advance is an infinite loop, and a DST
        # boundary is exactly where that could happen.
        try:
            from zoneinfo import ZoneInfo
            london = ZoneInfo("Europe/London")
        except Exception:  # noqa: BLE001
            london = None
        if london is None:
            self.skipTest("no zoneinfo data on this system")
        spring = dt.datetime(2026, 3, 29, tzinfo=UTC).timestamp()
        into: dict[int, float] = {}
        closures.spread_interval(spring, spring + 6 * 3600, london, into)
        self.assertAlmostEqual(sum(into.values()), 6 * 3600, delta=1.0)


class TestMeasuringOneDoor(unittest.TestCase):
    def series(self, weeks=4):
        """Shut all week; opened Friday 23:50 for twenty minutes."""
        points = []
        for w in range(weeks):
            base = MONDAY + dt.timedelta(weeks=w)
            points.append([base.isoformat(), "off"])
            late = base + dt.timedelta(days=4, hours=23, minutes=50)
            points.append([late.isoformat(), "on"])
            points.append([(late + dt.timedelta(minutes=20)).isoformat(), "off"])
        return points

    def test_the_hour_it_is_open_and_the_hour_it_is_not(self):
        built = closures.build_entity(self.series(), UTC, NOW)
        friday = hw(MONDAY + dt.timedelta(days=4, hours=23))
        saturday = hw(MONDAY + dt.timedelta(days=5))
        monday_9 = hw(MONDAY + dt.timedelta(hours=9))
        # Ten of sixty minutes, in each of the two hours it straddles.
        self.assertAlmostEqual(closures.usual_open(built, friday), 1 / 6, places=2)
        self.assertAlmostEqual(closures.usual_open(built, saturday), 1 / 6, places=2)
        self.assertEqual(closures.usual_open(built, monday_9), 0.0)

    def test_never_watched_is_not_never_open(self):
        # The distinction the check has to branch on: `None` means this
        # hour has no observation behind it.
        self.assertIsNone(closures.usual_open({}, 0))
        self.assertIsNone(closures.usual_open({"buckets": {}}, 5))

    def test_a_door_watched_for_one_evening_says_nothing(self):
        points = [[MONDAY.isoformat(), "off"],
                  [(MONDAY + dt.timedelta(hours=2)).isoformat(), "on"],
                  [(MONDAY + dt.timedelta(hours=3)).isoformat(), "off"]]
        self.assertIsNone(closures.build_entity(
            points, UTC, (MONDAY + dt.timedelta(hours=4)).timestamp()))

    def test_one_reading_is_not_a_history(self):
        self.assertIsNone(closures.build_entity(
            [[MONDAY.isoformat(), "off"]], UTC, NOW))
        self.assertIsNone(closures.build_entity([], UTC, NOW))

    def test_rubbish_and_unknown_rows_are_skipped(self):
        points = self.series() + [
            ["not-a-date", "on"], [MONDAY.isoformat(), "unavailable"],
            [MONDAY.isoformat(), "unknown"], ["x"], "nope", None]
        self.assertIsNotNone(closures.build_entity(points, UTC, NOW))

    def test_a_door_that_stands_open_reads_as_open(self):
        points = [[MONDAY.isoformat(), "on"],
                  [(MONDAY + dt.timedelta(weeks=4)).isoformat(), "off"]]
        built = closures.build_entity(points, UTC, NOW)
        self.assertEqual(closures.usual_open(built, hw(MONDAY + dt.timedelta(hours=9))), 1.0)


class TestTheBedtimeCheck(unittest.TestCase):
    """Every floor asserted against the answer it refuses to give."""

    def setUp(self):
        sys.path.insert(0, os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "brain", "panel", "checks"))
        import importlib
        import rhythm
        self.evening = importlib.import_module("checks.evening")
        self.rhythm = rhythm
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self._old = rhythm.STORE
        rhythm.STORE = os.path.join(self.dir.name, "rhythm.json")
        self.addCleanup(setattr, rhythm, "STORE", self._old)

    def at(self, hour, minute=0) -> float:
        return (MONDAY + dt.timedelta(days=7, hours=hour,
                                      minutes=minute)).timestamp()

    def house(self, state="on", buckets=None, **over):
        entry = {"name": "Back door", "changes": 300, "overall": 0.01,
                 "buckets": buckets if buckets is not None else
                 {str(h): {"open": 0.0, "hours": 4.0} for h in range(168)}}
        snap = {
            "now": self.at(23, 30),
            "states": {"binary_sensor.back": {
                "state": state,
                "attributes": {"device_class": "door",
                               "friendly_name": "Back door"},
                "last_changed": "", "last_updated": ""}},
            "entities": [{"entity_id": "binary_sensor.back",
                          "name": "Back door"}],
            "devices": [], "areas": [],
            "closures": {"built_at": int(NOW), "entities":
                         {"binary_sensor.back": entry}},
        }
        snap.update(over)
        return snap

    # -- silent on a healthy house, first --------------------------------

    def test_nothing_measured_files_nothing(self):
        self.assertEqual(self.evening.left_open({"now": self.at(23)},
                                                self.at(23)), [])

    def test_a_shut_door_files_nothing(self):
        self.assertEqual(
            self.evening.left_open(self.house(state="off"), self.at(23, 30)), [])

    def test_the_afternoon_is_not_bedtime(self):
        # A door open at four is a door somebody is using.
        for hour in (9, 13, 16, 19):
            self.assertEqual(
                self.evening.left_open(self.house(), self.at(hour)), [],
                f"{hour}:00")

    def test_a_door_that_is_usually_open_then_files_nothing(self):
        buckets = {str(h): {"open": 0.4, "hours": 4.0} for h in range(168)}
        self.assertEqual(
            self.evening.left_open(self.house(buckets=buckets),
                                   self.at(23, 30)), [])

    def test_an_hour_never_watched_files_nothing(self):
        # "I have not watched this hour" is not "it is never open then".
        self.assertEqual(
            self.evening.left_open(self.house(buckets={}), self.at(23, 30)), [])

    # -- and then the thing it is for ------------------------------------

    def test_a_door_open_at_bedtime_that_is_usually_shut(self):
        found = self.evening.left_open(self.house(), self.at(23, 30))
        self.assertEqual(len(found), 1)
        self.assertIn("Back door", found[0]["detail"])
        self.assertEqual(found[0]["entity_id"], "binary_sensor.back")
        # The store dedupes on text, so the names live in the detail.
        self.assertNotIn("Back door", found[0]["text"])

    def test_an_unlocked_lock_counts(self):
        snap = self.house()
        snap["states"] = {"lock.front": {
            "state": "unlocked",
            "attributes": {"friendly_name": "Front lock"},
            "last_changed": "", "last_updated": ""}}
        snap["entities"] = [{"entity_id": "lock.front", "name": "Front lock"}]
        snap["closures"]["entities"] = {
            "lock.front": {"name": "Front lock", "changes": 100,
                           "overall": 0.0,
                           "buckets": {str(h): {"open": 0.0, "hours": 4.0}
                                       for h in range(168)}}}
        self.assertEqual(len(self.evening.left_open(snap, self.at(23, 30))), 1)

    def test_four_open_doors_are_one_row(self):
        # One thing to do before bed. Four rows to dismiss one at a time
        # is a chore, and a chore is what stops a list being read.
        snap = self.house()
        for i in range(3):
            eid = f"binary_sensor.extra{i}"
            snap["states"][eid] = {
                "state": "on",
                "attributes": {"device_class": "window",
                               "friendly_name": f"Window {i}"},
                "last_changed": "", "last_updated": ""}
            snap["entities"].append({"entity_id": eid, "name": f"Window {i}"})
            snap["closures"]["entities"][eid] = dict(
                snap["closures"]["entities"]["binary_sensor.back"])
        found = self.evening.left_open(snap, self.at(23, 30))
        self.assertEqual(len(found), 1)
        self.assertIn("Window 0", found[0]["detail"])

    def test_the_whole_house_open_is_the_house_not_a_door(self):
        snap = self.house()
        for i in range(closures.MIN_BUCKETS):
            eid = f"binary_sensor.w{i}"
            snap["states"][eid] = {
                "state": "on",
                "attributes": {"device_class": "window",
                               "friendly_name": f"W{i}"},
                "last_changed": "", "last_updated": ""}
            snap["entities"].append({"entity_id": eid, "name": f"W{i}"})
            snap["closures"]["entities"][eid] = dict(
                snap["closures"]["entities"]["binary_sensor.back"])
        self.assertEqual(self.evening.left_open(snap, self.at(23, 30)), [])

    # -- and the window follows the house, not a constant ----------------

    def test_a_measured_bedtime_moves_the_window(self):
        # A house that settles at 21:00 is asked about at 21:00, and the
        # fallback hour is then the wrong answer rather than the only one.
        rows = [{"ts": (MONDAY + dt.timedelta(days=d, hours=21)).timestamp(),
                 "cause": "person", "entity_id": "light.hall"}
                for d in range(20)]
        self.rhythm.record(rows, UTC, self.at(23))
        self.assertEqual(len(self.evening.left_open(
            self.house(), self.at(21, 10))), 1)
        self.assertEqual(self.evening.left_open(self.house(), self.at(23, 30)), [])


if __name__ == "__main__":
    unittest.main()
