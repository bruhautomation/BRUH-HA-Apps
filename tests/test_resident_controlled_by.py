#!/usr/bin/env python3
"""A device is judged by what switches it, not by a sensor in its room.

Seen on a house: an investigation said a dehumidifier "hasn't run even when
the room humidity hit 73%", reading a room sensor — while the automation
that switches the unit watches a different one, a thermostat's humidity,
and turns it on above 60%. The investigation had the tools to look that
up and nothing told it to; and the panel, which reads every automation on
each checks pass, handed it only "what uses this device", not what
SWITCHES it.

So the panel builds, from the snapshot the pass already fetched, which
automations act on each entity and what they watch (`_controlled_by_map`),
the investigation is handed those rows for the entities it is about, and
the contract says to judge the device by them.
"""

import asyncio
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "brain"
                       / "panel"))

import resident  # noqa: E402
from test_resident_loop import LoopCase, case_reply, reply  # noqa: E402

UNIT = "switch.cellar_dehumidifier"
STAT = "sensor.landing_thermostat_humidity"
ROOM = "sensor.cellar_humidity"


def snapshot() -> dict:
    return {
        "states": {
            UNIT: {"entity_id": UNIT, "state": "off",
                   "attributes": {"friendly_name": "Cellar dehumidifier"}},
            STAT: {"entity_id": STAT, "state": "58",
                   "attributes": {"friendly_name":
                                  "Landing thermostat humidity"}},
            ROOM: {"entity_id": ROOM, "state": "73",
                   "attributes": {"friendly_name": "Cellar humidity"}},
        },
        "automations": [{
            "id": "1", "alias": "Dehumidifier on when damp",
            "triggers": [{"trigger": "numeric_state", "entity_id": STAT,
                          "above": 60}],
            "actions": [{"action": "switch.turn_on",
                         "target": {"entity_id": UNIT}}]}],
        "services": [],
    }


class TestThePanelKnowsWhatSwitchesADevice(LoopCase):
    def test_the_map_names_the_controlling_sensor_and_threshold(self):
        srv = self.server
        rows = srv._controlled_by_map(snapshot()).get(UNIT) or []
        self.assertEqual(len(rows), 1, rows)
        self.assertIn("Dehumidifier on when damp", rows[0])
        self.assertIn("Landing thermostat humidity", rows[0])
        self.assertIn("above 60", rows[0])
        self.assertNotIn("Cellar humidity", rows[0])

    def test_a_sensor_the_automation_only_watches_is_not_switched(self):
        self.assertNotIn(STAT, self.server._controlled_by_map(snapshot()))

    def test_the_investigation_is_handed_what_switches_it(self):
        srv = self.server
        srv._CONTROLLED_BY.clear()
        srv._CONTROLLED_BY.update(srv._controlled_by_map(snapshot()))
        try:
            srv.RESIDENT_PENDING.append(srv.signals.make(
                "state", UNIT, now=time.time(), source="bus",
                text="the cellar dehumidifier has stayed off all day",
                evidence=[srv.signals.evidence_row(UNIT, "off", time.time())]))
            self.looks.append(reply([{"id": 1, "verdict": "investigate",
                                      "why": "it should have run"}]))
            self.investigations.append(case_reply())
            asyncio.run(srv._resident_tick(time.time()))
            self.assertTrue(self.analyst_calls, "no investigation ran")
            prompt = self.analyst_calls[0]["prompt"]
            self.assertIn("WHAT SWITCHES THESE DEVICES", prompt)
            self.assertIn("Landing thermostat humidity", prompt)
        finally:
            srv._CONTROLLED_BY.clear()


class TestTheContractSaysToCompareAgainstIt(unittest.TestCase):
    def test_the_contract_names_the_lookup(self):
        text = " ".join(resident.INVESTIGATE_SYSTEM.split())
        self.assertIn("what switches it", text)
        self.assertIn("not a sensor that only shares its room", text)

    def test_the_prompt_renders_the_rows(self):
        out = resident.investigate_prompt(
            {"kind": "state", "subject": UNIT}, controlled_by=[
                f"{UNIT}: switched on by automation “x”"])
        self.assertIn("WHAT SWITCHES THESE DEVICES", out)


if __name__ == "__main__":
    unittest.main()
