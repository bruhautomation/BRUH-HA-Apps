#!/usr/bin/env python3
"""Tests for the baseline engine — what is normal for this house.

"Unusual" is the word behind most of what people want a smart home to
notice, and until there is a number behind it every rule that uses it is
a threshold somebody guessed. So the tests that matter here are not
"does it compute a median" — they are the four ways a baseline can be
confidently, invisibly wrong:

  * bucketed in the wrong timezone, which files somebody's evening as
    their morning and looks exactly like a working baseline;
  * a spread set by one outlier, which draws a band nothing can fall
    outside;
  * a spread of zero, which makes every change infinite;
  * a bucket with two samples in it, which is an anecdote wearing a
    normal's clothes.

Each is asserted against the failure, not just the fix.
"""

import datetime as dt
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))

import baselines  # noqa: E402

# A Monday, 00:00 UTC.
MONDAY = dt.datetime(2026, 1, 5, 0, 0, tzinfo=dt.timezone.utc).timestamp()
HOUR = 3600.0


def hourly(values, start=MONDAY):
    return [{"start": start + i * HOUR, "mean": v} for i, v in enumerate(values)]


class TestTheClockIsTheHouses(unittest.TestCase):
    """A day of the week matters and so does the local hour. UTC would
    smear every household's morning across two buckets and move it twice
    a year."""

    def test_monday_midnight_is_bucket_zero(self):
        self.assertEqual(baselines.hour_of_week(MONDAY, dt.timezone.utc), 0)

    def test_the_week_runs_to_one_six_seven(self):
        sunday_11pm = MONDAY + 6 * 24 * HOUR + 23 * HOUR
        self.assertEqual(
            baselines.hour_of_week(sunday_11pm, dt.timezone.utc), 167)

    def test_a_timezone_actually_moves_the_bucket(self):
        """The test that would fail if the tz argument were ignored — which
        is the shape of this bug, since a wrongly bucketed baseline looks
        exactly like a right one."""
        tokyo = None
        try:
            from zoneinfo import ZoneInfo  # noqa: PLC0415
            tokyo = ZoneInfo("Asia/Tokyo")
        except Exception:  # noqa: BLE001 — a system with no timezone database
            # Bound before the try and tested after it, rather than
            # skipping from inside the handler: `skipTest` raises, so the
            # code below IS unreachable without it — but nothing at the
            # point of use says so, which is exactly what a reader (and a
            # scanner) has to take on faith.
            pass
        if tokyo is None:  # pragma: no cover — depends on the host's tz data
            self.skipTest("this system has no timezone database")
        self.assertEqual(baselines.hour_of_week(MONDAY, tokyo), 9)

    def test_an_unreadable_cache_is_utc_and_says_so(self):
        tz, name = baselines.house_timezone("/nope/not/here")
        self.assertEqual(name, "UTC")
        self.assertIs(tz, dt.timezone.utc)

    def test_a_timezone_this_system_does_not_know_is_utc_not_a_crash(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "tz")
            Path(path).write_text("Mars/Olympus_Mons")
            _tz, name = baselines.house_timezone(path)
            self.assertEqual(name, "UTC")


class TestOneOutlierMayNotSetTheBand(unittest.TestCase):
    def test_the_spread_is_a_mad_not_a_standard_deviation(self):
        """A meter that spiked when the oven came on would set a standard
        deviation wide enough to swallow everything after it."""
        ordinary = [20.0, 20.1, 19.9, 20.2, 19.8]
        spiked = ordinary + [900.0]
        self.assertLess(baselines.mad(spiked), 1.0)
        # And to show the failure this avoids: the same data's standard
        # deviation is enormous.
        mean = sum(spiked) / len(spiked)
        stdev = (sum((v - mean) ** 2 for v in spiked) / len(spiked)) ** 0.5
        self.assertGreater(stdev, 100.0)

    def test_a_spike_stays_unusual_against_the_rest(self):
        rows = hourly([20.0, 20.1, 19.9] * 60)
        built = baselines.build_buckets(rows, dt.timezone.utc)
        found = baselines.deviation(900.0, built, 0)
        self.assertGreater(found["sigmas"], 50)


class TestAFlatReadingHasNoBaseline(unittest.TestCase):
    """A thermostat setpoint sits at 20.0 for weeks. Its MAD is zero, and
    dividing by zero makes 20.5 infinitely unusual."""

    def test_a_constant_history_is_reported_as_flat(self):
        built = baselines.build_buckets(hourly([20.0] * 200), dt.timezone.utc)
        self.assertTrue(built.get("flat"))

    def test_a_flat_entity_yields_no_deviation_rather_than_infinity(self):
        built = baselines.build_buckets(hourly([20.0] * 200), dt.timezone.utc)
        self.assertIsNone(baselines.deviation(20.5, built, 0))

    def test_a_nearly_flat_reading_still_gets_a_floor_under_its_spread(self):
        """Not literally constant, but close enough that the raw MAD is 0."""
        values = [20.0] * 100 + [20.4]
        summary = baselines.summarise(values)
        self.assertGreater(summary["spread"], 0)
        self.assertAlmostEqual(summary["spread"],
                               20.0 * baselines.MIN_SPREAD_FRACTION, places=6)

    def test_a_reading_whose_normal_is_zero_still_gets_a_floor(self):
        """A power meter at night, a rain gauge. The fractional floor is
        zero here, which is the same divide-by-zero in a disguise."""
        self.assertGreaterEqual(baselines.spread_floor(0.0),
                                baselines.MIN_SPREAD_ABS)
        summary = baselines.summarise([0.0, 0.0, 0.0, 0.0])
        self.assertGreater(summary["spread"], 0)


