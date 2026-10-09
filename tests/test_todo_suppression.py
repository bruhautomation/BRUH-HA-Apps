#!/usr/bin/env python3
"""A finding about something already on the To Do list is not filed again.

"Add to To Do" settles the finding's key as `accepted`, which stops the
same TEXT while the chore is open. A model-written producer (the overnight
check, the Resident, a card) rewords every pass, so text dedupe missed and
the owner saw problems they had already moved to To Do come back as new
findings. Now a new row whose `entity_id` is an OPEN to-do item's entity is
not filed: the item records that it was seen again instead. Never a safety
row (a leak on an entity with an open chore is still a leak), and once the
chore is done or dropped, filing works again.

Driven over the real findings store and the real to-do store.
"""

import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import findings_store  # noqa: E402
import todo_store  # noqa: E402

PUMP = "switch.cellar_pump"
LEAK = "binary_sensor.cellar_leak"


def report(text: str, source: str = "sre", eid: str = PUMP, **over) -> dict:
    row = {"text": text, "entity_id": eid, "source": source,
           "source_title": "Overnight health check", "severity": "warning"}
    row.update(over)
    return row


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self._fs = (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
                    findings_store.STATE_FILE)
        findings_store.FINDINGS_FILE = root / "findings.json"
        findings_store.SETTLED_FILE = root / "settled.json"
        findings_store.STATE_FILE = root / "nowhere" / ".brain" / "s.json"
        self._td = (todo_store.TODO_FILE, todo_store.STATE_FILE)
        todo_store.TODO_FILE = root / "todo.json"
        todo_store.STATE_FILE = root / "nowhere" / ".brain" / "todo.json"

    def tearDown(self):
        (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
         findings_store.STATE_FILE) = self._fs
        todo_store.TODO_FILE, todo_store.STATE_FILE = self._td
        self.tmp.cleanup()

    def chore(self, eid: str = PUMP) -> dict:
        item = todo_store.add("The cellar pump router keeps dropping",
                              entity_id=eid, origin="finding", source="sre",
                              finding_key="the cellar pump router keeps dropping")
        self.assertIsNotNone(item)
        return item


class TestAnOpenChoreHoldsItsEntity(Case):
    def test_a_reworded_report_is_not_filed_and_the_chore_is_told(self):
        item = self.chore()
        made = findings_store.add_many([report(
            "Z-Wave cannot reach the cellar pump at night")])
        self.assertEqual(made, [])
        self.assertEqual(findings_store.list_all(), [])
        seen = todo_store.get(item["id"])
        self.assertTrue(seen["seen_again_at"])
        self.assertEqual(seen["seen_again"], 1)
        self.assertIn("cellar pump", seen["seen_again_text"])

    def test_any_producer_is_held_not_only_the_one_that_filed_it(self):
        self.chore()
        for source in ("resident", "custom-abc", "check:dev.unavailable"):
            self.assertEqual(findings_store.add_many([report(
                f"Pump problem from {source}", source=source)]), [], source)
        self.assertEqual(todo_store.get(
            todo_store.listing()["items"][0]["id"])["seen_again"], 3)

    def test_a_different_entity_is_filed_as_ever(self):
        self.chore()
        made = findings_store.add_many([report("Hall light flickers",
                                               eid="light.hall")])
        self.assertEqual(len(made), 1)

    def test_a_row_with_no_entity_is_filed_as_ever(self):
        self.chore()
        self.assertEqual(len(findings_store.add_many([report(
            "Something in the log", eid="")])), 1)


class TestSafetyIsNeverSwallowed(Case):
    def test_the_safety_lane_and_the_tripped_check_still_file(self):
        self.chore(LEAK)
        lane = findings_store.add_many([report(
            "Water leak detected by Cellar leak (Tue 6 Oct, 03:10)",
            source="safety", eid=LEAK, severity="critical")])
        self.assertEqual(len(lane), 1)
        check = findings_store.add_many([report(
            "Cellar leak is reporting a water leak",
            source="check:safety.tripped", eid=LEAK, severity="critical")])
        # The check's row is not swallowed by the chore — but it is the
        # same trip the lane already filed, so it is folded into nothing
        # and the lane's card stands alone.
        self.assertEqual(check, [])
        self.assertEqual(len(findings_store.list_all()), 1)

    def test_the_tripped_check_files_when_no_lane_card_exists(self):
        self.chore(LEAK)
        made = findings_store.add_many([report(
            "Cellar leak is reporting a water leak",
            source="check:safety.tripped", eid=LEAK, severity="critical")])
        self.assertEqual(len(made), 1)

    def test_a_freeze_and_the_tripwire_still_file(self):
        self.chore()
        for source in ("check:climate.freeze", "security"):
            self.assertEqual(len(findings_store.add_many([report(
                f"Harm from {source}", source=source)])), 1, source)


class TestTheChoreEndingReleasesIt(Case):
    def test_done_releases_the_entity(self):
        item = self.chore()
        todo_store.complete(item["id"])
        self.assertEqual(len(findings_store.add_many([report(
            "Z-Wave cannot reach the cellar pump at night")])), 1)

    def test_dropped_releases_the_entity(self):
        item = self.chore()
        todo_store.remove(item["id"])
        self.assertEqual(len(findings_store.add_many([report(
            "Z-Wave cannot reach the cellar pump at night")])), 1)

    def test_an_unreadable_todo_store_holds_nothing(self):
        self.chore()
        todo_store.TODO_FILE.write_text("{not json")
        self.assertEqual(len(findings_store.add_many([report(
            "Z-Wave cannot reach the cellar pump at night")])), 1)


if __name__ == "__main__":
    unittest.main()
