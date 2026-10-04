"""The first hour shows what it found, and ends on something to try.

Onboarding's half hour of study was a progress bar: five sessions each in
somebody's house for minutes, and nothing on screen said what any of them
had learned until a recommend pass turned it into cards. Two changes:

* `onboarding.reveals` reads what the study sessions filed AS IT LANDS —
  the memory inbox and `processed/` beside it, so a consolidation pass
  that filed a line does not take it off the screen — and rides
  `learning_progress` to the screen the poll already refreshes.
* the recommend pass may offer ONE automation, as a sentence, and ticking
  it sends the sentence through the ask bar's own drop with `trial: true`:
  drafted and refused or simulated by `authoring.build` exactly as a typed
  sentence is, and its shadow week started the moment the proposal lands.
  Nothing is written to the house by that press.
"""
from __future__ import annotations

import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PANEL = REPO / "brain" / "panel"
sys.path.insert(0, str(PANEL))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import onboarding  # noqa: E402
from test_proposal_accept import AcceptCase  # noqa: E402


def line(fact, source="study:presence", ts=1000):
    return json.dumps({"ts": ts, "source": source, "fact": fact,
                       "confidence": "medium"})


class TestWhatItFoundShowsAsItLands(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self._olds = (onboarding.INBOX_DIR, onboarding.STATE_FILE,
                      onboarding.CURRICULUM_FILE, onboarding.MEMORY_FILE)
        onboarding.INBOX_DIR = root / "inbox"
        onboarding.STATE_FILE = root / "onboarding.json"
        onboarding.CURRICULUM_FILE = root / "curriculum.json"
        onboarding.MEMORY_FILE = root / "memory.md"
        (onboarding.INBOX_DIR / "processed").mkdir(parents=True)

    def tearDown(self):
        (onboarding.INBOX_DIR, onboarding.STATE_FILE,
         onboarding.CURRICULUM_FILE, onboarding.MEMORY_FILE) = self._olds
        self.tmp.cleanup()

    def write(self, name, *lines, processed=False):
        folder = onboarding.INBOX_DIR / "processed" if processed else onboarding.INBOX_DIR
        (folder / name).write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_study_facts_newest_first_from_the_queue_and_the_archive(self):
        self.write("1000-study-presence.jsonl",
                   line("The house is up by 06:40.", ts=1000), processed=True)
        self.write("2000-study-devices.jsonl",
                   line("The garage freezer is on a smart plug.",
                        source="study:devices", ts=2000))
        got = onboarding.reveals()
        self.assertEqual([r["fact"] for r in got],
                         ["The garage freezer is on a smart plug.",
                          "The house is up by 06:40."])
        self.assertEqual([r["topic"] for r in got], ["devices", "presence"])

    def test_only_what_a_study_session_filed_and_only_since_onboarding_began(self):
        self.write("1-x.jsonl",
                   line("A voice fact.", source="voice", ts=5000),
                   line("FORGET: the old note", ts=5000),
                   line("An old study fact.", ts=10),
                   line("A fresh study fact.", source="study:adhoc", ts=5000),
                   line("A fresh study fact.", source="study:adhoc", ts=5001),
                   "{torn")
        got = onboarding.reveals(since=100)
        self.assertEqual([r["fact"] for r in got], ["A fresh study fact."])
        self.assertEqual(got[0]["topic"], "", "a topic outside the syllabus is not shown as one")

    def test_the_list_is_capped(self):
        self.write("1-study.jsonl", *[line(f"Fact {i}.", ts=1000 + i) for i in range(20)])
        self.assertEqual(len(onboarding.reveals()), onboarding.MAX_REVEALS)

    def test_the_progress_the_screen_polls_carries_them(self):
        onboarding._write_state({"phase": "learning", "started_at": 1500})
        self.write("1-study.jsonl", line("Too early.", ts=1000),
                   line("Found during onboarding.", ts=2000))
        got = onboarding.learning_progress(now=3000)
        self.assertEqual([r["fact"] for r in got["reveals"]],
                         ["Found during onboarding."])


class TestTheOneAutomationToTry(unittest.TestCase):
    def test_a_sentence_is_kept_and_a_question_is_not(self):
        self.assertEqual(onboarding.parse_try(
            {"sentence": "  When the back door opens after sunset,\n turn on the patio light.",
             "why": "seen most evenings"}),
            {"sentence": "When the back door opens after sunset, turn on the patio light.",
             "why": "seen most evenings"})
        self.assertIsNone(onboarding.parse_try({"sentence": "Should the patio light come on?"}))
        self.assertIsNone(onboarding.parse_try({"sentence": ""}))
        self.assertIsNone(onboarding.parse_try("turn on the light"))
        long = onboarding.parse_try({"sentence": "x" * 900})
        self.assertEqual(len(long["sentence"]), onboarding.MAX_TRY_CHARS)

    def test_the_recommend_reply_carries_it_and_the_store_keeps_it(self):
        reply = json.dumps({
            "recommendations": [{"title": "Garage freezer", "focus": "Watch it.",
                                 "why": "It is on a plug."}],
            "try": {"sentence": "When the back door opens after sunset, turn on the patio light.",
                    "why": "you do it by hand most evenings"},
        })
        parsed = onboarding.parse_recommendations(reply)
        self.assertEqual(parsed["try_rule"]["why"], "you do it by hand most evenings")
        with tempfile.TemporaryDirectory() as tmp:
            old = onboarding.STATE_FILE
            onboarding.STATE_FILE = Path(tmp) / "onboarding.json"
            try:
                onboarding.save_recommendations(parsed)
                stored = onboarding.stored_recommendations()
                self.assertEqual(stored["try_rule"], parsed["try_rule"])
                self.assertEqual(stored["tried_rule"], "")
                onboarding.mark_tried("the sentence")
                self.assertEqual(onboarding.stored_recommendations()["tried_rule"],
                                 "the sentence")
            finally:
                onboarding.STATE_FILE = old

    def test_a_reply_with_no_try_offers_none(self):
        parsed = onboarding.parse_recommendations(json.dumps({"recommendations": []}))
        self.assertIsNone(parsed["try_rule"])

    def test_the_contract_asks_for_one_grounded_and_safe(self):
        system = onboarding.RECOMMEND_SYSTEM
        self.assertIn('"try"', system)
        self.assertIn("AT MOST ONE", system)
        self.assertIn("Never a lock", system)


class TestTheRequestCarriesTheTrial(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.intents = importlib.import_module("intents")
        self._dir = self.intents.REQUEST_DIR
        self.intents.REQUEST_DIR = Path(self.tmp.name)

    def tearDown(self):
        self.intents.REQUEST_DIR = self._dir
        self.tmp.cleanup()

    def test_only_a_literal_true_rides(self):
        self.intents.request("When x, do y.", "onboarding", trial=True)
        self.intents.request("When a, do b.", "panel")
        got = sorted(self.intents.collect(), key=lambda r: r["sentence"])
        self.assertNotIn("trial", got[0])
        self.assertIs(got[1]["trial"], True)
        self.assertIsNone((self.intents.parse_request(
            {"ts": 1, "sentence": "s", "trial": "yes"}) or {}).get("trial"))


STANDING = json.dumps({
    "once": False,
    "plain": "Turn the patio light on when the back door opens after sunset.",
    "trigger": [{"platform": "state", "entity_id": "binary_sensor.back_door", "to": "on"}],
    "condition": [{"condition": "sun", "after": "sunset"}],
    "action": [{"service": "light.turn_on", "target": {"entity_id": "light.patio"}}],
})
ONE_OFF = json.dumps({
    "once": True,
    "plain": "Turn the porch light off once the guests leave.",
    "trigger": [{"platform": "state", "entity_id": "binary_sensor.front_door",
                 "to": "off", "for": {"minutes": 10}}],
    "action": [{"service": "light.turn_off", "target": {"entity_id": "light.porch"}}],
})


class TestTheFirstHourEndsOnATrial(AcceptCase):
    """The onboarding accept route into the real intent drain."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.answers = [STANDING]
        self.prompts: list[str] = []
        engine = self.server.engine
        self._old_analyst = engine.run_analyst

        def analyst(prompt, system, *a, **kw):
            self.prompts.append(prompt)
            text = self.answers.pop(0) if self.answers else ""
            return {"ok": bool(text), "text": text, "error": "", "meta": {}}

        engine.run_analyst = analyst
        self.addCleanup(setattr, engine, "run_analyst", self._old_analyst)
        import ha_data
        old_orient = ha_data.collect_orientation

        async def orient(question=None):
            return {"areas": {"Garden": 2}, "domains": {"light": 2},
                    "meta": {"now": "2026-10-04T09:00:00"}}

        ha_data.collect_orientation = orient
        self.addCleanup(setattr, ha_data, "collect_orientation", old_orient)

        # The onboarding store, its own; and `accept` stubbed, because what
        # it writes (settings, the shipped-card list) is not what this is
        # about and lives under /data.
        ob = self.server.onboarding
        old_state, old_accept = ob.STATE_FILE, ob.accept
        ob.STATE_FILE = Path(self.tmp.name) / "onboarding.json"
        ob.accept = lambda picked, shipped=None: []
        self.addCleanup(setattr, ob, "STATE_FILE", old_state)
        self.addCleanup(setattr, ob, "accept", old_accept)
        ob.save_recommendations({
            "recommendations": [], "shipped": [], "sparse": False, "missing": "",
            "try_rule": {"sentence": "the back door opens after sunset, turn on the patio light",
                         "why": "by hand most evenings"}})

    async def accept(self, **body):
        resp = await self.client.post("/api/onboarding/accept",
                                      json={"accept": [], "shipped": [], **body})
        return resp.status, await resp.json()

    async def test_ticked_it_is_simulated_and_its_week_starts(self):
        status, out = await self.accept(try_rule=True)
        self.assertEqual(status, 200, out)
        # Put in the shape the ask bar's third verb reads.
        self.assertEqual(out["tried"],
                         "From now on, the back door opens after sunset, turn on the patio light")
        self.assertEqual(self.server.onboarding.stored_recommendations()["tried_rule"],
                         out["tried"])
        self.assertEqual(await self.server._apply_intent_requests(), 1)
        [row] = self.proposals.listing()
        self.assertEqual(row["kind"], "automation")
        self.assertEqual(row["status"], "trialling", "the week did not start")
        self.assertIn("trial_ends_at", row)
        self.assertIn("back door", self.prompts[0])
        # Nothing reached the house: a trial replays, it does not write.
        self.assertNotIn("brain_asked_", (self.config / "automations.yaml").read_text())

    async def test_unticked_nothing_is_queued(self):
        status, out = await self.accept(try_rule=False)
        self.assertEqual((status, out["tried"]), (200, ""))
        self.assertEqual(await self.server._apply_intent_requests(), 0)
        self.assertEqual(self.proposals.listing(), [])

    async def test_a_one_off_answer_ignores_the_trial(self):
        self.answers = [ONE_OFF]
        await self.accept(try_rule=True)
        await self.server._apply_intent_requests()
        [row] = self.proposals.listing()
        self.assertEqual(row["kind"], "intent")
        self.assertEqual(row["status"], "proposed")


if __name__ == "__main__":
    unittest.main()