class TestNotEnoughIsNotANormal(unittest.TestCase):
    def test_a_bucket_below_the_floor_says_nothing(self):
        for n in range(baselines.MIN_SAMPLES):
            self.assertIsNone(baselines.summarise([20.0, 21.0, 19.0][:n]), n)

    def test_it_speaks_at_the_floor(self):
        self.assertIsNotNone(
            baselines.summarise([20.0] * baselines.MIN_SAMPLES))

    def test_a_thin_hour_falls_back_to_the_whole_history_and_says_which(self):
        """A fortnight-old install has most of the week empty, and 'no
        baseline at all' and 'no baseline for 3am on a Tuesday' are
        different answers."""
        # Four weeks of Mondays-at-midnight only: bucket 0 is rich, and
        # every other bucket is empty.
        rows = [{"start": MONDAY + w * 7 * 24 * HOUR, "mean": 20.0 + w}
                for w in range(4)]
        built = baselines.build_buckets(rows, dt.timezone.utc)
        self.assertEqual(baselines.deviation(21.0, built, 0)["source"], "hour")
        self.assertEqual(baselines.deviation(21.0, built, 99)["source"], "overall")


class TestReadingTheRows(unittest.TestCase):
    def test_rubbish_rows_are_skipped_rather_than_crashing(self):
        rows = [
            {"start": MONDAY, "mean": 20.0},
            {"start": None, "mean": 20.0},
            {"start": MONDAY + HOUR, "mean": None},
            {"start": MONDAY + 2 * HOUR, "mean": True},   # bool is not a reading
            "not a row",
            {"start": MONDAY + 3 * HOUR, "mean": 21.0},
            {"start": MONDAY + 4 * HOUR, "mean": 22.0},
        ]
        built = baselines.build_buckets(rows, dt.timezone.utc)
        self.assertEqual(built["samples"], 3)

    def test_a_house_with_no_rows_gets_no_baseline_not_an_empty_one(self):
        self.assertEqual(baselines.build_buckets([], dt.timezone.utc), {})

    def test_only_entities_the_recorder_keeps_statistics_for_are_asked_about(self):
        """Asking about anything without a state_class is asking for rows
        that do not exist."""
        states = {
            "sensor.power": {"state": "12", "attributes": {"state_class": "measurement"}},
            "sensor.text": {"state": "hello", "attributes": {}},
            "sensor.gone": {"state": "unavailable",
                            "attributes": {"state_class": "measurement"}},
            "light.kitchen": {"state": "on", "attributes": {}},
        }
        self.assertEqual(baselines.candidates(states), ["sensor.power"])

    def test_the_cap_takes_the_same_entities_every_night(self):
        """An arbitrary set that changes nightly would give half the house
        a baseline that keeps appearing and disappearing."""
        states = {f"sensor.s{i:04d}": {"state": "1",
                                       "attributes": {"state_class": "measurement"}}
                  for i in range(baselines.MAX_ENTITIES + 50)}
        first = baselines.candidates(states)
        second = baselines.candidates(dict(reversed(list(states.items()))))
        self.assertEqual(first, second)
        self.assertEqual(len(first), baselines.MAX_ENTITIES)


class TestTheStore(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "baselines.json")

    def test_a_missing_store_is_no_baselines_not_nothing_unusual(self):
        payload = baselines.load(self.path)
        self.assertEqual(payload["entities"], {})
        self.assertEqual(payload["built_at"], 0)

    def test_a_corrupt_store_reads_as_missing(self):
        Path(self.path).write_text("{not json")
        self.assertEqual(baselines.load(self.path)["entities"], {})

    def test_a_store_that_was_never_written_has_no_age(self):
        """None and 'zero days old' are different, and only one of them
        means the nightly pass has never run."""
        self.assertIsNone(baselines.age_days(baselines.load(self.path)))

    def test_staleness_is_measured_from_when_it_was_built(self):
        now = 1_800_000_000.0
        fresh = {"built_at": now - 3600, "entities": {"a": {}}}
        old = {"built_at": now - (baselines.STALE_DAYS + 1) * 86400,
               "entities": {"a": {}}}
        self.assertFalse(baselines.is_stale(fresh, now))
        self.assertTrue(baselines.is_stale(old, now))

    def test_a_round_trip_survives_json(self):
        built = baselines.build_buckets(hourly([20.0, 21.0, 19.0] * 60),
                                        dt.timezone.utc)
        baselines.save({"built_at": 1, "tz": "UTC", "entities": {"sensor.a": built}},
                       self.path)
        back = baselines.load(self.path)
        self.assertEqual(back["entities"]["sensor.a"], json.loads(json.dumps(built)))

    def test_saving_where_there_is_no_directory_is_silent(self):
        """A dev checkout has no /data, and a baseline store is derived —
        losing it costs a night, never a finding."""
        baselines.save({"entities": {}}, "/nope/not/here/baselines.json")


