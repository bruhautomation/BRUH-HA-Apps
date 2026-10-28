#!/usr/bin/env python3
"""Before brAIn says a device did not run, it reads what runs it.

The Resident filed "the dehumidifier hasn't run" from state history alone,
comparing the dehumidifier with whatever humidity reading it found, while
the automation that drives it triggers on one specific sensor — not the one
the claim named. A claim that an actuator did not run when it should have
is only grounded if the reading it compares the actuator with is something
the actuator's own automations read: a trigger or a condition. Otherwise
the claim is about a rule the house does not have, and no case is filed.

This is a deterministic gate in code (`resident.ungrounded_did_not_run`,
over `resident.drivers_of` built from the checks snapshot's automations),
applied to every investigation's case after it is parsed — never only a
line in the prompt. The second example is one the report never named: a
bathroom fan driven by the bathroom's humidity, faulted against the hall's.
"""

import asyncio
import json
import sys
import time
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "brain" / "panel"))
sys.path.insert(0, str(TESTS_DIR))

import resident  # noqa: E402
from checks._util import House  # noqa: E402
from test_house_checks import house  # noqa: E402
from test_resident_loop import LoopCase  # noqa: E402

DEHUMIDIFIER = "switch.basement_dehumidifier"
FAN = "fan.bathroom_extractor"

AUTOMATIONS = [
    {"id": "1", "alias": "Dehumidifier on when the crawl space is damp",
     "triggers": [{"trigger": "numeric_state",
                   "entity_id": "sensor.crawl_space_humidity", "above": 65}],
     "actions": [{"action": "switch.turn_on",
                  "target": {"entity_id": DEHUMIDIFIER}}]},
    {"id": "2", "alias": "Bathroom fan after a shower",
     "trigger": [{"platform": "state", "entity_id": "binary_sensor.shower"}],
     "condition": [{"condition": "numeric_state",
                    "entity_id": "sensor.bathroom_humidity", "above": 70}],
     "action": [{"service": "fan.turn_on", "entity_id": FAN}]},
]


def drivers():
    snap = house()
    for eid in (DEHUMIDIFIER, FAN, "sensor.crawl_space_humidity",
                "sensor.basement_humidity", "sensor.bathroom_humidity",
                "sensor.hall_humidity", "binary_sensor.shower"):
        snap["states"][eid] = {"state": "50", "attributes": {}}
    snap["automations"] = AUTOMATIONS
    return resident.drivers_of(snap["automations"], House(snap))


def case(claim, *readings, detail=""):
    return {"claim": claim, "text": claim, "detail": detail,
            "evidence": [{"entity": e, "value": "x"} for e in readings]}


class TestTheDriversAreRead(unittest.TestCase):
    def test_triggers_and_conditions_per_actuator(self):
        d = drivers()
        self.assertEqual(d[DEHUMIDIFIER][0]["reads"],
                         ["sensor.crawl_space_humidity"])
        self.assertEqual(sorted(d[FAN][0]["reads"]),
                         ["binary_sensor.shower", "sensor.bathroom_humidity"])


class TestTheGate(unittest.TestCase):
    def test_the_dehumidifier_against_a_sensor_its_automation_never_reads(self):
        why = resident.ungrounded_did_not_run(case(
            "The basement dehumidifier hasn't run although humidity is 72%",
            DEHUMIDIFIER, "sensor.basement_humidity"), drivers())
        self.assertIn("Dehumidifier on when the crawl space is damp", why)
        self.assertIn("sensor.basement_humidity", why)

    def test_a_fan_faulted_against_the_hall(self):
        why = resident.ungrounded_did_not_run(case(
            "The bathroom extractor didn't turn on while the hall read 80%",
            FAN, "sensor.hall_humidity"), drivers())
        self.assertTrue(why)

    def test_the_sensor_it_does_read_is_a_grounded_claim(self):
        self.assertEqual(resident.ungrounded_did_not_run(case(
            "The basement dehumidifier hasn't run although the crawl space "
            "is at 72%", DEHUMIDIFIER, "sensor.crawl_space_humidity"),
            drivers()), "")
        # A condition counts as much as a trigger.
        self.assertEqual(resident.ungrounded_did_not_run(case(
            "The bathroom extractor never came on after the shower",
            FAN, "sensor.bathroom_humidity"), drivers()), "")

    def test_a_reading_named_only_in_the_words_counts(self):
        why = resident.ungrounded_did_not_run(case(
            "The dehumidifier should have run: sensor.basement_humidity "
            "has been above 70% all day", DEHUMIDIFIER), drivers())
        self.assertTrue(why)

    def test_other_claims_are_not_this_gate_s(self):
        d = drivers()
        self.assertEqual(resident.ungrounded_did_not_run(case(
            "The dehumidifier is drawing more power than usual",
            DEHUMIDIFIER, "sensor.basement_humidity"), d), "")
        # Nothing drives it: nothing to read, nothing refused.
        self.assertEqual(resident.ungrounded_did_not_run(case(
            "The kitchen light didn't turn on",
            "light.kitchen", "sensor.basement_humidity"), d), "")
        # No reading compared: the claim is about the device alone.
        self.assertEqual(resident.ungrounded_did_not_run(case(
            "The dehumidifier hasn't run in three days", DEHUMIDIFIER), d), "")


class TestTheInvestigationIsGated(LoopCase):
    """The real `_resident_investigate`, a live signal, the CLI stubbed."""

    def setUp(self):
        super().setUp()
        self._driven = dict(self.server._DRIVEN_BY)
        self._trail = self.server.decision_trail.TRAIL_FILE
        self.server.decision_trail.TRAIL_FILE = str(
            Path(self.tmp.name)
            / "decisions.jsonl")
        self.server._DRIVEN_BY.clear()
        self.server._DRIVEN_BY.update(drivers())

    def tearDown(self):
        self.server.decision_trail.TRAIL_FILE = self._trail
        self.server._DRIVEN_BY.clear()
        self.server._DRIVEN_BY.update(self._driven)
        super().tearDown()

    def investigate(self, reading):
        self.investigations.append({
            "ok": True, "error": "", "meta": {"session_id": "inv-d"},
            "text": json.dumps({
                "claim": "The basement dehumidifier hasn't run although "
                         "humidity is at 72%",
                "detail": "It stayed off all afternoon.",
                "kind": "problem", "confidence": 0.8, "stakes": "medium",
                "fix": "Check the dehumidifier.",
                "evidence": [{"entity": DEHUMIDIFIER, "value": "off",
                              "when": "14:00"},
                             {"entity": reading, "value": "72",
                              "when": "14:00"}],
                "actions": [], "escalate": False})})
        signal = {"kind": "state", "subject": DEHUMIDIFIER, "salience": 0.6,
                  "text": "Basement dehumidifier stayed off", "evidence": []}
        asyncio.run(self.server._resident_investigate(
            signal, time.time(), "normal"))
        return [r for r in self.server.findings_store._load()
                if r.get("source") == "resident"]

    def test_no_case_against_a_sensor_the_automation_never_reads(self):
        self.assertEqual(self.investigate("sensor.basement_humidity"), [])
        trail = Path(self.server.decision_trail.TRAIL_FILE).read_text()
        self.assertIn("Dehumidifier on when the crawl space is damp", trail)

    def test_a_case_against_its_own_trigger_is_filed(self):
        self.assertEqual(len(self.investigate("sensor.crawl_space_humidity")),
                         1)


if __name__ == "__main__":
    unittest.main()
