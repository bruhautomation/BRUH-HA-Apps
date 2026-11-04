#!/usr/bin/env python3
"""What the house already knows, or the owner already said, is not open (#697).

A house was asked "Where is <a sensor>?" about a sensor that has a room,
how to disarm without a phone when it already knew a keypad press does it,
was reminded about a low battery in a remote the owner said they no longer
use, and was told a device "isn't new". Three places now read what the
house holds before a card stays open:

  * an investigation says it in a WORD (`resident.CASE_ANSWERED`, the
    case contract's `already`, the first look's `answered`): a reply that
    gives it is held like one whose step says nothing is needed
    (`resident.unfinished`'s `already_known`). Never a reading of the
    step, the detail or a look's reason: a first attempt matched sentences
    with "already" in them, and "the automation already locks the door at
    night, so the lock motor needs replacing" is a problem that mentions
    what the house knows — every such sentence here must still be filed;
  * the question generator (the house book's, and the Resident's through
    the same lookup) reads the facts the house holds — an earlier answer
    among them — beside the room and the automations
    (`house_book.registry_answers`), and only a fact that PLACES the thing
    answers "where";
  * a device the owner said is finished with, on any card, closes the
    device checks for it (`House.answered_off` over `known_faulty`).

Made-up examples: a loft smoke alarm, a house alarm with a hall keypad, a
garden-shed remote.
"""

import json
import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "brain" / "panel"))
sys.path.insert(0, str(TESTS_DIR))

import checks  # noqa: E402
import house_book  # noqa: E402
import resident  # noqa: E402
import triage  # noqa: E402
from test_house_checks import NOW, house  # noqa: E402

# Sentences that mention what the house already knows and report a
# problem all the same — the two from the first review and the three from
# the second. Each must still be filed, whichever field it is written in.
STILL_A_PROBLEM = (
    "The automation Night lock already locks the door at 22:00, yet it was "
    + "found unlocked at 3am.",
    "You already said it is fine, but the battery is now at 4%.",
    "The automation already locks the door at night, so the lock motor "
    + "needs replacing.",
    "The owner already told us the garage is fine, so the door open at 3am "
    + "should be closed.",
    "The automation Night lock already turns off the lights at 11 pm, "
    + "replace the bulb in the hall which is failing.",
)
# Sentences that only say the house knows: still not a verdict, because a
# sentence is not how a run says it.
ONLY_SAYS_SO = (
    "The loft smoke alarm already has a room, so there is nothing to ask.",
    "The owner already said they no longer use the shed remote.",
    "The house already knows the keypad disarms the alarm.",
    "An automation called Keypad disarm already does this.",
)


def problem(**fields) -> dict:
    case = {"kind": "problem", "claim": "Something needs a look",
            "detail": "Seen tonight.", "fix": "Replace the battery."}
    case.update(fields)
    return case


