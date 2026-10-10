#!/usr/bin/env python3
"""A question brAIn could answer itself is not put to the homeowner.

A real house was asked "Where is <a sensor>?" about a sensor the registry
already placed, "How do you arm the alarm without somebody's phone?" about
an alarm an automation already arms, and told by a finding to read the
Supervisor log for brAIn's own error — a log brAIn can read itself. Three
places answer for it:

  * `house_book.parse` drops a where-question about anything the registry
    places (its own area, its device's, or the entity a fact is about,
    whatever words the question uses), and a how-to question about an
    entity an automation already operates;
  * a house-book question a first look answers `ignore` is HELD with the
    look's reason — the one producer whose open row a verdict may set
    aside; every other row already on screen stays where it is;
  * the investigation's contract never tells somebody to read a log brAIn
    can read with its own tools.
"""

import sys
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))

import findings_store  # noqa: E402
import house_book  # noqa: E402
import resident  # noqa: E402


def house() -> dict:
    return {
        "states": {
            "sensor.cellar_temperature": {"state": "12", "attributes": {
                "friendly_name": "Cellar temperature",
                "device_class": "temperature"}},
            "alarm_control_panel.home": {"state": "disarmed", "attributes": {
                "friendly_name": "House alarm"}},
            "binary_sensor.front_door": {"state": "off", "attributes": {
                "friendly_name": "Front door"}},
            "switch.mains_valve": {"state": "on", "attributes": {
                "friendly_name": "Mains valve"}},
        },
        # The registry names an area id the area list does not carry: the
        # room is known even where its name is not.
        "entities": [
            {"entity_id": "sensor.cellar_temperature", "device_id": "dev-1"},
            {"entity_id": "binary_sensor.front_door", "area_id": "hall"},
        ],
        "devices": [{"id": "dev-1", "name": "Cellar probe",
                     "area_id": "cellar"}],
        "areas": [{"area_id": "hall", "name": "Hall"}],
        "automations": [
            {"id": "arm-when-away", "alias": "Arm when everyone leaves",
             "triggers": [{"trigger": "state",
                           "entity_id": "binary_sensor.front_door"}],
             "actions": [{"action": "alarm_control_panel.alarm_arm_away",
                          "target": {"entity_id":
                                     "alarm_control_panel.home"}}]},
            {"id": "cellar-watch", "alias": "Cellar too cold",
             "triggers": [{"trigger": "numeric_state",
                           "entity_id": "sensor.cellar_temperature",
                           "below": 5}],
             "actions": [{"action": "switch.turn_off",
                          "target": {"entity_id": "switch.mains_valve"}}]},
        ],
        "scripts": {}, "scenes": [],
    }


def ask(dig, *questions):
    out = house_book.parse({"sections": [], "questions": [
        {"question": q, "subject": s} for q, s in questions]}, dig)
    return [q["question"] for q in out["questions"]]


