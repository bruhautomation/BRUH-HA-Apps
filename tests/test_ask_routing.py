#!/usr/bin/env python3
"""Which verb the ask bar heard, and the one ending an intent has.

Two bugs, both in `server.py`, both about a sentence or a row that had no
way out.

**"when did the boiler last run?" is a question.** It opens with the same
word as "when the guests leave, turn the porch light off", so `INTENT_RE`
matched it and the ask bar spent a Claude run producing a *refusal card*
about a one-off it could not arm — for a question a card would have
answered. The signal is one word further along: an auxiliary verb straight
after the opener is somebody asking, and an instruction never has one
there.

**Remove is an intent's only ending.** If the automation is already gone
from `automations.yaml` — somebody deleted it by hand — the splice has
nothing to cut, and reporting that as a failure leaves a card on the
Proposals tab that nothing can clear. `automation_writer.remove` says
`missing: True` for exactly that case, and `_remove_automation` reads it as
the removal having happened.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL))


class ServerCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = self.tmp.name
        self.config = Path(base) / "config"
        self.config.mkdir()
        for key, value in {
            "BRAIN_CONFIG_DIR": str(self.config),
            "BRAIN_INTENTS_FILE": os.path.join(base, "intents.json"),
            "BRAIN_INTENT_REQUESTS_DIR": os.path.join(base, "intent-requests"),
            "BRAIN_EDIT_JOURNAL": os.path.join(base, "edits"),
            "BRAIN_FINDINGS_FILE": os.path.join(base, "findings.json"),
            "BRAIN_FINDINGS_SETTLED": os.path.join(base, "settled.json"),
            "BRAIN_FINDINGS_STATE": os.path.join(base, "state.json"),
            "BRAIN_FINDINGS_INBOX": os.path.join(base, "finbox"),
            "BRAIN_JOURNAL_FILE": os.path.join(base, "journal.jsonl"),
            "BRAIN_MEMORY_DIR": os.path.join(base, "memory"),
            "BRAIN_MEMORY_INBOX": os.path.join(base, "memory", "inbox"),
            "BRAIN_DIR": os.path.join(base, "insights"),
            "BRAIN_SETTINGS_FILE": os.path.join(base, "settings.json"),
            "BRAIN_KNOWLEDGE_FILE": os.path.join(base, "knowledge.json"),
            "BRAIN_DIAGNOSTICS_FILE": os.path.join(base, "diag.json"),
            "BRAIN_PROPOSALS_FILE": os.path.join(base, "proposals.json"),
        }.items():
            os.environ[key] = value
        import automation_writer
        self.writer = importlib.reload(automation_writer)
        import intents
        self.intents = importlib.reload(intents)
        import server
        self.server = importlib.reload(server)

    async def asyncTearDown(self):
        self.tmp.cleanup()


# ---------------------------------------------------------------------------
# The ask bar's third verb, and the questions that share its opener
# ---------------------------------------------------------------------------

class TestIntentRouting(ServerCase):
    """Driven through the real route, because the bug was in how the two
    patterns compose and either one alone reads as correct."""

    async def _route(self, question: str) -> dict:
        class R:
            async def json(self_inner):
                return {"question": question}
        resp = await self.server.h_generate(R())
        return json.loads(resp.text)

    QUESTIONS = [
        "when did the boiler last run?",
        "when is bin day",
        "once was the alarm armed",
        "when was the filter last changed?",
        "when will the battery run out",
        "whenever does the heating come on",
        "when can I run the dishwasher cheaply",
    ]
    INSTRUCTIONS = [
        "tell me when the dishwasher is done",
        "whenever the door opens, turn on the hall light",
        "when the guests leave turn the porch light off",
        "once the washing finishes, remind me",
        "as soon as the freezer warms up, notify me",
        "next time the bin sensor trips, send a notification",
    ]

    async def test_a_question_opening_with_when_becomes_a_card(self):
        for question in self.QUESTIONS:
            with self.subTest(question):
                out = await self._route(question)
                self.assertNotIn("intent", out, question)

    async def test_an_instruction_opening_with_when_still_arms_a_one_off(self):
        for question in self.INSTRUCTIONS:
            with self.subTest(question):
                out = await self._route(question)
                self.assertIn("intent", out, question)

    async def test_the_signal_is_the_auxiliary_and_not_the_question_mark(self):
        """Nobody types a `?` on a phone, so a rule that needed one would
        route half these to the wrong verb."""
        self.assertTrue(
            self.server.INTENT_QUESTION_RE.match("when did the boiler run"))
        self.assertIsNone(
            self.server.INTENT_QUESTION_RE.match("when the boiler runs?"))

    async def test_a_question_costs_no_intent_request_file(self):
        """The failure was not the wrong answer, it was the Claude run and
        the refusal card that came out of it."""
        await self._route("when did the boiler last run?")
        self.assertEqual(self.intents.pending(), 0)
        await self._route("when the guests leave turn the porch light off")
        self.assertEqual(self.intents.pending(), 1)


# ---------------------------------------------------------------------------
# Removing an automation somebody already deleted
# ---------------------------------------------------------------------------

AUTOS = """\
# somebody's own file, with their own comment
- id: morning_lights
  alias: Morning lights
  trigger:
    - platform: sun
      event: sunrise
  action:
    - service: light.turn_on
      target:
        entity_id: light.hall
