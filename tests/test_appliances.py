"""A washer, a dishwasher: idle, running, and finished.

Nothing in Home Assistant says a cycle ended, and every rule anybody
writes on top of a smart plug is a wattage typed into a box. So the
numbers here are measured from the machine's own history — and every
case is about one of the four ways that measurement is confidently
wrong: a floor set by one bad reading, a dry phase read as a finish, a
compressor read as a cycle, and an empty machine read as a full one.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import appliances  # noqa: E402
from checks import chores  # noqa: E402

NOW = 1_756_800_000.0
BUCKET = appliances.BUCKET_S


def series(spec: list[tuple[float, float]], start: float = 0.0) -> list[dict]:
    """`[(minutes, watts), ...]` as five-minute statistics rows.

    Each pair is "this many minutes at this draw", laid end to end from
    `start` seconds before NOW.
    """
    rows, when = [], NOW - start
    for minutes, watts in spec:
        for _ in range(int(minutes * 60 / BUCKET)):
            rows.append({"start": when, "mean": watts})
            when += BUCKET
    return rows


def a_week(cycle_min: float = 120.0, idle_w: float = 0.6,
           busy_w: float = 1800.0, runs: int = 6,
           lull_min: float = 20.0) -> list[dict]:
    """A dishwasher: a long idle, a cycle with a quiet dry phase, repeat."""
    half = cycle_min / 2 - lull_min / 2
    spec: list[tuple[float, float]] = []
    for _ in range(runs):
        spec.append((10 * 60, idle_w))          # ten hours idle
        spec.append((half, busy_w))             # wash
        spec.append((lull_min, idle_w))         # dry: quiet, not finished
        spec.append((half, busy_w))             # rinse
    spec.append((10 * 60, idle_w))
    total_min = sum(m for m, _w in spec)
    return series(spec, start=total_min * 60)


class TestWhichSensorsHaveAShape(unittest.TestCase):
    def test_a_power_sensor_the_recorder_keeps_statistics_for(self):
        self.assertTrue(appliances.is_power(
            "sensor.washer", {"device_class": "power",
                              "state_class": "measurement"}))

    def test_anything_else_has_no_shape_to_measure(self):
        for eid, attrs in (
            ("sensor.washer", {"device_class": "energy",
                               "state_class": "measurement"}),
            ("sensor.washer", {"device_class": "power"}),
            ("sensor.washer", {"device_class": "power",
                               "state_class": "total_increasing"}),
            ("switch.washer", {"device_class": "power",
                               "state_class": "measurement"}),
            ("sensor.washer", {}),
        ):
            self.assertFalse(appliances.is_power(eid, attrs), (eid, attrs))

    def test_candidates_are_sorted_capped_and_alive(self):
        attrs = {"device_class": "power", "state_class": "measurement"}
        states = {f"sensor.p{i:03d}": {"state": "3", "attributes": attrs}
                  for i in range(appliances.MAX_ENTITIES + 10)}
        states["sensor.gone"] = {"state": "unavailable", "attributes": attrs}
        got = appliances.candidates(states)
        self.assertEqual(len(got), appliances.MAX_ENTITIES)
        self.assertEqual(got, sorted(got))
        self.assertNotIn("sensor.gone", got)


class TestTheShape(unittest.TestCase):
    def test_a_dishwasher_gets_a_profile(self):
        shape = appliances.profile(a_week(), NOW)
        self.assertIsNotNone(shape)
        self.assertLess(shape["idle_w"], 5)
        self.assertGreater(shape["busy_w"], 1000)
        self.assertGreater(shape["threshold_w"], shape["idle_w"])
        self.assertLess(shape["threshold_w"], shape["busy_w"])
        # Twelve draws, not six cycles: the dry phase splits each cycle
        # into two above-threshold stretches, and the gap between them
        # is what the settle time is measured from.
        self.assertEqual(shape["draws"], 12)

    def test_a_constant_draw_is_not_an_appliance(self):
        # A router, a hub, a standing fridge draw. A threshold through
        # the middle of one would report it as running all week.
        rows = series([(10 * 24 * 60, 12.0)], start=10 * 24 * 3600)
        self.assertIsNone(appliances.profile(rows, NOW))

    def test_a_small_swing_is_not_an_appliance_either(self):
        # 3W to 9W is a phone charger. It has a ratio but no span, and
        # both floors have to hold or every plug in the house profiles.
        rows = series([(60, 3.0), (30, 9.0)] * 40, start=10 * 24 * 3600)
        self.assertIsNone(appliances.profile(rows, NOW))

    def test_one_bad_reading_does_not_set_the_floor(self):
        # A power cut, or the second the plug was re-paired. The
        # minimum would be zero; a low percentile is not.
        rows = a_week(idle_w=4.0)
        rows[500]["mean"] = 0.0
        shape = appliances.profile(rows, NOW)
        self.assertGreater(shape["idle_w"], 1.0)

    def test_a_true_zero_floor_is_the_clearest_shape_of_all(self):
        # A machine that draws nothing at all between runs passes the
        # ratio by construction, and that is right rather than a
        # loophole — nothing is more clearly bimodal.
        shape = appliances.profile(a_week(idle_w=0.0), NOW)
        self.assertIsNotNone(shape)
        self.assertEqual(shape["idle_w"], 0.0)

    def test_one_low_bucket_does_not_split_a_run(self):
        # A single dip is noise; the quiet phase that genuinely
        # interrupts a cycle is what the settle time is for.
        rows = series([(60, 0.6), (20, 1800.0), (5, 0.6), (20, 1800.0),
                       (60, 0.6)], start=165 * 60)
        segs = appliances.segments(appliances._readings(rows), 450.0)
        self.assertEqual(len(segs), 1)

    def test_too_little_history_says_nothing(self):
        rows = series([(60, 0.5), (60, 1800.0)], start=2 * 3600)
        self.assertIsNone(appliances.profile(rows, NOW))

    def test_too_few_draws_says_nothing_rather_than_guessing(self):
        # One wash in ten days leaves one gap, and a jump cannot be
        # found in one number — a settle time guessed here is a machine
        # that reports finished mid-cycle forever.
        self.assertIsNone(appliances.profile(a_week(runs=1), NOW))

    def test_rubbish_rows_are_skipped_rather_than_crashing(self):
        rows = ["nonsense", {"mean": 1.0}, {"start": None, "mean": 1.0},
                {"start": True, "mean": 1.0}, {"start": 1.0, "mean": True},
                {"start": 2.0}]
        self.assertIsNone(appliances.profile(rows, NOW))
        self.assertEqual(appliances._readings(rows), [])

    def test_seconds_and_milliseconds_read_as_the_same_instant(self):
        one = appliances._readings([{"start": NOW, "mean": 5.0}])
        two = appliances._readings([{"start": NOW * 1000.0, "mean": 5.0}])
        self.assertEqual(one, two)


class TestTheQuietPhase(unittest.TestCase):
    """The measurement that stops a dry cycle reading as a finish."""

    def test_the_machine_says_how_long_its_own_lulls_are(self):
        # Lulls of twenty minutes inside a cycle, idles of ten hours
        # between them. The widest jump in the sorted gaps is where one
        # becomes the other.
        shape = appliances.profile(a_week(lull_min=20.0), NOW)
        self.assertTrue(shape["measured_settle"])
        self.assertGreaterEqual(shape["settle_min"], 20.0)

    def test_a_longer_lull_is_measured_as_a_longer_one(self):
        short = appliances.profile(a_week(lull_min=12.0), NOW)
        longer = appliances.profile(a_week(lull_min=35.0), NOW)
        self.assertGreater(longer["settle_min"], short["settle_min"])

    def test_it_is_bounded_at_both_ends(self):
        # A machine with no lulls at all still waits the floor, or a
        # one-bucket dip reads as finished; and one strange gap must not
        # decide that a cycle lasts all afternoon.
        none = appliances.profile(a_week(lull_min=0.0), NOW)
        self.assertGreaterEqual(none["settle_min"], appliances.MIN_SETTLE_MIN)
        huge = appliances.profile(a_week(cycle_min=400.0, lull_min=180.0),
                                  NOW)
        self.assertLessEqual(huge["settle_min"], appliances.MAX_SETTLE_MIN)

    def test_nothing_to_measure_from_is_None_not_a_number(self):
        self.assertIsNone(appliances.settle_minutes([]))
        self.assertIsNone(appliances.settle_minutes([(0.0, 60.0)]))
        self.assertIsNone(appliances.settle_minutes(
            [(0.0, 60.0), (3600.0, 4000.0)]))


class TestWhatItIsDoingNow(unittest.TestCase):
    def shape(self, **kw):
        base = {"idle_w": 0.6, "busy_w": 1800.0, "threshold_w": 450.0,
                "settle_min": 22.0, "measured_settle": True}
        base.update(kw)
        return base

    def test_a_machine_that_has_not_run_is_idle(self):
        rows = series([(6 * 60, 0.6)], start=6 * 3600)
        got = appliances.state_at(self.shape(), rows, NOW)
        self.assertEqual(got["state"], appliances.IDLE)
        self.assertEqual(got["finished_at"], 0.0)

    def test_a_machine_drawing_power_is_running(self):
        rows = series([(60, 0.6), (40, 1800.0)], start=100 * 60)
        got = appliances.state_at(self.shape(), rows, NOW)
        self.assertEqual(got["state"], appliances.RUNNING)

    def test_a_dry_phase_is_still_running(self):
        # The failure this whole module exists for: a machine that
        # reports done the moment the draw drops reports done three
        # times a cycle.
        rows = series([(60, 0.6), (40, 1800.0), (15, 0.6)],
                      start=115 * 60)
        got = appliances.state_at(self.shape(), rows, NOW)
        self.assertEqual(got["state"], appliances.RUNNING)

    def test_past_its_own_quiet_phase_it_is_finished(self):
        rows = series([(60, 0.6), (40, 1800.0), (30, 0.6)],
                      start=130 * 60)
        got = appliances.state_at(self.shape(), rows, NOW)
        self.assertEqual(got["state"], appliances.FINISHED)
        self.assertAlmostEqual((NOW - got["finished_at"]) / 60.0, 30.0,
                               delta=6)

    def test_a_machine_with_a_longer_lull_waits_longer(self):
        rows = series([(60, 0.6), (40, 1800.0), (30, 0.6)], start=130 * 60)
        self.assertEqual(
            appliances.state_at(self.shape(settle_min=45.0), rows,
                                NOW)["state"],
            appliances.RUNNING)

    def test_a_blip_is_not_a_cycle(self):
        # Every compressor, every kettle, every inrush clears a
        # threshold for a moment.
        rows = series([(3 * 60, 0.6), (5, 1800.0), (60, 0.6)],
                      start=245 * 60)
        got = appliances.state_at(self.shape(), rows, NOW)
        self.assertEqual(got["state"], appliances.IDLE)

    def test_there_is_no_unloaded_state(self):
        # An empty machine and a full one draw exactly the same power,
        # so the fourth state is a person saying so and this must never
        # claim to have seen it.
        rows = series([(60, 0.6), (40, 1800.0), (10 * 60, 0.6)],
                      start=700 * 60)
        got = appliances.state_at(self.shape(), rows, NOW)
        self.assertEqual(got["state"], appliances.FINISHED)
        self.assertNotIn("unloaded", json.dumps(got))

    def test_nothing_to_read_answers_with_no_state_at_all(self):
        self.assertEqual(
            appliances.state_at(self.shape(), [], NOW)["state"], "")
        self.assertEqual(
            appliances.state_at({}, series([(60, 5.0)], 3600), NOW)["state"],
            "")


class TestTheStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "appliances.json")

    def test_a_round_trip(self):
        appliances.save({"built_at": 1, "entities": {"a": {"idle_w": 1}}},
                        self.path)
        self.assertEqual(appliances.load(self.path)["entities"]["a"]["idle_w"], 1)

    def test_every_bad_file_is_an_empty_store(self):
        for junk in ("{not json", "[1,2]", '{"entities": 5}', ""):
            with open(self.path, "w", encoding="utf-8") as fh:
                fh.write(junk)
            self.assertEqual(appliances.load(self.path), {"entities": {}}, junk)

    def test_a_missing_directory_is_not_a_crash(self):
        gone = os.path.join(self.tmp.name, "nope", "appliances.json")
        appliances.save({"entities": {}}, gone)
        self.assertEqual(appliances.load(gone), {"entities": {}})

    def test_age_is_None_when_nothing_has_been_measured(self):
        self.assertIsNone(appliances.age_days({}))
        self.assertIsNone(appliances.age_days({"built_at": 0}))
        self.assertAlmostEqual(
            appliances.age_days({"built_at": NOW - 2 * 86400}, NOW), 2.0,
            places=3)


class FakeWS:
    def __init__(self, rows):
        self.rows, self.asked = rows, []

    async def __call__(self, session, commands):
        self.asked.append(commands[0])
        wanted = commands[0]["statistic_ids"]
        return [{k: v for k, v in self.rows.items() if k in wanted}]


class TestTheBuild(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "appliances.json")

    def run_build(self, states, rows):
        import ha_data
        fake = FakeWS(rows)
        real = ha_data._ws_commands
        ha_data._ws_commands = fake
        try:
            return asyncio.run(
                appliances.build(None, states, NOW, self.path)), fake
        finally:
            ha_data._ws_commands = real

    def states(self, **extra):
        attrs = {"device_class": "power", "state_class": "measurement"}
        out = {"sensor.dishwasher_power": {
            "state": "0.6",
            "attributes": {**attrs, "friendly_name": "Dishwasher power"}}}
        out.update(extra)
        return out

    def test_only_the_sensors_with_a_shape_are_stored(self):
        rows = {"sensor.dishwasher_power": a_week(),
                "sensor.router_power": series([(10 * 24 * 60, 9.0)],
                                              start=10 * 24 * 3600)}
        attrs = {"device_class": "power", "state_class": "measurement"}
        got, _ = self.run_build(
            self.states(**{"sensor.router_power": {
                "state": "9", "attributes": {**attrs,
                                             "friendly_name": "Router"}}}),
            rows)
        self.assertIn("sensor.dishwasher_power", got["entities"])
        self.assertNotIn("sensor.router_power", got["entities"])
        self.assertEqual(got["asked"], 2)

    def test_the_name_rides_along_because_the_chore_needs_it(self):
        got, _ = self.run_build(self.states(),
                                {"sensor.dishwasher_power": a_week()})
        self.assertEqual(got["entities"]["sensor.dishwasher_power"]["name"],
                         "Dishwasher power")

    def test_a_house_with_no_power_sensors_writes_an_empty_store(self):
        got, fake = self.run_build({}, {})
        self.assertEqual(got["entities"], {})
        # And never went looking for statistics it had no ids for.
        self.assertEqual(fake.asked, [])

    def test_it_asks_for_five_minute_buckets_over_ten_days(self):
        _got, fake = self.run_build(self.states(),
                                    {"sensor.dishwasher_power": a_week()})
        cmd = fake.asked[0]
        self.assertEqual(cmd["period"], "5minute")
        self.assertEqual(cmd["types"], ["mean"])
        asked = dt.datetime.fromisoformat(cmd["start_time"])
        days = (NOW - asked.timestamp()) / 86400.0
        self.assertAlmostEqual(days, appliances.HISTORY_DAYS, places=1)


class TestTheChore(unittest.TestCase):
    """Silent on a healthy house in six ways, then at its planted case."""

    def snap(self, entities=None, recent=None, **extra):
        base = {
            "available": {"states": True, "registry": True,
                          "appliances": True},
            "errors": {},
            "states": {"sensor.dishwasher_power": {
                "state": "0.6",
                "attributes": {"friendly_name": "Dishwasher power",
                               "device_class": "power",
                               "state_class": "measurement"}}},
            "entities": [
                {"entity_id": "sensor.dishwasher_power", "disabled_by": None}],
            "devices": [], "areas": [],
            "appliances": {"built_at": NOW - 86400,
                           "entities": entities if entities is not None
                           else {"sensor.dishwasher_power": self.shape()},
                           "recent": recent or {}},
        }
        base.update(extra)
        return base

    def shape(self, name="Dishwasher power"):
        return {"name": name, "idle_w": 0.6, "busy_w": 1800.0,
                "threshold_w": 450.0, "settle_min": 22.0,
                "measured_settle": True, "draws": 12,
                "typical_run_min": 50.0}

    def finished(self, minutes_ago: float) -> dict:
        """A cycle that ended this many minutes ago."""
        run = 45.0
        return {"sensor.dishwasher_power": series(
            [(120, 0.6), (run, 1800.0), (minutes_ago, 0.6)],
            start=(120 + run + minutes_ago) * 60)}

    # --- the six silences -------------------------------------------------

    def test_nothing_measured_says_nothing(self):
        self.assertEqual(chores.waiting(self.snap(entities={}), NOW), [])

    def test_a_machine_that_has_not_run_says_nothing(self):
        recent = {"sensor.dishwasher_power": series([(8 * 60, 0.6)],
                                                    start=8 * 3600)}
        self.assertEqual(chores.waiting(self.snap(recent=recent), NOW), [])

    def test_a_machine_still_running_says_nothing(self):
        recent = {"sensor.dishwasher_power": series(
            [(60, 0.6), (40, 1800.0)], start=100 * 60)}
        self.assertEqual(chores.waiting(self.snap(recent=recent), NOW), [])

    def test_somebody_standing_at_the_machine_says_nothing(self):
        # It finished four minutes ago. They can hear it.
        got = chores.waiting(self.snap(recent=self.finished(4.0)), NOW)
        self.assertEqual(got, [])

    def test_yesterday_s_washing_is_not_a_chore(self):
        # Being told at lunchtime about yesterday is how a list stops
        # being read.
        ago = (chores.STALE_HOURS + 2) * 60
        got = chores.waiting(self.snap(recent=self.finished(ago)), NOW)
        self.assertEqual(got, [])

    def test_a_machine_nobody_has_to_empty_says_nothing(self):
        # The one guess in this check, made in the direction where being
        # wrong is cheap: a missing chore, never a notification telling
        # somebody to go and empty their television.
        for name in ("Living room TV", "Kettle", "Oven", "Utility plug",
                     "Immersion heater", "Air fryer"):
            snap = self.snap(
                entities={"sensor.dishwasher_power": self.shape(name)},
                recent=self.finished(60.0))
            self.assertEqual(chores.waiting(snap, NOW), [], name)

    def test_a_shape_with_no_name_falls_back_to_the_entity_s_own(self):
        # A profile written before names were stored still has to reach
        # the check, and the fallback is the same source the build reads.
        snap = self.snap(entities={"sensor.dishwasher_power": self.shape("")},
                         recent=self.finished(60.0))
        got = chores.waiting(snap, NOW)
        self.assertEqual(len(got), 1)
        self.assertIn("dishwasher", got[0]["text"].lower())

    # --- and the case it exists for ---------------------------------------

    def test_a_dishwasher_that_finished_an_hour_ago(self):
        got = chores.waiting(self.snap(recent=self.finished(60.0)), NOW)
        self.assertEqual(len(got), 1)
        row = got[0]
        self.assertIn("dishwasher", row["text"].lower())
        self.assertIn("still full", row["text"].lower())
        self.assertEqual(row["entity_id"], "sensor.dishwasher_power")
        self.assertFalse(row["fixable"])

    def test_the_minutes_are_in_detail_and_never_in_the_text(self):
        # The store dedupes on text, so a number there re-files the row
        # every pass.
        one = chores.waiting(self.snap(recent=self.finished(40.0)), NOW)[0]
        two = chores.waiting(self.snap(recent=self.finished(95.0)), NOW)[0]
        self.assertEqual(one["text"], two["text"])
        self.assertNotEqual(one["detail"], two["detail"])
        self.assertIn("minutes ago", one["detail"])
        self.assertIn("hours ago", two["detail"])

    def test_the_fix_says_brAIn_cannot_see_you_emptied_it(self):
        # The honest limit, on the row: an empty machine and a full one
        # draw exactly the same power, so the ending is a person's.
        row = chores.waiting(self.snap(recent=self.finished(60.0)), NOW)[0]
        self.assertIn("cannot see", row["fix"])
        self.assertIn("tick it off", row["fix"])

    def test_each_kind_is_named_by_what_it_is_not_by_its_sensor(self):
        # "Utility Plug Power" is a washing machine to the check and
        # "Utility Plug Power" to nobody.
        for name, said in (("Washing machine plug", "washing machine"),
                           ("Tumble dryer power", "dryer"),
                           ("Kitchen dishwasher", "dishwasher")):
            snap = self.snap(
                entities={"sensor.dishwasher_power": self.shape(name)},
                recent=self.finished(60.0))
            got = chores.waiting(snap, NOW)
            self.assertEqual(len(got), 1, name)
            self.assertIn(said, got[0]["text"].lower())

    def test_a_washing_machine_is_not_read_as_a_dryer(self):
        # Longest phrase first, or a name carrying both words is filed
        # under whichever the dict happened to iterate first.
        self.assertEqual(chores.kind_of("Washing machine / dryer plug"),
                         "washer")
        self.assertEqual(chores.kind_of("dryer"), "dryer")
        self.assertEqual(chores.kind_of("nothing at all"), "")
        self.assertEqual(chores.kind_of(None), "")

    def test_a_disabled_entity_is_not_a_chore(self):
        snap = self.snap(recent=self.finished(60.0))
        snap["entities"][0]["disabled_by"] = "user"
        self.assertEqual(chores.waiting(snap, NOW), [])

    def test_two_machines_are_two_rows_oldest_first(self):
        shapes = {"sensor.dishwasher_power": self.shape("Dishwasher"),
                  "sensor.washer_power": self.shape("Washing machine")}
        recent = {**self.finished(30.0)}
        recent["sensor.washer_power"] = self.finished(120.0)[
            "sensor.dishwasher_power"]
        snap = self.snap(entities=shapes, recent=recent)
        snap["states"]["sensor.washer_power"] = dict(
            snap["states"]["sensor.dishwasher_power"])
        snap["entities"].append(
            {"entity_id": "sensor.washer_power", "disabled_by": None})
        got = chores.waiting(snap, NOW)
        self.assertEqual(len(got), 2)
        self.assertIn("washing machine", got[0]["text"].lower())

    def test_past_the_cap_it_says_nothing_at_all(self):
        shapes, recent, states, reg = {}, {}, {}, []
        for i in range(chores.MAX_ROWS + 1):
            eid = f"sensor.washer{i}_power"
            shapes[eid] = self.shape(f"Washing machine {i}")
            recent[eid] = self.finished(60.0)["sensor.dishwasher_power"]
            states[eid] = {"state": "0.6", "attributes": {
                "friendly_name": f"Washing machine {i}",
                "device_class": "power", "state_class": "measurement"}}
            reg.append({"entity_id": eid, "disabled_by": None})
        snap = self.snap(entities=shapes, recent=recent)
        snap["states"] = states
        snap["entities"] = reg
        self.assertEqual(chores.waiting(snap, NOW), [])

    def test_a_chore_is_never_urgent(self):
        # It arrives in the evening by construction, and an emptied
        # dishwasher at eight in the morning is the same dishwasher —
        # so quiet hours have to be able to hold it.
        import notify_router
        self.assertEqual(
            notify_router.urgency_of({"source": "check:chore.waiting"}),
            "whenever")



if __name__ == "__main__":
    unittest.main()
