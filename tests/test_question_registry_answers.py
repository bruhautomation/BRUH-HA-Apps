#!/usr/bin/env python3
"""A question the registry or an automation already answers is not asked.

Seen on a house (#561): the house book asked "Where is <a motion sensor>?"
about a sensor the registry had already put in a room, and "How is the
alarm disarmed?" while an automation showed that a double press on a wall
remote disarms it. The first came in under a subject that was not the
sensor (so the subject check never saw it), the second was worded "how
is…", which the how-to check did not read as a how-to question.

So before a question is raised brAIn looks it up (`house_book.
registry_answers`): a where-question about an entity — by its subject, or
by the thing it asks about, named in its words — that has a room of its
own or through its device is not asked; a how-question about an entity an
automation operates in the way asked (disarm, unlock, open…) is not asked,
because that automation is the answer. The same lookup runs on a question
an investigation would put to the owner. A question nothing answers is
still asked. Everything below is invented.
"""

import asyncio
import json
import sys
import time
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "brain" / "panel"))
sys.path.insert(0, str(TESTS_DIR))

import house_book  # noqa: E402
from test_resident_loop import LoopCase  # noqa: E402

MOTION = "binary_sensor.landing_motion"
ALARM = "alarm_control_panel.villa"
LOCK = "lock.side_gate"
VALVE = "valve.garden_tap"


def house() -> dict:
    return {
        "states": {
            MOTION: {"state": "off", "attributes": {
                "friendly_name": "Landing motion", "device_class": "motion"}},
            ALARM: {"state": "armed_away", "attributes": {
                "friendly_name": "Villa alarm"}},
            LOCK: {"state": "locked", "attributes": {
                "friendly_name": "Side gate lock"}},
            VALVE: {"state": "open", "attributes": {
                "friendly_name": "Garden tap"}},
            "light.landing": {"state": "off", "attributes": {
                "friendly_name": "Landing light"}},
        },
        "entities": [{"entity_id": MOTION, "device_id": "pir-1"}],
        "devices": [{"id": "pir-1", "name": "Landing PIR",
                     "area_id": "landing"}],
        "areas": [{"area_id": "landing", "name": "Landing"}],
        "automations": [
            {"id": "landing-light", "alias": "Landing light on motion",
             "triggers": [{"trigger": "state", "entity_id": MOTION,
                           "to": "on"}],
             "actions": [{"action": "light.turn_on",
                          "target": {"entity_id": "light.landing"}}]},
            {"id": "remote-disarm", "alias": "Hall remote double press",
             "triggers": [{"trigger": "device", "device_id": "remote-9",
                           "domain": "zha",
                           "type": "remote_button_double_press",
                           "subtype": "button_1"}],
             "actions": [{"action": "alarm_control_panel.alarm_disarm",
                          "target": {"entity_id": ALARM}}]},
            {"id": "gate-open", "alias": "Gate tag",
             "triggers": [{"trigger": "event", "event_type": "tag_scanned",
                           "event_data": {"tag_id": "gate"}}],
             "actions": [{"action": "lock.unlock",
                          "target": {"entity_id": LOCK}}]},
        ],
        "scripts": {}, "scenes": [],
    }


def ask(dig, *questions):
    out = house_book.parse({"sections": [], "questions": [
        {"question": q, "subject": s} for q, s in questions]}, dig)
    return [q["question"] for q in out["questions"]]


AUTO = {"kind": "automation", "id": "landing-light"}


class TestWhereIsAnsweredByTheRegistry(unittest.TestCase):
    def setUp(self):
        self.dig = house_book.digest(house())

    def test_where_is_a_placed_sensor_asked_under_another_subject(self):
        self.assertEqual(ask(self.dig, (
            "Where is the landing motion sensor?", AUTO)), [])

    def test_its_device_name_is_the_same_thing(self):
        self.assertEqual(ask(self.dig, (
            "Where is the Landing PIR mounted?", AUTO)), [])

    def test_a_thing_beside_a_placed_one_is_still_asked(self):
        """Naming a placed sensor is not asking where IT is."""
        self.assertEqual(ask(self.dig, (
            "Where is the fuse for the landing motion sensor?", AUTO)),
            ["Where is the fuse for the landing motion sensor?"])

    def test_an_unplaced_thing_is_still_asked(self):
        self.assertEqual(ask(self.dig, (
            "Where is the garden tap?", {"kind": "entity", "id": VALVE})),
            ["Where is the garden tap?"])


