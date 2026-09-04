"""What the house used, and the four ways that number can be quietly wrong.

Every case here is about a total that *looks* right. A double-counted
week, a week compared against six days, a meter reset added as a
negative, and a cost quoted off a sensor nobody named — none of them
raises anything, and all four produce a report somebody would act on.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "brain", "panel"))

import energy  # noqa: E402

UTC = dt.timezone.utc
# A Wednesday, so "the last seven complete days" is not a calendar week
# and the windows have to be computed rather than named.
NOW = dt.datetime(2026, 9, 2, 14, 30, tzinfo=UTC).timestamp()


def day_rows(start: dt.datetime, values: list[float], base: float = 100.0,
             kind: str = "sum") -> list[dict]:
    """`values` as daily statistics rows, in whichever shape is asked for.

    `sum` is cumulative (what the recorder stores); `change` is the
    per-period consumption a modern core answers with directly.
    """
    rows = []
    running = base
    for i, v in enumerate(values):
        when = (start + dt.timedelta(days=i)).timestamp() * 1000.0
        running += v
        if kind == "sum":
            rows.append({"start": when, "sum": running})
        elif kind == "change":
            rows.append({"start": when, "change": v})
        else:
            rows.append({"start": when, "sum": running, "change": v})
    return rows


class TestWhichMeters(unittest.TestCase):
    """The set is Home Assistant's own, or there is no set."""

    def test_grid_consumption_and_its_cost_are_taken(self):
        prefs = {"energy_sources": [{
            "type": "grid",
            "flow_from": [
                {"stat_energy_from": "sensor.grid_in", "stat_cost": "sensor.grid_cost"},
                {"stat_energy_from": "sensor.grid_in_2"},
            ],
            "flow_to": [{"stat_energy_to": "sensor.grid_out"}],
        }]}
        used, cost = energy.sources(prefs)
        self.assertEqual(used, ["sensor.grid_in", "sensor.grid_in_2"])
        self.assertEqual(cost, ["sensor.grid_cost"])

    def test_solar_and_battery_are_not_consumption(self):
        # Reporting production and consumption as one total is the
        # double-count this module exists to avoid, one level up.
        prefs = {"energy_sources": [
            {"type": "solar", "stat_energy_from": "sensor.pv"},
            {"type": "battery", "stat_energy_from": "sensor.batt_out"},
            {"type": "gas", "stat_energy_from": "sensor.gas",
             "stat_cost": "sensor.gas_cost"},
        ]}
        self.assertEqual(energy.sources(prefs), ([], []))

    def test_a_price_to_multiply_is_not_a_cost_statistic(self):
        # HA makes its own cost sensor under a derived id; guessing that
        # id is how a report quotes somebody else's number.
        prefs = {"energy_sources": [{"type": "grid", "flow_from": [
            {"stat_energy_from": "sensor.grid_in",
             "number_energy_price": 0.28}]}]}
        used, cost = energy.sources(prefs)
        self.assertEqual(used, ["sensor.grid_in"])
        self.assertEqual(cost, [])

    def test_no_configuration_is_no_meters_rather_than_a_guess(self):
        for prefs in (None, {}, {"energy_sources": []},
                      {"energy_sources": ["nonsense"]},
                      {"energy_sources": [{"type": "grid"}]}):
            self.assertEqual(energy.sources(prefs), ([], []), prefs)


