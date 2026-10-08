#!/usr/bin/env python3
"""A look's reason that only repeats the finding is not a conclusion.

A Resident-filed card read "brAIn checked: <its own claim>", word for word:
the card said it had been reviewed and no conclusion had ever been written.
`refine` stamped the investigation's claim into the triage reason, and the
card's title is that same claim. A reason identical (normalised) to the
row's own text or claim says nothing, so it is never written by a look and
never shown, and the honest line under the card is the one with no reason.
"""

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import cases  # noqa: E402
import findings_store  # noqa: E402
from test_cases import StoresCase  # noqa: E402,F401  (setUp/tearDown)

TEXT = "Hall sensor battery is at 3%"


def _triaging_row() -> dict:
    [row] = findings_store.add_many([{
        "text": TEXT, "detail": "It reads 3%.", "severity": "warning",
        "source": "check:dev.battery_low", "entity_id": "sensor.hall_battery",
        "status": "triaging"}])
    return row


class TestAnEchoIsNotAConclusion(StoresCase):
    def test_refine_does_not_write_the_claim_as_what_the_look_concluded(self):
        row = _triaging_row()
        claim = "The hall sensor's battery is nearly flat"
        findings_store.refine(row["ts"], {"claim": claim, "kind": "problem"},
                              run_id="sess-2")
        stored = findings_store.get(row["ts"])
        self.assertEqual(stored["claim"], claim)
        self.assertNotEqual(
            findings_store.normalize(stored["triage"]["reason"]),
            findings_store.normalize(claim))

    def test_refine_keeps_the_first_look_reason_it_already_had(self):
        row = _triaging_row()
        findings_store.record_triage(
            {row["ts"]: ("elevated", "It fell 20 points in a week.")},
            run_id="look-1")
        findings_store.refine(row["ts"], {"claim": "Battery nearly flat",
                                          "kind": "problem"}, run_id="inv-1")
        stored = findings_store.get(row["ts"])
        self.assertEqual(stored["triage"]["reason"],
                         "It fell 20 points in a week.")

    def test_a_first_look_that_echoes_the_row_writes_no_reason(self):
        row = _triaging_row()
        findings_store.record_triage(
            {row["ts"]: ("elevated", TEXT.lower() + ".")}, run_id="look-1")
        stored = findings_store.get(row["ts"])
        self.assertEqual(stored["triage"]["verdict"], "elevated")
        self.assertEqual(stored["triage"]["reason"], "")

    def test_a_hold_that_echoes_the_row_writes_no_reason(self):
        row = _triaging_row()
        findings_store.hold_after_look(row["ts"], TEXT, run_id="inv-1")
        self.assertEqual(findings_store.get(row["ts"])["triage"]["reason"], "")

    def test_the_tab_and_the_feed_show_no_echo_of_a_case(self):
        claim = "The garage freezer has been drifting warmer"
        row = findings_store.add_case(
            {"text": claim, "claim": claim, "kind": "problem",
             "detail": "6C warmer than a month ago.", "severity": "serious",
             "stakes": "high"}, run_id="sess-1")
        listed = [f for f in findings_store.listing()["findings"]
                  if f["ts"] == row["ts"]]
        self.assertEqual(listed[0]["triage"]["reason"], "")
        self.assertEqual(listed[0]["triage"]["verdict"], "elevated")
        [case] = [c for c in cases.list_cases() if c.get("ts") == row["ts"]
                  or c.get("id") == f"f:{row['ts']}"]
        self.assertEqual(case["triage"]["reason"], "")

    def test_a_real_reason_is_shown(self):
        row = _triaging_row()
        findings_store.record_triage(
            {row["ts"]: ("elevated", "It fell 20 points in a week.")})
        [f] = [f for f in findings_store.listing()["findings"]
               if f["ts"] == row["ts"]]
        self.assertEqual(f["triage"]["reason"], "It fell 20 points in a week.")


if __name__ == "__main__":
    unittest.main()
