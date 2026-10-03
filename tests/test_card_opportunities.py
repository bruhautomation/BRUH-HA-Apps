#!/usr/bin/env python3
"""What a card says the house is missing becomes an automation offer.

A card could only say "the patio light should come on when the back door
opens after dark" as prose in its summary, which nothing parses: the
improvements the Automations focus and the milestone frame explicitly ask
for were a dead end, and acting on one meant retyping it into the ask bar.
The contract has an ``opportunities`` field now, and ``_generate`` hands
each one to the ask bar's own intent drop — the same path a typed sentence
takes into drafting, replaying, grading and the Proposals tab.

It is an unattended producer, so it is held to what every scheduled Claude
run is held to (a credential, ``auto_enabled``, the budget), capped per
card and per day, and never re-offers what the same card offered last run.

Driven through the real ``_generate`` with the model's reply stubbed, the
same arrangement ``test_insights_knowledge.TestGenerateLearns`` uses; the
request it writes is read back through ``intents.collect`` — the drain the
ask bar's sentences go through — rather than by guessing at its file shape.
"""

import asyncio
import json
import sys
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import categories  # noqa: E402
import engine  # noqa: E402
import intents  # noqa: E402
import settings_store  # noqa: E402
import usage_store  # noqa: E402

from test_insights_knowledge import InsightsServerCase  # noqa: E402

PATIO = "When the back door opens after sunset, turn on the patio light"


class CardCase(InsightsServerCase):
    def setUp(self):
        super().setUp()
        settings_store.save({"onboarded": True, "auto_enabled": True,
                             "gather_mode": "snapshot"})
        self.reply = {
            "title": "Evening lights",
            "summary": "The patio is dark when the back door opens at night.",
            "highlights": [{"label": "Back door at night", "value": "9 times"}],
            "tags": ["lighting"],
            "opportunities": [
                {"text": PATIO,
                 "entities": ["binary_sensor.back_door", "light.patio",
                              "not an id"]},
            ],
            "html": "<!DOCTYPE html><html><body>ok</body></html>",
        }
        self._olds_card = (self.ha_data.collect_bundle, engine.run_claude,
                           engine.get_auth, intents.REQUEST_DIR,
                           dict(self.server.CARD_OPPS_STATE),
                           usage_store.USAGE_FILE, usage_store.LIMITS_FILE,
                           usage_store.budget_state)
        self.server.CARD_OPPS_STATE.update(day="", count=0)
        intents.REQUEST_DIR = Path(self.tmp.name) / "intent-requests"
        # The budget is read off files under /data and /config that every
        # other test on the machine may be spending into; this one's own.
        usage_store.USAGE_FILE = str(Path(self.tmp.name) / "usage.json")
        usage_store.LIMITS_FILE = str(Path(self.tmp.name) / "usage_limits.json")

        async def fake_collect(category, days, question=None):
            return {"entities": []}

        def fake_run(prompt, *a, **k):
            return {"ok": True, "text": json.dumps(self.reply), "error": "",
                    "meta": {"duration_ms": 5}}

        self.ha_data.collect_bundle = fake_collect
        engine.run_claude = fake_run
        engine.get_auth = lambda: {"type": "oauth", "value": "x"}

    def tearDown(self):
        (self.ha_data.collect_bundle, engine.run_claude, engine.get_auth,
         intents.REQUEST_DIR, old_state, usage_store.USAGE_FILE,
         usage_store.LIMITS_FILE, usage_store.budget_state) = self._olds_card
        self.server.CARD_OPPS_STATE.clear()
        self.server.CARD_OPPS_STATE.update(old_state)
        super().tearDown()

    def generate(self, insight_id="lighting"):
        asyncio.run(self.server._generate(insight_id))
        with open(Path(self.tmp.name) / f"{insight_id}.json") as f:
            return json.load(f)

    def queued(self):
        return intents.collect() if intents.REQUEST_DIR.exists() else []


class TestACardsSuggestionIsOffered(CardCase):
    def test_it_goes_into_the_intent_drop_the_ask_bar_uses(self):
        card = self.generate()
        requests = self.queued()
        self.assertEqual([r["sentence"] for r in requests], [PATIO])
        self.assertEqual(requests[0]["via"], "card:lighting")
        row = card["opportunities"][0]
        self.assertTrue(row["queued"])
        self.assertEqual(row["sentence"], PATIO)
        # An id that is not an id names nothing and is not kept.
        self.assertEqual(row["entities"], ["binary_sensor.back_door", "light.patio"])

    def test_a_sentence_that_is_not_a_rule_yet_is_put_in_its_shape(self):
        """The drain routes on the opening words, so a suggestion phrased
        as an instruction is handed over as a standing one."""
        self.reply["opportunities"] = [
            {"text": "Turn the porch light off at midnight every night"}]
        card = self.generate()
        self.assertEqual([r["sentence"] for r in self.queued()],
                         ["From now on, turn the porch light off at midnight "
                          "every night"])
        self.assertTrue(card["opportunities"][0]["queued"])

    def test_a_question_is_not_offered_as_a_rule(self):
        self.reply["opportunities"] = [
            {"text": "When did the patio light last come on?"}]
        card = self.generate()
        self.assertEqual(self.queued(), [])
        row = card["opportunities"][0]
        self.assertFalse(row["queued"])
        self.assertIn("question", row["why"])

    def test_a_card_offers_at_most_two(self):
        self.reply["opportunities"] = [
            {"text": f"When the hall motion fires after {h}:00, dim the hall light"}
            for h in (20, 21, 22, 23)]
        card = self.generate()
        self.assertEqual(len(card["opportunities"]),
                         self.server.MAX_CARD_OPPORTUNITIES)
        self.assertEqual(len(self.queued()), self.server.MAX_CARD_OPPORTUNITIES)

    def test_the_same_suggestion_next_run_is_not_offered_again(self):
        """Whatever was answered on Proposals is the answer; asking again
        would spend an authoring run to be told so."""
        self.generate()
        self.assertEqual(len(self.queued()), 1)
        intents.collect()            # the drain took it
        card = self.generate()
        self.assertEqual(self.queued(), [])
        row = card["opportunities"][0]
        self.assertTrue(row["queued"])
        self.assertIn("earlier run", row["why"])

    def test_a_card_with_nothing_to_suggest_writes_nothing(self):
        self.reply.pop("opportunities")
        card = self.generate()
        self.assertEqual(card["opportunities"], [])
        self.assertEqual(self.queued(), [])


