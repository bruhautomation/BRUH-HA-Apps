#!/usr/bin/env python3
"""An open card never carries a look's argument for not showing it.

A real house had five OPEN rows whose "brAIn checked" line argued against
the card being there at all: "this is the known dropout, nothing new was
added", "unused helpers are clutter and change nothing". Each was a row
silence had already put on the list (`triage.UNJUDGED`); a later look
answered `ignore` about it, and `record_triage`'s late-verdict path keeps
such a row `open` — a row on screen never vanishes into a run — while
writing the look's reason onto it. The verdict is still recorded (the look
did judge the row); what a person reads beside an open card must not be a
sentence saying it should not be there. And a reason that names an entity
the row is not about — neither its own nor one in its evidence — is about
some other row, so it is not shown either.
"""

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import cases  # noqa: E402
import findings_store  # noqa: E402
import triage  # noqa: E402
from test_cases import StoresCase  # noqa: E402,F401  (setUp/tearDown)

TEXT = "Hall plug keeps dropping off the network"


DROPOUT = "This is the known dropout, nothing new was added."


def _shown_row(reason_verdict=("held", DROPOUT)):
    [row] = findings_store.add_many([{
        "text": TEXT, "detail": "It went unavailable 4 times today.",
        "severity": "warning", "source": "check:dev.unavailable",
        "entity_id": "switch.hall_plug", "status": "triaging",
        "evidence": [{"entity": "sensor.hall_plug_power", "value": "0 W",
                      "when": ""}]}])
    # Silence shows it first, then a look answers about it late.
    findings_store.record_triage({row["ts"]: ("untriaged", triage.UNJUDGED)})
    findings_store.record_triage({row["ts"]: reason_verdict}, run_id="look-2")
    return row


def _listed(ts):
    [f] = [f for f in findings_store.listing()["findings"] if f["ts"] == ts]
    return f


def _case(ts):
    [c] = [c for c in cases.list_cases() if c.get("id") == f"f:{ts}"]
    return c


class TestAnIgnoreReasonIsNotShownBesideAnOpenCard(StoresCase):
    def test_the_row_stays_open_and_the_reason_is_not_shown(self):
        row = _shown_row()
        stored = findings_store.get(row["ts"])
        self.assertEqual(stored["status"], "open")
        self.assertEqual(stored["triage"]["verdict"], "held")
        self.assertEqual(_listed(row["ts"])["triage"]["reason"], "")
        self.assertEqual(_case(row["ts"])["triage"]["reason"], "")

    def test_an_elevating_reason_is_still_shown(self):
        row = _shown_row(("elevated", "It dropped four times in an hour."))
        self.assertEqual(_listed(row["ts"])["triage"]["reason"],
                         "It dropped four times in an hour.")

    def test_a_held_row_keeps_its_reason_in_history(self):
        [row] = findings_store.add_many([{
            "text": TEXT, "severity": "warning", "status": "triaging",
            "source": "check:dev.unavailable", "entity_id": "switch.hall_plug"}])
        findings_store.record_triage(
            {row["ts"]: ("held", "A passing moment.")}, run_id="look-1")
        self.assertEqual(_listed(row["ts"])["triage"]["reason"],
                         "A passing moment.")


class TestAReasonAboutAnotherEntityIsDropped(StoresCase):
    def test_another_rows_entity_is_not_this_rows_reason(self):
        row = _shown_row(("elevated", "Same as sensor.garage_freezer_temp, "
                                      + "which you already know about."))
        self.assertEqual(_listed(row["ts"])["triage"]["reason"], "")
        self.assertEqual(_case(row["ts"])["triage"]["reason"], "")

    def test_its_own_entity_and_its_evidence_are_fine(self):
        row = _shown_row(("elevated", "switch.hall_plug went away four times "
                                      + "and sensor.hall_plug_power read 0 W."))
        self.assertIn("four times", _listed(row["ts"])["triage"]["reason"])

    def test_a_dotted_word_that_is_no_entity_is_fine(self):
        row = _shown_row(("elevated", "The log names automations.yaml and "
                                      + "version 2.18.5."))
        self.assertIn("automations.yaml", _listed(row["ts"])["triage"]["reason"])


if __name__ == "__main__":
    unittest.main()
