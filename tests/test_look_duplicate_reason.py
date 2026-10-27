#!/usr/bin/env python3
"""A look that says a row repeats another open finding folds it away, and
never shows that as the row's own reason (#448).

A house had rows shown under brAIn's check with "…is already an open
problem for you" — a sentence about the LIST, written on the very row it
called a repeat — and those rows had lost their what-to-do, because a
concluded look hides the rule's own fix. Three halves:

  * a first look whose reason says the row repeats another open finding is
    read as the `duplicate` it is, so the row is set aside, not shown;
  * a reason saying so, or one that names the row it is on, is never shown
    on a card;
  * and with no real conclusion shown, the rule's what-to-do comes back.
"""

import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import cases  # noqa: E402
import findings_store  # noqa: E402
import resident  # noqa: E402
import triage  # noqa: E402

FIX = "Restart the access point the garage cameras connect through."


def _row(reason, **over):
    row = {"ts": 1_700_000_000, "status": "open", "severity": "warning",
           "text": "The garage cameras keep dropping off the network",
           "detail": "Four drops in a day.", "fix": FIX, "fix_by": "",
           "source": "check:net.wifi_flapping",
           "entity_id": "camera.garage_side",
           "triage": {"verdict": "elevated", "reason": reason, "at": 1}}
    row.update(over)
    return row


# Reasons that only say the row repeats something else on the list.
REPEATS = (
    "The garage cameras dropping is already an open problem for you.",
    "This duplicates another open finding about the same access point.",
    "Same problem as the open card about the garage access point.",
    "Already covered by an open finding.",
)


class TestADuplicateVerdictFoldsTheRow(unittest.TestCase):

    def test_a_first_look_that_calls_a_row_a_repeat_sets_it_aside(self):
        for why in REPEATS:
            out = resident.parse_first_look(
                {"verdicts": [{"id": 1, "verdict": "watch", "why": why}]}, 1,
                [{"kind": "check", "subject": "camera.garage_side",
                  "finding_ts": 1}])
            self.assertEqual(out[1]["verdict"], "ignore", why)
            self.assertEqual(out[1].get("already"), "duplicate", why)

    def test_a_reason_about_the_house_is_not_a_repeat(self):
        for why in ("The cameras drop when the garage door motor runs.",
                    "Normal for this camera at night."):
            out = resident.parse_first_look(
                {"verdicts": [{"id": 1, "verdict": "watch", "why": why}]}, 1)
            self.assertEqual(out[1]["verdict"], "watch", why)

    def test_the_never_ignore_floor_still_wins(self):
        out = resident.parse_first_look(
            {"verdicts": [{"id": 1, "verdict": "watch", "why": REPEATS[0]}]},
            1, [{"kind": "state", "subject": "binary_sensor.leak",
                 "safety": True, "hot": True}])
        self.assertNotEqual(out[1]["verdict"], "ignore")


class TestARepeatIsNeverTheRowsOwnReason(unittest.TestCase):

    def test_a_repeat_reason_is_not_shown_and_the_fix_comes_back(self):
        for why in REPEATS:
            case = cases._from_finding(_row(why), {})
            self.assertEqual(case["triage"].get("reason") or "", "", why)
            self.assertEqual(case["fix"], FIX, why)

    def test_a_reason_naming_the_row_it_is_on_is_not_shown(self):
        why = ("The garage cameras keep dropping off the network, which "
               "brAIn is following.")
        case = cases._from_finding(_row(why), {})
        self.assertEqual(case["triage"].get("reason") or "", "")
        self.assertEqual(case["fix"], FIX)

    def test_a_real_conclusion_is_still_shown(self):
        why = "The drops line up with the garage door motor running."
        case = cases._from_finding(_row(why), {})
        self.assertEqual(case["triage"]["reason"], why)


class TestTheListingAgrees(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self._old = (findings_store.FINDINGS_FILE, findings_store.INBOX_DIR,
                     findings_store.SETTLED_FILE, findings_store.STATE_FILE)
        findings_store.FINDINGS_FILE = root / "findings.json"
        findings_store.INBOX_DIR = root / "inbox"
        findings_store.SETTLED_FILE = root / "settled.json"
        findings_store.STATE_FILE = root / "none" / ".brain" / "state.json"

    def tearDown(self):
        (findings_store.FINDINGS_FILE, findings_store.INBOX_DIR,
         findings_store.SETTLED_FILE, findings_store.STATE_FILE) = self._old
        self.tmp.cleanup()

    def test_the_tab_shows_no_repeat_reason_and_keeps_the_fix(self):
        row = _row(REPEATS[1])
        row.pop("ts")
        findings_store.add_many(triage.gate([{
            k: v for k, v in row.items() if k not in ("status", "triage")}]))
        items = findings_store._load()
        items[0]["status"] = "open"
        items[0]["triage"] = {"verdict": "elevated", "reason": REPEATS[1],
                              "at": 1}
        findings_store._write(items)
        [shown] = findings_store.listing()["findings"]
        self.assertEqual((shown.get("triage") or {}).get("reason") or "", "")
        self.assertEqual(shown["fix"], FIX)


if __name__ == "__main__":
    unittest.main()
