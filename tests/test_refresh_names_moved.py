"""A looked-at row whose list of names changed is looked at again.

`sys.entry_failed` files ONE row naming every integration that failed to
set up, and `refresh_details` rewrites its detail in place when another
integration joins the list — while the row went on carrying the look's
verdict about the old list ("nothing new has been added"). A count or a
time moving is the same report; a name joining or leaving it is new
evidence the verdict never saw. A HELD row goes back to `triaging`; a
row already on screen keeps its place and loses the stale verdict, marked
for the next look. Never over a row a person put back.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "brain" / "panel"))

import findings_store  # noqa: E402
from checks import system  # noqa: E402

SOURCE = "check:sys.entry_failed"


def row(detail: str) -> dict:
    return {"text": system.ENTRY_FAILED_TEXT, "detail": detail,
            "severity": "serious", "source": SOURCE, "fixable": False,
            "status": "triaging"}


TWO = ("2: Cloud thing and Garage hub. Everything they provide — entities, "
       "services, devices — is missing from Home Assistant until they load.")
THREE = ("3: Cloud thing, Garage hub and Pool pump. Everything they provide — "
         "entities, services, devices — is missing from Home Assistant until "
         "they load.")


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self._old = (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
                     findings_store.STATE_FILE)
        findings_store.FINDINGS_FILE = base / "findings.json"
        findings_store.SETTLED_FILE = base / "settled.json"
        findings_store.STATE_FILE = base / "nowhere" / ".brain" / "s.json"
        [self.filed] = findings_store.add_many([row(TWO)])

    def tearDown(self):
        (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
         findings_store.STATE_FILE) = self._old
        self.tmp.cleanup()

    def look(self, verdict: str, reason="Nothing new has been added."):
        findings_store.record_triage({self.filed["ts"]: (verdict, reason)})

    def stored(self) -> dict:
        return next(e for e in findings_store._load()
                    if e["ts"] == self.filed["ts"])


class TestANewNameIsNewEvidence(Case):
    def test_a_held_row_goes_back_to_be_looked_at(self):
        self.look("held")
        self.assertEqual(self.stored()["status"], "held")
        findings_store.refresh_details([row(THREE)])
        got = self.stored()
        self.assertEqual(got["status"], "triaging")
        self.assertEqual(got["detail"], THREE)

    def test_an_open_row_keeps_its_place_and_loses_the_stale_verdict(self):
        self.look("elevated")
        self.assertEqual(self.stored()["status"], "open")
        findings_store.refresh_details([row(THREE)])
        got = self.stored()
        self.assertEqual(got["status"], "open")
        self.assertNotIn("Nothing new", got["triage"].get("reason", ""))
        # And the next look is offered it.
        self.assertIn(self.filed["ts"],
                      [r["ts"] for r in findings_store.unjudged_open()])

    def test_a_count_or_a_date_moving_is_the_same_report(self):
        self.look("held")
        findings_store.refresh_details([row(TWO.replace("2:", "02:"))])
        self.assertEqual(self.stored()["status"], "held")

    def test_never_over_a_row_a_person_put_back(self):
        self.look("held")
        findings_store.elevate(self.filed["ts"])
        before = self.stored()
        findings_store.refresh_details([row(THREE)])
        got = self.stored()
        self.assertEqual(got["status"], before["status"])
        self.assertTrue(got["triage"]["elevated_by_person"])


if __name__ == "__main__":
    unittest.main()