class TestItIsGatedLikeEveryUnattendedRun(CardCase):
    def test_paused_says_so_on_the_card_and_queues_nothing(self):
        settings_store.save({"onboarded": True, "auto_enabled": False,
                             "gather_mode": "snapshot"})
        card = self.generate()
        self.assertEqual(self.queued(), [])
        row = card["opportunities"][0]
        self.assertFalse(row["queued"])
        self.assertEqual(row["why"], "automatic runs are paused")
        # The sentence is still on the card: the ⋯ puts it in the ask bar.
        self.assertEqual(row["sentence"], PATIO)

    def test_no_credential_holds_it(self):
        engine.get_auth = lambda: None
        card = self.generate()
        self.assertEqual(self.queued(), [])
        self.assertEqual(card["opportunities"][0]["why"],
                         "there is no Claude credential")

    def test_a_spent_budget_holds_it(self):
        real = usage_store.budget_state
        usage_store.budget_state = lambda settings: {**real(settings),
                                                     "blocked": True}
        card = self.generate()
        self.assertEqual(self.queued(), [])
        self.assertEqual(card["opportunities"][0]["why"],
                         "the session usage budget is spent")

    def test_the_days_cap_holds_whatever_the_cards_say(self):
        self.server.CARD_OPPS_STATE.update(
            day=time.strftime("%Y-%m-%d"),
            count=self.server.CARD_OPPORTUNITIES_PER_DAY)
        card = self.generate()
        self.assertEqual(self.queued(), [])
        self.assertIn("today", card["opportunities"][0]["why"])

    def test_a_drop_that_cannot_be_written_is_a_reason_not_a_failed_card(self):
        intents.REQUEST_DIR = Path("/proc/brain-nowhere/requests")
        card = self.generate()
        self.assertEqual(card["title"], "Evening lights")
        row = card["opportunities"][0]
        self.assertFalse(row["queued"])
        self.assertIn("could not be queued", row["why"])


class TestTheContract(unittest.TestCase):
    def test_the_schema_carries_the_field_and_nothing_loose(self):
        field = categories.CARD_SCHEMA["properties"]["opportunities"]
        item = field["items"]
        self.assertEqual(item["required"], ["text"])
        self.assertFalse(item["additionalProperties"])
        self.assertNotIn("opportunities", categories.CARD_SCHEMA["required"])

    def test_the_schema_validates_a_reply_carrying_one(self):
        import jsonschema  # noqa: PLC0415
        reply = {"title": "t", "summary": "s", "highlights": [], "html": "<p/>",
                 "opportunities": [{"text": PATIO, "entities": ["light.patio"]}]}
        jsonschema.validate(reply, categories.CARD_SCHEMA)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate({**reply, "opportunities": [{"entities": []}]},
                                categories.CARD_SCHEMA)

    def test_the_contract_tells_the_model_what_one_is(self):
        text = categories._CARD_CONTRACT
        self.assertIn('"opportunities"', text)
        self.assertIn("opportunities: usually none", text)
        # And that a broken thing is not one: those are findings.
        self.assertIn("Never something broken", text)

    def test_cleaning_is_pure_over_what_the_model_returned(self):
        import server  # noqa: PLC0415
        clean = server._card_opportunities
        self.assertEqual(clean(None), [])
        self.assertEqual(clean("When x, do y"), [])
        out = clean(["When the gate opens, light the drive",
                     {"text": "when the gate opens, light the drive!"},
                     {"text": "   "}, 7, {"entities": ["light.a"]}])
        self.assertEqual([o["text"] for o in out],
                         ["When the gate opens, light the drive"])

    def test_the_sentence_is_shaped_by_the_ask_bars_own_rules(self):
        import server  # noqa: PLC0415
        shape = server._opportunity_sentence
        self.assertEqual(shape(PATIO), PATIO)
        self.assertEqual(shape("Every time the dryer finishes, tell me"),
                         "Every time the dryer finishes, tell me")
        self.assertEqual(shape("Close the blinds at 4pm on hot days"),
                         "From now on, close the blinds at 4pm on hot days")
        # A proper noun at the start keeps its capital.
        self.assertEqual(shape("BRight should start the party at 8"),
                         "From now on, BRight should start the party at 8")
        for question in ("When did the boiler last run?",
                         "Should the porch light be on a timer?", ""):
            self.assertEqual(shape(question), "", question)


if __name__ == "__main__":
    unittest.main()