class TestTheChecksThatUseIt(unittest.TestCase):
    def setUp(self):
        from checks import baseline as check  # noqa: PLC0415
        self.check = check
        self.now = MONDAY + 10 * HOUR

    def house(self, value="20.0", **over):
        bucket = str(baselines.hour_of_week(self.now, dt.timezone.utc))
        snap = {
            "now": self.now,
            "states": {"sensor.hall_temp": {
                "state": value, "attributes": {"device_class": "temperature",
                                               "unit_of_measurement": "°C"},
                "last_changed": "", "last_updated": ""}},
            "entities": [{"entity_id": "sensor.hall_temp", "name": "Hall"}],
            "devices": [], "areas": [],
            "baselines": {
                "built_at": int(self.now - 3600), "tz": "UTC", "days": 28,
                "entities": {"sensor.hall_temp": {
                    "unit": "°C", "samples": 672,
                    "overall": {"median": 20.0, "spread": 0.5, "n": 672},
                    "buckets": {bucket: {"median": 20.0, "spread": 0.5, "n": 4}},
                }},
            },
        }
        snap.update(over)
        return snap

    def test_an_ordinary_reading_is_silent(self):
        self.assertEqual(self.check.unusual(self.house("20.3"), self.now), [])

    def test_a_reading_far_outside_the_band_is_reported(self):
        found = self.check.unusual(self.house("28.0"), self.now)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["entity_id"], "sensor.hall_temp")
        # The text is stable across runs and the number lives in detail.
        self.assertNotIn("28", found[0]["text"])
        self.assertIn("28", found[0]["detail"])

    def test_a_small_absolute_move_is_not_news_however_many_spreads(self):
        """Six spreads of a band 0.02 wide is 0.12 degrees."""
        snap = self.house("20.2")
        entity = snap["baselines"]["entities"]["sensor.hall_temp"]
        for row in entity["buckets"].values():
            row["spread"] = 0.001
        entity["overall"]["spread"] = 0.001
        self.assertEqual(self.check.unusual(snap, self.now), [])

    def test_an_impossible_reading_is_the_other_checks(self):
        """A thermometer at 99°C is impossible before it is unusual, and
        dev.implausible says so with the better fix."""
        self.assertEqual(self.check.unusual(self.house("99"), self.now), [])

    def test_a_house_with_no_baselines_yet_files_nothing(self):
        self.assertEqual(self.check.unusual(self.house(baselines={}), self.now), [])

    def test_too_many_rows_is_the_measurement_being_wrong(self):
        """A heating season starting, a meter replaced. Reporting fifty
        rows would be reporting the measurement rather than the house."""
        snap = self.house("28.0")
        for i in range(self.check.MAX_ROWS + 1):
            eid = f"sensor.other{i}"
            snap["states"][eid] = dict(snap["states"]["sensor.hall_temp"])
            snap["entities"].append({"entity_id": eid, "name": f"Other {i}"})
            snap["baselines"]["entities"][eid] = dict(
                snap["baselines"]["entities"]["sensor.hall_temp"])
        self.assertEqual(self.check.unusual(snap, self.now), [])

    def test_an_unavailable_sensor_is_not_unusual(self):
        self.assertEqual(self.check.unusual(self.house("unavailable"), self.now), [])

    def test_a_stale_store_is_reported_as_brains_problem_not_the_houses(self):
        snap = self.house()
        snap["baselines"]["built_at"] = int(
            self.now - (baselines.STALE_DAYS + 2) * 86400)
        found = self.check.stale_baselines(snap, self.now)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["severity"], "warning")

    def test_a_fresh_store_is_silent(self):
        self.assertEqual(self.check.stale_baselines(self.house(), self.now), [])

    def test_a_house_that_has_never_measured_is_not_stale(self):
        """Never measured and stopped measuring are different, and only
        the second is worth a row."""
        self.assertEqual(
            self.check.stale_baselines(self.house(baselines={}), self.now), [])


class TestTheThresholdIsNotASigma(unittest.TestCase):
    def test_the_module_says_what_its_spread_is(self):
        """A MAD is about two thirds of a standard deviation, so a reader
        who takes `spread` for a sigma reads the bar as tighter than it
        is. It is said in the code and in the tool's own answer."""
        import re  # noqa: PLC0415

        from checks import baseline as check  # noqa: PLC0415

        def flat(text):
            # These are prose in wrapped source, so the phrase is split
            # across a line break as often as not.
            return re.sub(r"\s+", " ", text)

        self.assertIn("median absolute deviation", flat(check.__doc__))
        mcp = (BASE_DIR / "brain" / "ha-mcp-server"
               / "ha_mcp_server.py").read_text()
        block = mcp.split("def get_baseline", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("median absolute deviation", flat(block))


if __name__ == "__main__":
    unittest.main()
