#!/usr/bin/env python3
"""Ignore on a Resident report offers short reasons, and the next run reads them.

The household ignored five of eight Resident reports with a bare Ignore:
nothing said why, and the Resident's own reports have no rule to mute. The
reason box now offers chips — "Already know", "Sensor is broken", "Not an
issue here" — that write their words into the box, so a chip is a typed
reason one tap away and goes down the one path a typed reason does
(`_end_finding` → the exception rule → memory), and "Sensor is broken" is
read by `corrections.gone_for_good` like any typed "the sensor is broken".

Never on a safety, leak, smoke, lock or security report: the never-ignore
floors stand, and a chip must not make waving one of those off easier.
"""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import answers  # noqa: E402
import corrections  # noqa: E402
import findings_store  # noqa: E402
import resident  # noqa: E402
import signals  # noqa: E402
from test_outcomes import OutcomesLoop  # noqa: E402
from test_resident_loop import reply  # noqa: E402


def report(**over) -> dict:
    row = {"source": "resident", "claim": "The hall motion sensor's signal "
           "is weak and it misses people", "entity_id":
           "binary_sensor.hall_motion", "severity": "warning"}
    row.update(over)
    return row


class TestWhichReportsOfferChips(unittest.TestCase):
    def test_a_resident_report_offers_the_three(self):
        self.assertEqual(answers.reason_chips(report()),
                         ["Already know", "Sensor is broken",
                          "Not an issue here"])

    def test_a_second_example_a_garage_tilt_sensors_battery(self):
        chips = answers.reason_chips(report(
            claim="The garage door tilt sensor's battery is at 9%",
            entity_id="sensor.garage_door_tilt_battery"))
        self.assertIn("Sensor is broken", chips)

    def test_sensor_is_broken_needs_a_device(self):
        chips = answers.reason_chips(report(entity_id="",
                                            claim="Two automations disagree"))
        self.assertEqual(chips, ["Already know", "Not an issue here"])

    def test_another_producer_offers_none(self):
        self.assertEqual(answers.reason_chips(report(source="check:dev.frozen")),
                         [])

    def test_never_on_safety_leak_smoke_lock_or_security(self):
        for over in ({"claim": "Water under the dishwasher: the leak sensor "
                               "is wet"},
                     {"claim": "The smoke detector chirped twice"},
                     {"claim": "The front door was left unlocked overnight"},
                     {"entity_id": "lock.front_door", "claim": "x is slow"},
                     {"entity_id": "alarm_control_panel.house"},
                     {"claim": "Pipes may freeze in the crawl space"},
                     {"source": "safety"}, {"source": "check:sec.exposed"},
                     {"protected": True}, {"safety": True},
                     {"severity": "critical"}):
            with self.subTest(over):
                self.assertEqual(answers.reason_chips(report(**over)), [])
        self.assertEqual(answers.reason_chips(report(), urgent=True), [])

    def test_the_words_cover_every_never_ignore_class(self):
        self.assertLessEqual(set(resident.NEVER_IGNORE),
                             set(answers.CHIP_NEVER_WORDS))
        self.assertEqual(answers.RESIDENT_SOURCE, findings_store.RESIDENT_SOURCE)

    def test_sensor_is_broken_is_the_existing_broken_reading(self):
        self.assertTrue(corrections.gone_for_good(answers.BROKEN_CHIP))
        for words in answers.REASON_CHIPS:
            with self.subTest(words):
                # A plain Wrong with words: not a snooze, not a condition.
                self.assertFalse(corrections.puts_off(words))
                self.assertFalse(corrections.conditional(words))


class TestThroughTheServer(OutcomesLoop):
    def setUp(self):
        super().setUp()
        self.point("decision_trail",
                   TRAIL_FILE=str(Path(self.tmp.name) / "decisions.jsonl"))

    def file_report(self, **over) -> dict:
        over.setdefault("claim", "The hall motion sensor's signal is weak")
        over.setdefault("text", over["claim"])
        row = self.fs.add_case({
            "detail": "It reads -94 dBm.", "kind": "problem",
            "stakes": "medium", "fix": "Move the hub closer.",
            "entity_id": "binary_sensor.hall_motion",
            "evidence": [{"entity": "binary_sensor.hall_motion",
                          "value": "-94"}], **over}, run_id="inv-1")
        self.assertIsNotNone(row)
        return row

    def test_the_case_and_the_loose_card_both_carry_the_chips(self):
        row = self.file_report()
        cases = self.server._cases_payload()["cases"]
        [case] = [c for c in cases if c.get("ts") == row["ts"]]
        wrong = [a for a in case["answers"] + case["more"]
                 if a.get("verb") == "wrong"]
        self.assertTrue(wrong)
        self.assertIn("Sensor is broken", wrong[0].get("chips") or [])
        listed = self.server._findings_payload()["findings"]
        [loose] = [f for f in listed if f["ts"] == row["ts"]]
        self.assertIn("Not an issue here", loose["reason_chips"])

    def test_a_leak_report_carries_none(self):
        row = self.file_report(
            claim="The dishwasher leak sensor reported water twice",
            entity_id="binary_sensor.dishwasher_leak",
            evidence=[{"entity": "binary_sensor.dishwasher_leak",
                       "value": "on"}])
        cases = self.server._cases_payload()["cases"]
        [case] = [c for c in cases if c.get("ts") == row["ts"]]
        self.assertFalse([a for a in case["answers"] + case["more"]
                          if a.get("chips")])

    def test_sensor_is_broken_marks_it_known_faulty_and_the_next_look_reads_it(self):
        row = self.file_report()
        self.end(row["ts"], "wrong", answers.BROKEN_CHIP)
        self.assertIn("binary_sensor.hall_motion", corrections.known_faulty())
        now = time.time()
        self.server._resident_offer(signals.make(
            "state", "binary_sensor.hall_motion", now=now, source="eventbus",
            text="Hall motion unavailable → off", salience=0.6))
        self.looks.append(reply([{"id": 1, "verdict": "ignore",
                                  "why": "the owner said it is broken"}]))
        self.fresh_tick(now)
        self.assertIn(answers.BROKEN_CHIP, self.look_calls[-1]["prompt"])

    def test_a_second_example_not_an_issue_here_reaches_the_next_look(self):
        row = self.file_report(
            claim="The garage door tilt sensor reports open at night",
            entity_id="binary_sensor.garage_door_tilt",
            evidence=[{"entity": "binary_sensor.garage_door_tilt",
                       "value": "on"}])
        self.end(row["ts"], "wrong", "Not an issue here")
        self.assertNotIn("binary_sensor.garage_door_tilt",
                         corrections.known_faulty())
        now = time.time()
        self.server._resident_offer(signals.make(
            "state", "binary_sensor.garage_door_tilt", now=now,
            source="eventbus", text="Garage tilt off → on", salience=0.6))
        self.looks.append(reply([{"id": 1, "verdict": "ignore", "why": "x"}]))
        self.fresh_tick(now)
        self.assertIn("Not an issue here", self.look_calls[-1]["prompt"])


if __name__ == "__main__":
    unittest.main()
