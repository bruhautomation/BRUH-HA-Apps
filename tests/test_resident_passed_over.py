#!/usr/bin/env python3
"""A subject the household keeps saying mattered is not passed over again.

A house's outcome stream counted a freezer compressor's switch passed over
twenty times as "switched off as designed" while its probe read 47 °F, and
two Bluetooth sensors passed over as "only a signal-strength note" although
an auto-lock reads one of them — every one overruled by the household. The
record of those calls existed (`outcomes.tallies`, the nightly reflect's
`louder` candidate) and the look was never made to act on it.

The fix is a floor and a prompt, never a rule about one subject:

  * `outcomes.overruled` reads the graded log with `candidates`' own louder
    arithmetic, `resident.parse_first_look(floors=)` floors those subjects
    at `investigate` after the reply, and the look is shown them;
  * the look is shown what switches a device and what that reads now, and
    told an automation running is not the thing it keeps being fine;
  * a device's other entities carry what uses it (`_used_by_map`).
"""
from __future__ import annotations

import sys
import time
import unittest
import unittest.mock
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import outcomes  # noqa: E402
import resident  # noqa: E402
import signals  # noqa: E402
from test_resident_loop import LoopCase, case_reply, reply  # noqa: E402


def passed(subject, outcome, at, *, kind="state", source="eventbus"):
    """A dismissed look about ``subject``, graded ``outcome``."""
    agree = {"wrong": True, "stood": None}.get(outcome, False)
    return {"id": f"{subject}-{at}", "item": f"{subject}-{at}",
            "stage": "look", "class": "dismissed", "verdict": "ignore",
            "outcome": outcome, "agree": agree, "subject": subject,
            "entity": subject, "kind": kind, "source": source, "flags": [],
            "ended_at": at + 50 if outcome != "stood" else 0, "note": "",
            "why": "switched off as designed", "at": at}


def raised(subject, outcome, at):
    return {"id": f"{subject}-r{at}", "item": f"{subject}-r{at}",
            "stage": "look", "class": "surfaced", "verdict": "investigate",
            "outcome": outcome,
            "agree": {"confirmed": True, "wrong": False}.get(outcome),
            "subject": subject, "entity": subject, "kind": "state",
            "source": "eventbus", "flags": [], "ended_at": at + 50,
            "note": "", "why": "", "at": at}


FREEZER = "switch.freezer_compressor"
TILT = "binary_sensor.garage_door_tilt"


class TestTheRecord(unittest.TestCase):
    def test_a_subject_overruled_every_time_is_on_the_record(self):
        its = [passed(FREEZER, "missed", 1000 + i * 100) for i in range(20)]
        record = outcomes.overruled(its)
        self.assertIn(FREEZER, record)
        self.assertIn("20 of 20", record[FREEZER])

    def test_a_second_example_put_back_twice_in_three(self):
        """A garage tilt sensor the household pulled back out twice."""
        its = [passed(TILT, "put_back", 1000), passed(TILT, "stood", 2000),
               passed(TILT, "put_back", 3000)]
        self.assertIn(TILT, outcomes.overruled(its))

    def test_once_is_not_a_record_and_agreement_is_not_either(self):
        its = [passed(TILT, "missed", 1000)]
        its += [passed(FREEZER, "wrong", 1000 + i) for i in range(5)]
        self.assertEqual(outcomes.overruled(its), {})

    def test_a_raised_report_marked_not_a_problem_after_the_misses_ends_it(self):
        its = [passed(FREEZER, "missed", 1000 + i * 100) for i in range(3)]
        its.append(raised(FREEZER, "wrong", 9000))
        self.assertEqual(outcomes.overruled(its), {})

    def test_a_person_is_never_on_the_record(self):
        its = [passed("person.ben", "missed", 1000 + i) for i in range(4)]
        self.assertEqual(outcomes.overruled(its), {})

    def test_the_nightly_candidate_and_the_floor_use_one_arithmetic(self):
        its = [passed(FREEZER, "missed", 1000 + i * 100) for i in range(3)]
        [cand] = outcomes.candidates(outcomes.tallies(its))
        self.assertEqual(cand["direction"], "louder")
        self.assertEqual(cand["counts"], outcomes.overruled(its)[FREEZER])


