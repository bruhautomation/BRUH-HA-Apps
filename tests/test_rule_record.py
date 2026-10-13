#!/usr/bin/env python3
"""A rule the household marks wrong most of the time is quieted by brAIn.

In the field: check:dev.unavailable 2 right / 4 wrong, check:auto.conflict
1/4, check:dev.frozen 1/3, check:forecast.decline 0/3, and two at 0/2 —
and the only thing any of them earned was a fault row asking the owner to
mute it. The first look is now told a lopsided rule's record beside the
signals it filed (`rule_record`), as context: no floor moves, nothing is
muted, and a security, safety or unmutable producer is never quieted.
"""
from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL))
sys.path.insert(0, str(BASE_DIR / "tests"))

import reports  # noqa: E402
import rule_record  # noqa: E402
from test_outcomes import OutcomesLoop  # noqa: E402
from test_resident_loop import reply  # noqa: E402


def card(source, wrong, total, last="wrong", title="Sensors frozen"):
    return {"source": source, "title": title, "wrong": wrong,
            "confirmed": total - wrong, "total": total, "last": last}


def sig(source, **flags):
    return {"kind": "check", "subject": "sensor.x", "source": source,
            "finding_ts": 1, **flags}


class TestWhichRecordsAreRead(unittest.TestCase):
    def test_the_field_records_qualify(self):
        for src, wrong, total in (("check:dev.unavailable", 4, 6),
                                  ("check:auto.conflict", 4, 5),
                                  ("check:dev.frozen", 3, 4),
                                  ("check:forecast.decline", 3, 3),
                                  ("check:auto.condition_never_passes", 2, 2),
                                  ("check:auto.never_fired", 2, 2)):
            self.assertTrue(rule_record.qualifies(card(src, wrong, total)), src)

    def test_what_is_never_quieted(self):
        for src in ("check:sec.lock_cloud_voice", "check:climate.freeze",
                    "check:safety.tripped", "resident", "safety", "security",
                    "insight-energy", "custom-123"):
            self.assertFalse(rule_record.qualifies(card(src, 5, 5)), src)

    def test_a_balanced_or_recently_confirmed_rule_is_not(self):
        self.assertFalse(rule_record.qualifies(card("check:a.b", 1, 1)))
        self.assertFalse(rule_record.qualifies(card("check:a.b", 2, 5)))
        self.assertFalse(rule_record.qualifies(
            card("check:a.b", 4, 5, last="confirmed")))

    def test_a_floored_signal_gets_no_line(self):
        board = [card("check:dev.frozen", 3, 4)]
        for flags in ({"safety": True}, {"protected": True}, {"hot": True}):
            self.assertEqual(rule_record.lines(
                [sig("check:dev.frozen", **flags)], board), [], flags)
        self.assertEqual(rule_record.lines(
            [sig("check:dev.frozen")], board,
            floor=lambda s: ("watch", "x")), [])

    def test_the_line_names_the_positions_and_the_record(self):
        board = [card("check:dev.frozen", 3, 4)]
        got = rule_record.lines([sig("check:other"), sig("check:dev.frozen"),
                                 sig("check:dev.frozen")], board)
        self.assertEqual(len(got), 1)
        self.assertIn("Signals 2 and 3", got[0])
        self.assertIn("3 of its 4", got[0])
        self.assertIn("Sensors frozen", got[0])

    def test_the_restated_sets_agree_with_their_owners(self):
        import cases
        import signals
        self.assertEqual(rule_record.UNMUTABLE_SOURCES, cases.UNMUTABLE_SOURCES)
        self.assertEqual(rule_record.SAFETY_CHECKS, signals.SAFETY_FLAG_CHECKS)


