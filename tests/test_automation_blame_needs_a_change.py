#!/usr/bin/env python3
"""A finding that blames an automation offers a change to it, or is not raised.

Report #698 (c): "The automation is working; it is doing the wrong thing",
with nothing to change, is noise — the household can only agree and wait.
`house_words.blames_automation` / `concrete_change` are the one reading:
`resident.unfinished` answers `no_change` for an investigation's case, and
`findings_store.add_many` drops a model-written row of the same shape. A
step that names a change (a trigger, a condition, a delay, a value) stays,
and so does a case that blames a device rather than an automation.

The examples are made up: a porch light automation and a bathroom fan.
"""
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import decision_trail  # noqa: E402
import findings_store  # noqa: E402
import house_words  # noqa: E402
import resident  # noqa: E402
import triage  # noqa: E402

BLAME = ("The porch light automation is working; it is doing the wrong "
         "thing")


def case(**kw):
    base = {"claim": BLAME, "detail": "It turned the porch light on at noon.",
            "kind": "problem", "confidence": 0.8, "stakes": "low",
            "fix": "Review the automation.", "evidence": [],
            "actions": [], "todo_text": ""}
    base.update(kw)
    return resident.parse_case(base)


VAGUE = ("Review the automation.", "Check what the automation is doing.",
         "Look into why the automation keeps doing this.",
         "Keep an eye on the porch light automation.", "")
CONCRETE = ("Change the porch light automation's trigger from sunset to "
            + "after 18:00.",
            "Add a condition that the sun is below the horizon.",
            "Remove the 5 minute delay before it turns the light on.",
            "Turn off the porch light automation.",
            "Leave the landing plug on overnight.")


# Steps that are a change in everyday words, with no verb from any list
# (#698c): each is kept. A step is dropped only when it is positively
# vague — a watching verb and no change named at all.
KEPT = ("Limit it to weekdays.", "Narrow its trigger to weekdays.",
        "Make it only run when someone is home.",
        "Only let it run after sunset.", "Use a 10 minute delay instead.",
        "Give it a condition on presence.",
        "Limit it to weekdays and only when someone is home.",
        "Review the automation and limit it to weekdays.",
        "Check the trigger, then tighten it to after sunset.")
HALLWAY = ("The hallway heating automation turns the heating on at 3am "
           "while nobody is home")
HALLWAY_FIX = "Limit it to weekdays and only when someone is home."
VAGUE_TOO = ("Review the automation and the lights.",
             "Keep an eye on it and see whether it happens again.",
             "You could look into why it fires at noon.",
             "Monitor it for a week.", "Consider whether it is needed.")


class TestTheReading(unittest.TestCase):
    def test_a_change_in_everyday_words_is_kept(self):
        for fix in KEPT:
            self.assertTrue(house_words.concrete_change(fix), fix)
        for fix in VAGUE_TOO:
            self.assertFalse(house_words.concrete_change(fix), fix)

    def test_what_blames_an_automation(self):
        self.assertTrue(house_words.blames_automation(BLAME))
        self.assertTrue(house_words.blames_automation(
            "automation.porch_light turns the light on at noon"))
        self.assertFalse(house_words.blames_automation(
            "The bathroom fan is stuck on"))

    def test_an_automation_merely_named_is_not_blamed(self):
        for text in ("The leak automation can't run.",
                     "The hall motion automation uses the lock.",
                     "An automation uses the front door lock.",
                     "Basement leak sensor offline"):
            self.assertFalse(house_words.blames_automation(text), text)

    def test_what_is_a_change(self):
        for fix in CONCRETE:
            self.assertTrue(house_words.concrete_change(fix), fix)
        for fix in VAGUE:
            self.assertFalse(house_words.concrete_change(fix), fix)


class TestACaseWithNoChangeIsNotFiled(unittest.TestCase):
    def test_vague_steps_are_refused(self):
        for fix in VAGUE:
            self.assertEqual(resident.unfinished(case(fix=fix))[0],
                             "no_change" if fix else "no_step", fix)

    def test_a_change_is_filed(self):
        for fix in CONCRETE + KEPT:
            self.assertEqual(resident.unfinished(case(fix=fix)), ("", ""), fix)
        self.assertEqual(resident.unfinished(case(
            claim=HALLWAY, detail="It ran at 03:00 on three nights.",
            fix=HALLWAY_FIX)), ("", ""))
        for fix in VAGUE_TOO:
            self.assertEqual(resident.unfinished(case(fix=fix))[0],
                             "no_change", fix)

    def test_never_over_a_floor_or_high_stakes(self):
        # The store's drop spares a critical, high-stakes, safety, protected
        # or hot row and the safety/security producers; the case's reading
        # spares the same ones, which reach it as `never_ignore`'s floor
        # for the signal (a leak, a protected lock, a hot signal) or as
        # high stakes. A leak automation "doing the wrong thing" with
        # "review it" under it is still shown: silence there costs more.
        for floor in ("act", "investigate", "watch"):
            self.assertEqual(resident.unfinished(case(), floor), ("", ""),
                             floor)
        self.assertEqual(resident.unfinished(case(stakes="high")), ("", ""))
        self.assertEqual(resident.unfinished(case())[0], "no_change")

    def test_a_device_case_with_an_ordinary_step_is_not_this(self):
        self.assertEqual(resident.unfinished(case(
            claim="The leak automation cannot run",
            detail="The basement leak sensor is offline.",
            fix="Check the sensor is powered.")), ("", ""))
        self.assertEqual(resident.unfinished(case(
            claim="The bathroom fan is stuck on",
            detail="It has run for nine hours.",
            fix="Replace the fan's switch.")), ("", ""))