"""


class TestRemovingWhatIsAlreadyGone(ServerCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.autos = self.config / "automations.yaml"
        self.autos.write_text(AUTOS, encoding="utf-8")
        (self.config / "configuration.yaml").write_text(
            "automation: !include automations.yaml\n", encoding="utf-8")
        # Core is never reached on this path — there is nothing to reload —
        # so a stub that raises proves it, rather than one that answers.
        import ha_data
        self.ha_data = ha_data
        self._reload = ha_data.call_core_service

        async def refuse(*a, **k):
            raise AssertionError("nothing should be reloaded for an entry "
                                 "that was not in the file")
        ha_data.call_core_service = refuse

    async def asyncTearDown(self):
        self.ha_data.call_core_service = self._reload
        await super().asyncTearDown()

    async def test_an_entry_that_is_not_there_is_a_removal_that_happened(self):
        written, failure = await self.server._remove_automation(
            "brain_1700000000", "automation.a_one_off")
        self.assertEqual(failure, "")
        self.assertIsNone(written)
        self.assertEqual(self.autos.read_text(encoding="utf-8"), AUTOS,
                         "the file was touched over an entry it did not hold")

    async def test_the_row_leaves_the_list_and_still_hands_back_an_undo(self):
        row = self.intents.arm(
            {"ts": 1_700_000_000_000, "title": "Porch light once",
             "intent": {"sentence": "when the guests leave, "
                                    "turn the porch light off"}},
            {"automation_id": "brain_1700000000",
             "entity_id": "automation.porch_light_once"})
        self.assertIsNotNone(row)

        class R:
            match_info = {"ts": "1700000000000"}
        resp = await self.server.h_intent_remove(R())
        self.assertEqual(resp.status, 200)
        payload = json.loads(resp.text)
        self.assertTrue(payload["removed"])
        self.assertTrue(payload["undo"], "a press that deletes owes a token")
        self.assertEqual(self.intents.listing(), [])
        self.assertEqual(self.autos.read_text(encoding="utf-8"), AUTOS)

    async def test_the_undo_does_not_try_to_revert_a_file_it_never_wrote(self):
        row = self.intents.arm(
            {"ts": 1_700_000_001_000, "title": "Porch light once",
             "intent": {"sentence": "when the guests leave, "
                                    "turn the porch light off"}},
            {"automation_id": "brain_1700000001",
             "entity_id": "automation.porch_light_once"})
        self.assertIsNotNone(row)

        class R:
            match_info = {"ts": "1700000001000"}
        token = json.loads((await self.server.h_intent_remove(R())).text)["undo"]

        class U:
            match_info = {"token": token}
        # `call_core_service` still raises: an undo with nothing written
        # must not reload either, and the row must come back regardless.
        resp = await self.server.h_undo(U())
        payload = json.loads(resp.text)
        self.assertTrue(payload.get("undone"), payload)
        # `reloaded` is True because nothing was reloaded: the stub above
        # raises, so a reload attempted here would have come back False.
        self.assertTrue(payload.get("reloaded"), payload)
        self.assertEqual([r["ts"] for r in payload["intents"]],
                         [1_700_000_001_000])
        self.assertEqual(self.autos.read_text(encoding="utf-8"), AUTOS)

    async def test_an_entry_that_IS_there_still_goes_through_the_splice(self):
        """The `missing` branch must not swallow a real removal."""
        calls = []

        async def note(domain, service, *a, **k):
            calls.append((domain, service))
        self.ha_data.call_core_service = note
        gone = self.server._wait_for_gone
        self.server._wait_for_gone = lambda eid: asyncio.sleep(0, True)
        try:
            written, failure = await self.server._remove_automation(
                "morning_lights", "automation.morning_lights")
        finally:
            self.server._wait_for_gone = gone
        self.assertEqual(failure, "")
        self.assertIsNotNone(written)
        self.assertNotIn("morning_lights",
                         self.autos.read_text(encoding="utf-8"))
        self.assertEqual(calls, [("automation", "reload")])


if __name__ == "__main__":
    unittest.main()
