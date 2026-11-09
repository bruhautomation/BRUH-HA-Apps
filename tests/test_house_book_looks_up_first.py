#!/usr/bin/env python3
"""A house-book question the house already answers is written, not asked.

A house's gap report (#773): the house book asked the owner which room a
sensor was in when the registry gave it an area, and what a button did
when an automation mapped it. A where-question the registry answers was
already not asked, but the answer went nowhere — the book never said it —
and nothing read a button's or a remote's mapping at all.

Before a question goes to the owner brAIn looks it up: the area a thing
(or its device) is in, the automation that does what a how-question asks,
and the automations a button, a remote or any trigger entity starts. When
the lookup answers it, the answer is written into the book, cited to the
area or the automation, and nobody is asked. Everything here is invented:
an attic humidity sensor, a study button and a kitchen remote whose
automation is keyed on its device, not an entity.
"""

import asyncio
import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "brain" / "panel"))
sys.path.insert(0, str(TESTS_DIR))

import house_book  # noqa: E402
from test_house_book import BookPassCase  # noqa: E402

ATTIC = "sensor.attic_humidity"
BUTTON = "event.study_button"
REMOTE_BATTERY = "sensor.kitchen_remote_battery"
LAMP = "light.desk_lamp"
WASHER = "switch.dishwasher"


def house() -> dict:
    return {
        "states": {
            ATTIC: {"state": "61", "attributes": {
                "friendly_name": "Attic humidity", "device_class": "humidity"}},
            BUTTON: {"state": "unknown", "attributes": {
                "friendly_name": "Study button"}},
            REMOTE_BATTERY: {"state": "80", "attributes": {
                "friendly_name": "Kitchen remote battery"}},
            LAMP: {"state": "off", "attributes": {
                "friendly_name": "Desk lamp"}},
            "light.kitchen": {"state": "off", "attributes": {
                "friendly_name": "Kitchen lights"}},
            WASHER: {"state": "off", "attributes": {
                "friendly_name": "Dishwasher"}},
        },
        "entities": [
            {"entity_id": ATTIC, "device_id": "hygro-1"},
            {"entity_id": REMOTE_BATTERY, "device_id": "remote-3"},
        ],
        "devices": [{"id": "hygro-1", "name": "Attic hygrometer",
                     "area_id": "attic"},
                    {"id": "remote-3", "name": "Kitchen remote"}],
        "areas": [{"area_id": "attic", "name": "Attic"}],
        "automations": [
            {"id": "study-desk", "alias": "Study button lamp",
             "triggers": [{"trigger": "state", "entity_id": BUTTON}],
             "actions": [{"action": "light.toggle",
                          "target": {"entity_id": LAMP}}]},
            {"id": "kitchen-remote", "alias": "Kitchen remote on",
             "triggers": [{"trigger": "device", "device_id": "remote-3",
                           "domain": "zha", "type": "remote_button_short_press",
                           "subtype": "turn_on"}],
             "actions": [{"action": "light.turn_on",
                          "target": {"entity_id": "light.kitchen"}}]},
            {"id": "attic-fan", "alias": "Attic fan on humidity",
             "triggers": [{"trigger": "numeric_state", "entity_id": ATTIC,
                           "above": 70}],
             "actions": [{"action": "switch.turn_off",
                          "target": {"entity_id": WASHER}}]},
        ],
        "scripts": {}, "scenes": [],
    }


AUTO = {"kind": "automation", "id": "study-desk"}
QUESTIONS = (("Which room is the attic humidity sensor in?", AUTO),
             ("What does the study button do?",
              {"kind": "entity", "id": BUTTON}))


def parsed(dig, *questions):
    return house_book.parse({"sections": [], "questions": [
        {"question": q, "subject": s} for q, s in questions]}, dig)


def lines(sections):
    return [e for sec in sections for e in sec["entries"]]


class TestTheLookupWritesTheBook(unittest.TestCase):
    def setUp(self):
        self.dig = house_book.digest(house())

    def test_a_room_the_registry_has_is_written_not_asked(self):
        out = parsed(self.dig, QUESTIONS[0])
        self.assertEqual(out["questions"], [])
        [line] = lines(out["sections"])
        self.assertIn("Attic", line["text"])
        self.assertEqual([s["key"] for s in line["sources"]], ["area:attic"])

    def test_what_a_button_does_is_written_not_asked(self):
        out = parsed(self.dig, QUESTIONS[1])
        self.assertEqual(out["questions"], [])
        [line] = lines(out["sections"])
        self.assertIn("Study button lamp", line["text"])
        self.assertIn("automation:study-desk",
                      [s["key"] for s in line["sources"]])

    def test_a_remote_mapped_by_its_device_is_answered_too(self):
        out = parsed(self.dig, ("What does the kitchen remote do?", AUTO))
        self.assertEqual(out["questions"], [])
        [line] = lines(out["sections"])
        self.assertIn("Kitchen remote on", line["text"])

    def test_a_question_nothing_answers_is_still_asked(self):
        for q in ("What does the dishwasher do on its eco setting?",
                  "What should a sitter do if the study button stops?"):
            out = parsed(self.dig, (q, AUTO))
            self.assertEqual([x["question"] for x in out["questions"]], [q])
            self.assertEqual(lines(out["sections"]), [])


class TestACutAnswerSaysSo(unittest.TestCase):
    def test_more_than_three_automations_and_actions_say_and_more(self):
        snap = house()
        lights = [f"light.hall_{n}" for n in range(5)]
        for eid in lights:
            snap["states"][eid] = {"state": "off", "attributes": {
                "friendly_name": eid.split(".")[1].replace("_", " ").title()}}
        snap["automations"] += [
            {"id": f"study-{n}", "alias": f"Study press {n}",
             "triggers": [{"trigger": "state", "entity_id": BUTTON}],
             "actions": [{"action": "light.turn_on",
                          "target": {"entity_id": lights}}]}
            for n in range(4)]
        out = parsed(house_book.digest(snap), QUESTIONS[1])
        [line] = lines(out["sections"])
        self.assertIn("and 2 more automations", line["text"])
        self.assertIn("and 2 more", line["text"].split(";")[1])


class TestReplayedThroughThePass(BookPassCase):
    def test_two_looked_up_questions_reach_nobody(self):
        self.replies = [{"ok": True, "meta": {"session_id": "hb2"},
                         "data": {"sections": [], "questions": [
                             {"question": q, "subject": s}
                             for q, s in QUESTIONS]}}]
        asyncio.run(self.server._run_book("pressed", house()))
        self.assertEqual([f for f in self.server.findings_store.list_all()
                          if f.get("source") == house_book.SOURCE], [])
        book = house_book.load()["book"]
        said = " ".join(e["text"] for e in lines(book["sections"]))
        self.assertIn("Attic", said)
        self.assertIn("Study button lamp", said)


if __name__ == "__main__":
    unittest.main()
