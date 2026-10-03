#!/usr/bin/env python3
"""A guess needs a slot, and a run that cannot have one is not paid for.

A curiosity run answers explained, guess or unknown, and the guess is the
one answer that needs a place in the hypothesis queue — capped at three
open on purpose. A run that answered "guess" into a full queue paid for
the reasoning, threw the guess away and recorded the subject `guessed`,
which is "the question is on the list": it was on no list, and the subject
was closed for ever without anybody having been asked.

Driven against the real server module, the real curiosity store and the
real hypothesis queue (`test_curiosity_wiring`'s harness). Mutations:

  pay into a full queue   drop the budget gate in `_ask_why` -> the
                          candidates are read and a run would be spent
  guessed, never asked    map a refused guess to `guessed` -> the subject
                          is closed with nothing on any list
  lost guess              drop `_repropose_deferred` -> a freed slot is
                          never filled with the guess already paid for
  the question is filed   file the claim on confirm -> "…because X — why
                          did you…?" lands in memory, question mark and all
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

from test_curiosity_wiring import ServerCase  # noqa: E402

NOW = 1_789_800_000.0


class Gated(ServerCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        server = self.server
        self.patch(server.engine, "get_auth", lambda: {"type": "oauth"})
        self.patch(server.usage_store, "budget_state",
                   lambda *a, **k: {"blocked": False})

        def no_run(*a, **k):
            raise AssertionError("a curiosity run was spent")

        self.patch(server.engine, "run_analyst", no_run)
        self.read_candidates = 0

        def candidates(*a, **k):
            self.read_candidates += 1
            return []

        self.patch(server.manual_ledger, "candidates", candidates)

    def fill_queue(self):
        for i in range(self.hypotheses.MAX_OPEN):
            self.assertIsNotNone(self.hypotheses.propose(
                f"Somebody guessed thing number {i} about the house"))
        self.assertEqual(self.hypotheses.budget(), 0)


class TestNothingIsSpentIntoAFullQueue(Gated):

    async def test_a_full_queue_reads_nothing_and_runs_nothing(self):
        self.fill_queue()
        asked = await self.server._ask_why(NOW, "test")
        self.assertEqual(asked, 0)
        self.assertEqual(self.read_candidates, 0)

    async def test_room_in_the_queue_goes_on_to_look(self):
        asked = await self.server._ask_why(NOW, "test")
        self.assertEqual(asked, 0)
        self.assertEqual(self.read_candidates, 1)


class TestARefusedGuessIsDeferredNotGuessed(Gated):

    def guess(self):
        return self.answer(
            confidence="guess",
            because="the lawn is in full sun until about six",
            ask="do you water late so the sun does not burn it off?")

    async def test_the_refusal_is_its_own_status_and_stays_askable(self):
        self.fill_queue()
        self.curiosity.mark_asked(self.CANDIDATE, NOW)
        filed = self.server._file_curiosity(self.CANDIDATE, self.guess())
        self.assertEqual(filed, self.curiosity.REFUSED)
        self.curiosity.record_answer(self.CANDIDATE["subject"], self.guess(),
                                     filed, "", NOW)
        entry = self.curiosity.load()["asked"][self.CANDIDATE["subject"]]
        self.assertEqual(entry["status"], "deferred")
        self.assertIn("deferred", self.curiosity.RETRYABLE)
        self.assertEqual([e["subject"] for e in self.curiosity.deferred()],
                         [self.CANDIDATE["subject"]])

    async def test_a_freed_slot_takes_the_guess_already_paid_for(self):
        self.fill_queue()
        self.curiosity.mark_asked(self.CANDIDATE, NOW)
        filed = self.server._file_curiosity(self.CANDIDATE, self.guess())
        self.curiosity.record_answer(self.CANDIDATE["subject"], self.guess(),
                                     filed, "", NOW)
        # Nothing moves while the queue is still full.
        self.assertEqual(self.server._repropose_deferred(NOW), 0)
        open_rows = self.hypotheses.list_all("open")
        self.hypotheses.reject(open_rows[0]["ts"])
        self.assertEqual(self.server._repropose_deferred(NOW + 60), 1)
        entry = self.curiosity.load()["asked"][self.CANDIDATE["subject"]]
        self.assertEqual(entry["status"], "guessed")
        # The stored row, because the listing does not carry what a yes
        # would file — that is the confirm route's to read.
        proposed = [h for h in self.hypotheses._read()
                    if h.get("subject") == "switch.sprinklers"]
        self.assertEqual(len(proposed), 1)
        self.assertEqual(proposed[0]["fact"],
                         "the lawn is in full sun until about six")
        self.assertEqual(self.curiosity.deferred(), [])


class TestConfirmingFilesTheReasonNotTheQuestion(Gated):

    async def test_the_fact_and_its_subject_reach_the_inbox(self):
        answer = self.answer(
            confidence="guess",
            because="the lawn is in full sun until about six",
            ask="do you water late so the sun does not burn it off?")
        self.assertEqual(self.server._file_curiosity(self.CANDIDATE, answer),
                         "hypothesis")
        row = self.hypotheses.list_all("open")[0]
        self.assertIn("?", row["text"])
        await self.server._answer_hypothesis(row["ts"], "confirm")
        facts = [f for f in self.inbox_facts() if f.get("source") == "confirmed"]
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["fact"],
                         "the lawn is in full sun until about six")
        self.assertEqual(facts[0].get("subject"), "switch.sprinklers")

    async def test_a_guess_with_no_fact_files_its_claim_as_before(self):
        row = self.hypotheses.propose("The porch light is on a timer")
        await self.server._answer_hypothesis(row["ts"], "confirm")
        facts = [f["fact"] for f in self.inbox_facts()
                 if f.get("source") == "confirmed"]
        self.assertEqual(facts, ["The porch light is on a timer"])


if __name__ == "__main__":
    unittest.main()
