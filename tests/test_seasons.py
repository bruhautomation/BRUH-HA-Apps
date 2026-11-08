#!/usr/bin/env python3
"""The turns of the year, each said once in the morning brief (#643).

brAIn promises one sentence, at a waking hour, for the first frost, the
first heating morning, the solstices and equinoxes, and the last cooling
run (said in hindsight). Every claim is driven:

  * the turning points are computed, and land on the house's own date —
    the September 2026 equinox is the 23rd in London and the 22nd in New
    York, and December's solstice is the summer one in Sydney;
  * a first frost and a first heating run need a watch behind them, so the
    day brAIn was installed is never "the first";
  * the last cooling run is said after enough cool days, never before;
  * the brief says each once: a morning with nothing else to say sends the
    sentence as written without asking a model, a morning with a model's
    paragraph carries it after, and once delivered it never comes back.
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
# The houses' offsets on those dates, fixed so no zone database is needed:
# London in September (BST), New York in September (EDT), Sydney in
# December (AEDT).
LONDON_SEPT = dt.timezone(dt.timedelta(hours=1))
NEW_YORK_SEPT = dt.timezone(dt.timedelta(hours=-4))
SYDNEY_DEC = dt.timezone(dt.timedelta(hours=11))


def days_before(day: str, n: int) -> list[str]:
    d = dt.date.fromisoformat(day)
    return [(d - dt.timedelta(days=i)).isoformat() for i in range(1, n + 1)]


class TestTurningPoints(unittest.TestCase):
    def test_2026_instants_match_the_almanac(self):
        # Published: 20 Mar 14:46, 21 Jun 08:24, 23 Sep 00:05, 21 Dec 20:50 UTC.
        want = [dt.datetime(2026, 3, 20, 14, 46, tzinfo=UTC),
                dt.datetime(2026, 6, 21, 8, 24, tzinfo=UTC),
                dt.datetime(2026, 9, 23, 0, 5, tzinfo=UTC),
                dt.datetime(2026, 12, 21, 20, 50, tzinfo=UTC)]
        for which, expected in enumerate(want):
            got = seasons.turning_instant(2026, which)
            self.assertLess(abs((got - expected).total_seconds()), 300)

    def test_the_date_is_the_houses_own(self):
        london = seasons.turning_points(2026, LONDON_SEPT)
        new_york = seasons.turning_points(2026, NEW_YORK_SEPT)
        self.assertEqual(london[2]["date"], "2026-09-23")
        self.assertEqual(new_york[2]["date"], "2026-09-22")
        self.assertEqual(london[2]["name"], "autumn equinox")

    def test_the_southern_december_solstice_is_summer(self):
        sydney = seasons.turning_points(2026, SYDNEY_DEC, seasons.SOUTH)
        dec = sydney[3]
        self.assertEqual(dec["date"], "2026-12-22")
        self.assertEqual(dec["name"], "summer solstice")
        lines = seasons.due_lines({}, "2026-12-22", SYDNEY_DEC, seasons.SOUTH)
        self.assertEqual(lines, [(dec["key"], "Today is the summer solstice, "
                                  + "the longest day of the year.")])

    def test_said_once(self):
        store: dict = {}
        lines = seasons.due_lines(store, "2026-12-21", UTC)
        self.assertEqual(len(lines), 1)
        self.assertIn("shortest day", lines[0][1])
        seasons.mark_said(store, [k for k, _ in lines], 1.0)
        self.assertEqual(seasons.due_lines(store, "2026-12-21", UTC), [])
        self.assertEqual(seasons.due_lines(store, "2026-12-22", UTC), [])
        # And an ordinary day has nothing.
        self.assertEqual(seasons.due_lines({}, "2026-11-08", UTC), [])


class TestFirstFrost(unittest.TestCase):
    def watched(self, today):
        store: dict = {}
        seasons._looked(store, "frost", days_before(today, 25))
        return store

    def test_the_first_frost_after_a_watched_autumn(self):
        store = self.watched("2026-11-08")
        seasons.note_forecast(store, [
            {"date": "2026-11-08", "low": 3.0, "unit": "°C"},
            {"date": "2026-11-09", "low": -2.0, "unit": "°C"}], "2026-11-08")
        new = seasons.detect(store, "2026-11-08")
        self.assertEqual([e["key"] for e in new], ["frost:2026"])
        lines = seasons.due_lines(store, "2026-11-08", UTC)
        self.assertEqual(lines, [("frost:2026",
                                  "The first frost of the autumn is forecast "
                                  + "for tomorrow, with a low of −2 °C.")])
        # A second frost that season is not a first.
        seasons.note_forecast(store, [{"date": "2026-11-20", "low": -4.0,
                                       "unit": "°C"}], "2026-11-20")
        self.assertEqual(seasons.detect(store, "2026-11-20"), [])

    def test_a_fahrenheit_frost(self):
        store = self.watched("2026-10-30")
        seasons.note_forecast(store, [{"date": "2026-10-30", "low": 30.0,
                                       "unit": "°F"}], "2026-10-30")
        self.assertEqual([e["key"] for e in seasons.detect(store, "2026-10-30")],
                         ["frost:2026"])

    def test_the_day_brain_was_installed_is_not_a_first(self):
        store: dict = {}
        seasons.note_forecast(store, [{"date": "2026-11-08", "low": -3.0,
                                       "unit": "°C"}], "2026-11-08")
        self.assertEqual(seasons.detect(store, "2026-11-08"), [])


class TestHeatingAndCooling(unittest.TestCase):
    def test_the_first_heating_morning_from_hvac_action_history(self):
        raw = [[{"entity_id": "climate.hall", "state": "heat",
                 "attributes": {"hvac_action": "idle"},
                 "last_updated": "2026-10-14T20:00:00+00:00"},
                {"entity_id": "climate.hall", "state": "heat",
                 "attributes": {"hvac_action": "heating"},
                 "last_updated": "2026-10-15T05:30:00+00:00"}]]
        runs = seasons.climate_days(raw, UTC)
        self.assertEqual(runs["heating"], {"2026-10-15"})
        store: dict = {}
        seasons.note_climate(store, runs, days_before("2026-10-15", 28)
                             + ["2026-10-15"])
        self.assertEqual([e["key"] for e in seasons.detect(store, "2026-10-15")],
                         ["heating:2026"])
        self.assertEqual(seasons.due_lines(store, "2026-10-15", UTC),
                         [("heating:2026", "The heating came on for the first "
                           + "time this autumn this morning.")])

    def test_a_heating_run_in_spring_is_not_the_first_of_autumn(self):
        store: dict = {}
        seasons.note_climate(store, {"heating": {"2026-04-02"}},
                             days_before("2026-04-02", 28))
        self.assertEqual(seasons.detect(store, "2026-04-02"), [])

    def test_the_last_cooling_run_is_said_in_hindsight(self):
        store: dict = {}
        looked = days_before("2026-09-25", 40) + ["2026-09-25"]
        seasons.note_climate(store, {"cooling": {"2026-08-20", "2026-09-04"}},
                             looked)
        # Fifteen days after the last run is not yet enough.
        self.assertEqual(seasons.detect(store, "2026-09-19"), [])
        new = seasons.detect(store, "2026-09-25")
        self.assertEqual([e["key"] for e in new], ["cooling_end:2026"])
        (key, text), = seasons.due_lines(store, "2026-09-25", UTC)
        self.assertIn("last cooling run of the year", text)
        self.assertIn("21 days", text)


class TestTheBriefSaysItOnce(unittest.TestCase):
    """`server._send_brief` over a stubbed house: the sentence is sent as
    written, marked said once delivered, and never sent again."""

    def setUp(self):
        self.server = importlib.import_module("server")
        self.tmp = tempfile.TemporaryDirectory()
        s = self.server
        self.saved = (s._diagnostics_payload, s._brief_overnight,
                      s.findings_store.list_all, s._send_notification,
                      s._claude, s.occasions.STORE, s._house_hemisphere,
                      s.schedule_store.set_text, s.BRIEF_STATE.copy())
        s.occasions.STORE = Path(self.tmp.name) / "occasions.json"
        s._diagnostics_payload = lambda: {}

        async def overnight(now):
            return {}
        s._brief_overnight = overnight
        s.findings_store.list_all = lambda *a, **k: []
        s._house_hemisphere = lambda: seasons.NORTH
        s.schedule_store.set_text = lambda *a, **k: None
        self.sent: list[str] = []
        self.asked = 0

        async def send(rows, *a, message=None, **k):
            self.sent.append(message[1] if message else rows[0]["text"])
            return True

        async def claude(*a, **k):
            self.asked += 1
            return {"ok": True, "text": "The garage freezer is at -12°C; it "
                                        "usually holds -18, so check the door."}
        s._send_notification = send
        s._claude = claude

    def tearDown(self):
        s = self.server
        (s._diagnostics_payload, s._brief_overnight, s.findings_store.list_all,
         s._send_notification, s._claude, s.occasions.STORE,
         s._house_hemisphere, s.schedule_store.set_text, state) = self.saved
        s.BRIEF_STATE.clear()
        s.BRIEF_STATE.update(state)
        self.tmp.cleanup()

    def test_a_solstice_morning_is_one_sentence_and_no_model(self):
        # 21 December 2026, 08:00 UTC: the winter solstice in a UTC house.
        now = dt.datetime(2026, 12, 21, 8, 0, tzinfo=UTC).timestamp()
        saved_tz = self.server.baselines.house_timezone
        self.server.baselines.house_timezone = lambda: (UTC, "UTC")
        try:
            asyncio.run(self.server._send_brief(now))
            asyncio.run(self.server._send_brief(now + 3600))
        finally:
            self.server.baselines.house_timezone = saved_tz
        self.assertEqual(self.sent, ["Today is the winter solstice, the "
                                     "shortest day of the year."])
        self.assertEqual(self.asked, 0)

    def test_with_other_news_the_sentence_follows_the_paragraph(self):
        now = dt.datetime(2026, 12, 21, 8, 0, tzinfo=UTC).timestamp()
        saved = (self.server.baselines.house_timezone, brief.worth_saying)
        self.server.baselines.house_timezone = lambda: (UTC, "UTC")
        brief.worth_saying = lambda state: ["The garage freezer is warm"]
        try:
            asyncio.run(self.server._send_brief(now))
        finally:
            self.server.baselines.house_timezone, brief.worth_saying = saved
        self.assertEqual(self.asked, 1)
        self.assertEqual(len(self.sent), 1)
        self.assertTrue(self.sent[0].startswith("The garage freezer"))
        self.assertTrue(self.sent[0].endswith(
            "Today is the winter solstice, the shortest day of the year."))

    def test_a_brief_that_could_not_be_sent_says_it_next_time(self):
        now = dt.datetime(2026, 12, 21, 8, 0, tzinfo=UTC).timestamp()

        async def fail(*a, **k):
            return False
        ok_send = self.server._send_notification
        self.server._send_notification = fail
        saved_tz = self.server.baselines.house_timezone
        self.server.baselines.house_timezone = lambda: (UTC, "UTC")
        try:
            asyncio.run(self.server._send_brief(now))
            self.server._send_notification = ok_send
            asyncio.run(self.server._send_brief(now + 3600))
        finally:
            self.server.baselines.house_timezone = saved_tz
        self.assertEqual(len(self.sent), 1)


class TestComposition(unittest.TestCase):
    def test_with_turns_keeps_the_sentence_whole(self):
        body = " ".join(["word"] * 90)
        out = brief.with_turns(brief.tidy(body), ["Today is the winter "
                                                  "solstice, the shortest "
                                                  "day of the year."])
        self.assertTrue(out.endswith("shortest day of the year."))
        self.assertEqual(brief.with_turns("", ["One."]), "One.")


if __name__ == "__main__":
    unittest.main()
