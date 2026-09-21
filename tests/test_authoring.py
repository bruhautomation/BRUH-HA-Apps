#!/usr/bin/env python3
"""A standing automation from a sentence (2.3).

`intents.py` arms a one-off; this is the rule that keeps happening, drafted
by the same run, refused for the same reasons, and offered as an ordinary
proposal with the two simulations' case on it. The mutation each test
catches:

  a one-off handed to the standing builder  -> a rule that fires every
                                              evening about a thing meant
                                              to happen once
  a trigger nobody can replay               -> a card with no check on it
  an action that names nothing              -> an automation that does
                                              nothing, offered as one
  a protected target                        -> a card the writer will
                                              refuse, which is a wasted yes
  a case line that reads a refusal as zero  -> "it would never have fired"
                                              about a rule brAIn could
                                              not replay
"""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "brain", "panel"))

ANSWER = {
    "once": False,
    "plain": "Turn the porch light on whenever the front door opens.",
    "trigger": [{"platform": "state", "entity_id": "binary_sensor.front_door",
                 "to": "on"}],
    "action": [{"service": "light.turn_on",
                "target": {"entity_id": "light.porch"}}],
}
SENTENCE = "whenever the front door opens, turn the porch light on"


class AuthoringCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._env = dict(os.environ)
        os.environ["BRAIN_INTENTS_FILE"] = str(Path(self.tmp.name) / "intents.json")
        os.environ.pop("BRAIN_PROTECTED_ENTITIES", None)
        self.addCleanup(self._restore)
        for name in ("authoring", "intents", "automation_writer"):
            sys.modules.pop(name, None)
        self.authoring = importlib.import_module("authoring")

    def _restore(self):
        os.environ.clear()
        os.environ.update(self._env)
        for name in ("authoring", "intents", "automation_writer"):
            sys.modules.pop(name, None)

    def build(self, answer=None, patterns=None, sentence=SENTENCE):
        return self.authoring.build(sentence, answer or dict(ANSWER),
                                    1_700_000_000_000, patterns)


class TestWhatItBuilds(AuthoringCase):
    def test_a_standing_rule_is_an_ordinary_proposal_with_its_case_on_it(self):
        out = self.build()
        self.assertNotIn("refused", out)
        self.assertEqual(out["kind"], "automation")
        self.assertEqual(out["source"], "sentence")
        cfg = out["config"]
        self.assertEqual(cfg["id"], "brain_asked_1700000000000")
        self.assertEqual(cfg["mode"], "single")
        self.assertEqual([a["service"] for a in cfg["action"]], ["light.turn_on"],
                         "nothing here adds a disarm action")
        self.assertNotIn("alias", cfg)
        self.assertEqual(out["spoken"]["sentence"], SENTENCE)
        self.assertEqual(out["spoken"]["plain"], ANSWER["plain"])
        self.assertIsNone(out["spoken"]["against_you"])
        self.assertIn(SENTENCE, out["why"])
        self.assertIn(ANSWER["plain"], out["why"])
        self.assertEqual(out["title"][0], "W")

    def test_the_writer_takes_the_id_it_minted(self):
        import automation_writer
        entry = automation_writer.entry_for(self.build())
        self.assertEqual(entry["id"], "brain_asked_1700000000000")


class TestTheRefusals(AuthoringCase):
    def test_a_one_off_is_refused_rather_than_made_standing(self):
        out = self.build({**ANSWER, "once": True})
        self.assertIn("one-off", out["refused"])
        self.assertNotIn("config", out)

    def test_nothing_found_is_said_in_the_models_own_words(self):
        out = self.build({"once": False, "error": "no porch light here"})
        self.assertIn("no porch light here", out["refused"])

    def test_no_trigger_or_no_action(self):
        self.assertIn("no trigger or no action",
                      self.build({"once": False, "plain": "x"})["refused"])
        self.assertIn("no trigger or no action", self.build(
            {**ANSWER, "action": []})["refused"])

    def test_a_trigger_nobody_can_replay(self):
        out = self.build({**ANSWER, "trigger": [{"platform": "webhook",
                                                  "webhook_id": "x"}]})
        self.assertIn("will not offer", out["refused"])
        self.assertIn("replay", out["refused"])

    def test_an_action_that_names_nothing(self):
        out = self.build({**ANSWER, "action": [{"service": "light.turn_on"}]})
        self.assertIn("did not name anything", out["refused"])

    def test_a_protected_target_is_refused_at_the_producer(self):
        out = self.build(patterns=["light.porch"])
        self.assertIn("protected", out["refused"].lower())


class TestTheCaseLine(AuthoringCase):
    def line(self, replay, graded=None):
        return self.authoring.case_line(replay, graded, 30)

    def test_a_refusal_is_a_sentence_and_never_a_zero(self):
        line = self.line({"refused": True, "error": "webhook triggers cannot be replayed"})
        self.assertIn("could not replay", line)
        self.assertIn("webhook", line)
        self.assertNotIn(" 0 ", line)
        self.assertIn("could not replay", self.line(None))

    def test_nothing_fired_says_so(self):
        line = self.line({"would_run": 0, "days": 30})
        self.assertIn("fired 0 times", line)
        self.assertIn("nothing it waits for happened", line)

    def test_the_two_simulations_make_one_sentence(self):
        line = self.line({"would_run": 9, "days": 30},
                         {"would_fire": 4, "agreed": 3, "contradicted": 1,
                          "disagreed": 0, "days": 14})
        self.assertIn("fired 9 times", line)
        self.assertIn("4 in the last 14 days", line)
        self.assertIn("already done the same on 3", line)
        self.assertIn("did the opposite on 1", line)

    def test_a_grade_nothing_lined_up_with_says_that(self):
        line = self.line({"would_run": 2, "days": 30},
                         {"would_fire": 2, "agreed": 0, "contradicted": 0,
                          "disagreed": 2, "days": 14})
        self.assertIn("nothing you did lined up", line)

    def test_a_grade_that_could_not_be_made_leaves_the_replay_alone(self):
        line = self.line({"would_run": 1, "days": 30},
                         {"refused": True, "error": "not one entity"})
        self.assertEqual(line, "Over the last 30 days it would have fired 1 time.")

    def test_no_firings_inside_the_fortnight(self):
        line = self.line({"would_run": 3, "days": 30},
                         {"would_fire": 0, "agreed": 0, "contradicted": 0,
                          "disagreed": 0, "days": 14})
        self.assertIn("none of those fell in the last 14 days", line)


class TestThePrompt(AuthoringCase):
    def test_it_asks_the_question_the_one_off_prompt_presumed(self):
        self.assertIn('"once": false', self.authoring.SYSTEM)
        self.assertIn("standing rule", self.authoring.SYSTEM)
        for kind in ("time", "state", "numeric_state", "template"):
            self.assertIn(f"`{kind}`", self.authoring.SYSTEM)
        self.assertIn("after dark", self.authoring.SYSTEM)

    def test_the_schema_and_the_prompt_builder_are_the_one_offs(self):
        import intents
        self.assertIs(self.authoring.SCHEMA, intents.SCHEMA)
        self.assertIn(SENTENCE, self.authoring.prompt(SENTENCE, {}))


if __name__ == "__main__":
    unittest.main()
