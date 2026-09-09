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
import categories as shipped_categories  # noqa: E402
import prompt_store  # noqa: E402
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
            # accept() records which shipped categories this home asked
            # for, which is a write to prompt_store's own file. Every
            # store here takes its path from the environment so a test
            # can point it somewhere; this one is only reachable from
            # the accept path, so it went unredirected and the write
            # landed on the real /data — invisible to anyone running as
            # root, and a PermissionError on CI.
            "prompts": prompt_store.OVERRIDES_FILE,
        }
        settings_store.SETTINGS_FILE = str(root / "settings.json")
        onboarding.STATE_FILE = root / "onboarding.json"
        onboarding.STUDY_REQUESTS_DIR = root / "study_requests"
        onboarding.CURRICULUM_FILE = root / "curriculum.json"
        onboarding.MEMORY_FILE = root / "memory.md"
        user_categories.USER_CATS_FILE = str(root / "user_cats.json")
        hypotheses.HYPOTHESES_FILE = root / "hypotheses.jsonl"
        prompt_store.OVERRIDES_FILE = str(root / "prompt_overrides.json")

    def tearDown(self):
        settings_store.SETTINGS_FILE = self._old["settings"]
        onboarding.STATE_FILE = self._old["state"]
        onboarding.STUDY_REQUESTS_DIR = self._old["requests"]
        onboarding.CURRICULUM_FILE = self._old["curriculum"]
        onboarding.MEMORY_FILE = self._old["memory"]
        user_categories.USER_CATS_FILE = self._old["cats"]
        hypotheses.HYPOTHESES_FILE = self._old["hyp"]
        prompt_store.OVERRIDES_FILE = self._old["prompts"]
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


class TestStepZeroAsksWhereBrainMaySpeak(OnboardingCase):
    """The morning brief is the one place brAIn reaches a person where
    they already are, and it shipped off, behind two Configuration-tab
    options nobody had been told about. Asking costs one screen."""

    SERVICES = {
        "notify.mobile_app_bens_phone", "notify.mobile_app_kitchen_tablet",
        "notify.persistent_notification", "notify.send_message",
        "light.turn_on", "automation.reload",
    }

    def test_only_services_that_can_take_a_message_are_offered(self):
        rows = onboarding.notify_candidates(self.SERVICES)
        offered = [r["service"] for r in rows]
        self.assertNotIn("light.turn_on", offered)
        self.assertNotIn("automation.reload", offered)
        self.assertIn("notify.persistent_notification", offered)

    def test_the_entity_transport_is_left_out(self):
        """`notify.send_message` takes an entity_id rather than a target,
        so calling it the way everything here calls a notify service does
        nothing at all."""
        offered = [r["service"] for r in onboarding.notify_candidates(self.SERVICES)]
        self.assertNotIn("notify.send_message", offered)

    def test_phones_come_first_and_are_the_ones_that_take_buttons(self):
        rows = onboarding.notify_candidates(self.SERVICES)
        self.assertTrue(rows[0]["phone"])
        self.assertTrue(rows[0]["buttons"])
        self.assertFalse(
            [r for r in rows if r["service"] == "notify.persistent_notification"
             ][0]["buttons"])

    def test_a_house_with_no_notify_service_gets_an_empty_list(self):
        """Not a made-up default: a brief nobody sees is the thing this
        step exists to prevent."""
        self.assertEqual(onboarding.notify_candidates(set()), [])
        self.assertEqual(onboarding.notify_candidates(None), [])

    def test_choosing_a_service_turns_the_brief_on(self):
        saved = onboarding.save_notify("notify.mobile_app_bens_phone", 22, 7)
        self.assertEqual(saved["findings_notify_service"],
                         "notify.mobile_app_bens_phone")
        self.assertEqual(saved["notify_quiet_start"], "22")
        self.assertEqual(saved["notify_quiet_end"], "7")
        self.assertIs(saved["morning_brief"], True)
        stored = settings_store.load()
        self.assertEqual(stored["findings_notify_service"],
                         "notify.mobile_app_bens_phone")
        self.assertIs(stored["morning_brief"], True)

    def test_saying_no_to_the_brief_is_recorded_rather_than_inferred(self):
        """Somebody who says no must not be asked again by a rule that
        reads the service."""
        saved = onboarding.save_notify("notify.mobile_app_bens_phone",
                                       brief=False)
        self.assertIs(saved["morning_brief"], False)

    def test_skipping_the_step_leaves_the_brief_off(self):
        saved = onboarding.save_notify(None)
        self.assertIsNone(saved["findings_notify_service"])
        self.assertIs(saved["morning_brief"], False)

    def test_the_hours_have_to_be_hours(self):
        for bad in ("half past", 24, -1, "99"):
            with self.subTest(bad):
                with self.assertRaises(ValueError):
                    onboarding.save_notify("notify.x", quiet_start=bad)

    def test_an_empty_hour_is_unset_rather_than_midnight(self):
        saved = onboarding.save_notify("notify.x", quiet_start="", quiet_end=None)
        self.assertIsNone(saved["notify_quiet_start"])
        self.assertIsNone(saved["notify_quiet_end"])

    def test_it_says_what_has_to_be_pasted_by_hand(self):
        """`addon_options.write` knows only the six generation options, so
        this choice cannot reach the Configuration tab — and an add-on
        that quietly kept a setting somewhere that tab does not show is
        the drift `_options_sync` exists to end."""
        saved = onboarding.save_notify("notify.mobile_app_bens_phone", 22, 7)
        pasted = "\n".join(saved["manual"])
        self.assertIn('findings_notify_service: "notify.mobile_app_bens_phone"',
                      pasted)
        self.assertIn('notify_quiet_start: "22"', pasted)
        self.assertIn("morning_brief: true", pasted)

    def test_nothing_chosen_is_nothing_to_paste(self):
        self.assertEqual(onboarding.save_notify(None)["manual"], [])

    def test_the_state_says_whether_the_step_was_answered(self):
        self.assertFalse(onboarding.notify_state()["asked"])
        onboarding.save_notify(None)
        self.assertTrue(onboarding.notify_state()["asked"])
        self.assertIn("notify", onboarding.state())


