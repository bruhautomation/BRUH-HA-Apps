#!/usr/bin/env python3
"""`chore.waiting` says what power shows, and "still full" only where a door does.

Report 442: "The washing machine has finished and is still full" and the
dryer's twin were both marked Wrong. A power reading sees a machine stop
and nothing run since; it cannot see whether the drum is empty. So the row
says that, and says "still full" only when a door or contact sensor on the
same machine has stayed shut since the cycle ended. The old wording rides
on the row as `was`, so an answer given to it is an answer to this report
and the new words do not ask again.
"""

import sys
import tempfile
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "brain" / "panel"))
sys.path.insert(0, str(TESTS_DIR))

import datetime as dt  # noqa: E402

import findings_store  # noqa: E402
from checks import chores  # noqa: E402
import test_appliances  # noqa: E402

NOW = test_appliances.NOW


DOOR = "binary_sensor.dryer_door"


def iso(stamp: float) -> str:
    return dt.datetime.fromtimestamp(stamp, tz=dt.timezone.utc).isoformat()


class Base(unittest.TestCase):
    """The dishwasher fixture, renamed as a dryer, with its plug on a device."""

    snap = test_appliances.TestTheChore.snap
    shape = test_appliances.TestTheChore.shape
    finished = test_appliances.TestTheChore.finished

    def dryer(self, door_state=None, door_changed=None):
        snap = self.snap(entities={"sensor.dishwasher_power":
                                   self.shape("Dryer power")},
                         recent=self.finished(60.0))
        snap["entities"][0]["device_id"] = "dev_dryer"
        snap["devices"] = [{"id": "dev_dryer", "name": "Dryer"}]
        if door_state is not None:
            snap["states"][DOOR] = {
                "state": door_state, "last_changed": iso(door_changed),
                "attributes": {"friendly_name": "Dryer door",
                               "device_class": "door"}}
            snap["entities"].append({"entity_id": DOOR,
                                     "device_id": "dev_dryer"})
        return snap


class TestTheWords(Base):
    def test_power_alone_never_says_full(self):
        row = chores.waiting(self.dryer(), NOW)[0]
        self.assertEqual(row["text"],
                         "The dryer finished a cycle and nothing has run since")
        self.assertNotIn("full", row["text"].lower())
        self.assertIn("nothing has run since", row["detail"])
        self.assertRegex(row["detail"], r"at \d\d:\d\d")

    def test_a_door_shut_since_the_cycle_ended_says_full(self):
        row = chores.waiting(self.dryer("off", NOW - 6 * 3600), NOW)[0]
        self.assertEqual(row["text"], "The dryer has finished and is still full")
        self.assertIn("Dryer door has stayed shut", row["detail"])

    def test_a_door_opened_since_files_nothing(self):
        self.assertEqual(chores.waiting(self.dryer("off", NOW - 5 * 60), NOW),
                         [])
        self.assertEqual(chores.waiting(self.dryer("on", NOW - 5 * 60), NOW),
                         [])

    def test_the_old_words_ride_on_the_row(self):
        row = chores.waiting(self.dryer(), NOW)[0]
        self.assertEqual(row["was"],
                         ["The dryer has finished and is still full"])


class TestAnAnswerToTheOldWordsStands(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.olds = (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
                     findings_store.STATE_FILE)
        findings_store.FINDINGS_FILE = root / "findings.json"
        findings_store.SETTLED_FILE = root / "settled.json"
        findings_store.STATE_FILE = root / "nope" / "state.json"

    def tearDown(self):
        (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
         findings_store.STATE_FILE) = self.olds
        self.tmp.cleanup()

    def row(self, text, was=()):
        return {"text": text, "severity": "info", "source": "check:chore.waiting",
                "entity_id": "sensor.washer_power", "was": list(was)}

    def test_a_wrong_on_the_old_text_keeps_the_new_one_quiet(self):
        old = "The washing machine has finished and is still full"
        created = findings_store.add_many([self.row(old)])
        findings_store.settle_and_clear(created[0]["ts"], "ignored")
        again = findings_store.add_many([self.row(
            "The washing machine finished a cycle and nothing has run since",
            was=[old])])
        self.assertEqual(again, [])

    def test_with_no_answer_the_new_text_files(self):
        got = findings_store.add_many([self.row(
            "The washing machine finished a cycle and nothing has run since",
            was=["The washing machine has finished and is still full"])])
        self.assertEqual(len(got), 1)


if __name__ == "__main__":
    unittest.main()