class TestTheArithmetic(unittest.TestCase):
    def test_a_cumulative_sum_becomes_daily_use(self):
        rows = day_rows(dt.datetime(2026, 8, 24, tzinfo=UTC), [3.0, 4.0, 5.0])
        got = [round(v, 3) for _w, v in energy.consumption(rows)]
        # The first row has no predecessor and yields nothing, which is
        # why the caller fetches one day more than it reports.
        self.assertEqual(got, [4.0, 5.0])

    def test_the_recorder_answers_it_directly_where_it_can(self):
        rows = day_rows(dt.datetime(2026, 8, 24, tzinfo=UTC), [3.0, 4.0, 5.0],
                        kind="change")
        got = [round(v, 3) for _w, v in energy.consumption(rows)]
        # `change` needs no predecessor, so all three days are there.
        self.assertEqual(got, [3.0, 4.0, 5.0])

    def test_change_wins_and_sum_still_tracks_behind_it(self):
        rows = day_rows(dt.datetime(2026, 8, 24, tzinfo=UTC), [3.0, 4.0],
                        kind="both")
        rows.append({"start": dt.datetime(2026, 8, 26, tzinfo=UTC).timestamp()
                     * 1000.0, "sum": 112.0})
        got = [round(v, 3) for _w, v in energy.consumption(rows)]
        # 3, 4 from `change`; the last row lost the key and falls back to
        # the step from the sum it has been keeping all along (107 -> 112).
        self.assertEqual(got, [3.0, 4.0, 5.0])

    def test_a_meter_reset_is_dropped_and_not_added_as_a_negative(self):
        start = dt.datetime(2026, 8, 24, tzinfo=UTC)
        rows = [
            {"start": start.timestamp() * 1000.0, "sum": 100.0},
            {"start": (start + dt.timedelta(days=1)).timestamp() * 1000.0,
             "sum": 104.0},
            # The meter was replaced overnight.
            {"start": (start + dt.timedelta(days=2)).timestamp() * 1000.0,
             "sum": 2.0},
            {"start": (start + dt.timedelta(days=3)).timestamp() * 1000.0,
             "sum": 7.0},
        ]
        got = [round(v, 3) for _w, v in energy.consumption(rows)]
        self.assertEqual(got, [4.0, 5.0])
        # And the window is short by the dropped day, which is what makes
        # the comparison stand down rather than report a plausible fall.
        self.assertEqual(len(got), 2)

    def test_rubbish_rows_are_skipped_rather_than_crashing(self):
        rows = ["nonsense", {"sum": 1.0}, {"start": None, "sum": 1.0},
                {"start": True, "sum": 1.0},
                {"start": 1.0, "sum": True}, {"start": 2.0}]
        self.assertEqual(energy.consumption(rows), [])

    def test_seconds_and_milliseconds_both_read_as_the_same_instant(self):
        when = dt.datetime(2026, 8, 24, tzinfo=UTC).timestamp()
        in_s = energy.consumption([{"start": when, "change": 1.0}])
        in_ms = energy.consumption([{"start": when * 1000.0, "change": 1.0}])
        self.assertEqual(in_s, in_ms)

    def test_days_are_the_fewest_any_meter_gave_not_the_average(self):
        start = dt.datetime(2026, 8, 24, tzinfo=UTC)
        end = start + dt.timedelta(days=4)
        series = {
            "a": day_rows(start, [1.0] * 4, kind="change"),
            "b": day_rows(start, [1.0, 1.0], kind="change"),
        }
        used, days = energy.total(series, start, end)
        self.assertAlmostEqual(used, 6.0)
        # Two meters missing different days leave a total short on both;
        # an averaged count would call this window complete.
        self.assertEqual(days, 2)

    def test_a_week_that_used_nothing_has_no_percentage(self):
        self.assertIsNone(energy.change_pct(4.0, 0.0))
        self.assertIsNone(energy.change_pct(0.0, 0.0))
        self.assertAlmostEqual(energy.change_pct(110.0, 100.0), 10.0)
        self.assertAlmostEqual(energy.change_pct(90.0, 100.0), -10.0)

    def test_a_move_smaller_than_the_noise_is_not_news(self):
        self.assertFalse(energy.worth_mentioning(None))
        self.assertFalse(energy.worth_mentioning(1.0))
        self.assertFalse(energy.worth_mentioning(-4.9))
        self.assertTrue(energy.worth_mentioning(-12.0))
        self.assertTrue(energy.worth_mentioning(30.0))