class TestTheBookDoesNotAskWhatItWasHanded(unittest.TestCase):
    def setUp(self):
        self.dig = house_book.digest(house())

    def test_where_is_a_sensor_placed_through_its_device(self):
        """The device carries the area and the area list does not name it:
        the room is still known."""
        self.assertEqual(ask(self.dig, (
            "Where is the cellar temperature sensor?",
            {"kind": "entity", "id": "sensor.cellar_temperature"})), [])

    def test_what_room_is_a_where_question_too(self):
        self.assertEqual(ask(self.dig, (
            "What room is the front door sensor in?",
            {"kind": "entity", "id": "binary_sensor.front_door"})), [])

    def test_how_do_you_arm_an_alarm_an_automation_arms(self):
        self.assertEqual(ask(self.dig, (
            "How do you arm the alarm without a phone?",
            {"kind": "entity", "id": "alarm_control_panel.home"})), [])

    def test_where_is_asked_through_a_fact_about_a_placed_sensor(self):
        fact = {"id": "f1", "subject": "sensor.cellar_temperature",
                "text": "The cellar probe reads cold in winter."}
        with mock.patch.object(house_book, "_fact_rows", lambda: [fact]):
            dig = house_book.digest(house())
        self.assertEqual(ask(dig, (
            "Where is the cellar probe mounted?",
            {"kind": "fact", "id": "f1"})), [])

    def test_a_question_brain_cannot_answer_still_stands(self):
        asked = ask(self.dig,
                    ("Where is the stopcock the mains valve closes?",
                     {"kind": "entity", "id": "switch.mains_valve"}),
                    ("What temperature should the cellar be kept at?",
                     {"kind": "entity", "id": "sensor.cellar_temperature"}))
        self.assertEqual(asked, [
            "Where is the stopcock the mains valve closes?",
            "What temperature should the cellar be kept at?"])


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = (findings_store.FINDINGS_FILE, findings_store.INBOX_DIR,
                     findings_store.SETTLED_FILE, findings_store.STATE_FILE)
        findings_store.FINDINGS_FILE = Path(self.tmp.name) / "findings.json"
        findings_store.INBOX_DIR = Path(self.tmp.name) / "inbox"
        findings_store.SETTLED_FILE = Path(self.tmp.name) / "settled.json"
        findings_store.STATE_FILE = (
            Path(self.tmp.name) / "config" / ".brain" / "findings_state.json")

    def tearDown(self):
        (findings_store.FINDINGS_FILE, findings_store.INBOX_DIR,
         findings_store.SETTLED_FILE, findings_store.STATE_FILE) = self._old
        self.tmp.cleanup()


class TestALookMaySetABookQuestionAside(StoreCase):
    WHY = "The Arm when everyone leaves automation already arms it."

    def book_question(self):
        rows = house_book.question_rows([{
            "question": "How do you arm the alarm?", "why": "",
            "subject": "entity:alarm_control_panel.home",
            "label": "House alarm"}], [], 0)
        rows[0].pop("_subject")
        return findings_store.add_case(rows[0])

    def test_the_store_names_the_books_own_source(self):
        """Spelled in the store, which imports no producer; held equal."""
        self.assertEqual(findings_store.LOOK_MAY_SET_ASIDE,
                         frozenset({house_book.SOURCE}))

    def test_an_ignore_holds_it_with_the_looks_reason(self):
        row = self.book_question()
        self.assertEqual(row["status"], "open")
        moved = findings_store.record_triage({row["ts"]: ("held", self.WHY)})
        stored = findings_store.get(row["ts"])
        self.assertEqual(stored["status"], "held")
        self.assertEqual(stored["triage"]["reason"], self.WHY)
        # Held, so announced to nobody.
        self.assertEqual(moved, [])

    def test_an_elevated_verdict_leaves_it_where_it_was(self):
        row = self.book_question()
        findings_store.record_triage({row["ts"]: ("elevated", "Ask it.")})
        self.assertEqual(findings_store.get(row["ts"])["status"], "open")

    def test_every_other_producers_row_on_screen_stays(self):
        [row] = findings_store.add_many([{
            "text": "The hall light is on with nobody home",
            "source": "lighting", "kind": "question", "claim": "On?"}])
        findings_store.record_triage({row["ts"]: ("held", self.WHY)})
        self.assertEqual(findings_store.get(row["ts"])["status"], "open")

    def test_a_question_somebody_put_back_is_not_set_aside_again(self):
        row = self.book_question()
        items = findings_store._load()
        for entry in items:
            if entry["ts"] == row["ts"]:
                entry["triage"]["elevated_by_person"] = True
        findings_store._write(items)
        findings_store.record_triage({row["ts"]: ("held", self.WHY)})
        self.assertEqual(findings_store.get(row["ts"])["status"], "open")


class TestTheLookIsToldAndTheFixNeverSendsSomebodyToALog(unittest.TestCase):
    def test_the_first_look_sets_aside_what_the_house_already_answers(self):
        self.assertIn("a question the house already answers",
                      resident.FIRST_LOOK_SYSTEM)

    def test_a_fix_never_says_read_a_log_brain_can_read(self):
        self.assertIn("Never tell the person to read a log",
                      resident.INVESTIGATE_SYSTEM)


if __name__ == "__main__":
    unittest.main()
