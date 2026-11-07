#!/usr/bin/env python3
"""A sensor the owner called broken is not reasoned about, by anything.

A house answered "this sensor is broken, please ignore it" and the next
passes kept reading it: the impossible-readings check and the Resident
raised its odd readings again, and other findings cited them as evidence
of a real fault. `corrections.known_faulty` already told the Resident's
investigation gate (`resident.faulty_case`) and the device checks
(`House.answered_off` over `DEVICE_FINISHED`), but not the band check that
judges the same readings, not the first look's live signals, and not the
door every other producer files through (`triage.gate`).

Driven with sensors the report never named: a dishwasher's water probe
whose band check still filed, a pump's pressure sensor cited as evidence by
a row about the pump, and a live signal about a humidity sensor.
"""

import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "brain" / "panel"))
sys.path.insert(0, str(TESTS_DIR))

import corrections  # noqa: E402
import resident  # noqa: E402
import triage  # noqa: E402
from checks import baseline as band  # noqa: E402
from test_running_machine_readings import NOW, WATER, dishwasher  # noqa: E402

BROKEN = "This sensor is broken, please ignore it"
PRESSURE = "sensor.pump_pressure"


class TestTheBandCheckLeavesABrokenSensorAlone(unittest.TestCase):
    def test_a_reading_from_a_sensor_called_broken_files_nothing(self):
        snap = dishwasher("finished")
        self.assertEqual([r["entity_id"] for r in band.unusual(snap, NOW)],
                         [WATER])
        snap = dishwasher("finished")
        snap["faulty"] = {WATER: BROKEN}
        self.assertEqual(band.unusual(snap, NOW), [])


class TestTheDoorDropsRowsThatRestOnIt(unittest.TestCase):
    def setUp(self):
        old = corrections.known_faulty
        corrections.known_faulty = lambda now=None: {PRESSURE: BROKEN}
        self.addCleanup(setattr, corrections, "known_faulty", old)

    def gate(self, rows):
        return triage.gate(rows, muted=set(), held={})

    def test_a_row_about_it_is_not_filed(self):
        self.assertEqual(self.gate([{
            "text": "Pump pressure is reading far outside its usual range",
            "source": "check:base.unusual", "severity": "info",
            "entity_id": PRESSURE}]), [])

    def test_a_row_citing_it_as_evidence_is_not_filed(self):
        self.assertEqual(self.gate([{
            "text": "The pump is losing pressure",
            "source": "insights", "severity": "warning",
            "entity_id": "switch.pump",
            "evidence": [{"entity": PRESSURE, "value": "-3"}]}]), [])

    def test_a_row_about_something_else_still_is(self):
        rows = self.gate([{"text": "The pump ran all night",
                           "source": "insights", "severity": "warning",
                           "entity_id": "switch.pump",
                           "evidence": [{"entity": "switch.pump",
                                         "value": "on"}]}])
        self.assertEqual(len(rows), 1)

    def test_a_safety_row_is_never_dropped(self):
        rows = self.gate([{"text": "Water on the floor by the pump",
                           "source": "safety", "severity": "critical",
                           "entity_id": PRESSURE}])
        self.assertEqual(len(rows), 1)


class TestTheFirstLookIsNotHandedItsReadings(unittest.TestCase):
    def test_a_live_signal_about_it_is_let_go(self):
        faulty = {"sensor.bathroom_humidity": BROKEN}
        about = {"kind": "state", "subject": "sensor.bathroom_humidity",
                 "evidence": []}
        citing = {"kind": "state", "subject": "fan.bathroom",
                  "evidence": [{"entity": "sensor.bathroom_humidity"}]}
        other = {"kind": "state", "subject": "light.hall", "evidence": []}
        leak = {"kind": "state", "subject": "sensor.bathroom_humidity",
                "evidence": [], "safety": True}
        kept, let_go = resident.without_faulty(
            [about, citing, other, leak], faulty)
        self.assertEqual(kept, [other, leak])
        self.assertEqual(let_go, [about, citing])


class TestIgnoreThisSensorIsTheSameAnswer(unittest.TestCase):
    """Only the plain instruction about the sensor itself — unnegated, with
    no time limit, no condition and no explanation after it — reads as the
    sensor finished with. `known_faulty` re-reads stored rule text, so a
    loose match here turns old rules into "broken" with nobody pressing
    anything."""

    def test_said_as_ignore(self):
        for said in ("please ignore this sensor", "Please ignore this sensor.",
                     "ignore that probe, it's broken",
                     "Ignore this thermometer for good"):
            self.assertTrue(corrections.gone_for_good(said), said)

    def test_negated_timed_or_about_one_reading_is_not(self):
        for said in ("don't ignore this sensor, it matters",
                     "never ignore this sensor",
                     "do not ignore the smoke sensor",
                     "ignore this sensor until tomorrow",
                     "ignore the sensor for a week",
                     "ignore this reading, it spikes on the hour",
                     "ignore the reading just this once",
                     "ignore this sensor, it's the cat"):
            self.assertFalse(corrections.gone_for_good(said), said)

    def test_everyday_sentences_are_not(self):
        for said in ("ignore it, it's fine", "you can ignore this",
                     "ignore the alert, we were cooking",
                     "I ignore this sensor in summer",
                     "it's normal, ignore",
                     "ignore the sensor when the window is open",
                     "ignore this sensor while the printer is printing",
                     "ignore the readings when the oven is on",
                     "ignore this sensor today",
                     "ignore this sensor for now",
                     "please don't ignore that probe",
                     "the sensor ignores the draught",
                     "that's normal for this sensor"):
            self.assertFalse(corrections.gone_for_good(said), said)

if __name__ == "__main__":
    unittest.main()
