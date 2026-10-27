#!/usr/bin/env python3
"""Morph's card is Needs you's card (#452): the same chip, the same who-acts
line and the same presses — Snooze, Check again and Ignore among them — and
each press Morph sends reaches the helper the panel's own button runs.

Driven through the real request drain (`_apply_finding_requests`) over
request files, with only the Claude runs stubbed (`MorphCase`).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import finding_requests  # noqa: E402
import findings_store  # noqa: E402
from test_morph_contracts_drain import MorphCase  # noqa: E402


class TestMorphCanCarryTheNewPresses(unittest.TestCase):
    def test_recheck_and_wrong_are_accepted(self):
        for action in ("recheck", "wrong", "snooze"):
            got = finding_requests.parse({"kind": "morph", "case": "f:12",
                                          "action": action, "text": "why"})
            self.assertIsNotNone(got, action)
            self.assertEqual(got["action"], action)


class TestTheCaseRowIsTheCard(MorphCase):
    def test_chip_who_and_presses_ride_to_morph(self):
        row = self.check_row()
        payload = self.server._morph_cases_payload()
        [case] = [c for c in payload["cases"] if c["id"] == f"f:{row['ts']}"]
        self.assertEqual(case["chip"], "problem")
        self.assertEqual(case["who"]["line"], "This needs you.")
        actions = [a["action"] for a in case["answers"]]
        for action in ("recheck", "dismiss", "snooze", "wrong"):
            self.assertIn(action, actions)
        labels = {a["action"]: a["label"] for a in case["answers"]}
        self.assertEqual(labels["snooze"], "Snooze")
        self.assertEqual(labels["wrong"], "Ignore")


class TestThePressesReachThePanelsHelpers(MorphCase):
    def test_ignore_with_a_reason_is_the_cards_own_wrong(self):
        row = self.check_row()
        self.request({"kind": "morph", "case": f"f:{row['ts']}",
                      "action": "wrong", "text": "It is a cupboard nobody opens.",
                      "via": "morph"})
        got = self.drain()
        self.assertTrue(got[0]["ok"], got)
        self.assertIsNone(findings_store.get(row["ts"]))
        settled = findings_store.settled_listing()
        self.assertEqual([s.get("kind") for s in settled], ["ignored"])
        self.assertIn("cupboard nobody opens", str(settled[0]))

    def test_check_again_runs_the_check(self):
        row = self.check_row()
        seen = []

        async def recheck(finding):
            seen.append(finding["ts"])
            return {"checked": True, "cleared": False, "why": ""}

        old = self.server._recheck_finding
        self.server._recheck_finding = recheck
        try:
            self.request({"kind": "morph", "case": f"f:{row['ts']}",
                          "action": "recheck", "via": "morph"})
            got = self.drain()
        finally:
            self.server._recheck_finding = old
        self.assertTrue(got[0]["ok"], got)
        self.assertEqual(seen, [row["ts"]])


if __name__ == "__main__":
    unittest.main()
