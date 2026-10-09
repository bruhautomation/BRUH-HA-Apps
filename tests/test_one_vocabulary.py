#!/usr/bin/env python3
"""One vocabulary on every pane: a producer in words, and no ratio nobody can read.

Two things the house's own photographs of the panel found, both the same
complaint — the screen printing the machine rather than the house:

* a Needs you card named its producer in whichever style the row was filed
  under: a check's GROUP ("Device check"), a card's title, and on some rows
  the raw `check:…` / `user-…` / `custom-…` id. Every row now carries
  `source_name`, worded once by `server._producer_label` over
  `plain_words.producer_name`, and History's "Everything like this" row
  names a muted rule the same way;
* `base.unusual` said "That is N times its normal variation", and a sensor
  whose normal variation is almost nothing printed "1,109,306 times its
  normal variation". The detail now says what the reading usually is, in
  its own units, and the finding's `text` (the dedupe key) did not move.
"""
from __future__ import annotations

import datetime as dt
import importlib
import re
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import baselines  # noqa: E402
import plain_words  # noqa: E402
import today  # noqa: E402
import test_baselines  # noqa: E402
from checks import baseline as band  # noqa: E402

RAW = re.compile(r"check:[a-z]|\buser-\d|\bcustom-[a-z0-9]|\bProducer\b|\bRun \(")


def flat_house(value: str, median: float, spread: float, unit: str = "%") -> dict:
    """One baselined sensor whose hour's band is `spread` wide."""
    now = test_baselines.MONDAY + 10 * test_baselines.HOUR
    bucket = str(baselines.hour_of_week(now, dt.timezone.utc))
    entry = {"unit": unit, "samples": 650,
             "overall": {"median": median, "spread": spread, "n": 650},
             "buckets": {bucket: {"median": median, "spread": spread, "n": 4}}}
    return {
        "now": now,
        "states": {"sensor.attic_humidity": {
            "state": value,
            "attributes": {"state_class": "measurement", "unit_of_measurement": unit},
            "last_changed": "", "last_updated": ""}},
        "entities": [{"entity_id": "sensor.attic_humidity", "name": "Attic humidity"}],
        "devices": [], "areas": [],
        "baselines": {"built_at": int(now - 3600), "tz": "UTC", "days": 28,
                      "entities": {"sensor.attic_humidity": entry}},
    }


class TestAnUnusualReadingSaysWhatIsUsual(unittest.TestCase):

    def unusual(self, snap):
        return band.unusual(snap, snap["now"])

    def test_a_near_flat_sensor_prints_no_ratio(self):
        """The photographed case: a spread of almost nothing under a real
        move. The old sentence divided by it."""
        found = self.unusual(flat_house("55", 0.0, 0.0000496))
        self.assertEqual(len(found), 1)
        detail = found[0]["detail"]
        self.assertNotIn("times", detail)
        self.assertNotIn("variation", detail)
        self.assertNotRegex(detail, r"\d{1,3}(,\d{3}){2,}")
        self.assertIn("55", detail)
        self.assertIn("It usually reads about 0", detail)

    def test_an_ordinary_band_is_a_range_in_its_own_units(self):
        found = self.unusual(flat_house("28.0", 20.0, 0.5, "°C"))
        detail = found[0]["detail"]
        self.assertIn("28 °C now", detail)
        self.assertIn("It usually reads between 19 °C and 21 °C for this hour "
                      "of the week (from 4 weeks of readings).", detail)

    def test_a_reading_never_below_zero_is_not_usually_below_zero(self):
        found = self.unusual(flat_house("900", 2.0, 20.0, "W"))
        detail = found[0]["detail"]
        self.assertIn("between 0 W and 42 W", detail)
        self.assertNotIn("−", detail)

    def test_the_dedupe_key_did_not_move(self):
        found = self.unusual(flat_house("28.0", 20.0, 0.5, "°C"))
        self.assertEqual(found[0]["text"], "Attic humidity is reading far outside its usual range")


