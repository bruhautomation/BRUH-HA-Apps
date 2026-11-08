#!/usr/bin/env python3
"""The turns of the year, held to the review of #643.

  * "The last cooling run of the year" is said only late in the season and
    only over days that were measured cool: a three-week lull in July is
    not the end of summer, and a gap with no daily highs says nothing.
  * A brief whose reasons could not be written up is not sent as a
    season sentence alone (the reasons would vanish), and a season sentence
    whose notification failed stays unsaid.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import importlib
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import brief  # noqa: E402
import seasons  # noqa: E402

UTC = dt.timezone.utc


def span(first: str, last: str) -> list[str]:
    a, b = dt.date.fromisoformat(first), dt.date.fromisoformat(last)
    out = []
    while a <= b:
        out.append(a.isoformat())
        a += dt.timedelta(days=1)
    return out


def house(cooling: dict[str, float], cool_from: str, today: str,
          high: float | None = 20.0) -> dict:
    """Cooling ran on `cooling`'s days at those highs; every day from
    `cool_from` to `today` was watched and topped out at `high`."""
    store: dict = {}
    seasons.note_climate(store, {"cooling": set(cooling)},
                         span(min(cooling), today))
    for day, value in cooling.items():
        seasons.note_high(store, day, value)
    if high is not None:
        for day in span(cool_from, today):
            seasons.note_high(store, day, high)
    return store


class TestTheLastCoolingRun(unittest.TestCase):
    def test_a_july_lull_is_not_the_end_of_summer(self):
        store = house({"2026-06-20": 30.0, "2026-07-02": 29.0},
                      "2026-07-03", "2026-07-28")
        self.assertEqual(seasons.detect(store, "2026-07-28"), [])
        self.assertEqual(seasons.due_lines(store, "2026-07-28", UTC), [])

    def test_the_south_says_it_in_autumn(self):
        store = house({"2026-02-10": 31.0, "2026-03-01": 28.0},
                      "2026-03-02", "2026-03-25")
        new = seasons.detect(store, "2026-03-25", seasons.SOUTH)
        self.assertEqual([e["key"] for e in new], ["cooling_end:2026"])
        # And the same lull in the north's March is not its autumn.
        self.assertEqual(seasons.detect(
            house({"2026-02-10": 31.0, "2026-03-01": 28.0},
                  "2026-03-02", "2026-03-25"), "2026-03-25"), [])

    def test_warm_days_without_cooling_are_not_cool_days(self):
        # Late September, three weeks without the cooling running, but the
        # days were as hot as the ones it ran on: away, or a window open.
        store = house({"2026-08-20": 29.0, "2026-09-04": 28.0},
                      "2026-09-05", "2026-09-28", high=30.0)
        self.assertEqual(seasons.detect(store, "2026-09-28"), [])

    def test_no_daily_highs_says_nothing(self):
        store = house({"2026-08-20": 29.0, "2026-09-04": 28.0},
                      "2026-09-05", "2026-09-28", high=None)
        self.assertEqual(seasons.detect(store, "2026-09-28"), [])

    def test_the_forecast_read_keeps_todays_high(self):
        store: dict = {}
        seasons.note_forecast(store, [
            {"date": "2026-09-10", "low": 8.0, "high": 66.2, "unit": "°F"},
            {"date": "2026-09-11", "low": 9.0, "high": 90.0, "unit": "°F"}],
            "2026-09-10")
        self.assertEqual(store["seen"]["high"], {"2026-09-10": 19.0})


class TestTheClimateRead(unittest.TestCase):
    def test_only_climate_entities_and_capped(self):
        names = {f"climate.room_{i:02d}": {} for i in range(30)}
        names["sensor.hall"] = {}
        ids = seasons.climate_ids(names)
        self.assertEqual(len(ids), seasons.MAX_CLIMATE)
        self.assertTrue(all(i.startswith("climate.") for i in ids))


class TestTheBriefKeepsWhatItOwes(unittest.TestCase):
    def setUp(self):
        self.server = importlib.import_module("server")
        self.tmp = tempfile.TemporaryDirectory()
        s = self.server
        self.saved = (s._diagnostics_payload, s._brief_overnight,
                      s.findings_store.list_all, s._send_notification,
                      s._claude, s.occasions.STORE, s._house_hemisphere,
                      s.schedule_store.set_text, s.BRIEF_STATE.copy(),
                      s.baselines.house_timezone, brief.worth_saying)
        s.occasions.STORE = Path(self.tmp.name) / "occasions.json"
        s._diagnostics_payload = lambda: {}

        async def overnight(now):
            return {}
        s._brief_overnight = overnight
        s.findings_store.list_all = lambda *a, **k: []
        s._house_hemisphere = lambda: seasons.NORTH
        s.schedule_store.set_text = lambda *a, **k: None
        s.baselines.house_timezone = lambda: (UTC, "UTC")
        self.sent: list[str] = []
        self.deliver = True

        async def send(rows, *a, message=None, **k):
            if self.deliver:
                self.sent.append(message[1] if message else rows[0]["text"])
            return self.deliver
        s._send_notification = send
        self.now = dt.datetime(2026, 12, 21, 8, 0, tzinfo=UTC).timestamp()

    def tearDown(self):
        s = self.server
        (s._diagnostics_payload, s._brief_overnight, s.findings_store.list_all,
         s._send_notification, s._claude, s.occasions.STORE,
         s._house_hemisphere, s.schedule_store.set_text, state,
         s.baselines.house_timezone, brief.worth_saying) = self.saved
        s.BRIEF_STATE.clear()
        s.BRIEF_STATE.update(state)
        self.tmp.cleanup()

    def said(self) -> dict:
        return seasons.load(self.server._seasons_path()).get("said") or {}

    def test_a_failed_summary_is_not_sent_as_the_solstice_alone(self):
        brief.worth_saying = lambda state: ["The garage freezer is warm"]

        async def claude(*a, **k):
            return {"ok": False, "error": "rate limited"}
        self.server._claude = claude
        body = asyncio.run(self.server._send_brief(self.now))
        self.assertEqual(body, "")
        self.assertEqual(self.sent, [])
        # The solstice is still owed: nothing went out.
        self.assertEqual(self.said(), {})
        self.assertEqual(len(self.server._season_turns(self.now)), 1)

    def test_a_failed_notification_leaves_the_sentence_unsaid(self):
        async def claude(*a, **k):
            raise AssertionError("no model for a season-only morning")
        self.server._claude = claude
        self.deliver = False
        asyncio.run(self.server._send_brief(self.now))
        self.assertEqual(self.said(), {})
        self.assertEqual(len(self.server._season_turns(self.now)), 1)
        self.deliver = True
        asyncio.run(self.server._send_brief(self.now + 3600))
        self.assertEqual(len(self.said()), 1)
        self.assertEqual(self.server._season_turns(self.now + 7200), [])


if __name__ == "__main__":
    unittest.main()
