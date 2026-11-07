#!/usr/bin/env python3
"""Eight things a house found wrong with how findings and cards are worded.

1. developer words in a check's rows: held by `test_finding_words_sweep`;
2. one vocabulary: the shared prompts name the assistant and the owner one
   way, and no shipped prompt mixes "you" with "the homeowner";
3. a log error's detail says what it means, what it affects and usual
   against now, and never "something it was doing failed";
4. a card's first sentence is its conclusion; an absence of events or a
   closing guess is held back by code;
5. a device-health title is built from the measured state, and a finding
   whose words disagree about the state is caught;
6. a generic usual cause is not said once a look found the cause (the
   fix a look wrote stands);
7. and 8. a finding the look called noise, a side effect or a repeat is
   held, with the look's reason, never open at full severity.
"""

import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "brain" / "panel"))
sys.path.insert(0, str(BASE / "tests"))

import card_claims  # noqa: E402
import categories  # noqa: E402
import findings_store  # noqa: E402
import house_words  # noqa: E402
import prompt_kit  # noqa: E402
import sre  # noqa: E402
import triage  # noqa: E402
from test_cases import StoresCase  # noqa: E402


class TestOneVocabulary(unittest.TestCase):
    def test_the_shared_prompt_fixes_the_name_and_the_address(self):
        text = prompt_kit.IDENTITY
        self.assertIn('call it "brAIn"', text)
        self.assertIn('"you" and "your"', text)
        self.assertIn('never "the homeowner"', text)

    def test_the_card_contract_does_not_mix_the_owner_names(self):
        # The contract addresses the reader one way: the household.
        for name in ("the owner", "the user", "the homeowner"):
            self.assertNotIn(name, categories._CARD_CONTRACT.lower(), name)

    def test_one_finding_does_not_switch_voice(self):
        said = house_words.household(
            "The homeowner's plug is off. You can also reset it.")
        self.assertNotRegex(said.lower(), r"homeowner")
        self.assertNotRegex(house_words.household(
            "The owner already said so. Your hub is fine.").lower(), r"owner")


class TestTheCardPromptsNameTheReaderOneWay(unittest.TestCase):
    def test_no_homeowner_or_user_in_a_card_prompt(self):
        for text in (categories.SYSTEM_PROMPT, categories.ANALYST_SYSTEM,
                     categories.MEMORY_HEAD, categories._CARD_CONTRACT):
            self.assertNotRegex(text, r"(?i)\bthe (?:home ?owner|user)\b")


class TestALogErrorSaysWhatItMeans(unittest.TestCase):
    def test_the_stock_phrase_is_gone(self):
        for message in ("Something odd happened", "", "weird"):
            said = house_words.log_meaning(message)
            self.assertNotIn("something it was doing failed", said)
            self.assertNotRegex(said, r"[0-9{}]")

    def test_the_flood_check_says_meaning_effect_and_usual(self):
        from test_house_checks import NOW as CNOW, house
        from checks import integrations
        snap = house()
        snap["core_log"] = {"hours": 24, "lines": 300, "groups": [{
            "logger": "homeassistant.components.tado", "domain": "tado",
            "count": 1200, "last": CNOW, "ips": [],
            "message": "Something odd happened"}]}
        [row] = integrations.log_flood(snap, CNOW)
        self.assertNotIn("something it was doing failed", row["detail"])
        self.assertIn("1200 times", row["detail"])
        self.assertIn("Usually", row["detail"])
        self.assertIn("may not update", row["detail"])

    def test_a_second_example_the_night_check(self):
        logs = [{"message": "Something odd happened", "count": 12,
                 "last_hours_ago": 2.0, "integration": "tado"}]
        said = sre._log_said(logs, {"names": {}})
        self.assertNotIn("something it was doing failed", said)
        self.assertIn("well above", said)
        self.assertIn("may not update", said)


