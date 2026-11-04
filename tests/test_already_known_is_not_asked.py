#!/usr/bin/env python3
"""What the house already knows, or the owner already said, is not open (#697).

A house was asked "Where is <a sensor>?" about a sensor that has a room,
how to disarm without a phone when it already knew a keypad press does it,
was reminded about a low battery in a remote the owner said they no longer
use, and was told a device "isn't new". Three places now read what the
house holds before a card stays open:

  * a look's reason, or an investigation's own detail or step, that says
    the house already holds the answer or the owner already gave it sets
    the card aside (`triage.says_already_known`, the `answered` word,
    `resident.unfinished`'s `already_known`);
  * the question generator (the house book's, and the Resident's through
    the same lookup) reads the facts the house holds — an earlier answer
    among them — beside the room and the automations
    (`house_book.registry_answers`);
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

KNOWN = (
    "The loft smoke alarm already has a room, so there is nothing to ask.",
    "The owner already said they no longer use the shed remote.",
    "The house already knows the keypad disarms the alarm.",
    "An automation called Keypad disarm already does this.",
    "This was previously answered in the house book.",
    "The sensor is already in the Landing area.",
)
NOT_KNOWN = (
    "The owner already left for work this morning.",
    "The door was already open when the alarm armed.",
    "The heater already ran twice today.",
    "The landing is the warmest room in the house.",
    "Somebody switched the automation off already.",
)
# Sentences that say the house knows something and then report a problem:
# a contrast, or a new fact after it. Each must still be filed.
STILL_A_PROBLEM = (
    "The automation Night lock already locks the door at 22:00, yet it was "
    "found unlocked at 3am.",
    "You already said it is fine, but the battery is now at 4%.",
    "The house already knows the keypad disarms the alarm. Tonight it was "
    "disarmed with no keypad press.",
    "The sensor is already in the Garage area; it has reported nothing for "
    "two days.",
)


class TestTheWordsForAlreadyKnown(unittest.TestCase):
    def test_conclusions_that_say_the_house_knows(self):
        for said in KNOWN:
            self.assertTrue(triage.says_already_known(said), said)

    def test_everyday_sentences_are_not(self):
        for said in NOT_KNOWN:
            self.assertFalse(triage.says_already_known(said), said)

    def test_a_contrast_or_a_new_fact_after_it_is_a_report(self):
        for said in STILL_A_PROBLEM:
            self.assertFalse(triage.says_already_known(said), said)


class TestAnInvestigationThatConcludesItIsKnownIsNotOpen(unittest.TestCase):
    def test_its_own_step_holds_the_card(self):
        case = {"kind": "problem", "claim": "The shed remote battery is low",
                "detail": "It reads 4%.",
                "fix": "Leave it: the owner already said they no longer use "
                       "the shed remote."}
        code, said = resident.unfinished(case)
        self.assertEqual(code, "already_known")
        self.assertIn("no longer use", said)

    def test_the_detail_is_where_a_report_says_what_is_wrong(self):
        # Only the step is read: a detail saying what the house knows and
        # then what went wrong is the report itself.
        case = {"kind": "problem", "claim": "The back door was unlocked at 3am",
                "detail": "The automation Night lock already locks the door "
                          "at 22:00. It was found unlocked at 3am.",
                "fix": "Check the lock's batteries tonight."}
        self.assertEqual(resident.unfinished(case), ("", ""))

    def test_a_step_that_turns_on_itself_is_still_filed(self):
        for said in STILL_A_PROBLEM:
            case = {"kind": "problem", "claim": "Something needs a look",
                    "detail": "Seen tonight.", "fix": said}
            self.assertEqual(resident.unfinished(case), ("", ""), said)

    def test_a_real_problem_is_still_one(self):
        case = {"kind": "problem", "claim": "The shed remote battery is low",
                "detail": "It reads 4% and fell 20 points this week.",
                "fix": "Replace the battery."}
        self.assertEqual(resident.unfinished(case), ("", ""))

    def test_a_look_that_says_so_sets_the_row_aside(self):
        reply = json.dumps({"verdicts": [
            {"id": 1, "verdict": "watch",
             "why": "The loft smoke alarm already has a room in the registry."},
            {"id": 2, "verdict": "watch", "why": "The reading keeps rising."},
            {"id": 3, "verdict": "watch", "why": STILL_A_PROBLEM[0]},
            {"id": 4, "verdict": "investigate", "why": STILL_A_PROBLEM[1]}]})
        out = resident.parse_first_look(reply, 4)
        self.assertEqual(out[1]["verdict"], "ignore")
        self.assertEqual(out[1]["already"], "answered")
        self.assertEqual(out[2]["verdict"], "watch")
        self.assertEqual(out[3]["verdict"], "watch")
        self.assertNotIn("already", out[3])
        self.assertEqual(out[4]["verdict"], "investigate")


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
                         "text": "Loft smoke alarm: it is mounted above the "
                                 "loft hatch"}])
        self.assertTrue(house_book.registry_answers(
            self.WHERE, "binary_sensor.loft_smoke", dig))

    def test_an_earlier_answer_by_name_answers_it_too(self):
        dig = book_dig([{"id": "f2", "subject": "",
                         "text": "Loft smoke alarm: on the Landing ceiling"}])
        self.assertTrue(house_book.registry_answers(self.WHERE, "", dig))

    def test_a_how_question_a_fact_answers_is_not_asked(self):
        dig = book_dig([{"id": "f3", "subject": "alarm_control_panel.house",
                         "text": "House alarm: double-press disarm on the "
                                 "hall keypad"}])
        self.assertTrue(house_book.registry_answers(
            self.HOW, "alarm_control_panel.house", dig))

    def test_a_fact_about_something_else_answers_nothing(self):
        dig = book_dig([{"id": "f4", "subject": "binary_sensor.loft_smoke",
                         "text": "Loft smoke alarm: tested every January"}])
        self.assertEqual(house_book.registry_answers(
            self.WHERE, "binary_sensor.loft_smoke", dig), "")
        self.assertEqual(house_book.registry_answers(
            self.HOW, "alarm_control_panel.house", dig), "")

    def test_parse_drops_the_question(self):
        dig = book_dig([{"id": "f1", "subject": "binary_sensor.loft_smoke",
                         "text": "Loft smoke alarm: it is mounted above the "
                                 "loft hatch"}])
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
