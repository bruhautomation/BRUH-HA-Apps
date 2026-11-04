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


class TestTheReading(unittest.TestCase):
    def test_what_blames_an_automation(self):
        self.assertTrue(house_words.blames_automation(BLAME))
        self.assertTrue(house_words.blames_automation(
            "automation.porch_light turns the light on at noon"))
        self.assertFalse(house_words.blames_automation(
            "The bathroom fan is stuck on"))

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
        for fix in CONCRETE:
            self.assertEqual(resident.unfinished(case(fix=fix)), ("", ""), fix)

    def test_a_device_case_with_an_ordinary_step_is_not_this(self):
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

    def test_a_check_row_is_left_to_its_rule(self):
        created = findings_store.add_many(triage.gate([{
            "text": "Porch light has never fired", "detail": "d",
            "fix": "Review the automation.", "severity": "info",
            "source": "check:auto.never_fired",
            "entity_id": "automation.porch_light"}]))
        self.assertEqual(len(created), 1)


if __name__ == "__main__":
    unittest.main()