class TestEveryProducerIsNamedInWords(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.server = importlib.import_module("server")

    def setUp(self):
        self._old = self.server.resolve_category
        self.server.resolve_category = (
            lambda cid: {"title": "Laundry watch"}
            if cid == "user-1789499215" else None)

    def tearDown(self):
        self.server.resolve_category = self._old

    def label(self, source, title=""):
        return self.server._producer_label(source, title)

    def test_a_check_is_named_by_its_catalog_title_not_its_group(self):
        name = self.label("check:dev.unavailable", "Device check")
        spec = self.server.checks.get_check("dev.unavailable")
        self.assertEqual(name, spec["title"])
        self.assertNotEqual(name, "Device check")

    def test_no_shape_of_row_reaches_the_screen_as_an_id(self):
        cases = [
            ("check:dev.unavailable", ""),
            ("check:no.such_rule", ""),
            ("user-1789499215", "user-1789499215"),
            ("user-1700000000", ""),
            ("custom-k9x2", "custom-k9x2"),
            ("custom-k9x2", "Custom"),
            ("resident", ""),
            ("mute_offer", "Rules"),
            ("hypothesis", "energy"),
            ("", "check:dev.frozen"),
        ]
        for source, title in cases:
            with self.subTest(source=source, title=title):
                name = self.label(source, title)
                self.assertTrue(name)
                self.assertNotRegex(name, RAW)

    def test_a_card_the_homeowner_made_is_named_by_the_card(self):
        self.assertEqual(self.label("user-1789499215", "user-1789499215"),
                         "Laundry watch")

    def test_a_deleted_asked_card_reads_as_the_scorecard_reads_it(self):
        self.assertEqual(self.label("custom-gone", "Custom"), "A question you asked")

    def test_a_title_somebody_gave_is_kept(self):
        self.assertEqual(self.label("energy-card", "Energy use"), "Energy use")

    def test_the_feed_carries_the_name_on_every_case(self):
        rows = [
            {"id": "f:1", "kind": "problem", "claim": "x", "detail": "",
             "source": "check:dev.unavailable", "source_title": "Device check",
             "origin": {"store": "findings", "key": 1}, "status": "open",
             "severity": "warning", "stakes": "medium", "entity_id": "",
             "evidence": [], "actions": [], "fix": "", "ts": 1},
            {"id": "f:2", "kind": "problem", "claim": "y", "detail": "",
             "source": "custom-k9x2", "source_title": "custom-k9x2",
             "origin": {"store": "findings", "key": 2}, "status": "open",
             "severity": "warning", "stakes": "medium", "entity_id": "",
             "evidence": [], "actions": [], "fix": "", "ts": 2},
        ]
        named = [dict(r) for r in rows]
        self.server._name_producers(named)
        for row in named:
            with self.subTest(row=row["id"]):
                self.assertTrue(row["source_name"])
                self.assertNotRegex(row["source_name"], RAW)
        # A row with no producer gets no name rather than an invented one.
        bare = [{"id": "t:3"}]
        self.server._name_producers(bare)
        self.assertNotIn("source_name", bare[0])

    def test_to_do_names_a_moved_finding(self):
        old = self.server.todo_store.listing
        self.server.todo_store.listing = lambda: {
            "items": [{"id": 2, "text": "Hall sensor", "origin": "finding",
                       "source": "custom-k9x2", "source_title": "custom-k9x2"}],
            "done": [], "open": 1}
        try:
            payload = self.server._todo_payload()
        finally:
            self.server.todo_store.listing = old
        self.assertEqual(payload["items"][0]["source_name"], "A question you asked")


class TestHistoryNamesAMutedRule(unittest.TestCase):

    def test_a_mute_with_no_title_is_named_in_words(self):
        out = today.history(
            findings=[], settled=[], muted=[{"source": "check:forecast.decline", "title": ""}],
            snoozed_cases=[], todo_done=[], tidy_batches=[], hidden_rows={},
            now=1_790_000_000)
        titles = [r["title"] for rows in (out.get("rows") or {}).values() for r in rows]
        mute = [t for t in titles if t.startswith("Everything like this")]
        self.assertTrue(mute, titles)
        self.assertNotRegex(mute[0], RAW)
        self.assertEqual(mute[0], "Everything like this: "
                         + plain_words.producer_name("check:forecast.decline"))


if __name__ == "__main__":
    unittest.main()