class TestTheWindows(unittest.TestCase):
    def test_both_windows_are_seven_complete_local_days(self):
        prior, mid, end = energy.windows(NOW, UTC)
        self.assertEqual(end, dt.datetime(2026, 9, 2, tzinfo=UTC))
        self.assertEqual(mid, dt.datetime(2026, 8, 26, tzinfo=UTC))
        self.assertEqual(prior, dt.datetime(2026, 8, 19, tzinfo=UTC))
        self.assertEqual((end - mid).days, 7)
        self.assertEqual((mid - prior).days, 7)

    def test_the_window_ends_at_midnight_and_never_at_now(self):
        # Half of today against seven full days is a 45% fall that is
        # nothing but the clock, on the one number people act on.
        _prior, _mid, end = energy.windows(NOW, UTC)
        self.assertLess(end.timestamp(), NOW)
        self.assertEqual((end.hour, end.minute), (0, 0))

    def test_the_boundaries_survive_a_daylight_saving_change(self):
        # This is the property the wall-clock arithmetic buys, and the
        # reason the windows are not computed on the epoch: each boundary
        # is a local midnight and the two windows are seven CALENDAR days
        # each, even though one of them is 169 hours long. Computed in
        # UTC a boundary would land at 23:00 and one window would swallow
        # an extra day's row — a one-seventh move, twice a year, that is
        # nothing but the clock going back.
        tz = None
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo("Europe/London")
        except Exception:  # noqa: BLE001
            tz = None
        if tz is None:
            self.skipTest("no tz database")
        # The UK clocks went back on 25 October 2026; this is the Friday
        # after, so the earlier window spans the change.
        after = dt.datetime(2026, 10, 30, 11, 0, tzinfo=UTC).timestamp()
        prior, mid, end = energy.windows(after, tz)
        for edge in (prior, mid, end):
            self.assertEqual((edge.hour, edge.minute), (0, 0), edge)
        # Seven calendar days each, even though one is 169 hours long.
        self.assertEqual((end.date() - mid.date()).days, 7)
        self.assertEqual((mid.date() - prior.date()).days, 7)
        self.assertNotEqual(end.timestamp() - mid.timestamp(),
                            mid.timestamp() - prior.timestamp())
        # And the recipe the docstring rejects, run on the same instant,
        # so the claim is measured rather than described: seven days of
        # epoch seconds back from local midnight lands at 01:00, and the
        # window it opens misses that day's row.
        epoch_mid = dt.datetime.fromtimestamp(
            end.timestamp() - 7 * 86400, tz)
        self.assertEqual(epoch_mid.hour, 1)

    def test_the_windows_are_the_house_clock_not_utc(self):
        # Bound before the `try`: an `except` that skips reads like a
        # return and is not one the analyser can see.
        tokyo = None
        try:
            from zoneinfo import ZoneInfo
            tokyo = ZoneInfo("Asia/Tokyo")
        except Exception:  # noqa: BLE001
            tokyo = None
        if tokyo is None:
            self.skipTest("no tz database")
        _p, _m, utc_end = energy.windows(NOW, UTC)
        _p2, _m2, jp_end = energy.windows(NOW, tokyo)
        # 14:30 UTC is already the next day in Tokyo, so its last complete
        # day ends nine hours later. A test that ignored the argument
        # would see these agree.
        self.assertNotEqual(utc_end.timestamp(), jp_end.timestamp())


class FakeWS:
    """The two WebSocket commands `energy` makes, and nothing else."""

    def __init__(self, prefs, stats, meta=None, fail=()):
        self.prefs, self.stats = prefs, stats
        self.meta, self.fail = meta or [], set(fail)
        self.asked = []

    async def __call__(self, session, commands):
        kind = commands[0]["type"]
        self.asked.append(commands[0])
        if kind in self.fail:
            raise RuntimeError("nope")
        if kind == "energy/get_prefs":
            return [self.prefs]
        if kind == "recorder/list_statistic_ids":
            return [self.meta]
        wanted = commands[0]["statistic_ids"]
        return [{k: v for k, v in self.stats.items() if k in wanted}]


