#!/usr/bin/env python3
"""A reworded report about the same entity from the same model is the same
report.

Ten findings about one pair of "Cooling Time Yesterday" history_stats
sensors were filed over three weeks — Sep 16, 20, 22, 23, 28, 29 twice,
Oct 1, 3 and 4 — each worded differently, so each passed a dedupe keyed on
normalised text, and some said "change the window" while others said it
was by design. For a producer whose sentences a model writes, the entity
plus the producer is the key as well as the text, against the live list
(any status) and against a "Wrong" already given. A house check keeps its
text-only dedupe (its text is stable, and one check may say two different
things about one entity); a different producer about the same entity is a
different claim; and the safety lane, whose rows are one per trip, is
never folded.

Driven over the real store.
"""
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import findings_store  # noqa: E402

COOLING = "sensor.cooling_time_yesterday"


def report(text: str, source: str = "resident", eid: str = COOLING) -> dict:
    return {"text": text, "entity_id": eid, "source": source,
            "source_title": "The Resident", "severity": "warning"}


class FoldCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self._old = (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
                     findings_store.STATE_FILE)
        findings_store.FINDINGS_FILE = root / "findings.json"
        findings_store.SETTLED_FILE = root / "settled.json"
        findings_store.STATE_FILE = root / "nowhere" / ".brain" / "s.json"

    def tearDown(self):
        (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
         findings_store.STATE_FILE) = self._old
        self.tmp.cleanup()


class TestTheSameSubject(FoldCase):

    def test_a_reworded_report_folds_into_the_one_already_there(self):
        first = findings_store.add_many([report(
            "Cooling Time Yesterday reads 0 h because its window misses "
            "midnight")])
        self.assertEqual(len(first), 1)
        again = findings_store.add_many([report(
            "Cooling Time Yesterday is by design and should not change")])
        self.assertEqual(again, [])
        self.assertEqual(len(findings_store.list_all()), 1)

    def test_a_snoozed_row_still_holds_its_subject(self):
        first = findings_store.add_many([report("Cooling time looks wrong")])
        findings_store.snooze(first[0]["ts"], 2_000_000_000)
        self.assertEqual(findings_store.add_many([report(
            "The cooling-time sensor's window is off by a day")]), [])

    def test_wrong_is_remembered_for_the_subject_not_just_the_words(self):
        first = findings_store.add_many([report("Cooling time looks wrong")])
        findings_store.settle_and_clear(first[0]["ts"], "ignored",
                                        note="by design")
        self.assertEqual(findings_store.list_all(), [])
        self.assertEqual(findings_store.add_many([report(
            "Change the Cooling Time Yesterday history_stats window")]), [])

    def test_a_fix_is_a_dated_event_and_does_not_hold_the_subject(self):
        first = findings_store.add_many([report("Cooling time looks wrong")])
        findings_store.settle_and_clear(first[0]["ts"], "fixed")
        self.assertEqual(len(findings_store.add_many([report(
            "Cooling Time Yesterday stopped counting again")])), 1)

    def test_two_reworded_reports_in_one_batch_are_one(self):
        created = findings_store.add_many([
            report("Cooling time looks wrong"),
            report("The cooling-time window is off by a day")])
        self.assertEqual(len(created), 1)


class TestWhatIsNeverFolded(FoldCase):

    def test_a_different_producer_about_the_same_entity_is_a_new_claim(self):
        findings_store.add_many([report("Cooling time looks wrong")])
        self.assertEqual(len(findings_store.add_many([report(
            "Cooling time is double-counting", source="climate")])), 1)

    def test_a_house_check_keeps_its_text_only_dedupe(self):
        eid = "sensor.back_door_battery"
        findings_store.add_many([report("Back Door battery is low",
                                        source="check:dev.battery_low",
                                        eid=eid)])
        self.assertEqual(len(findings_store.add_many([report(
            "Back Door has stopped reporting its battery",
            source="check:dev.battery_low", eid=eid)])), 1)

    def test_every_trip_of_a_safety_detector_is_its_own_row(self):
        eid = "binary_sensor.laundry_leak"
        findings_store.add_many([report("Water at Laundry leak (3 Oct 22:10)",
                                        source="safety", eid=eid)])
        self.assertEqual(len(findings_store.add_many([report(
            "Water at Laundry leak (4 Oct 02:40)", source="safety",
            eid=eid)])), 1)

    def test_a_report_about_no_entity_is_deduped_on_its_text(self):
        findings_store.add_many([report("The house is too warm", eid="")])
        self.assertEqual(len(findings_store.add_many([report(
            "Upstairs runs hot every afternoon", eid="")])), 1)


if __name__ == "__main__":
    unittest.main()