class TestTheFloor(unittest.TestCase):
    BATCH = [{"kind": "state", "subject": FREEZER, "source": "eventbus",
              "text": "Freezer compressor on → off"},
             {"kind": "state", "subject": "light.hall", "source": "eventbus",
              "text": "Hall light on → off"}]

    def test_ignore_on_an_overruled_subject_is_raised_and_says_why(self):
        record = {FREEZER: "20 of 20 it passed over turned out to matter"}
        floors = outcomes.overruled_floors(self.BATCH, record)
        self.assertEqual(set(floors), {1})
        got = resident.parse_first_look(
            {"verdicts": [{"id": 1, "verdict": "ignore",
                           "why": "switched off as designed"},
                          {"id": 2, "verdict": "ignore", "why": "a person"}]},
            2, self.BATCH, floors=floors)
        self.assertEqual(got[1]["verdict"], "investigate")
        self.assertTrue(got[1]["forced"])
        self.assertIn("overruled", got[1]["why"])
        self.assertEqual(got[2]["verdict"], "ignore")

    def test_already_cannot_set_an_overruled_subject_aside(self):
        floors = {1: ("investigate", "overruled before")}
        got = resident.parse_first_look(
            {"verdicts": [{"id": 1, "verdict": "watch", "already": "explained",
                           "why": "the thermostat switched it off"},
                          {"id": 2, "verdict": "ignore", "why": "x"}]},
            2, self.BATCH, floors=floors)
        self.assertEqual(got[1]["verdict"], "investigate")

    def test_a_record_floor_never_lowers_a_safety_floor(self):
        leak = [{"kind": "state", "subject": "binary_sensor.leak",
                 "source": "eventbus", "safety": True}]
        got = resident.parse_first_look(
            {"verdicts": [{"id": 1, "verdict": "ignore", "why": "x"}]}, 1,
            leak, floors={1: ("investigate", "overruled")})
        self.assertEqual(got[1]["verdict"], "act")

    def test_the_look_is_shown_the_record_and_what_switches_the_device(self):
        prompt = resident.first_look_prompt(
            self.BATCH, passed_over=[f"{FREEZER}: 20 of 20 it passed over "
                                     "turned out to matter"],
            controlled_by=[f"{FREEZER}: automation “Freezer thermostat” "
                           "(turn_off, turn_on)",
                           f"{FREEZER}: what starts it reads now — "
                           "sensor.freezer_probe 47"])
        self.assertIn("PASSED OVER BEFORE", prompt)
        self.assertIn("20 of 20", prompt)
        self.assertIn("WHAT SWITCHES THESE DEVICES", prompt)
        self.assertIn("sensor.freezer_probe 47", prompt)

    def test_the_rules_say_the_reading_not_the_switch_and_what_depends_on_it(self):
        system = resident.FIRST_LOOK_SYSTEM
        self.assertIn("freezer warmer than", system)
        self.assertIn("fridge warmer than", system)
        self.assertIn('never "only a', system)
        self.assertIn("PASSED OVER BEFORE", system)


