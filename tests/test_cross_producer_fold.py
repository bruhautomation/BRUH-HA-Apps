#!/usr/bin/env python3
"""Two insight cards about one sensor are one report, not six.

Reported from a real house: two different cards — one about the cooling
and one about what a dehumidifier costs — filed the same diagnosis about
the same sensor six times over ten days, two of them open and four held.
The subject fold already made one card's rewordings one row; it was keyed
on `(entity_id, source)` and so never saw the second card. A model-written
report about an entity that already has a LIVE model-written row about it
now folds into that row, whichever card wrote it — with the same refusals
the subject fold always had, plus two of its own: never against a row that
is not live (a fix brAIn made is a dated event), and never the Resident,
whose case is the look itself and refines a row rather than filing beside
one (`test_subject_fold`'s different-producer case is that boundary).

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

SENSOR = "sensor.example_cooling_hours"


def card(text: str, source: str, eid: str = SENSOR, **over) -> dict:
    return {"text": text, "entity_id": eid, "source": source,
            "source_title": source.title(), "severity": "warning",
            "detail": over.pop("detail", ""), **over}


class TestTwoCardsOneSensor(FoldCase):

    def test_a_second_card_folds_into_the_first_cards_row(self):
        first = findings_store.add_many(triage.gate([card(
            "Cooling hours yesterday reads 0 while the AC ran", "hvac")]))
        self.assertEqual(len(first), 1)
        again = findings_store.add_many(triage.gate([card(
            "The cooling-hours sensor is stuck at zero", "dehumidifier",
            detail="it read 0 on a day the compressor ran for hours")]))
        self.assertEqual(again, [])
        rows = findings_store.list_all()
        self.assertEqual(len(rows), 1)
        # Refreshed in place: the newer report's evidence is on the row.
        self.assertIn("compressor ran", rows[0]["detail"])

    def test_a_held_row_absorbs_every_re_report_from_any_card(self):
        [row] = findings_store.add_many(triage.gate([card(
            "Cooling hours yesterday reads 0", "hvac")]))
        findings_store.record_triage({row["ts"]: ("held", "seasonal")})
        for i, source in enumerate(("hvac", "dehumidifier", "hvac",
                                    "dehumidifier")):
            findings_store.add_many(triage.gate([card(
                f"Cooling hours reads zero again ({i})", source)]))
        rows = findings_store.list_all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "held")


class TestWhatTheCrossFoldNeverTouches(FoldCase):

    def test_a_check_row_is_never_folded_into(self):
        findings_store.add_many([card("Cooling hours sensor frozen",
                                      "check:dev.frozen")])
        self.assertEqual(len(findings_store.add_many([card(
            "Cooling hours reads 0 while the AC ran", "hvac")])), 1)

    def test_a_check_is_never_folded_into_a_card_row(self):
        findings_store.add_many([card("Cooling hours reads 0", "hvac")])
        self.assertEqual(len(findings_store.add_many([card(
            "Cooling hours sensor frozen", "check:dev.frozen")])), 1)

    def test_a_row_brain_fixed_does_not_hold_the_entity(self):
        [row] = findings_store.add_many([card("Cooling hours reads 0", "hvac")])
        items = findings_store._load()
        for e in items:
            if int(e.get("ts") or 0) == row["ts"]:
                e["status"] = "fixed"
        findings_store._write(items)
        self.assertEqual(len(findings_store.add_many([card(
            "Cooling hours stopped counting again", "dehumidifier")])), 1)

    def test_a_safety_family_producer_is_never_folded(self):
        findings_store.add_many([card("Cooling hours reads 0", "hvac")])
        self.assertEqual(len(findings_store.add_many([card(
            "Somebody corrected the cooling hours", "correction")])), 1)

    def test_a_report_about_no_entity_is_never_folded(self):
        findings_store.add_many([card("The house is warm", "hvac", eid="")])
        self.assertEqual(len(findings_store.add_many([card(
            "Upstairs runs hot", "dehumidifier", eid="")])), 1)

    def test_the_resident_is_the_exclusion_by_its_own_name(self):
        self.assertIn(findings_store.RESIDENT_SOURCE,
                      findings_store.CROSS_FOLD_EXCLUDED)

    def test_a_wrong_given_to_one_card_does_not_silence_another(self):
        """The ledger fold stays per producer: a person told THIS card it
        had misread the house, which says nothing about another card's
        claim about the same sensor."""
        [row] = findings_store.add_many([card("Cooling hours reads 0", "hvac")])
        findings_store.settle_and_clear(row["ts"], "ignored", note="by design")
        self.assertEqual(len(findings_store.add_many([card(
            "Cooling hours reads zero", "dehumidifier")])), 1)


if __name__ == "__main__":
    unittest.main()