class TestTheWordAndNotTheSentence(unittest.TestCase):
    def test_the_contract_offers_the_word(self):
        prop = resident.CASE_SCHEMA["properties"]["already"]
        self.assertEqual(prop["enum"], ["", resident.CASE_ANSWERED])
        self.assertNotIn("already", resident.CASE_SCHEMA["required"])
        self.assertIn('"already"', resident.INVESTIGATE_SYSTEM)
        self.assertIn('"answered"', resident.INVESTIGATE_SYSTEM)
        # The same word the first look gives, so the two tiers agree.
        self.assertIn(resident.CASE_ANSWERED, resident.ALREADY)

    def test_the_word_rides_through_parse_case_and_nothing_else_does(self):
        reply = {"claim": "The shed remote battery is low",
                 "detail": ("The owner said in March they no longer use the "
                            "shed remote."),
                 "confidence": 0.9, "stakes": "low", "evidence": [],
                 "actions": [], "escalate": False, "already": "answered"}
        self.assertEqual(resident.parse_case(reply)["already"], "answered")
        self.assertNotIn("already", resident.parse_case({**reply, "already": ""}))
        self.assertNotIn("already", resident.parse_case(
            {**reply, "already": "explained"}))
        self.assertNotIn("already", resident.parse_case(
            {k: v for k, v in reply.items() if k != "already"}))

    def test_the_word_holds_the_case_with_where_the_answer_is(self):
        case = problem(claim="The shed remote battery is low",
                       detail=("The owner said in March they no longer use "
                               "the shed remote. It reads 4%."),
                       fix="Leave it.", already="answered")
        code, said = resident.unfinished(case)
        self.assertEqual(code, "already_known")
        self.assertEqual(said, "The owner said in March they no longer use "
                               "the shed remote.")

    def test_a_question_the_house_answers_is_held_too(self):
        case = {"kind": "question", "claim": "Where is the loft smoke alarm?",
                "detail": "The registry puts it on the Landing.",
                "fix": "", "already": "answered"}
        self.assertEqual(resident.unfinished(case)[0], "already_known")
        # …and a question with no word is a question, as before.
        self.assertEqual(resident.unfinished({**case, "already": ""}),
                         ("", ""))

    def test_no_sentence_holds_a_case(self):
        for said in STILL_A_PROBLEM + ONLY_SAYS_SO:
            self.assertEqual(resident.unfinished(problem(fix=said)),
                             ("", ""), said)
            self.assertEqual(resident.unfinished(problem(detail=said)),
                             ("", ""), said)

    def test_a_real_problem_is_still_one(self):
        case = {"kind": "problem", "claim": "The shed remote battery is low",
                "detail": "It reads 4% and fell 20 points this week.",
                "fix": "Replace the battery."}
        self.assertEqual(resident.unfinished(case), ("", ""))

    def test_a_step_that_says_nothing_is_needed_still_withdraws(self):
        # The one reading of a step that stays (#604) is the step saying
        # nothing is needed — not a step that mentions what the house knows.
        code, _said = resident.unfinished(problem(
            fix="Nothing is needed: the owner retired the shed remote."))
        self.assertEqual(code, "nothing_needed")

    def test_triage_reads_no_sentence_for_it(self):
        # The absent reader is the fix: a regex over "already" held
        # "the automation already locks it, so the motor needs replacing".
        self.assertFalse(hasattr(triage, "says_already_known"))
        self.assertFalse(hasattr(triage, "ALREADY_KNOWN_RE"))


class TestTheFirstLookIsReadTheSameWay(unittest.TestCase):
    def look(self, verdict: str, why: str) -> dict:
        reply = json.dumps({"verdicts": [{"id": 1, "verdict": verdict,
                                          "why": why}]})
        return resident.parse_first_look(reply, 1, [
            {"kind": "state", "subject": "lock.back_door"}])[1]

    def test_a_reason_that_mentions_what_the_house_knows_keeps_its_verdict(self):
        for why in STILL_A_PROBLEM + ONLY_SAYS_SO:
            for verdict in ("watch", "investigate"):
                out = self.look(verdict, why)
                self.assertEqual(out["verdict"], verdict, why)
                self.assertNotIn("already", out, why)

    def test_the_word_itself_still_sets_a_row_aside(self):
        reply = json.dumps({"verdicts": [
            {"id": 1, "verdict": "watch", "already": "answered",
             "why": "The registry puts the loft smoke alarm on the Landing."}]})
        out = resident.parse_first_look(reply, 1)[1]
        self.assertEqual((out["verdict"], out["already"]), ("ignore", "answered"))


def book_dig(facts):
    snap = {"states": {
                "binary_sensor.loft_smoke": {"state": "off", "attributes": {
                    "friendly_name": "Loft smoke alarm",
                    "device_class": "smoke"}},
                "alarm_control_panel.house": {"state": "armed_away",
                                              "attributes": {
                                                  "friendly_name": "House alarm"}}},
            "entities": [], "devices": [], "areas": [
                {"area_id": "landing", "name": "Landing"}],
            "automations": []}
    import unittest.mock as mock
    with mock.patch.object(house_book, "_fact_rows", return_value=facts):
        return house_book.digest(snap)


