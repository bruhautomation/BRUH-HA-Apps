#!/usr/bin/env python3
"""Before the Resident says how long something lasted or that it did not
run, it reads the history that would say so (#625, #580).

#625: a case said a dehumidifier did not run, or drew 0 W, without reading
the automation and set point that decide when it turns on. `not_due` read
the trigger sensor NOW; the claim is about the day behind it. The day is
now read: the claim is filed only when a rule that starts the machine was
due (its sensor past the threshold, its conditions holding) at a moment
the machine was off. "0 W" is the not-running claim in a power reading's
words, and a claim about a plug's own power sensor is a claim about the
plug.

#580: a case said a garage door had been open 70 minutes; it had opened
and closed eight minutes apart. A stated duration is now read against the
door's last open and close: a door that has closed since is not filed as
open, and one still open is filed with the duration its history says.

Made-up entities: a loft dehumidifier on a landing hygrometer, a second
example the report never named — a greenhouse irrigation pump started on
soil moisture — a garage door and a side gate.
"""

import asyncio
import datetime as dt
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
from test_resident_loop import LoopCase  # noqa: E402

NOW = 1_800_000_000.0
H = 3600.0
DRY = "switch.loft_dehumidifier"
DRY_POWER = "sensor.loft_dehumidifier_power"
LANDING = "sensor.landing_hygrometer"
PUMP = "switch.greenhouse_pump"
SOIL = "sensor.greenhouse_soil_moisture"
GARAGE = "cover.garage_door"
GATE = "binary_sensor.side_gate"

AUTOMATIONS = [
    {"id": "d", "alias": "Loft dehumidifier on when the landing is damp",
     "triggers": [{"trigger": "numeric_state", "entity_id": LANDING,
                   "above": 65}],
     "actions": [{"action": "switch.turn_on", "target": {"entity_id": DRY}}]},
    {"id": "p", "alias": "Water the greenhouse when the soil is dry",
     "triggers": [{"trigger": "numeric_state", "entity_id": SOIL,
                   "below": 30}],
     "actions": [{"action": "switch.turn_on", "target": {"entity_id": PUMP}}]},
]


def maps():
    snap = {"states": {e: {"state": "0", "attributes": {}}
                       for e in (DRY, DRY_POWER, LANDING, PUMP, SOIL)},
            "entities": [{"entity_id": DRY, "device_id": "plug"},
                         {"entity_id": DRY_POWER, "device_id": "plug"}],
            "devices": [{"id": "plug", "name": "Loft plug"}],
            "automations": AUTOMATIONS}
    house = House(snap)
    drivers = resident.drivers_of(AUTOMATIONS, house)
    return drivers, resident.device_aliases(drivers, house)


def iso(ago_h):
    return dt.datetime.fromtimestamp(NOW - ago_h * H, dt.timezone.utc).isoformat()


def series(*steps):
    return [[iso(ago), word] for ago, word in steps]


def case(claim, *evidence, entity=""):
    return {"claim": claim, "text": claim, "entity_id": entity, "detail": "",
            "evidence": [{"entity": e, "value": v} for e, v in evidence]}


DID_NOT_RUN = case("The loft dehumidifier did not run today",
                   (DRY_POWER, "0 W"), entity=DRY)
DREW_ZERO = case("The loft dehumidifier drew 0 W all day", (DRY_POWER, "0"),
                 entity=DRY_POWER)


