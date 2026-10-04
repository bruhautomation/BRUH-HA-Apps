#!/usr/bin/env python3
"""The sentence somebody dictated is in the automation it became.

`automation_writer.entry_for` stamped one fixed description on every
accepted proposal — *"Proposed by brAIn from what you do by hand"* — which
is wrong for every rule anybody typed, and it threw away the one fact
nothing else in the house records: why the rule exists, in the person's own
words. The description now carries the sentence, and quotes a card's
suggestion as the card's rather than as the person's.

Driven through the real drain and the real accept (the `AcceptCase` harness:
a real `/config`, a real journal, the real panel and a fake Core), because
the sentence crosses three hands on the way — the drain stamps who said it,
`proposals.add` keeps it, `entry_for` writes it — and a test of the last
hand alone would prove only that it reads what the test handed it.

The mutation each test catches:

  the fixed description         -> "why does this rule exist" has no answer
  a card quoted as the person   -> words put in somebody's mouth in their
                                   own automations file
  a routine's description moved -> a rule nobody dictated claims a sentence
"""
from __future__ import annotations

import json
import os
import sys
import unittest

HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "brain", "panel"))

from test_proposal_accept import AcceptCase, proposal_obj  # noqa: E402

STANDING = json.dumps({
    "once": False,
    "plain": "Turn the porch light on whenever the front door opens.",
    "trigger": [{"platform": "state", "entity_id": "binary_sensor.front_door",
                 "to": "on"}],
    "action": [{"service": "light.turn_on",
                "target": {"entity_id": "light.porch"}}],
})
ONE_OFF = json.dumps({
    "once": True,
    "plain": "Turn the porch light off when the guests leave.",
    "trigger": [{"platform": "state", "entity_id": "binary_sensor.front_door",
                 "to": "off"}],
    "action": [{"service": "light.turn_off",
                "target": {"entity_id": "light.porch"}}],
})
SAID = "whenever the front door opens, turn the porch light on"


class SentenceCase(AcceptCase):

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.answers: list[str] = []
        self._old_analyst = self.server.engine.run_analyst

        def analyst(prompt, system, *a, **kw):
            text = self.answers.pop(0) if self.answers else ""
            return {"ok": bool(text), "text": text, "error": "", "meta": {}}

        self.server.engine.run_analyst = analyst
        self.addCleanup(setattr, self.server.engine, "run_analyst",
                        self._old_analyst)
        import ha_data

        self._old_orient = ha_data.collect_orientation

        async def orient(question=None, **kw):
            return {"areas": {"Porch": 3}, "domains": {"light": 4}}

        ha_data.collect_orientation = orient
        self.addCleanup(setattr, ha_data, "collect_orientation",
                        self._old_orient)

    async def drain(self, sentence: str, via: str) -> dict:
        self.intents.request(sentence, via)
        self.assertEqual(await self.server._apply_intent_requests(), 1)
        rows = self.proposals.listing()
        self.assertEqual(len(rows), 1, rows)
        return rows[0]

    async def accepted_entry(self, row: dict) -> dict:
        import yaml

        self.live.add(f"automation.{self.writer.slugify(row['title'])}")
        status, out = await self.accept(row["ts"])
        self.assertEqual(status, 200, out)
        entries = yaml.safe_load(self.automations())
        want = (row["config"].get("id")
                or f"{self.writer.ID_PREFIX}{int(row['ts'])}")
        mine = [e for e in entries if e.get("id") == want]
        self.assertEqual(len(mine), 1, entries)
        return mine[0]


class TestTheSentenceIsKept(SentenceCase):

    async def test_a_standing_rule_carries_the_persons_sentence(self):
        self.answers = [STANDING]
        row = await self.drain(SAID, "panel")
        self.assertEqual(row["spoken"]["via"], "panel")
        entry = await self.accepted_entry(row)
        self.assertIn(SAID, entry["description"])
        self.assertTrue(entry["description"].startswith("Asked for in brAIn"))
        self.assertNotIn("what you do by hand", entry["description"])

    async def test_a_one_off_carries_it_too(self):
        self.answers = [ONE_OFF]
        said = "when the guests leave, turn the porch light off"
        row = await self.drain(said, "service")
        self.assertEqual(row["intent"]["via"], "service")
        entry = await self.accepted_entry(row)
        self.assertIn(said, entry["description"])

    async def test_a_cards_suggestion_is_quoted_as_the_cards(self):
        self.answers = [STANDING]
        row = await self.drain(SAID, "card:energy")
        entry = await self.accepted_entry(row)
        self.assertTrue(entry["description"].startswith(
            "Suggested by a brAIn insight card"), entry["description"])
        self.assertNotIn("Asked for in brAIn", entry["description"])

    async def test_a_routine_nobody_dictated_keeps_the_old_line(self):
        row = self.offer()
        entry = await self.accepted_entry(row)
        self.assertIn("what you do by hand", entry["description"])

    def test_the_via_never_reaches_the_hashed_config(self):
        """`proposals.key_for` hashes the config, so a sentence typed on the
        panel and the same sentence said through `brain.intent` must be the
        same proposal — `via` rides beside the config, never in it."""
        obj = {**proposal_obj(), "spoken": {"sentence": SAID, "via": "panel"}}
        other = {**proposal_obj(), "spoken": {"sentence": SAID, "via": "service"}}
        self.assertEqual(self.proposals.key_for(obj),
                         self.proposals.key_for(other))


class TestTheDescriptionIsOneLine(unittest.TestCase):

    def test_newlines_and_runaway_sentences_are_folded(self):
        sys.path.insert(0, os.path.join(HERE, "..", "brain", "panel"))
        import automation_writer

        row = {"spoken": {"sentence": "turn the\nporch light\n\non " + "x" * 900,
                          "via": "panel"}}
        text = automation_writer.description_for(row, 0)
        self.assertNotIn("\n", text)
        self.assertLess(len(text), automation_writer.DESCRIPTION_SAID_MAX + 80)


if __name__ == "__main__":
    unittest.main()
