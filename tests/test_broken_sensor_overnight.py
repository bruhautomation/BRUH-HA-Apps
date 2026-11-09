#!/usr/bin/env python3
"""A sensor the owner called broken is not evidence overnight either (#788).

"This sensor is broken, ignore it" said under a Resident report stood the
Resident's look and investigation down (`corrections.broken_answer`,
`tests/test_broken_sensor_answer.py`), and the overnight check went on
filing new reports drawn from the same pressure sensor. It reads the same
ONE helper now: a cause whose subject the owner called broken is not filed,
and each one dropped writes a decision-trail entry. The helper's floors come
first, so the same words said about a leak sensor drop nothing; and only the
wording that already finishes a device counts, so "ignore this sensor for a
week" drops nothing either.
"""

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import sre  # noqa: E402
from test_sre import NOW, PassCase, collected, iso  # noqa: E402

BROKEN = "This sensor is broken, please ignore it."


def house():
    """Two struggling Zigbee end devices: the pump's pressure sensor and the
    basement leak sensor."""
    return collected(
        log=[],
        automations=[],
        zha=[{"ieee": "dd:dd:dd:dd:dd:dd:dd:04", "name": "Pump pressure",
              "device_type": "EndDevice", "available": True, "lqi": 20,
              "last_seen": iso(9 * 3600), "device_reg_id": "dev-pump"},
             {"ieee": "ee:ee:ee:ee:ee:ee:ee:05", "name": "Basement leak",
              "device_type": "EndDevice", "available": True, "lqi": 20,
              "last_seen": iso(9 * 3600), "device_reg_id": "dev-leak"}],
        entities=[{"entity_id": "sensor.pump_pressure", "device_id": "dev-pump",
                   "platform": "zha"},
                  {"entity_id": "binary_sensor.basement_leak",
                   "device_id": "dev-leak", "platform": "zha"}],
        states={"sensor.pump_pressure": {
                    "state": "-3", "attributes": {"device_class": "pressure"},
                    "last_changed": iso(60)},
                "binary_sensor.basement_leak": {
                    "state": "off", "attributes": {"device_class": "moisture"},
                    "last_changed": iso(60)}})


class TestTheOvernightPass(PassCase):
    def setUp(self):
        super().setUp()
        import decision_trail
        self.trail = decision_trail
        old = decision_trail.TRAIL_FILE
        decision_trail.TRAIL_FILE = str(Path(self.tmp.name) / "decisions.jsonl")
        decision_trail._RECENT.clear()
        self.addCleanup(setattr, decision_trail, "TRAIL_FILE", old)
        corrections = self.server.corrections
        saved = corrections.known_faulty
        self.addCleanup(setattr, corrections, "known_faulty", saved)
        self.faulty = {}
        corrections.known_faulty = lambda now=None: dict(self.faulty)
        self.collected = house()
        dig = sre.digest(self.collected, NOW)
        self.pump = next(r["id"] for r in dig["records"]
                         if r["id"].endswith(":04"))
        self.leak = next(r["id"] for r in dig["records"]
                         if r["id"].endswith(":05"))

    def night(self):
        self.reply([
            {"title": "The pump pressure sensor reads below zero",
             "records": [self.pump], "entity_id": "sensor.pump_pressure",
             "detail": "It reads -3 and its Zigbee link is weak.",
             "fix": "Move it closer to a router."},
            {"title": "The basement leak sensor's link is weak",
             "records": [self.leak], "entity_id": "binary_sensor.basement_leak",
             "detail": "It has not been heard from for nine hours.",
             "fix": "Move it closer to a router."}])
        self.run_pass()
        return {r["entity_id"] for r in self.rows()}

    def test_before_the_answer_both_are_filed(self):
        self.assertEqual(self.night(), {"sensor.pump_pressure",
                                        "binary_sensor.basement_leak"})

    def test_a_pressure_sensor_called_broken_gets_no_new_report(self):
        self.faulty = {"sensor.pump_pressure": BROKEN,
                       "binary_sensor.basement_leak": BROKEN}
        self.assertEqual(self.night(), {"binary_sensor.basement_leak"})
        rows, readable = self.trail.read()
        self.assertTrue(readable)
        said = [r for r in rows if r.get("subject") == "sensor.pump_pressure"]
        self.assertEqual(len(said), 1)
        self.assertEqual(said[0]["kind"], "exception")
        self.assertFalse([r for r in rows
                          if r.get("subject") == "binary_sensor.basement_leak"])

    def test_words_that_are_not_broken_drop_nothing(self):
        self.faulty = {"sensor.pump_pressure": "Ignore this sensor. For a week."}
        self.assertIn("sensor.pump_pressure", self.night())


if __name__ == "__main__":
    unittest.main()
