#!/usr/bin/env python3
"""A machine an automation starts on a threshold is idle while it is unmet.

Seen on a house (#558): the Resident and a card called a dehumidifier idle
or broken from its power and the room's humidity, while the automation
that switches it starts it only when ONE particular sensor reads above a
threshold — and that sensor was under it. Both were marked Wrong.

Before brAIn says an automation-driven machine is not running, it reads
the automations that start it: their numeric trigger, the sensor and the
threshold, and the sensor's value now. When every rule that starts it is
waiting on a reading that is on the wrong side of its bound, the claim is
held (`resident.not_due`), and `chore.dehumidifier` says nothing. When the
trigger sensor IS past the threshold and the machine is off, the finding
stands. The examples are invented: a cellar drier switched on by a stair
hygrometer while two other rooms read damper, and a second example the
report never mentioned — a bathroom extractor whose numeric CONDITION
does not hold.
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
import shadow  # noqa: E402
from checks import chores  # noqa: E402
from checks._util import House  # noqa: E402
from test_resident_loop import LoopCase  # noqa: E402

DRIER = "switch.cellar_drier"
DRIER_POWER = "sensor.cellar_drier_power"
STAIR = "sensor.stair_hygrometer"
CELLAR = "sensor.cellar_humidity"
UTILITY = "sensor.utility_humidity"
FAN = "fan.washroom_extractor"
WASHROOM = "sensor.washroom_humidity"

AUTOMATIONS = [
    {"id": "a", "alias": "Cellar drier on when the stairs are damp",
     "triggers": [{"trigger": "numeric_state", "entity_id": STAIR,
                   "above": 60}],
     "actions": [{"action": "switch.turn_on", "target": {"entity_id": DRIER}}]},
    {"id": "b", "alias": "Cellar drier off when dry",
     "triggers": [{"trigger": "numeric_state", "entity_id": STAIR,
                   "below": 50}],
     "actions": [{"action": "switch.turn_off",
                  "target": {"entity_id": DRIER}}]},
    {"id": "c", "alias": "Extractor after a shower",
     "trigger": [{"platform": "state", "entity_id": "binary_sensor.shower",
                  "to": "on"}],
     "condition": [{"condition": "numeric_state", "entity_id": WASHROOM,
                    "above": 70}],
     "action": [{"service": "fan.turn_on", "entity_id": FAN}]},
]


def snapshot():
    return {
        "states": {e: {"state": "0", "attributes": {}} for e in (
            DRIER, DRIER_POWER, STAIR, CELLAR, UTILITY, FAN, WASHROOM,
            "binary_sensor.shower")},
        "entities": [{"entity_id": DRIER, "device_id": "plug"},
                     {"entity_id": DRIER_POWER, "device_id": "plug"}],
        "devices": [{"id": "plug", "name": "Cellar plug"}],
        "automations": AUTOMATIONS,
    }


def drivers():
    snap = snapshot()
    house = House(snap)
    d = resident.drivers_of(snap["automations"], house)
    return d, resident.device_aliases(d, house)


def readings(**values):
    table = {STAIR: 55.0, CELLAR: 72.0, UTILITY: 68.0, WASHROOM: 50.0}
    table.update({k.replace("__", "."): v for k, v in values.items()})
    return table.get


def case(claim, *evidence, entity=""):
    return {"claim": claim, "text": claim, "entity_id": entity,
            "evidence": [{"entity": e, "value": v} for e, v in evidence]}


class TestTheBoundsAreRead(unittest.TestCase):
    def test_a_numeric_trigger_is_a_bound(self):
        trig, cond = shadow.bounds_of(AUTOMATIONS[0])
        self.assertEqual(trig, [{"entity": STAIR, "above": 60, "below": None}])
        self.assertEqual(cond, [])

    def test_any_other_trigger_means_no_trigger_bound(self):
        trig, cond = shadow.bounds_of(AUTOMATIONS[2])
        self.assertIsNone(trig)
        self.assertEqual(cond, [{"entity": WASHROOM, "above": 70,
                                 "below": None}])

    def test_only_a_starting_rule_counts(self):
        d, _ = drivers()
        starts = {r["alias"]: r["starts"] for r in d[DRIER]}
        self.assertTrue(starts["Cellar drier on when the stairs are damp"])
        self.assertFalse(starts["Cellar drier off when dry"])


class TestTheFloor(unittest.TestCase):
    def test_idle_while_its_trigger_sensor_is_under_the_threshold(self):
        d, aliases = drivers()
        why = resident.not_due(case(
            "The cellar drier has been idle all day although the cellar "
            "reads 72%", (DRIER_POWER, "1 W"), (CELLAR, "72")),
            d, readings(), aliases)
        self.assertIn("Cellar drier on when the stairs are damp", why)
        self.assertIn(STAIR, why)
        self.assertIn("55", why)

    def test_the_other_sensors_reading_higher_change_nothing(self):
        d, aliases = drivers()
        why = resident.not_due(case(
            "The cellar drier hasn't run while the utility room is at 68%",
            (UTILITY, "68"), entity=DRIER), d, readings(), aliases)
        self.assertTrue(why)

    def test_trigger_past_threshold_and_off_is_still_raised(self):
        d, aliases = drivers()
        self.assertEqual(resident.not_due(case(
            "The cellar drier has been idle all day", entity=DRIER),
            d, readings(sensor__stair_hygrometer=66.0), aliases), "")

    def test_the_runs_own_reading_past_the_bound_counts(self):
        d, aliases = drivers()
        self.assertEqual(resident.not_due(case(
            "The cellar drier didn't turn on when the stairs hit 64%",
            (STAIR, "64%"), entity=DRIER), d, readings(), aliases), "")

    def test_an_unknown_reading_never_holds(self):
        d, aliases = drivers()
        self.assertEqual(resident.not_due(case(
            "The cellar drier has been idle all day", entity=DRIER),
            d, lambda _e: None, aliases), "")

    def test_a_condition_that_does_not_hold_keeps_it_off(self):
        d, aliases = drivers()
        why = resident.not_due(case(
            "The washroom extractor never came on after the shower",
            entity=FAN), d, readings(), aliases)
        self.assertIn("Extractor after a shower", why)
        self.assertEqual(resident.not_due(case(
            "The washroom extractor never came on after the shower",
            entity=FAN), d, readings(sensor__washroom_humidity=78.0),
            aliases), "")

    def test_a_threshold_set_by_a_helper_is_read_now(self):
        auto = {"alias": "Drier above the helper",
                "triggers": [{"trigger": "numeric_state", "entity_id": STAIR,
                              "above": "input_number.drier_start"}],
                "actions": [{"action": "switch.turn_on",
                             "target": {"entity_id": DRIER}}]}
        snap = snapshot()
        snap["automations"] = [auto]
        d = resident.drivers_of(snap["automations"], House(snap))
        values = {STAIR: 55.0, "input_number.drier_start": 58.0}
        self.assertTrue(resident.not_due(case(
            "The cellar drier has been idle", entity=DRIER), d, values.get))
        values["input_number.drier_start"] = 50.0
        self.assertEqual(resident.not_due(case(
            "The cellar drier has been idle", entity=DRIER), d,
            values.get), "")

    def test_other_claims_are_not_this_floor_s(self):
        d, aliases = drivers()
        self.assertEqual(resident.not_due(case(
            "The cellar drier is drawing more power than usual",
            entity=DRIER), d, readings(), aliases), "")


class TestTheWordsForNotRunning(unittest.TestCase):
    def test_idle_and_standby_are_not_running(self):
        for said in ("The drier has been idle since noon",
                     "It sat idle all afternoon",
                     "The unit stopped running at 14:00",
                     "It drew only standby power for five hours",
                     "The plug is drawing no power",
                     "The dehumidifier may be broken"):
            self.assertTrue(resident._DID_NOT_RUN_RE.search(said), said)

    def test_everyday_sentences_are_not(self):
        for said in ("The rain stopped around noon",
                     "The car was idling in the drive",
                     "The dehumidifier is drawing more power than usual",
                     "The kitchen is busy every evening",
                     "The fan was turned off at 22:00",
                     "Somebody broke the glass on the porch light",
                     "The music stopped when the door opened",
                     "Power use was idle-time heavy on Sunday"):
            self.assertIsNone(resident._DID_NOT_RUN_RE.search(said), said)


class TestTheCheckReadsTheAutomationToo(unittest.TestCase):
    """`chore.dehumidifier`, whose plug an automation starts off a sensor
    in another room."""

    def snap(self, attic: str):
        from test_dehumidifier_stopped import RH, SWITCH, snap
        s = snap()
        s["states"]["sensor.attic_humidity"]["state"] = attic
        s["automations"] = [{
            "alias": "Basement plug on when the attic is damp",
            "triggers": [{"trigger": "numeric_state",
                          "entity_id": "sensor.attic_humidity", "above": 60}],
            "actions": [{"action": "switch.turn_on",
                         "target": {"entity_id": SWITCH}}]}]
        self.assertEqual(s["states"][RH]["state"], "70")
        return s

    def test_silent_while_its_trigger_is_under_the_threshold(self):
        from test_dehumidifier_stopped import NOW
        self.assertEqual(chores.dehumidifier(self.snap("40"), NOW), [])

    def test_raised_when_its_trigger_is_past_it(self):
        from test_dehumidifier_stopped import NOW
        self.assertEqual(len(chores.dehumidifier(self.snap("66"), NOW)), 1)


class TestTheInvestigationIsHeld(LoopCase):
    """The real `_resident_investigate` with the maps a checks pass
    leaves, and the bus moving the trigger sensor."""

    def setUp(self):
        super().setUp()
        srv = self.server
        self._trail = srv.decision_trail.TRAIL_FILE
        srv.decision_trail.TRAIL_FILE = str(Path(self.tmp.name)
                                            / "decisions.jsonl")
        snap = snapshot()
        snap["states"][STAIR]["state"] = "55"
        srv._DRIVEN_BY.clear()
        srv._DRIVEN_BY.update(resident.drivers_of(AUTOMATIONS, House(snap)))
        srv._note_live_readings(snap, srv._DRIVEN_BY)

    def tearDown(self):
        srv = self.server
        srv.decision_trail.TRAIL_FILE = self._trail
        srv._DRIVEN_BY.clear()
        srv._DRIVEN_ALIASES.clear()
        srv._LIVE_READINGS.clear()
        super().tearDown()

    def investigate(self):
        self.investigations.append({
            "ok": True, "error": "", "meta": {"session_id": "inv-w"},
            "text": json.dumps({
                "claim": "The cellar drier has been idle all day although "
                         "the cellar reads 72%",
                "detail": "Its plug drew 1 W since the morning.",
                "kind": "problem", "confidence": 0.8, "stakes": "medium",
                "fix": "Check the cellar drier.",
                "evidence": [{"entity": DRIER_POWER, "value": "1",
                              "when": "09:00"}],
                "actions": [], "escalate": False})})
        signal = {"kind": "state", "subject": DRIER_POWER, "salience": 0.6,
                  "text": "Cellar drier power low", "evidence": []}
        asyncio.run(self.server._resident_investigate(
            signal, time.time(), "normal"))
        return [r for r in self.server.findings_store._load()
                if r.get("source") == "resident"]

    def test_nothing_filed_while_the_trigger_is_under_its_threshold(self):
        self.assertEqual(self.investigate(), [])
        trail = Path(self.server.decision_trail.TRAIL_FILE).read_text()
        self.assertIn("Cellar drier on when the stairs are damp", trail)

    def test_filed_once_the_bus_moves_it_past(self):
        self.server._on_bus_event("state_changed", {
            "entity_id": STAIR, "new_state": {"state": "67"}})
        self.assertEqual(len(self.investigate()), 1)

    def test_the_run_is_shown_the_trigger_reading_now(self):
        rows = self.server._controlled_by_rows([DRIER_POWER])
        self.assertTrue(any(STAIR in r and "55" in r for r in rows), rows)


if __name__ == "__main__":
    unittest.main()