class TestTheBlockIsContextNotAFloor(unittest.TestCase):
    def test_the_prompt_carries_the_block_and_the_capture_keeps_it(self):
        import outcomes
        import resident
        inputs: dict = {}
        line = "Signal 1 came from the rule “X”: marked 3 of its 4 wrong."
        prompt = resident.first_look_prompt(["[check] sensor.x"],
                                            rule_records=[line], inputs=inputs)
        self.assertIn(line, prompt)
        self.assertIn("fresh, specific evidence", prompt)
        self.assertEqual(inputs["rule_records"], [line])
        replay = outcomes.replay_prompt({"batch": [], "inputs": inputs,
                                         "now": 1000.0})
        self.assertIn(line, replay)
        # no records, no block
        self.assertNotIn("fresh, specific evidence",
                         resident.first_look_prompt(["[check] sensor.x"]))

    def test_the_floor_still_overrules_an_ignore_after_the_reply(self):
        import resident
        protected = {"kind": "check", "subject": "lock.front",
                     "source": "check:dev.frozen", "protected": True}
        got = resident.parse_first_look(
            {"verdicts": [{"id": 1, "verdict": "ignore", "why": "record"}]},
            1, [protected])
        self.assertNotEqual(got[1]["verdict"], "ignore")


class TestTheLookIsToldByTheLoop(OutcomesLoop):
    def setUp(self):
        super().setUp()
        self.point("decision_trail",
                   TRAIL_FILE=str(Path(self.tmp.name) / "decisions.jsonl"))

    def _wrongs(self, source, n):
        for i in range(n):
            row = self.file_row(f"The pantry contact has not changed {i}",
                                entity=f"binary_sensor.p{i}", source=source)
            self.end(row["ts"], "wrong")

    def test_a_lopsided_rule_is_named_to_the_next_look(self):
        self._wrongs("check:dev.frozen", 3)
        self.file_row("The pantry contact has not changed again",
                      entity="binary_sensor.q")
        self.looks.append(reply([{"id": 1, "verdict": "ignore", "why": "x"}]))
        self.fresh_tick(time.time())
        prompt = self.look_calls[-1]["prompt"]
        self.assertIn("Signal 1 came from the rule", prompt)
        self.assertIn("3 of its 3", prompt)
        # nothing was muted on the way
        import settings_store
        self.assertNotIn("check:dev.frozen",
                         settings_store.muted())

    def test_a_security_rule_is_never_named(self):
        self._wrongs("check:sec.addon_unprotected", 3)
        self.file_row("An add-on is not protected again",
                      entity="binary_sensor.q",
                      source="check:sec.addon_unprotected")
        self.looks.append(reply([{"id": 1, "verdict": "watch", "why": "x"}]))
        self.fresh_tick(time.time())
        self.assertNotIn("came from the rule", self.look_calls[-1]["prompt"])


class TestTheFaultRowSaysWhatBrainDoes(unittest.TestCase):
    def _rows(self, source, title="Sensors frozen on one value",
              wrong=4, total=5, offered=()):
        diag = {"findings": {"scorecard": [card(source, wrong, total,
                                                title=title)],
                             "mute_offers_open": list(offered)}}
        return [r for r in reports.faults(diag)
                if str(r.get("where", "")).startswith("Producer")]

    def test_a_quieted_rule_says_brain_holds_it_back_and_mute_stays_yours(self):
        [row] = self._rows("check:dev.frozen")
        text = json.dumps(row).lower()
        self.assertIn("holds", text)
        self.assertIn("fresh", text)
        self.assertIn("ignore all like this", text)

    def test_with_a_question_open_it_still_says_what_brain_does(self):
        [row] = self._rows("check:dev.frozen", offered=["check:dev.frozen"])
        text = json.dumps(row).lower()
        self.assertIn("holds", text)
        self.assertIn("needs you", text)

    def test_a_security_rule_keeps_the_old_sentence(self):
        [row] = self._rows("check:sec.addon_unprotected", title="Add-ons")
        self.assertNotIn("holds", json.dumps(row).lower())


if __name__ == "__main__":
    unittest.main()