class TestHowIsAnsweredByAnAutomation(unittest.TestCase):
    def setUp(self):
        self.dig = house_book.digest(house())

    def test_how_is_the_alarm_disarmed(self):
        self.assertEqual(ask(self.dig, (
            "How is the alarm disarmed?", {"kind": "entity", "id": ALARM})),
            [])

    def test_a_second_example_named_only_in_the_words(self):
        self.assertEqual(ask(self.dig, (
            "How do you unlock the side gate lock without a phone?",
            {"kind": "automation", "id": "gate-open"})), [])

    def test_an_operation_no_automation_does_is_still_asked(self):
        """An automation disarms the alarm; nothing ARMS it."""
        self.assertEqual(ask(self.dig, (
            "How is the alarm armed when everyone leaves?",
            {"kind": "entity", "id": ALARM})),
            ["How is the alarm armed when everyone leaves?"])

    def test_the_registry_says_how_and_by_what(self):
        why = house_book.registry_answers(
            "How is the alarm disarmed?", ALARM, house_book.digest(house()))
        self.assertIn("Hall remote double press", why)

    def test_a_how_question_that_is_not_how_to_operate_it(self):
        self.assertEqual(ask(self.dig, (
            "How is the side gate lock powered?",
            {"kind": "entity", "id": LOCK})),
            ["How is the side gate lock powered?"])


class TestTheWordsAreReadNarrowly(unittest.TestCase):
    """Everyday questions that are not where/how-to-operate questions."""

    def test_everyday_questions_are_left_alone(self):
        dig = house_book.digest(house())
        for q in ("Is the landing motion sensor meant to cover the stairs?",
                  "Who should be told when the villa alarm sounds?",
                  "How long should the landing light stay on?",
                  "What should a sitter do if the side gate lock jams?",
                  "Where should a parcel be left when nobody is home?"):
            self.assertEqual(house_book.registry_answers(q, "", dig), "", q)


class TestAnInvestigationsQuestionIsLookedUpToo(LoopCase):
    """The real `_resident_investigate`: a question it would put to the
    owner goes through the same lookup, over the maps a checks pass left."""

    def setUp(self):
        super().setUp()
        srv = self.server
        self._trail = srv.decision_trail.TRAIL_FILE
        srv.decision_trail.TRAIL_FILE = str(Path(self.tmp.name)
                                            / "decisions.jsonl")
        self._names = dict(srv._NAMES)
        srv._NAMES.clear()
        srv._NAMES.update({MOTION: {"name": "Landing motion",
                                    "area": "landing"},
                           VALVE: {"name": "Garden tap", "area": ""},
                           ALARM: {"name": "Villa alarm", "area": ""}})
        srv._OPERATED.clear()
        srv._OPERATED.update(house_book.operated_by(house()["automations"]))

    def tearDown(self):
        srv = self.server
        srv.decision_trail.TRAIL_FILE = self._trail
        srv._NAMES.clear()
        srv._NAMES.update(self._names)
        srv._OPERATED.clear()
        super().tearDown()

    def investigate(self, question, subject):
        self.investigations.append({
            "ok": True, "error": "", "meta": {"session_id": "inv-q"},
            "text": json.dumps({
                "claim": question, "detail": "A sitter would need to know.",
                "kind": "question", "confidence": 0.7, "stakes": "low",
                "fix": "", "evidence": [{"entity": subject, "value": "off"}],
                "actions": [], "escalate": False})})
        signal = {"kind": "state", "subject": subject, "salience": 0.5,
                  "text": "A question about the house", "evidence": []}
        asyncio.run(self.server._resident_investigate(
            signal, time.time(), "normal"))
        return [r for r in self.server.findings_store._load()
                if r.get("source") == "resident"]

    def test_where_is_a_placed_sensor_is_not_asked(self):
        self.assertEqual(self.investigate(
            "Where is the landing motion sensor?", MOTION), [])

    def test_how_is_the_alarm_disarmed_is_not_asked(self):
        self.assertEqual(self.investigate(
            "How is the villa alarm disarmed?", ALARM), [])

    def test_a_question_nothing_answers_is_asked(self):
        self.assertEqual(len(self.investigate(
            "Where is the stopcock for the garden tap?", VALVE)), 1)


if __name__ == "__main__":
    unittest.main()