class TestAModelRowWithNoChangeIsNotFiled(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self._old = (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
                     findings_store.STATE_FILE)
        findings_store.FINDINGS_FILE = root / "findings.json"
        findings_store.SETTLED_FILE = root / "settled.json"
        findings_store.STATE_FILE = root / "state.json"
        self._trail = decision_trail.TRAIL_FILE
        decision_trail.TRAIL_FILE = str(root / "decisions.jsonl")

    def tearDown(self):
        (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
         findings_store.STATE_FILE) = self._old
        decision_trail.TRAIL_FILE = self._trail
        self.tmp.cleanup()

    def file(self, fix):
        return findings_store.add_many(triage.gate([{
            "text": BLAME, "detail": "It turned the porch light on at noon.",
            "fix": fix, "severity": "warning", "source": "insight-lights",
            "entity_id": "automation.porch_light"}]))

    def test_no_change_no_row(self):
        self.assertEqual(self.file("Review the automation."), [])

    def test_a_change_is_a_row(self):
        self.assertEqual(len(self.file(CONCRETE[0])), 1)

    def test_a_change_in_everyday_words_is_a_row(self):
        for fix in KEPT:
            findings_store.FINDINGS_FILE.unlink(missing_ok=True)
            self.assertEqual(len(self.file(fix)), 1, fix)
        findings_store.FINDINGS_FILE.unlink(missing_ok=True)
        self.assertEqual(len(findings_store.add_many(triage.gate([{
            "text": HALLWAY, "detail": "It ran at 03:00 on three nights.",
            "fix": HALLWAY_FIX, "severity": "warning",
            "source": "insight-heating",
            "entity_id": "automation.hallway_heating"}]))), 1)
        for fix in VAGUE_TOO:
            findings_store.FINDINGS_FILE.unlink(missing_ok=True)
            self.assertEqual(self.file(fix), [], fix)

    def row(self, **kw):
        base = {"text": BLAME, "detail": "It turned the porch light on at noon.",
                "fix": "Review the automation.", "severity": "warning",
                "source": "insight-lights",
                "entity_id": "automation.porch_light"}
        base.update(kw)
        return findings_store.add_many(triage.gate([base]))

    def test_a_device_row_that_mentions_an_automation_is_kept(self):
        # The reviewer's two probes: the automation is named, not blamed.
        self.assertEqual(len(self.row(
            text="Basement leak sensor offline",
            detail="The leak automation can't run.",
            fix="Check the sensor is powered",
            entity_id="binary_sensor.basement_leak")), 1)
        self.assertEqual(len(self.row(
            text="Front door lock battery at 8%",
            detail="The hall motion automation uses the lock to lock up "
                   + "at night.",
            fix="Check the lock's battery soon",
            entity_id="sensor.front_door_lock_battery")), 1)

    def test_a_high_stakes_or_critical_row_is_never_dropped(self):
        for extra in ({"severity": "critical"}, {"stakes": "high"},
                      {"safety": True}, {"protected": True}):
            findings_store.FINDINGS_FILE.unlink(missing_ok=True)
            self.assertEqual(len(self.row(**extra)), 1, extra)

    def test_a_dropped_row_leaves_a_line_on_the_trail(self):
        import json
        decision_trail.clear_memory()
        self.assertEqual(self.row(), [])
        lines = [json.loads(x) for x in Path(
            decision_trail.TRAIL_FILE).read_text().splitlines()]
        self.assertEqual([x["kind"] for x in lines], ["no_change"])
        self.assertEqual(lines[0]["subject"], "automation.porch_light")

    def test_a_check_row_is_left_to_its_rule(self):
        created = findings_store.add_many(triage.gate([{
            "text": "Porch light has never fired", "detail": "d",
            "fix": "Review the automation.", "severity": "info",
            "source": "check:auto.never_fired",
            "entity_id": "automation.porch_light"}]))
        self.assertEqual(len(created), 1)


if __name__ == "__main__":
    unittest.main()