class TestADidNotRunClaimReadsWhatStartsIt(unittest.TestCase):
    def setUp(self):
        self.drivers, self.aliases = maps()

    def never(self, c, history):
        return resident.never_due(c, self.drivers, history, self.aliases)

    def test_it_asks_for_the_machine_and_its_trigger_sensor(self):
        self.assertEqual(resident.history_wanted(DID_NOT_RUN, self.drivers,
                                                 self.aliases), [DRY, LANDING])
        self.assertEqual(resident.history_wanted(DREW_ZERO, self.drivers,
                                                 self.aliases), [DRY, LANDING])

    def test_condition_never_met_files_nothing(self):
        history = {LANDING: series((20, "58"), (12, "61"), (3, "63")),
                   DRY: series((24, "off"))}
        for c in (DID_NOT_RUN, DREW_ZERO):
            why = self.never(c, history)
            self.assertIn("Loft dehumidifier on when the landing is damp", why)
            self.assertIn("63", why)

    def test_condition_met_while_it_stayed_off_is_filed(self):
        history = {LANDING: series((20, "58"), (12, "71"), (3, "63")),
                   DRY: series((24, "off"))}
        for c in (DID_NOT_RUN, DREW_ZERO):
            self.assertEqual(self.never(c, history), "")

    def test_condition_met_and_it_was_on_is_not_did_not_run(self):
        history = {LANDING: series((20, "58"), (12, "71"), (3, "63")),
                   DRY: series((24, "off"), (12.1, "on"), (6, "off"))}
        self.assertIn("was on each time", self.never(DID_NOT_RUN, history))

    def test_a_below_threshold_rule_is_read_the_same_way(self):
        pump = case("The greenhouse pump hasn't run since yesterday",
                    entity=PUMP)
        dry_soil = {SOIL: series((20, "40"), (8, "24")), PUMP: series((24, "off"))}
        moist = {SOIL: series((20, "40"), (8, "34")), PUMP: series((24, "off"))}
        self.assertEqual(self.never(pump, dry_soil), "")
        self.assertIn("never got there", self.never(pump, moist))

    def test_unread_history_refuses_nothing(self):
        self.assertEqual(self.never(DID_NOT_RUN, None), "")
        self.assertEqual(self.never(DID_NOT_RUN, {DRY: series((24, "off"))}), "")

    def test_zero_watts_is_the_not_running_claim(self):
        for said in ("It drew 0 W all afternoon", "The plug reads 0W",
                     "stuck at 0 watts since noon", "drawing zero watts"):
            self.assertTrue(resident._DID_NOT_RUN_RE.search(said), said)
        for said in ("It drew 10 W", "The heater reads 1500 W",
                     "Solar was at 0 kWh before sunrise"):
            self.assertIsNone(resident._DID_NOT_RUN_RE.search(said), said)

    def test_the_plugs_own_power_sensor_is_not_a_reading_beside_it(self):
        c = case("The loft dehumidifier drew 0 W", (DRY_POWER, "0"),
                 entity=DRY_POWER)
        self.assertEqual(resident.ungrounded_did_not_run(
            c, self.drivers, self.aliases), "")
        beside = case("The loft dehumidifier drew 0 W although "
                      "sensor.loft_humidity read 80%",
                      (DRY_POWER, "0"), ("sensor.loft_humidity", "80"),
                      entity=DRY_POWER)
        self.assertIn(LANDING, resident.ungrounded_did_not_run(
            beside, self.drivers, self.aliases))


class TestAStatedOpenDurationIsReadAgainstTheHistory(unittest.TestCase):
    GARAGE_CASE = case("The garage door has been open for 70 minutes",
                       (GARAGE, "open"), entity=GARAGE)

    def test_a_door_that_opened_and_closed_is_not_filed_as_open(self):
        history = {GARAGE: series((3, "closed"), (70 / 60, "open"),
                                  (62 / 60, "closed"))}
        verdict, _c, why = resident.open_duration(self.GARAGE_CASE, history, NOW)
        self.assertEqual(verdict, "refuse")
        self.assertIn("8 minutes later", why)

    def test_a_door_still_open_gets_the_history_s_duration(self):
        history = {GARAGE: series((3, "closed"), (25 / 60, "open"))}
        verdict, fixed, why = resident.open_duration(self.GARAGE_CASE,
                                                     history, NOW)
        self.assertEqual(verdict, "correct")
        self.assertIn("open for 25 minutes", fixed["claim"])
        self.assertNotIn("70", fixed["claim"])
        self.assertIn("25 minutes", why)

    def test_a_duration_the_history_agrees_with_is_left_alone(self):
        history = {GARAGE: series((3, "closed"), (72 / 60, "open"))}
        verdict, c, _why = resident.open_duration(self.GARAGE_CASE, history, NOW)
        self.assertEqual(verdict, "ok")
        self.assertIs(c, self.GARAGE_CASE)

    def test_a_gate_sensor_in_hours(self):
        gate = case("The side gate was left open 2 hours", (GATE, "on"))
        history = {GATE: series((5, "off"), (0.25, "on"), (0.1, "off"))}
        verdict, _c, why = resident.open_duration(gate, history, NOW)
        self.assertEqual(verdict, "refuse")
        self.assertIn(GATE, why)

    def test_unread_history_and_other_claims_pass(self):
        self.assertEqual(resident.open_duration(self.GARAGE_CASE, None, NOW)[0],
                         "ok")
        other = case("The garage light was on for 70 minutes", entity="light.garage")
        self.assertIsNone(resident.stated_open(other))


