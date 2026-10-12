#!/usr/bin/env python3
"""A question card has a way to say "this question is irrelevant".

The owner's words: "When brain is asking a question it gives yes or no,
but it needs a dismiss option too because sometimes the question it asks
is irrelevant." Yes files a fact, No is a correction that teaches, and
Snooze asks again later — and none of the three is "never mind". So every
question card carries **Doesn't apply** (`not_applicable`): the card
closes, NOTHING is recorded as an answer (no memory line, no confirmed or
wrong on the producer scorecard, no capture label), and the same question
is not asked again about the same subject.

Driven through the real `/api/case/<id>/not_applicable` route over the
real stores, for each store a question lives in: a hypothesis, a question
the Resident filed into the findings store, a house-book gap question and
a "stop raising this rule?" offer.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import answers  # noqa: E402
import test_resident_loop as loop  # noqa: E402


class TheRowOffersIt(unittest.TestCase):
    def case(self, **over):
        base = {"id": "f:1", "kind": "question", "status": "open",
                "origin": {"store": "findings", "key": 1}, "source": "resident"}
        base.update(over)
        return base

    def test_every_question_card_shows_doesnt_apply(self):
        for case in (self.case(),
                     self.case(id="h:2", origin={"store": "hypotheses", "key": 2},
                               source="hypothesis"),
                     self.case(source="house_book"),
                     self.case(source="mute_offer"),
                     self.case(source="notify_policy"),
                     self.case(source="correction")):
            got = answers.answers(case)
            na = [a for a in got if a["verb"] == "not_applicable"]
            self.assertEqual(len(na), 1, (case["source"], got))
            self.assertEqual(na[0]["label"], "Doesn't apply")
            self.assertEqual(na[0]["route"],
                             f"/api/case/{case['id']}/not_applicable")
            self.assertFalse(na[0]["primary"])
            self.assertFalse(na[0]["note"], "it asks for no reason")
            # Panel-only: Home Assistant's Repairs and a notification carry
            # no such answer back, so it rides no request.
            self.assertIsNone(na[0]["request"])

    def test_a_yes_no_question_keeps_yes_no_and_snooze(self):
        verbs = [a["verb"] for a in answers.answers(self.case())]
        self.assertEqual(verbs, ["yes", "no", "not_now", "not_applicable"])

    def test_a_gap_question_no_longer_files_a_wrong(self):
        """The gap's Ignore said "This doesn't apply to this house" and was
        a Wrong: a memory line and a mark against the house book."""
        verbs = [a["verb"] for a in answers.answers(self.case(source="house_book"))]
        self.assertEqual(verbs, ["answer", "not_now", "not_applicable"])

    def test_home_assistant_is_not_offered_it(self):
        row = {"ts": 5, "kind": "question", "status": "open",
               "source": "resident", "text": "Is the garage heated?"}
        actions = [a["action"] for a in answers.request_answers(row)]
        self.assertNotIn("not_applicable", actions)


class DoesntApplyRecordsNothing(loop.RouteCase):
    def memory_lines(self) -> list[str]:
        out = []
        for path in sorted(self.server.MEMORY_INBOX_DIR.glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    out.append(json.loads(line)["fact"])
        return out

    def scores(self) -> list[tuple]:
        return [(r["source"], r["confirmed"], r["wrong"])
                for r in self.server.findings_store.scorecard()]

    def file_question(self, text: str, source: str = "resident", **extra):
        fs = self.server.findings_store
        row = fs.add_case({"text": text, "claim": text, "kind": "question",
                           "severity": "info", "source": source,
                           "memory_hint": "The garage is heated in winter.",
                           **extra})
        self.assertIsNotNone(row)
        return row

    def test_a_resident_question_closes_and_is_not_asked_again(self):
        fs = self.server.findings_store
        before = self.scores()
        row = self.file_question("Is the garage heated in winter?",
                                 entity_id="sensor.garage_temperature")
        status, payload = self.post(f"/api/case/f:{row['ts']}/not_applicable")
        self.assertEqual(status, 200, payload)
        self.assertIsNone(fs.get(row["ts"]))
        self.assertEqual(self.memory_lines(), [])
        self.assertEqual(self.scores(), before, "Doesn't apply scored the producer")
        [entry] = fs.settled_listing()
        self.assertEqual(entry["kind"], "not_applicable")
        self.assertNotIn(entry["kind"], ("fixed", "accepted", "ignored"))
        # Not asked again: the same question is suppressed by the ledger.
        again = fs.add_case({"text": "Is the garage heated in winter?",
                             "claim": "Is the garage heated in winter?",
                             "kind": "question", "severity": "info",
                             "source": "resident"})
        self.assertIsNone(again)
        # No rule was written against the entity either: the question was
        # irrelevant, not wrong.
        self.assertEqual(self.server.facts_store.exceptions(
            "sensor.garage_temperature", "resident"), [])
        self.assertTrue(payload.get("undo"))

    def test_a_gap_question_files_nothing_into_memory(self):
        fs = self.server.findings_store
        row = fs.add_case({"text": "House book: Where is the stopcock?",
                           "claim": "Where is the stopcock?", "kind": "question",
                           "severity": "info", "source": "house_book",
                           "source_title": "House book",
                           "memory_hint": "Stopcock:", "fixable": False})
        status, payload = self.post(f"/api/case/f:{row['ts']}/not_applicable")
        self.assertEqual(status, 200, payload)
        self.assertIsNone(fs.get(row["ts"]))
        self.assertEqual(self.memory_lines(), [])
        self.assertEqual(self.scores(), [])

    def test_a_hypothesis_closes_unanswered_and_its_subject_is_left_alone(self):
        hyp = self.server.hypotheses
        guess = hyp.propose("The garage fridge runs all night", "fridge",
                            subject="switch.garage_fridge")
        status, payload = self.post(f"/api/case/h:{guess['ts']}/not_applicable")
        self.assertEqual(status, 200, payload)
        self.assertEqual(hyp.awake(), [])
        [entry] = hyp.list_all()
        self.assertEqual(entry["status"], "not_applicable")
        # Not a dead end: it is not a correction the model should learn from.
        self.assertEqual(hyp.dead_ends(), [])
        self.assertEqual(self.memory_lines(), [])
        # Never re-proposed: the same guess, or a new one about the subject.
        self.assertIsNone(hyp.propose("The garage fridge runs all night", "x"))
        self.assertIsNone(hyp.propose("The garage fridge is a beer fridge", "x",
                                      subject="switch.garage_fridge"))
        # A guess about something else is still welcome.
        self.assertIsNotNone(hyp.propose("The porch light is on a timer", "x",
                                         subject="light.porch"))
        # And the toast's Undo puts it back on the list.
        self.assertTrue(payload.get("undo"))
        status, _ = self.post(f"/api/undo/{payload['undo']}")
        self.assertEqual(status, 200)
        self.assertIn(guess["ts"], [e["ts"] for e in hyp.awake()])

    def test_a_mute_offer_closes_without_muting(self):
        import settings_store
        self.point("mute_offer", STORE=Path(self.tmp.name) / "mute-offers.json")
        fs = self.server.findings_store
        row = self.file_question('Stop raising "Sensors frozen on one value"?',
                                 source="mute_offer")
        status, payload = self.post(f"/api/case/f:{row['ts']}/not_applicable")
        self.assertEqual(status, 200, payload)
        self.assertIsNone(fs.get(row["ts"]))
        self.assertEqual(settings_store.load().get("muted_sources") or [], [])
        self.assertEqual(self.memory_lines(), [])

    def test_the_route_refuses_it_on_a_problem(self):
        fs = self.server.findings_store
        [row] = fs.add_many([{"text": "The disk is 91% full",
                              "severity": "warning", "source": "check:sys.disk_low"}])
        status, _ = self.post(f"/api/case/f:{row['ts']}/not_applicable")
        self.assertEqual(status, 409)
        self.assertIsNotNone(fs.get(row["ts"]))


if __name__ == "__main__":
    unittest.main()