class TestTheWeek(unittest.TestCase):
    def setUp(self):
        self._real = None

    def run_week(self, prefs, stats, meta=None, fail=()):
        import ha_data
        fake = FakeWS(prefs, stats, meta, fail)
        real = ha_data._ws_commands
        ha_data._ws_commands = fake
        try:
            return asyncio.run(energy.week(None, NOW, UTC)), fake
        finally:
            ha_data._ws_commands = real

    def prefs(self, cost=True):
        flow = {"stat_energy_from": "sensor.grid"}
        if cost:
            flow["stat_cost"] = "sensor.grid_cost"
        return {"energy_sources": [{"type": "grid", "flow_from": [flow]}]}

    def stats(self, this: float, last: float, days: int = 7):
        # The fetch starts a day before the earlier window, so the first
        # row is the predecessor and the two windows both get `days`.
        start = dt.datetime(2026, 8, 18, tzinfo=UTC)
        values = [0.0] + [last / days] * days + [this / days] * days
        return {"sensor.grid": day_rows(start, values),
                "sensor.grid_cost": day_rows(
                    start, [v * 0.3 for v in values])}

    def test_a_house_with_no_energy_configuration_says_so(self):
        out, fake = self.run_week(None, {})
        self.assertFalse(out["available"])
        self.assertIn("no energy configuration", out["reason"])
        # And it never went looking for statistics it had no ids for.
        self.assertEqual(len(fake.asked), 1)

    def test_a_house_that_cannot_be_asked_says_so_rather_than_zero(self):
        out, _ = self.run_week(self.prefs(), {},
                               fail=("energy/get_prefs",))
        self.assertFalse(out["available"])
        self.assertTrue(out["reason"])

    def test_a_recorder_with_nothing_to_say_is_not_a_quiet_week(self):
        out, _ = self.run_week(self.prefs(), {})
        self.assertFalse(out["available"])
        self.assertIn("recorder", out["reason"])

    def test_the_week_and_the_week_before_it(self):
        out, _ = self.run_week(self.prefs(), self.stats(140.0, 100.0))
        self.assertTrue(out["available"])
        power = out["energy"]
        self.assertAlmostEqual(power["this"], 140.0, places=1)
        self.assertAlmostEqual(power["last"], 100.0, places=1)
        self.assertAlmostEqual(power["change_pct"], 40.0, places=1)
        self.assertTrue(power["comparable"])
        self.assertEqual((power["days"], power["days_before"]), (7, 7))

    def test_the_cost_rides_beside_it_in_its_own_unit(self):
        out, _ = self.run_week(
            self.prefs(), self.stats(140.0, 100.0),
            meta=[{"statistic_id": "sensor.grid", "unit_of_measurement": "kWh"},
                  {"statistic_id": "sensor.grid_cost",
                   "display_unit_of_measurement": "£"}])
        self.assertEqual(out["energy"]["unit"], "kWh")
        self.assertEqual(out["cost"]["unit"], "£")
        self.assertAlmostEqual(out["cost"]["this"], 42.0, places=1)

    def test_no_cost_statistic_means_no_cost_section(self):
        out, _ = self.run_week(self.prefs(cost=False),
                               self.stats(140.0, 100.0))
        self.assertIn("energy", out)
        self.assertNotIn("cost", out)

    def test_a_short_window_refuses_the_comparison_rather_than_reporting_it(self):
        # Four days against seven is a 43% fall that is entirely the three
        # missing days, and it is the one number people would act on.
        start = dt.datetime(2026, 8, 18, tzinfo=UTC)
        values = [0.0] + [100.0 / 7] * 7 + [20.0] * 4
        out, _ = self.run_week(
            self.prefs(cost=False), {"sensor.grid": day_rows(start, values)})
        power = out["energy"]
        self.assertFalse(power["comparable"])
        self.assertIsNone(power["change_pct"])
        self.assertEqual(power["days"], 4)
        # The total it DID measure is still reported: "four days of the
        # seven" is a fact, and "no comparison" is the missing half.
        self.assertAlmostEqual(power["this"], 80.0, places=1)

    def test_a_unit_that_cannot_be_read_still_leaves_the_number(self):
        out, _ = self.run_week(self.prefs(cost=False),
                               self.stats(140.0, 100.0),
                               fail=("recorder/list_statistic_ids",))
        self.assertAlmostEqual(out["energy"]["this"], 140.0, places=1)
        self.assertEqual(out["energy"]["unit"], "kWh")

    def test_the_fetch_reaches_one_day_before_the_earlier_window(self):
        _out, fake = self.run_week(self.prefs(cost=False),
                                   self.stats(140.0, 100.0))
        fetch = [c for c in fake.asked
                 if c["type"] == "recorder/statistics_during_period"][0]
        prior, _mid, _end = energy.windows(NOW, UTC)
        asked = dt.datetime.fromisoformat(fetch["start_time"])
        self.assertEqual((prior - asked).days, 1)
        # And it asks for both shapes, so a core without `change` still
        # answers and a core with it is not made to be derived from.
        self.assertEqual(fetch["types"], ["sum", "change"])


if __name__ == "__main__":
    unittest.main()
