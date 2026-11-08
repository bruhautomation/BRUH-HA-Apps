#!/usr/bin/env python3
"""One device's link trouble and what it causes are one row (#582).

A lock's weak Bluetooth link and the same lock's late battery reading were
two findings, each with its own advice, and nothing said the weak link
probably explains the late reading. A row about a device's battery going
low or quiet now folds into a live row about the same device's link (weak,
dropping, unavailable): one card, the link's step first, the battery's
report kept on the card as evidence that names the shared cause.

The second example is one the report did not name: a device that is
unavailable and whose battery row says low. A safety or security row is
never folded, and rows about two different devices stay two.
"""
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import findings_store  # noqa: E402
from test_subject_fold import FoldCase  # noqa: E402

NAMES = {
    "sensor.front_lock_signal": {"name": "Front lock signal",
                                 "device": "dev-lock"},
    "sensor.front_lock_battery": {"name": "Front lock battery",
                                  "device": "dev-lock"},
    "lock.front_door": {"name": "Front door", "device": "dev-lock"},
    "sensor.shed_battery": {"name": "Shed sensor battery",
                            "device": "dev-shed"},
    "binary_sensor.shed_motion": {"name": "Shed motion", "device": "dev-shed"},
    "sensor.porch_battery": {"name": "Porch sensor battery",
                             "device": "dev-porch"},
}


class LinkCase(FoldCase):
    def setUp(self):
        super().setUp()
        self._names = findings_store.DISPLAY_NAMES
        findings_store.DISPLAY_NAMES = lambda: NAMES

    def tearDown(self):
        findings_store.DISPLAY_NAMES = self._names
        super().tearDown()


def weak_link():
    return {"text": "Front lock has a weak Bluetooth signal",
            "claim": "Front lock has a weak Bluetooth signal",
            "detail": "Its signal has read -92 dBm all week.",
            "fix": "Move the Bluetooth proxy closer to the front door.",
            "source": "resident", "kind": "problem", "severity": "warning",
            "entity_id": "sensor.front_lock_signal"}


def battery_late(eid="sensor.front_lock_battery", who="Front lock"):
    return {"text": f"{who} has stopped reporting its battery",
            "detail": "Last heard 3 days ago; it still shows 60%.",
            "fix": "Replace its battery.",
            "source": "check:dev.battery_low", "severity": "warning",
            "fixable": False, "entity_id": eid}


def live():
    return [f for f in findings_store.list_all()
            if f["status"] in findings_store.CROSS_FOLD_STATUSES]


class TestOneDeviceOneCause(LinkCase):
    def test_a_late_battery_folds_under_the_weak_link_on_the_same_lock(self):
        findings_store.add_many([weak_link(), battery_late()])
        rows = live()
        self.assertEqual(len(rows), 1, [r["text"] for r in rows])
        row = rows[0]
        # The link's step is the one said first.
        self.assertEqual(row["fix"],
                         "Move the Bluetooth proxy closer to the front door.")
        said = [e for e in row["evidence"]
                if e["entity"] == "sensor.front_lock_battery"]
        self.assertEqual(len(said), 1)
        self.assertIn("stopped reporting its battery", said[0]["value"])
        self.assertIn("same", said[0]["value"].lower())

    def test_the_order_they_are_filed_in_does_not_matter(self):
        findings_store.add_many([battery_late()])
        findings_store.add_many([weak_link()])
        rows = live()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["entity_id"], "sensor.front_lock_signal")

    def test_an_unavailable_device_takes_in_its_low_battery(self):
        # Not in the report: the device is unavailable, and its battery row
        # says low. One card, the outage first.
        findings_store.add_many([
            {"text": "Shed motion has been unavailable for a day",
             "detail": "Unavailable since Tuesday 14:00.",
             "fix": "Re-pair the shed sensor.",
             "source": "check:dev.unavailable", "severity": "warning",
             "fixable": False, "entity_id": "binary_sensor.shed_motion"},
            {"text": "Shed sensor battery is low",
             "detail": "4% as of Tuesday 13:50.",
             "fix": "Replace the battery.",
             "source": "check:dev.battery_low", "severity": "serious",
             "fixable": False, "entity_id": "sensor.shed_battery"}])
        rows = live()
        self.assertEqual(len(rows), 1, [r["text"] for r in rows])
        self.assertEqual(rows[0]["entity_id"], "binary_sensor.shed_motion")
        self.assertEqual(rows[0]["fix"], "Re-pair the shed sensor.")
        # Nothing hidden: the battery row is on the card, and its severity
        # carried over.
        self.assertIn("sensor.shed_battery",
                      {e["entity"] for e in rows[0]["evidence"]})
        self.assertEqual(rows[0]["severity"], "serious")

    def test_a_battery_on_another_device_stays_its_own_row(self):
        findings_store.add_many([weak_link(),
                                 battery_late("sensor.porch_battery",
                                              "Porch sensor")])
        self.assertEqual(len(live()), 2)

    def test_two_battery_rows_without_a_link_row_stay_apart(self):
        findings_store.add_many([battery_late(),
                                 {**battery_late(),
                                  "text": "Front lock battery is low"}])
        self.assertEqual(len(live()), 2)

    def test_a_security_row_on_the_same_lock_is_never_folded(self):
        findings_store.add_many([weak_link(), {
            "text": "Front door is unlocked at night",
            "detail": "Unlocked since 23:10.",
            "fix": "Lock the front door.",
            "source": "check:sec.unlocked_night", "severity": "serious",
            "fixable": False, "entity_id": "lock.front_door"}])
        self.assertEqual(len(live()), 2)


if __name__ == "__main__":
    unittest.main()
