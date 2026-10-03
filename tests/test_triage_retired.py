#!/usr/bin/env python3
"""The triage drain is gone, and what it held that still means something.

`_triage_findings` was a second judge of the rows `triage.gate` marks: one
Claude run per drain answering `elevated` or `held`. Once the Resident's
first look took its queue nothing scheduled it, and it lived on for its
own tests — a second vocabulary for one decision, with a prompt, a schema
and a parser nobody ran. The cut is a real removal, so the first half of
this file says the code is gone; the second half drives the Resident
through the rules the drain's tests pinned that were not already pinned
there, so nothing they protected went with it:

* two looks started in one tick spend one run;
* what the homeowner has already said rides into the look;
* a row the reply never mentioned is SHOWN, never held — silence surfaces.
"""
from __future__ import annotations

import ast
import asyncio
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_resident_loop import LoopCase, reply  # noqa: E402

import triage  # noqa: E402


class TestTheDrainIsGone(unittest.TestCase):
    def test_nothing_in_the_panel_defines_or_calls_it(self):
        tree = ast.parse((PANEL_DIR / "server.py").read_text())
        names = {n.name for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        self.assertNotIn("_triage_findings", names)
        self.assertNotIn("_triage_drain", names)
        called = {n.attr if isinstance(n, ast.Attribute) else n.id
                  for n in ast.walk(tree)
                  if isinstance(n, (ast.Attribute, ast.Name))}
        self.assertNotIn("_triage_findings", called)

    def test_the_drains_own_vocabulary_went_with_it(self):
        """A prompt, a schema and a parser that nothing runs are a second
        answer to "what does a look say", waiting to be picked up again."""
        for gone in ("SYSTEM", "SCHEMA", "frame", "parse", "MAX_BATCH",
                     "NOT_MENTIONED", "NO_CREDENTIAL", "PAUSED", "NO_BUDGET"):
            self.assertFalse(hasattr(triage, gone), gone)
        # …and what the Resident still reads stayed.
        for kept in ("gate", "VERDICTS", "STALE_S", "UNJUDGED", "RUN_FAILED",
                     "MAX_PER_DAY", "MAX_REASON"):
            self.assertTrue(hasattr(triage, kept), kept)

    def test_no_job_in_the_plan_is_left_with_nothing_to_run(self):
        import model_plan
        self.assertNotIn("triage", model_plan.JOBS)
        # The haiku tier the shell half reads is the first look's.
        self.assertEqual(model_plan.env_exports()["BRAIN_MODEL_HAIKU"],
                         model_plan.resolve("first_look")[0])


class TestWhatTheDrainPinnedNowHoldsForTheLook(LoopCase):
    def setUp(self):
        super().setUp()
        import facts_store
        # A stray /config/.brain/memory on a shared machine makes the
        # facts store read as a real install; this test asks about the
        # document, so the store is pointed somewhere empty.
        self._facts = (facts_store.FACTS_FILE,)
        self._facts_tmp = tempfile.TemporaryDirectory()
        facts_store.FACTS_FILE = Path(self._facts_tmp.name) / "none" / "facts.json"

    def tearDown(self):
        import facts_store
        (facts_store.FACTS_FILE,) = self._facts
        self._facts_tmp.cleanup()
        super().tearDown()

    def test_two_ticks_at_once_spend_one_look(self):
        """`create_task` and `await` both only schedule, so the in-flight
        flag is set before the first await; the loser does nothing."""
        self.file_check_row()
        self.looks.append(reply([{"id": 1, "verdict": "watch",
                                  "why": "one reading is not enough"}]))

        async def both():
            now = time.time()
            return await asyncio.gather(self.server._resident_tick(now),
                                        self.server._resident_tick(now))

        first, second = asyncio.run(both())
        self.assertEqual(len(self.look_calls), 1)
        self.assertIn("skipped", second)
        self.assertTrue(first.get("looked"), first)

    def test_what_the_homeowner_has_already_said_rides_into_the_look(self):
        self.server._read_shared_memory = (
            lambda: "The pantry contact is on a cupboard nobody opens.")
        self.file_check_row()
        self.looks.append(reply([{"id": 1, "verdict": "ignore",
                                  "why": "they said it is a cupboard"}]))
        self.tick()
        [call] = self.look_calls
        self.assertIn("cupboard nobody opens", call["prompt"])

    def test_a_row_the_reply_never_mentioned_is_shown_not_held(self):
        row = self.file_check_row()
        other = self.file_check_row(text="The loft contact has not changed")
        # The reply answers for the second row only.
        self.looks.append(reply([{"id": 2, "verdict": "ignore",
                                  "why": "it is a loft hatch"}]))
        self.tick()
        statuses = self.statuses()
        self.assertEqual(statuses[row["ts"]], "open")
        self.assertEqual(statuses[other["ts"]], "held")

    def test_an_unreadable_reply_holds_nothing(self):
        row = self.file_check_row()
        self.looks.append({"ok": True, "error": "", "text": "I think so?",
                           "meta": {"session_id": "look-1"}})
        self.tick()
        self.assertEqual(self.statuses()[row["ts"]], "open")
        self.assertNotEqual(json.dumps(self.statuses()), "{}")


if __name__ == "__main__":
    unittest.main()