class TestACardLeadsWithItsConclusion(unittest.TestCase):
    def test_the_contract_asks_for_the_conclusion_then_usual_against_now(self):
        for text in (categories._CARD_CONTRACT, categories.SYSTEM_PROMPT,
                     categories.ANALYST_SYSTEM):
            self.assertIn("first sentence is the conclusion", text)
            self.assertIn("usual against now", text)
            self.assertIn("Never end on a guess", text)

    def test_a_card_ending_in_a_guess_loses_the_guess(self):
        out = {"summary": "The freezer held 0 °F, as usual. It may be the "
                          "new door seal."}
        changed = []
        card_claims.trim_guess(out, changed)
        self.assertEqual(out["summary"], "The freezer held 0 °F, as usual.")
        self.assertTrue(changed)

    def test_a_guess_with_a_figure_is_a_reading(self):
        out = {"summary": "Fine. It probably cycled 14 times."}
        card_claims.trim_guess(out, [])
        self.assertIn("14", out["summary"])

    def test_a_card_that_only_reports_an_absence_is_blind(self):
        card = {"title": "Garage door", "summary": "No openings were "
                "recorded today. The sensor stayed closed."}
        self.assertEqual(card_claims.blind_lead(card, "all fine"),
                         "nothing happened")
        # A second example: nothing but a guess.
        guess = {"title": "Hall humidity", "summary": "It may be the "
                 "shower. It could be the dryer."}
        self.assertEqual(card_claims.blind_lead(guess, "all fine"),
                         "an unproven guess")

    def test_a_comparison_makes_it_news(self):
        card = {"title": "Garage door", "summary": "No openings today "
                "against 6 on a usual day."}
        self.assertEqual(card_claims.blind_lead(card, "all fine"), "")


class TestADeviceTitleNamesTheMeasuredState(unittest.TestCase):
    def rec(self, **over):
        return {"id": "zha:1", "kind": "zigbee", "name": "Hall plug",
                "available": True, "lqi": 120, "last_seen_hours": 0.2,
                **over}

    def test_titles_come_from_the_state(self):
        title = sre._plain_title
        self.assertEqual(title(self.rec(available=False,
                                        last_seen_hours=5), {}),
                         "Hall plug has been offline for 5 hours")
        self.assertEqual(title(self.rec(lqi=20), {}),
                         "Hall plug has a weak signal to the Zigbee network")
        for t in (title(self.rec(available=False), {}), title(self.rec(), {})):
            self.assertNotIn("struggling", t)
        zw = {"id": "zw:1", "kind": "zwave", "name": "Pump", "status": "alive",
              "stats": {"commandsDroppedTX": 4}}
        self.assertEqual(title(zw, {}), "Z-Wave dropped 4 commands to Pump")

    def test_a_stock_verb_from_the_model_is_replaced(self):
        t, f = sre._one_state(self.rec(lqi=20), {}, "Hall plug is struggling",
                              "Its link reads 20.", "Move the router.")
        self.assertIn("weak signal", t)
        self.assertEqual(f, "Move the router.")

    def test_a_fix_for_a_state_the_detail_calls_fine_is_dropped(self):
        self.assertEqual(
            house_words.states_disagree(
                "Hall plug is offline", "The signal looked fine.",
                "Move the plug closer to improve its signal."), {"signal"})
        t, f = sre._one_state(
            self.rec(available=False, last_seen_hours=9), {},
            "Hall plug has been offline for 9 hours",
            "The signal looked fine, but it has not answered.",
            "Move the plug closer to improve its signal. Plug it back in.")
        self.assertNotIn("signal", f)
        self.assertIn("Plug it back in", f)

    def test_a_second_example_battery(self):
        self.assertEqual(
            house_words.states_disagree(
                "Door sensor battery is low", "Its battery reads full.",
                "Replace the battery."), {"battery"})
        self.assertFalse(house_words.states_disagree(
            "Door sensor is offline", "Its battery is low.",
            "Replace the battery."))


