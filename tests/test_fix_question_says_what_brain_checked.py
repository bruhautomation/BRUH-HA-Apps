#!/usr/bin/env python3
"""An "is this fixed now?" card says what brAIn could not check, and the
one thing to try; a question nobody answered does not linger (#605).

After an update the owner was asked whether a fix held, with nothing on the
card saying whether brAIn had looked itself or what would tell, and
questions carried over from earlier updates sat on Today with no context.
The card now says brAIn cannot check this kind of report itself (only the
owner's own requests and the chat's unmet ones are ever asked: a fault is
verified by its fingerprint and never asked), names the one thing to try —
the report's own "Done when" when it has one — and says which release it
was reported on. A question unanswered for `QUESTION_TTL_DAYS` is withdrawn
with nothing posted.

Made-up reports: a garden-hose timer card on Today, and a chat request to
dim the study lamp at sunset.
"""

import asyncio
import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "brain" / "panel"))
sys.path.insert(0, str(TESTS_DIR))

from devloop import verify  # noqa: E402
from test_devloop_verify_after_update import DAY, VerifyCase  # noqa: E402

LOOK = {"fp": "1" * 16, "verdict": "fixed", "stream": "look",
        "fixed_in": "4.2.0", "version": "4.1.3", "where": "Today",
        "what": "The hose timer card shows yesterday's run as today's",
        "done_when": "the hose timer card shows today's run under today"}
UNMET = {"fp": "2" * 16, "verdict": "fixed", "stream": "unmet",
         "fixed_in": "4.2.0", "version": "4.1.3", "where": "Chat",
         "what": "The chat could not dim the study lamp at sunset"}


class TestTheCardSaysWhatBrainCouldNotCheck(unittest.TestCase):
    def test_a_request_says_brain_cannot_check_it_and_what_tells(self):
        row = verify.question_row(LOOK)
        self.assertIn("brAIn cannot check this one itself", row["detail"])
        self.assertIn("Try this: open Today", row["detail"])
        self.assertIn("counts as fixed when: the hose timer card shows "
                      "today's run under today", row["detail"])

    def test_the_chats_unmet_request_says_to_ask_again(self):
        row = verify.question_row(UNMET)
        self.assertIn("brAIn cannot check this one itself", row["detail"])
        self.assertIn("ask the chat again", row["detail"])

    def test_done_when_is_read_off_the_body_too(self):
        entry = {**LOOK, "done_when": "",
                 "body": "**Done when:** the card says today\n\nmore"}
        self.assertIn("counts as fixed when: the card says today",
                      verify.question_row(entry)["detail"])

    def test_it_says_where_the_report_came_from(self):
        self.assertIn("You reported this on brAIn 4.1.3",
                      verify.question_row(LOOK)["detail"])

    def test_a_grouped_question_says_it_too(self):
        other = {**LOOK, "fp": "3" * 16,
                 "what": "The hose timer card has no stop button",
                 "where": "Today"}
        row = verify.group_row([{**LOOK, "where": "Fix: Hose timer date"},
                                {**other, "where": "Fix: Hose timer stop"}])
        self.assertIn("brAIn cannot check this one itself", row["detail"])


class TestAnUnansweredQuestionIsWithdrawn(unittest.TestCase):
    def test_moot_after_the_set_time(self):
        rec = {"fixed_in": "4.2.0", "at": 1_000_000, "answer": ""}
        self.assertEqual(verify.moot(LOOK, rec, 1_000_000 + DAY), "")
        later = 1_000_000 + (verify.QUESTION_TTL_DAYS + 1) * DAY
        self.assertIn("nobody answered", verify.moot(LOOK, rec, later))
        self.assertEqual(verify.moot(LOOK, {**rec, "answer": "held"}, later), "")


class TestTheSettlePassDropsIt(VerifyCase):
    def test_a_fortnight_old_question_is_withdrawn_with_nothing_posted(self):
        fp = "4" * 16
        self.seed(fp)
        row = self.ask(fp)
        state = self.server.devloop.verify.load()
        state[fp]["at"] = self.now - (verify.QUESTION_TTL_DAYS + 1) * DAY
        self.server.devloop.verify.save(state)
        done = asyncio.run(self.server._devloop_verify_settle(self.now))
        self.assertEqual(done["withdrawn"], 1)
        self.assertFalse(self.live(row))
        self.assertEqual(self.owner(fp), {})

    def test_a_fresh_question_stays(self):
        fp = "5" * 16
        self.seed(fp)
        row = self.ask(fp)
        self.assertEqual(self.settle()["withdrawn"], 0)
        self.assertTrue(self.live(row))


if __name__ == "__main__":
    unittest.main()