class TestTheLoop(LoopCase):
    """Through the real `_resident_tick`: the record is read off the graded
    log, shown to the look, and floors the verdict on record."""

    def setUp(self):
        super().setUp()
        self.point("decision_trail",
                   TRAIL_FILE=str(Path(self.tmp.name) / "decisions.jsonl"))

    def fresh_tick(self, now: float) -> dict:
        """A tick that is due for both a sweep and a look."""
        self.server.RESIDENT_STATE["last_look_at"] = 0.0
        self.server.RESIDENT_STATE["last_sweep_at"] = 0.0
        return self.tick(now)

    def graded(self, its):
        return unittest.mock.patch.object(self.server.outcomes, "load_graded",
                                 return_value=its)

    def test_the_freezer_switch_is_not_passed_over_a_twenty_first_time(self):
        now = time.time()
        its = [passed(FREEZER, "missed", int(now) - 86400 * 30 + i * 3600)
               for i in range(20)]
        self.server._resident_offer(signals.make(
            "state", FREEZER, now=now, source="eventbus",
            text="Freezer compressor on → off", salience=0.6))
        self.looks.append(reply([{"id": 1, "verdict": "ignore",
                                  "why": "switched off as designed"}]))
        self.investigations.append(case_reply())
        with self.graded(its):
            self.fresh_tick(now)
        prompt = self.look_calls[-1]["prompt"]
        self.assertIn("PASSED OVER BEFORE", prompt)
        self.assertIn(FREEZER, prompt)
        logged = [r for r in self.server.outcomes.load_rows()
                  if r.get("stage") == "look"]
        self.assertEqual(logged[-1]["verdict"], "investigate")
        self.assertTrue(logged[-1]["forced"])
        self.assertEqual(len(self.analyst_calls), 1)

    def test_a_subject_with_no_record_is_left_to_the_look(self):
        now = time.time()
        self.server._resident_offer(signals.make(
            "state", "light.hall", now=now, source="eventbus",
            text="Hall light on → off", salience=0.6))
        self.looks.append(reply([{"id": 1, "verdict": "ignore",
                                  "why": "somebody switched it off"}]))
        with self.graded([passed(FREEZER, "missed", 1000 + i)
                          for i in range(3)]):
            self.fresh_tick(now)
        self.assertNotIn("PASSED OVER BEFORE", self.look_calls[-1]["prompt"])
        logged = [r for r in self.server.outcomes.load_rows()
                  if r.get("stage") == "look"]
        self.assertEqual(logged[-1]["verdict"], "ignore")


class TestUsedThroughTheDevice(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import importlib
        cls.server = importlib.import_module("server")

    def used_by(self, snap, ids):
        srv = self.server
        old_used, old_names = dict(srv._USED_BY), dict(srv._NAMES)
        try:
            srv._note_registry(snap)
            return srv._used_by_rows(ids)
        finally:
            srv._USED_BY.clear()
            srv._USED_BY.update(old_used)
            srv._NAMES.clear()
            srv._NAMES.update(old_names)

    def snapshot(self, contact, other, alias, action):
        return {
            "states": {contact: {"state": "off", "attributes": {}},
                       other: {"state": "-92", "attributes": {}}},
            "entities": [{"entity_id": contact, "device_id": "dev1"},
                         {"entity_id": other, "device_id": "dev1"}],
            "devices": [{"id": "dev1", "name": "Sensor"}], "areas": [],
            "automations": [{"id": "a1", "alias": alias,
                             "triggers": [{"trigger": "state",
                                           "entity_id": contact}],
                             "actions": [action]}],
            "scripts": {},
        }

    def test_a_door_sensors_signal_reading_carries_the_auto_lock(self):
        snap = self.snapshot(
            "binary_sensor.front_door_contact", "sensor.front_door_rssi",
            "Auto-lock the front door",
            {"action": "lock.lock", "target": {"entity_id": "lock.front"}})
        rows = self.used_by(snap, ["sensor.front_door_rssi"])
        self.assertEqual(len(rows), 1)
        self.assertIn("Auto-lock the front door", rows[0])
        self.assertIn("binary_sensor.front_door_contact", rows[0])

    def test_a_garage_tilt_sensors_battery_carries_its_automation(self):
        snap = self.snapshot(
            "binary_sensor.garage_door_tilt", "sensor.garage_door_tilt_battery",
            "Close the garage at night",
            {"action": "cover.close_cover",
             "target": {"entity_id": "cover.garage"}})
        rows = self.used_by(snap, ["sensor.garage_door_tilt_battery"])
        self.assertEqual(len(rows), 1)
        self.assertIn("Close the garage at night", rows[0])


if __name__ == "__main__":
    unittest.main()