class TestTheQuestionGeneratorReadsTheFacts(unittest.TestCase):
    WHERE = "Where is the loft smoke alarm?"
    HOW = "How do you disarm the house alarm without a phone?"

    def test_a_where_question_a_fact_answers_is_not_asked(self):
        dig = book_dig([{"id": "f1", "subject": "binary_sensor.loft_smoke",
                         "text": ("Loft smoke alarm: it is mounted above the "
                                  "loft hatch")}])
        self.assertTrue(house_book.registry_answers(
            self.WHERE, "binary_sensor.loft_smoke", dig))

    def test_an_earlier_answer_by_name_answers_it_too(self):
        dig = book_dig([{"id": "f2", "subject": "",
                         "text": "Loft smoke alarm: on the Landing ceiling"}])
        self.assertTrue(house_book.registry_answers(self.WHERE, "", dig))

    def test_a_how_question_a_fact_answers_is_not_asked(self):
        dig = book_dig([{"id": "f3", "subject": "alarm_control_panel.house",
                         "text": ("House alarm: double-press disarm on the "
                                  "hall keypad")}])
        self.assertTrue(house_book.registry_answers(
            self.HOW, "alarm_control_panel.house", dig))

    def test_a_fact_about_something_else_answers_nothing(self):
        dig = book_dig([{"id": "f4", "subject": "binary_sensor.loft_smoke",
                         "text": "Loft smoke alarm: tested every January"}])
        self.assertEqual(house_book.registry_answers(
            self.WHERE, "binary_sensor.loft_smoke", dig), "")
        self.assertEqual(house_book.registry_answers(
            self.HOW, "alarm_control_panel.house", dig), "")

    def test_a_fact_that_only_has_is_in_or_on_in_it_places_nothing(self):
        # "is in use", "is on the list", "is at 4%" say nothing about where.
        for said in ("Loft smoke alarm: it is in use every night",
                     "Loft smoke alarm: it is on the list to replace",
                     "Loft smoke alarm: its battery is at 4%"):
            dig = book_dig([{"id": "f5", "subject": "binary_sensor.loft_smoke",
                             "text": said}])
            self.assertEqual(house_book.registry_answers(
                self.WHERE, "binary_sensor.loft_smoke", dig), "", said)

    def test_parse_drops_the_question(self):
        dig = book_dig([{"id": "f1", "subject": "binary_sensor.loft_smoke",
                         "text": ("Loft smoke alarm: it is mounted above the "
                                  "loft hatch")}])
        out = house_book.parse({"sections": [], "questions": [
            {"subject": "entity:binary_sensor.loft_smoke",
             "question": self.WHERE, "why": "For a house-sitter."}]}, dig)
        self.assertEqual(out["questions"], [])


class TestAFinishedDeviceSaidAnywhereClosesItsChecks(unittest.TestCase):
    def remote_house(self):
        snap = house()
        snap["devices"].append({"id": "dev-shed", "name": "Shed remote"})
        snap["entities"].append({"entity_id": "sensor.shed_remote_battery",
                                 "platform": "mqtt", "device_id": "dev-shed"})
        snap["states"]["sensor.shed_remote_battery"] = {
            "state": "3", "last_updated": "2026-01-01T00:00:00+00:00",
            "attributes": {"device_class": "battery",
                           "unit_of_measurement": "%",
                           "friendly_name": "Shed remote battery"}}
        return snap

    def ids(self, snap):
        return [f["entity_id"] for f in checks.devices.battery_low(snap, NOW)]

    def test_it_files_without_a_word(self):
        self.assertEqual(self.ids(self.remote_house()),
                         ["sensor.shed_remote_battery"])

    def test_said_on_another_card_it_is_not_filed(self):
        snap = self.remote_house()
        snap["faulty"] = {"sensor.shed_remote_battery":
                          "we no longer use the shed remote"}
        self.assertEqual(self.ids(snap), [])

    def test_said_about_another_device_it_still_is(self):
        snap = self.remote_house()
        snap["faulty"] = {"sensor.hall_temp": "that sensor is broken"}
        self.assertEqual(self.ids(snap), ["sensor.shed_remote_battery"])


if __name__ == "__main__":
    unittest.main()
