#!/usr/bin/env python3
"""First-run flow: learn the home, then propose cards worth having.

The behaviour that matters here is what a *fresh* install does — it must
ship no cards, generate nothing, and refuse to invent generic ones for a
home it hasn't looked at.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))

import hypotheses  # noqa: E402
import onboarding  # noqa: E402
import settings_store  # noqa: E402
import user_categories  # noqa: E402


class OnboardingCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self._old = {
            "settings": settings_store.SETTINGS_FILE,
            "state": onboarding.STATE_FILE,
            "requests": onboarding.STUDY_REQUESTS_DIR,
            "curriculum": onboarding.CURRICULUM_FILE,
            "memory": onboarding.MEMORY_FILE,
            "cats": user_categories.USER_CATS_FILE,
            "hyp": hypotheses.HYPOTHESES_FILE,
        }
        settings_store.SETTINGS_FILE = str(root / "settings.json")
        onboarding.STATE_FILE = root / "onboarding.json"
        onboarding.STUDY_REQUESTS_DIR = root / "study_requests"
        onboarding.CURRICULUM_FILE = root / "curriculum.json"
        onboarding.MEMORY_FILE = root / "memory.md"
        user_categories.USER_CATS_FILE = str(root / "user_cats.json")
        hypotheses.HYPOTHESES_FILE = root / "hypotheses.jsonl"

    def tearDown(self):
        settings_store.SETTINGS_FILE = self._old["settings"]
        onboarding.STATE_FILE = self._old["state"]
        onboarding.STUDY_REQUESTS_DIR = self._old["requests"]
        onboarding.CURRICULUM_FILE = self._old["curriculum"]
        onboarding.MEMORY_FILE = self._old["memory"]
        user_categories.USER_CATS_FILE = self._old["cats"]
        hypotheses.HYPOTHESES_FILE = self._old["hyp"]
        self.tmp.cleanup()

    def _studied(self, *topics):
        onboarding.CURRICULUM_FILE.write_text(
            json.dumps({t: {"ts": 1700000000} for t in topics}))


class TestOnboardedFlag(OnboardingCase):
    def test_a_fresh_install_is_not_onboarded(self):
        self.assertFalse(onboarding.is_onboarded())

    def test_the_flag_round_trips_through_storage(self):
        """DEFAULTS, save() and load() are three separate places. Adding the
        key to two of them wrote True and read back False."""
        settings_store.save({"onboarded": True})
        self.assertIs(settings_store.load()["onboarded"], True)
        self.assertTrue(onboarding.is_onboarded())

    def test_the_flag_must_be_a_boolean(self):
        with self.assertRaises(ValueError):
            settings_store.save({"onboarded": "yes"})


class TestLearningPhase(OnboardingCase):
    def test_queues_the_opening_syllabus(self):
        result = onboarding.start_learning()
        self.assertEqual(result["queued"], list(onboarding.FIRST_TOPICS))
        queued = sorted(onboarding.STUDY_REQUESTS_DIR.glob("*.json"))
        self.assertEqual(len(queued), len(onboarding.FIRST_TOPICS))
        topics = {json.loads(p.read_text())["topic"] for p in queued}
        self.assertEqual(topics, set(onboarding.FIRST_TOPICS))

    def test_resuming_does_not_restudy(self):
        """The panel can be closed and reopened mid-run, and a study session
        is expensive — clicking again must not pay for it twice."""
        self._studied("naming", "energy")
        result = onboarding.start_learning()
        self.assertNotIn("naming", result["queued"])
        self.assertNotIn("energy", result["queued"])
        self.assertIn("climate", result["queued"])

    def test_progress_reports_what_is_left(self):
        self._studied("naming", "presence")
        p = onboarding.learning_progress()
        self.assertEqual(p["done"], ["naming", "presence"])
        self.assertFalse(p["complete"])
        self.assertIn("energy", p["remaining"])

    def test_complete_only_when_every_topic_is_done(self):
        self._studied(*onboarding.FIRST_TOPICS)
        self.assertTrue(onboarding.learning_progress()["complete"])

    def test_a_finished_syllabus_with_an_empty_document_is_not_ready(self):
        """Facts reach the document only at consolidation. Recommending from
        an empty memory would produce exactly the generic cards this flow
        exists to avoid."""
        self._studied(*onboarding.FIRST_TOPICS)
        p = onboarding.learning_progress()
        self.assertTrue(p["complete"])
        self.assertFalse(p["memory_ready"])

        onboarding.MEMORY_FILE.write_text("# Home Memory\n\n- " + "x" * 300)
        self.assertTrue(onboarding.learning_progress()["memory_ready"])


class TestRecommendationParsing(OnboardingCase):
    def test_parses_a_clean_reply(self):
        out = onboarding.parse_recommendations(json.dumps({
            "recommendations": [
                {"title": "Heat pump share", "icon": "🔥",
                 "focus": "Track the heat pump against total draw.",
                 "why": "It is 60% of your usage."}],
            "sparse": False}))
        self.assertEqual(len(out["recommendations"]), 1)
        self.assertFalse(out["sparse"])
        self.assertEqual(out["recommendations"][0]["title"], "Heat pump share")

    def test_tolerates_code_fences(self):
        out = onboarding.parse_recommendations(
            '```json\n{"recommendations": [{"title": "A", "focus": "B"}]}\n```')
        self.assertEqual(len(out["recommendations"]), 1)

    def test_drops_entries_missing_a_title_or_focus(self):
        out = onboarding.parse_recommendations(json.dumps({
            "recommendations": [
                {"title": "Good", "focus": "Real focus"},
                {"title": "", "focus": "no title"},
                {"title": "no focus", "focus": "  "},
                "not even an object"]}))
        self.assertEqual([r["title"] for r in out["recommendations"]], ["Good"])

    def test_caps_the_list(self):
        many = [{"title": f"C{i}", "focus": "f"} for i in range(20)]
        out = onboarding.parse_recommendations(json.dumps({"recommendations": many}))
        self.assertLessEqual(len(out["recommendations"]),
                             onboarding.MAX_RECOMMENDATIONS)

    def test_a_sparse_home_gets_no_canned_cards(self):
        """The whole point: generic cards about an unknown home are noise, so
        an empty list is the correct answer, not a reason to invent some."""
        out = onboarding.parse_recommendations(json.dumps({
            "recommendations": [], "sparse": True,
            "missing": "No history and only three entities."}))
        self.assertEqual(out["recommendations"], [])
        self.assertTrue(out["sparse"])
        self.assertIn("three entities", out["missing"])

    def test_an_empty_list_counts_as_sparse_even_if_unflagged(self):
        out = onboarding.parse_recommendations(json.dumps({"recommendations": []}))
        self.assertTrue(out["sparse"])

    def test_unparseable_output_raises(self):
        with self.assertRaises(ValueError):
            onboarding.parse_recommendations("I'm sorry, I can't do that.")


class TestChoosing(OnboardingCase):
    def _offer(self, *titles):
        onboarding.save_recommendations({
            "recommendations": [
                {"title": t, "icon": "✨", "focus": f"Analyse {t}.", "why": ""}
                for t in titles],
            "sparse": False, "missing": ""})

    def test_only_the_chosen_cards_are_created(self):
        self._offer("Alpha", "Beta", "Gamma")
        created = onboarding.accept([0, 2])
        self.assertEqual([c["title"] for c in created], ["Alpha", "Gamma"])
        self.assertEqual(
            sorted(c["title"] for c in user_categories.load()), ["Alpha", "Gamma"])

    def test_choosing_finishes_onboarding(self):
        self._offer("Alpha")
        onboarding.accept([0])
        self.assertTrue(onboarding.is_onboarded())

    def test_choosing_none_still_finishes(self):
        """Reading the list and wanting none of it is a decision, not a
        dead end — otherwise the panel traps you on the first screen."""
        self._offer("Alpha")
        self.assertEqual(onboarding.accept([]), [])
        self.assertTrue(onboarding.is_onboarded())
        self.assertEqual(user_categories.load(), [])

    def test_out_of_range_indexes_are_ignored(self):
        self._offer("Alpha")
        created = onboarding.accept([0, 9, -1, "x"])
        self.assertEqual([c["title"] for c in created], ["Alpha"])

    def test_skip_finishes_with_nothing(self):
        onboarding.skip()
        self.assertTrue(onboarding.is_onboarded())
        self.assertEqual(user_categories.load(), [])

    def test_reset_reopens_the_flow_without_deleting_cards(self):
        self._offer("Alpha")
        onboarding.accept([0])
        onboarding.reset()
        self.assertFalse(onboarding.is_onboarded())
        self.assertEqual([c["title"] for c in user_categories.load()], ["Alpha"])


class TestPromptGrounding(OnboardingCase):
    def test_the_prompt_carries_what_was_learned(self):
        prompt = onboarding.build_prompt("- The dryer draws 3 kWh a cycle",
                                         {"entities": []})
        self.assertIn("The dryer draws 3 kWh a cycle", prompt)

    def test_rejected_lines_of_inquiry_are_passed_on(self):
        """Otherwise onboarding proposes a card built on something the
        homeowner has already said is wrong."""
        h = hypotheses.propose("The attic fan is broken — right?")
        hypotheses.reject(h["ts"])
        prompt = onboarding.build_prompt("memory", {"entities": []})
        self.assertIn("attic fan", prompt)

    def test_the_contract_forbids_generic_cards(self):
        self.assertIn("could not have been written for a different house",
                      onboarding.RECOMMEND_SYSTEM)
        self.assertIn("sparse", onboarding.RECOMMEND_SYSTEM)


if __name__ == "__main__":
    unittest.main()
