#!/usr/bin/env python3
"""A finding is read against the house as it is now, and a figure that
cannot be real is asked about, never stated (#722).

* "The hall plug is unplugged and 6 scenes still set it" stayed on the list
  after the plug came back. A row from a producer that does not re-check
  its own rows, saying something is unplugged, offline or unavailable, is
  re-read against the entity's latest state just before it is shown (the
  list and the feed): every entity it names reporting a real state that
  changed after the row was filed means it is not shown.
* A car's service reminder said "19,766 miles overdue" off a reminder whose
  interval is 1,000 miles. A figure more than ten times the interval it is
  measured against is a reminder set up wrong: the row asks about the
  setting instead of stating an overdue figure. The second example is a
  filter reminder in days.
"""
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import cases  # noqa: E402
import findings_store  # noqa: E402
from test_subject_fold import FoldCase  # noqa: E402


def unplugged(ts_entity="switch.hall_plug"):
    return {"text": "Hall plug is unplugged and 6 scenes still set it",
            "claim": "Hall plug is unplugged and 6 scenes still set it",
            "detail": "Six scenes still turn it on.",
            "fix": "Take the hall plug out of the six scenes.",
            "source": "sre", "kind": "problem", "severity": "warning",
            "entity_id": ts_entity, "about": [ts_entity]}


class LiveCase(FoldCase):
    def setUp(self):
        super().setUp()
        self._live = dict(findings_store.LIVE_STATES)
        findings_store.LIVE_STATES.clear()

    def tearDown(self):
        findings_store.LIVE_STATES.clear()
        findings_store.LIVE_STATES.update(self._live)
        super().tearDown()

    def shown(self):
        return [f["text"] for f in findings_store.listing()["findings"]]

    def on_feed(self):
        return [c["claim"] for c in cases.list_cases()]


class TestAStaleClaimIsNotShown(LiveCase):
    def test_a_plug_that_came_back_is_not_shown(self):
        [row] = findings_store.add_many([unplugged()])
        self.assertIn(row["text"], self.shown())
        # Still unplugged: the row stands.
        findings_store.note_state("switch.hall_plug", {
            "state": "unavailable", "last_changed": row["ts"] + 10})
        self.assertIn(row["text"], self.shown())
        # Back on: the claim no longer holds, on the list and on the feed.
        findings_store.note_state("switch.hall_plug", {
            "state": "on", "last_changed": row["ts"] + 60})
        self.assertNotIn(row["text"], self.shown())
        self.assertNotIn(row["claim"], self.on_feed())

    def test_a_reading_from_before_the_filing_proves_nothing(self):
        [row] = findings_store.add_many([unplugged()])
        findings_store.note_state("switch.hall_plug", {
            "state": "on", "last_changed": row["ts"] - 3600})
        self.assertIn(row["text"], self.shown())

    def test_an_offline_speaker_back_online_is_not_shown(self):
        # A second producer and a second word: an insight card's speaker.
        [row] = findings_store.add_many([{
            "text": "Kitchen speaker is offline",
            "claim": "Kitchen speaker is offline", "source": "media",
            "kind": "problem", "entity_id": "media_player.kitchen",
            "fix": "Power-cycle the kitchen speaker."}])
        findings_store.note_state("media_player.kitchen", {
            "state": "idle", "last_changed": row["ts"] + 5})
        self.assertNotIn(row["text"], self.shown())

    def test_a_house_check_row_is_left_to_its_check(self):
        [row] = findings_store.add_many([{
            "text": "Hall plug has been unavailable for a day",
            "source": "check:dev.unavailable",
            "entity_id": "switch.hall_plug", "fix": "Plug it back in."}])
        findings_store.note_state("switch.hall_plug", {
            "state": "on", "last_changed": row["ts"] + 60})
        self.assertIn(row["text"], self.shown())

    def test_a_safety_row_is_always_shown(self):
        [row] = findings_store.add_many([{
            "text": "Leak sensor under the sink is offline",
            "source": "safety", "entity_id": "binary_sensor.sink_leak"}])
        findings_store.note_state("binary_sensor.sink_leak", {
            "state": "off", "last_changed": row["ts"] + 60})
        self.assertIn(row["text"], self.shown())


class TestAFigureBeyondItsIntervalIsAQuestion(FoldCase):
    def test_miles_overdue_far_past_the_interval(self):
        [row] = findings_store.add_many([{
            "text": "Car service is 19,766 miles overdue",
            "claim": "Car service is 19,766 miles overdue",
            "detail": "The service reminder is set to every 1,000 miles.",
            "fix": "Book the car in for a service.",
            "source": "resident", "kind": "problem",
            "entity_id": "sensor.car_service_due"}])
        shown = " ".join(str(row.get(k) or "") for k in
                         ("text", "claim", "detail", "fix"))
        self.assertNotIn("overdue", shown.lower())
        self.assertEqual(row["kind"], "question")
        self.assertIn("?", row["claim"])
        self.assertIn("setting", row["claim"].lower())
        self.assertNotIn("Book the car", row["fix"])

    def test_days_overdue_far_past_the_interval(self):
        [row] = findings_store.add_many([{
            "text": "The furnace filter change is 412 days overdue",
            "claim": "The furnace filter change is 412 days overdue",
            "detail": "The reminder repeats every 30 days.",
            "source": "resident", "kind": "problem",
            "entity_id": "sensor.furnace_filter"}])
        self.assertEqual(row["kind"], "question")
        self.assertNotIn("overdue", row["claim"].lower())

    def test_a_figure_inside_ten_intervals_is_stated(self):
        [row] = findings_store.add_many([{
            "text": "Car service is 1,200 miles overdue",
            "claim": "Car service is 1,200 miles overdue",
            "detail": "The service reminder is set to every 10,000 miles.",
            "fix": "Book the car in for a service.",
            "source": "resident", "kind": "problem",
            "entity_id": "sensor.car_service_due"}])
        self.assertEqual(row["kind"], "problem")
        self.assertIn("1,200 miles overdue", row["claim"])


if __name__ == "__main__":
    unittest.main()