class TestTheInvestigationReadsTheHistory(LoopCase):
    """The real `_resident_investigate`, with the history it reads stubbed."""

    def setUp(self):
        super().setUp()
        srv = self.server
        self._trail = srv.decision_trail.TRAIL_FILE
        srv.decision_trail.TRAIL_FILE = str(Path(self.tmp.name)
                                            / "decisions.jsonl")
        drivers, aliases = maps()
        srv._DRIVEN_BY.clear()
        srv._DRIVEN_BY.update(drivers)
        srv._DRIVEN_ALIASES.clear()
        srv._DRIVEN_ALIASES.update(aliases)
        self.history: dict = {}
        self._history = srv._recent_history
        self.addCleanup(setattr, srv, "_recent_history", self._history)

        async def fake(ids, hours, now=None):
            return {e: self.history[e] for e in ids if e in self.history}
        srv._recent_history = fake

    def tearDown(self):
        srv = self.server
        srv.decision_trail.TRAIL_FILE = self._trail
        srv._DRIVEN_BY.clear()
        srv._DRIVEN_ALIASES.clear()
        super().tearDown()

    def investigate(self, claim, evidence, subject):
        now = time.time()
        self.investigations.append({
            "ok": True, "error": "", "meta": {"session_id": "inv-h"},
            "text": json.dumps({
                "claim": claim, "detail": "Seen in its history today.",
                "kind": "problem", "confidence": 0.8, "stakes": "medium",
                "fix": "Look at it when you are next home.",
                "evidence": evidence, "actions": [], "escalate": False})})
        signal = {"kind": "state", "subject": subject, "salience": 0.6,
                  "text": claim, "evidence": []}
        asyncio.run(self.server._resident_investigate(signal, now, "normal"))
        return [r for r in self.server.findings_store._load()
                if r.get("source") == "resident"]

    def rel(self, *steps):
        now = time.time()
        return [[dt.datetime.fromtimestamp(now - ago * H, dt.timezone.utc)
                 .isoformat(), word] for ago, word in steps]

    def test_did_not_run_with_its_trigger_never_met_is_not_filed(self):
        self.history = {LANDING: self.rel((20, "58"), (3, "62")),
                        DRY: self.rel((24, "off"))}
        rows = self.investigate("The loft dehumidifier drew 0 W all day",
                                [{"entity": DRY_POWER, "value": "0 W",
                                  "when": "09:00"}], DRY_POWER)
        self.assertEqual(rows, [])
        trail = Path(self.server.decision_trail.TRAIL_FILE).read_text()
        self.assertIn("landing is damp", trail)

    def test_did_not_run_with_its_trigger_met_is_filed(self):
        self.history = {LANDING: self.rel((20, "58"), (10, "72")),
                        DRY: self.rel((24, "off"))}
        rows = self.investigate("The loft dehumidifier drew 0 W all day",
                                [{"entity": DRY_POWER, "value": "0 W",
                                  "when": "09:00"}], DRY_POWER)
        self.assertEqual(len(rows), 1)

    def test_a_door_that_closed_is_not_filed_as_open_for_an_hour(self):
        self.history = {GARAGE: self.rel((3, "closed"), (70 / 60, "open"),
                                         (62 / 60, "closed"))}
        rows = self.investigate("The garage door has been open for 70 minutes",
                                [{"entity": GARAGE, "value": "open",
                                  "when": "14:02"}], GARAGE)
        self.assertEqual(rows, [])

    def test_a_door_still_open_is_filed_with_the_right_duration(self):
        self.history = {GARAGE: self.rel((3, "closed"), (25 / 60, "open"))}
        rows = self.investigate("The garage door has been open for 70 minutes",
                                [{"entity": GARAGE, "value": "open",
                                  "when": "14:02"}], GARAGE)
        self.assertEqual(len(rows), 1)
        said = rows[0].get("claim") or rows[0].get("text")
        self.assertIn("25 minutes", said)
        self.assertNotIn("70 minutes", said)


if __name__ == "__main__":
    unittest.main()
