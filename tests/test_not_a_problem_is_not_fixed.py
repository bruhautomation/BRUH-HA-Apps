#!/usr/bin/env python3
""""Not a problem, because…" is the rule's exception, never "I fixed it".

A homeowner told brAIn a battery finding was wrong (the device is mains
powered). What landed was a memory line about the room and a settled
`fixed`: no `exception:dev.battery_low` on the entity, the decision trail
reading "you said you had fixed it" every pass, and — `fixed` being a claim
that lapses when its check still reports the problem — the row back as a
recurrence a few hours later. The Repairs reason box sits under "Not a
problem", and the interpreter reading the words could turn that press into
`done`, which is the one ending that says the opposite of the press.

The box's sibling in the same dialog is "I've fixed it", so the reason box
never needs to carry a fix: the words decide how wide and how long the
correction is, and whether it is really a "later", never that the press
meant "fixed". "I've fixed it" still means fixed, from the dialog's own
step and from a phone reply.

Driven through the real request drain (`_apply_finding_requests`) with only
the model's reply stubbed.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import decision_trail  # noqa: E402
import deliveries  # noqa: E402
import findings_store  # noqa: E402
import interpret  # noqa: E402
import journal  # noqa: E402
from test_interpret import PhoneCase  # noqa: E402

TEXT = "Hall sensor battery is at 0%"


class NotAProblemCase(PhoneCase):
    ENTITY = "sensor.hall_battery"

    def setUp(self):
        super().setUp()
        root = Path(self.tmp.name)
        self._paths = (journal.JOURNAL_FILE, deliveries.DELIVERIES_FILE)
        journal.JOURNAL_FILE = str(root / "journal.jsonl")
        deliveries.DELIVERIES_FILE = root / "deliveries.jsonl"

    def tearDown(self):
        journal.JOURNAL_FILE, deliveries.DELIVERIES_FILE = self._paths
        super().tearDown()

    def battery_row(self):
        # A row the Resident looked at: the check's text, a claim of the
        # investigation's own and the fact it would teach on a yes.
        entry, created = findings_store.add(
            TEXT, severity="warning", detail="It reads 0%.",
            fix="Replace the battery.", source="check:dev.battery_low",
            source_title="Battery low", entity_id=self.ENTITY)
        self.assertTrue(created)
        findings_store.refine(entry["ts"], {
            "claim": "The hall sensor's battery looks flat", "kind": "problem",
            "memory_hint": "The hall sensor is in the laundry room."},
            run_id="inv-1")
        return findings_store.get(entry["ts"])

    def settled_kind(self):
        key = findings_store.normalize(TEXT)
        kinds = [e.get("kind") for e in findings_store.settled_listing()
                 if e.get("key") == key]
        return kinds[0] if kinds else None

    def repairs(self, row, action, note=""):
        self.server.finding_requests.collect = lambda: [
            {"ts": row["ts"], "action": action, "note": note,
             "hours": None, "via": "repairs"}]

        async def body(_client):
            return await self.server._apply_finding_requests()

        return self.drive(body)

    def battery_rules(self):
        return [r for r in self.rules()
                if r.get("predicate") == "exception:dev.battery_low"]


class TestTheReasonBoxIsTheCorrection(NotAProblemCase):
    SAID = "That's wrong, it's mains powered — there is no battery in it."

    def test_a_done_read_off_the_words_does_not_overrule_the_press(self):
        row = self.battery_row()
        self.replies["interpret"] = {"routes": [
            {"kind": "remember",
             "text": "The hall sensor in the laundry room is mains powered"},
            {"kind": "case_ending", "ending": "done", "note": ""}]}

        results = self.repairs(row, "wrong", self.SAID)
        self.assertTrue(results[0]["ok"])
        self.assertIsNone(findings_store.get(row["ts"]))
        self.assertEqual(self.settled_kind(), "ignored")
        rules = self.battery_rules()
        self.assertEqual(len(rules), 1, rules)
        self.assertIn(self.ENTITY, rules[0].get("subjects") or [
            rules[0].get("subject")])

    def test_the_trail_says_what_was_recorded(self):
        row = self.battery_row()
        self.replies["interpret"] = {"routes": [
            {"kind": "case_ending", "ending": "done", "note": ""}]}
        self.repairs(row, "wrong", self.SAID)

        # The next pass reports it again and the store swallows it: the
        # trail's sentence is the ledger's own kind.
        self.server._note_pass_decisions(
            {"findings": [{"text": TEXT, "source": "check:dev.battery_low",
                           "entity_id": self.ENTITY}]}, [])
        rows, readable = decision_trail.read()
        self.assertTrue(readable)
        reasons = [r.get("reason") for r in rows]
        self.assertTrue(reasons, "the pass wrote nothing to the trail")
        self.assertNotIn("you said you had fixed it", reasons)
        self.assertIn("you marked it Not a problem", reasons)

    def test_the_interpreter_cannot_carry_a_fix_from_that_box(self):
        got = interpret.parse({"routes": [
            {"kind": "case_ending", "ending": "done"}]}, "repairs", "x")
        self.assertIsNone(got)
        kept = interpret.parse({"routes": [
            {"kind": "case_ending", "ending": "todo"}]}, "repairs", "x")
        self.assertEqual(kept[0]["ending"], "todo")


class TestIveFixedItStillMeansFixed(NotAProblemCase):
    def test_the_dialogs_own_fixed_step(self):
        row = self.battery_row()
        self.repairs(row, "fixed")
        self.assertIsNone(findings_store.get(row["ts"]))
        self.assertEqual(self.settled_kind(), "fixed")
        self.assertEqual(self.battery_rules(), [])

    def test_a_phone_reply_that_says_it_was_fixed(self):
        row = self.battery_row()
        self.replies["interpret"] = {"routes": [
            {"kind": "case_ending", "ending": "done",
             "note": "replaced the CR2032"}]}

        async def body(_client):
            return await self.server._reply_to_finding(
                row, "replaced the CR2032")

        ok, why = self.drive(body)
        self.assertTrue(ok, why)
        self.assertEqual(self.settled_kind(), "fixed")
        self.assertEqual(self.battery_rules(), [])


if __name__ == "__main__":
    unittest.main()
