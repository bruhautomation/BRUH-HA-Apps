"""A lock left unlocked at bedtime is said as a lock, and a car's as a car:
"open" is a door's word."""
import datetime as dt
import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

PANEL = Path(__file__).resolve().parent.parent / "brain" / "panel"
sys.path.insert(0, str(PANEL))

import rhythm  # noqa: E402

MONDAY = dt.datetime(2026, 9, 7, tzinfo=dt.timezone.utc)


def at(hour, minute=0):
    return (MONDAY + dt.timedelta(days=7, hours=hour, minutes=minute)).timestamp()


def house(name):
    return {
        "now": at(23, 30),
        "states": {"lock.thing": {"state": "unlocked", "attributes": {
            "friendly_name": name}, "last_changed": "", "last_updated": ""}},
        "entities": [{"entity_id": "lock.thing", "name": name}],
        "devices": [], "areas": [],
        "closures": {"built_at": 1, "entities": {"lock.thing": {
            "name": name, "changes": 100, "overall": 0.0,
            "buckets": {str(h): {"open": 0.0, "hours": 4.0}
                        for h in range(168)}}}},
    }


class TestLockWords(unittest.TestCase):
    def setUp(self):
        self.evening = importlib.import_module("checks.evening")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        old = rhythm.STORE
        rhythm.STORE = os.path.join(tmp.name, "rhythm.json")
        self.addCleanup(setattr, rhythm, "STORE", old)

    def row(self, name):
        [row] = self.evening.left_open(house(name), at(23, 30))
        return row

    def test_a_lock_is_unlocked_not_open(self):
        row = self.row("Front lock")
        self.assertNotIn("open", (row["text"] + row["detail"]).lower())
        self.assertIn("unlocked", row["text"].lower())

    def test_a_car_is_said_as_a_car(self):
        row = self.row("Family car lock")
        self.assertIn("car", row["detail"].lower())
        self.assertNotIn("open", (row["text"] + row["detail"]).lower())


if __name__ == "__main__":
    unittest.main()