class TestInsightsIsWhatYouAskedFor(OnboardingCase):
    """Nine cards used to appear the moment onboarding finished — the
    generic ones the whole flow exists to avoid, beside the two somebody
    actually ticked."""

    def _offer(self, *titles):
        onboarding.save_recommendations({
            "recommendations": [
                {"title": t, "icon": "✨", "focus": f"Analyse {t}.", "why": ""}
                for t in titles],
            "shipped": [], "sparse": False, "missing": ""})

    def test_an_install_that_was_never_asked_keeps_every_card(self):
        """Absent flag = old behaviour. A release that silently deleted
        somebody's dashboard would be a worse failure than the one this
        fixes."""
        self.assertIsNone(prompt_store.accepted_ids())
        self.assertEqual(len(prompt_store.visible_categories()),
                         len(shipped_categories.CATEGORIES))

    def test_a_fresh_install_gets_only_what_was_ticked(self):
        self._offer("Alpha")
        onboarding.accept([0], ["energy", "climate"])
        self.assertTrue(settings_store.load()["curated_categories"])
        self.assertEqual([c["id"] for c in prompt_store.visible_categories()],
                         ["energy", "climate"])

    def test_an_id_the_catalog_does_not_hold_is_dropped(self):
        self._offer("Alpha")
        onboarding.accept([0], ["energy", "nonsense"])
        self.assertEqual([c["id"] for c in prompt_store.visible_categories()],
                         ["energy"])

    def test_ticking_none_leaves_the_dashboard_empty_on_purpose(self):
        self._offer("Alpha")
        onboarding.accept([0], [])
        self.assertEqual(prompt_store.visible_categories(), [])
        self.assertEqual(prompt_store.accepted_ids(), set())

    def test_skipping_curates_too(self):
        onboarding.skip()
        self.assertTrue(settings_store.load()["curated_categories"])
        self.assertEqual(prompt_store.visible_categories(), [])

    def test_the_first_card_survives_not_being_ticked(self):
        """It is already on the dashboard by the time anybody reaches the
        choose step, and dropping it here would delete a card somebody
        has been reading for the length of the syllabus."""
        onboarding.admit_first_card()
        self._offer("Alpha")
        onboarding.accept([0], [])
        self.assertEqual([c["id"] for c in prompt_store.visible_categories()],
                         [onboarding.FIRST_CARD])

    def test_a_removed_card_stays_removed_on_a_curated_install(self):
        """Two filters answering different questions: `hidden` is a card
        somebody deleted, `accepted` is the set they chose from."""
        self._offer("Alpha")
        onboarding.accept([0], ["energy", "climate"])
        prompt_store.save_override("climate", {"hidden": True})
        self.assertEqual([c["id"] for c in prompt_store.visible_categories()],
                         ["energy"])

    def test_a_corrupt_file_shows_everything_rather_than_nothing(self):
        """"I could not look" and "you chose none" are different claims,
        and only the second may empty somebody's dashboard."""
        onboarding.accept([], ["energy"])
        Path(prompt_store.OVERRIDES_FILE).write_text("not json")
        self.assertIsNone(prompt_store.accepted_ids())
        self.assertEqual(len(prompt_store.visible_categories()),
                         len(shipped_categories.CATEGORIES))

    def test_the_recommend_step_asks_for_shipped_cards_by_id(self):
        prompt = onboarding.build_prompt("- the hall is cold", {"entities": []})
        self.assertIn("GENERAL CARDS THAT SHIP", prompt)
        for cat in shipped_categories.CATEGORIES:
            self.assertIn(f"- {cat['id']}:", prompt)

    def test_a_reply_naming_shipped_cards_is_parsed(self):
        out = onboarding.parse_recommendations(json.dumps({
            "recommendations": [],
            "shipped": [{"id": "energy", "why": "you have six meters"},
                        {"id": "energy", "why": "duplicate"},
                        {"id": "made-up", "why": "nope"}],
            "sparse": False}))
        self.assertEqual([s["id"] for s in out["shipped"]], ["energy"])
        self.assertEqual(out["shipped"][0]["why"], "you have six meters")
        self.assertEqual(out["shipped"][0]["title"], "Energy")

    def test_a_home_with_only_a_shipped_card_is_not_sparse(self):
        """Sparse is about whether this home has enough for ANY card, and
        reading it otherwise shows "there is not enough here" above a
        list of things to accept."""
        out = onboarding.parse_recommendations(json.dumps({
            "recommendations": [], "shipped": [{"id": "energy"}]}))
        self.assertFalse(out["sparse"])

    def test_a_home_with_nothing_at_all_is_still_sparse(self):
        out = onboarding.parse_recommendations(json.dumps({
            "recommendations": [], "shipped": [], "sparse": False,
            "missing": "there are eleven entities here"}))
        self.assertTrue(out["sparse"])
        self.assertIn("eleven entities", out["missing"])


class TestTheOpeningSyllabusIsLighter(OnboardingCase):
    def test_an_onboarding_study_carries_a_turn_cap(self):
        """`brain learn` has no cap by design — depth is the deliverable
        — but five of them run back to back while somebody watches a
        progress bar."""
        onboarding.start_learning()
        requests = [json.loads(p.read_text())
                    for p in onboarding.STUDY_REQUESTS_DIR.glob("*.json")]
        self.assertTrue(requests)
        for request in requests:
            self.assertEqual(request["max_turns"], onboarding.STUDY_MAX_TURNS)

    def test_an_ordinary_study_request_carries_none(self):
        """An absent key is "whatever the watcher's default is", which is
        the no-cap behaviour every other caller wants."""
        onboarding.request_study("energy", tag="ask")
        request = json.loads(
            next(iter(onboarding.STUDY_REQUESTS_DIR.glob("*-ask-*.json"))
                 ).read_text())
        self.assertNotIn("max_turns", request)


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