class TestALookThatSaysItCanWaitHoldsTheRow(StoresCase):
    def _row(self, **over):
        [row] = findings_store.add_many([{
            "text": "Garage opener logged errors", "detail": "It logged 9.",
            "fix": "Restart the opener.", "severity": "warning",
            "source": "check:integ.log_flood", "status": "triaging", **over}])
        return row

    def test_log_noise_is_held_with_the_looks_reason(self):
        row = self._row()
        findings_store.record_triage(
            {row["ts"]: ("elevated", "This is log noise and can wait.")})
        stored = findings_store.get(row["ts"])
        self.assertEqual(stored["status"], "held")
        self.assertIn("log noise", stored["triage"]["reason"])

    def test_a_side_effect_of_another_fault_is_held(self):
        row = self._row(text="Porch light unavailable")
        findings_store.record_triage({row["ts"]: (
            "elevated", "Probably a side effect of the open hub fault.")})
        self.assertEqual(findings_store.get(row["ts"])["status"], "held")

    def test_a_safety_row_is_never_held_on_a_sentence(self):
        row = self._row(text="Smoke alarm tripped", source="safety",
                        severity="critical")
        findings_store.record_triage(
            {row["ts"]: ("elevated", "Looks like log noise.")})
        self.assertNotEqual(findings_store.get(row["ts"])["status"], "held")

    def test_a_row_a_person_raised_again_stays(self):
        row = self._row()
        findings_store.record_triage({row["ts"]: ("elevated", "ok")})
        entry = findings_store._load()
        for e in entry:
            e["triage"]["elevated_by_person"] = True
        findings_store._write(entry)
        self.assertEqual(findings_store.look_concluded(
            findings_store.get(row["ts"]), "This can wait."), "")

    def test_a_refine_whose_step_says_nothing_is_needed_is_held(self):
        row = self._row()
        findings_store.record_triage({row["ts"]: ("elevated", "")})
        findings_store.refine(row["ts"], {
            "claim": "Opener logged errors", "kind": "problem",
            "detail": "The errors stopped an hour ago.",
            "fix": "Nothing needs doing; it cleared itself."})
        self.assertEqual(findings_store.get(row["ts"])["status"], "held")

    def test_a_refine_that_is_the_same_cause_is_held(self):
        row = self._row(text="Kitchen blind slow")
        findings_store.record_triage({row["ts"]: ("elevated", "")})
        findings_store.refine(row["ts"], {
            "claim": "Kitchen blind slow", "kind": "problem",
            "detail": "This is the same cause as the open hub fault.",
            "fix": "Restart the hub."})
        self.assertEqual(findings_store.get(row["ts"])["status"], "held")

    def test_a_look_that_found_a_real_problem_stays_open(self):
        row = self._row()
        findings_store.record_triage(
            {row["ts"]: ("elevated", "The opener has been offline 6 hours.")})
        self.assertEqual(findings_store.get(row["ts"])["status"], "open")

    def test_a_look_that_found_the_cause_drops_the_generic_one(self):
        row = self._row(
            text="Garage plug offline",
            fix="Check it still has power (a wall switch turned off is the "
                "usual cause). Press its button.")
        findings_store.record_triage({row["ts"]: ("elevated", "")})
        findings_store.refine(row["ts"], {
            "claim": "Garage plug offline", "kind": "problem",
            "detail": "The garage breaker tripped at 02:10."})
        fix = findings_store.get(row["ts"])["fix"]
        self.assertNotIn("usual cause", fix)
        self.assertIn("Press its button", fix)

    def test_a_row_nobody_looked_at_keeps_the_generic_sentence(self):
        row = self._row(fix="A wall switch turned off is the usual cause.")
        self.assertIn("usual cause", findings_store.get(row["ts"])["fix"])
        self.assertEqual(
            house_words.without_usual_cause("Plug it in. Most often it is "
                                            "the cable."), "Plug it in.")

    def test_the_words_are_one_vocabulary(self):
        self.assertTrue(triage.says_can_wait("it can wait until Monday"))
        self.assertTrue(triage.says_can_wait("is probably a side effect"))
        self.assertFalse(triage.says_can_wait("the pump cannot wait"))


if __name__ == "__main__":
    unittest.main()
