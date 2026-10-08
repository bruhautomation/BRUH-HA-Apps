#!/usr/bin/env python3
"""A question somebody asked about an entity a house check already
reported is one card, not two.

Reported from a real house: "Your question" filed that a sensor's battery
was flat while `check:dev.battery_low` already had an open row about the
same sensor — two open cards for one battery. An asked report (an asked
card's `custom-<id>`, or the chat) about an entity that has a LIVE check
row now folds into the check's row: the check's text stays (it is the key
the check re-reports and clears under), the check's own detail stands
(every pass rewrites it), and the asked report's detail and fix fill in
only what the check row has none of. Never into a row brAIn fixed, never
into a security or safety check's row, never the Resident and never the
safety/security/correction family on the asking side; and a scheduled
card is a different claim (`test_cross_producer_fold` holds that).

Driven over the real store.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "brain" / "panel"))

import findings_store  # noqa: E402
import triage  # noqa: E402
from test_subject_fold import FoldCase  # noqa: E402

BATTERY = "sensor.back_door_battery"


def row(text, source, eid=BATTERY, **over):
    return {"text": text, "entity_id": eid, "source": source,
            "source_title": source, "severity": "warning", **over}


def check_row(**over):
    return row("Back Door sensor battery is low", "check:dev.battery_low",
               detail=over.pop("detail", "4% as of today."), **over)


class TestAnAskedReportFoldsIntoTheCheck(FoldCase):

    def test_your_question_folds_into_the_battery_check(self):
        [host] = findings_store.add_many(triage.gate([check_row()]))
        again = findings_store.add_many(triage.gate([row(
            "The back door sensor's battery is flat", "custom-abc123",
            detail="It read 4% and has not changed since Monday.",
            fix="Swap the CR2032.")]))
        self.assertEqual(again, [])
        [only] = findings_store.list_all()
        self.assertEqual(only["ts"], host["ts"])
        # The check's text and detail stand; the missing fix is filled.
        self.assertEqual(only["text"], "Back Door sensor battery is low")
        self.assertEqual(only["detail"], "4% as of today.")
        self.assertEqual(only["fix"], "Swap the CR2032.")

    def test_the_check_detail_is_filled_only_when_it_has_none(self):
        findings_store.add_many(triage.gate([check_row(detail="")]))
        findings_store.add_many(triage.gate([row(
            "The battery is flat", "chat", detail="Read 0% at noon.")]))
        [only] = findings_store.list_all()
        self.assertEqual(only["detail"], "Read 0% at noon.")

    def test_a_check_row_brain_fixed_does_not_take_it(self):
        [host] = findings_store.add_many(triage.gate([check_row()]))
        items = findings_store._load()
        for e in items:
            if int(e.get("ts") or 0) == host["ts"]:
                e["status"] = "fixed"
        findings_store._write(items)
        self.assertEqual(len(findings_store.add_many(triage.gate([row(
            "The battery is flat", "custom-abc123")]))), 1)

    def test_a_security_check_row_does_not_take_it(self):
        findings_store.add_many(triage.gate([row(
            "Front door lock answers cloud voice", "check:sec.lock_cloud_voice",
            eid="lock.front")]))
        self.assertEqual(len(findings_store.add_many(triage.gate([row(
            "Is the front lock safe?", "custom-abc123", eid="lock.front")]))), 1)

    def test_the_safety_family_never_folds_into_a_check(self):
        findings_store.add_many(triage.gate([check_row()]))
        self.assertEqual(len(findings_store.add_many([row(
            "Somebody corrected the battery", "correction")])), 1)

    def test_the_resident_never_folds_into_a_check(self):
        findings_store.add_many(triage.gate([check_row()]))
        created = findings_store.add_case({
            **row("Back door battery is really flat", "resident"),
            "claim": "The battery is flat."})
        self.assertIsNotNone(created)

    def test_a_scheduled_card_is_still_its_own_claim(self):
        findings_store.add_many(triage.gate([check_row()]))
        self.assertEqual(len(findings_store.add_many(triage.gate([row(
            "Battery reads low while the door reports", "doors")]))), 1)


if __name__ == "__main__":
    unittest.main()
