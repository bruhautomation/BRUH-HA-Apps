"""A washer that runs a few loads a week is still a washer.

`appliances.profile` read the busy level off the 95th percentile of every
five-minute bucket in ten days — 2,880 of them — so any machine that ran
fewer than about 145 buckets (twelve hours) read busy == idle, failed the
span floor, and was reported as "not an appliance". That is the commonest
washer and dryer there is: driven against the shipped arithmetic at 1 W
idle and 500 W running, nothing up to eight 90-minute cycles in ten days,
a profile at nine. And the forty-sensor cap took power sensors in id
order, so on a house with an inverter and a circuit monitor the washer
plug sorted last and was never read at all — with nothing anywhere to
say so. `chore.waiting` and everything built on it stayed silent.

Every case drives the real `profile`, `select` and `build`; the first
states the old answer on the same readings before asserting the new one.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import appliances  # noqa: E402

NOW = 1_756_800_000.0
BUCKET = appliances.BUCKET_S
TEN_DAYS = 10 * 24 * 60


def light_use(cycles: int, cycle_min: float = 90.0, idle_w: float = 1.0,
              busy_w: float = 500.0) -> list[dict]:
    """Ten days of five-minute means with `cycles` runs spread across them."""
    total = int(TEN_DAYS * 60 / BUCKET)
    per_cycle = int(cycle_min * 60 / BUCKET)
    gap = total // (cycles + 1)
    busy = set()
    for c in range(cycles):
        start = gap * (c + 1)
        busy.update(range(start, start + per_cycle))
    begin = NOW - total * BUCKET
    return [{"start": begin + i * BUCKET,
             "mean": busy_w if i in busy else idle_w} for i in range(total)]


class TestAMachineThatRunsALittleHasAShape(unittest.TestCase):

    def test_the_whole_window_percentile_could_not_see_it(self):
        """The old arithmetic, on the same readings: p95 of all of them."""
        watts = [r["mean"] for r in light_use(6)]
        self.assertEqual(appliances.percentile(watts, 95.0),
                         appliances.percentile(watts, 20.0))   # busy == idle

    def test_six_loads_in_ten_days_is_a_washer(self):
        shape = appliances.profile(light_use(6), NOW)
        self.assertIsNotNone(shape)
        self.assertEqual(shape["busy_w"], 500.0)
        self.assertGreater(shape["threshold_w"], 1.0)
        self.assertEqual(shape["draws"], 6)

    def test_three_hour_long_loads_is_enough(self):
        self.assertIsNotNone(appliances.profile(light_use(3, 60.0), NOW))

    def test_two_loads_is_still_too_few_to_measure(self):
        # MIN_DRAWS: two gaps is the fewest the settle time can be found in.
        self.assertIsNone(appliances.profile(light_use(2), NOW))

    def test_a_steady_draw_still_is_not_an_appliance(self):
        rows = light_use(0, idle_w=12.0)
        self.assertIsNone(appliances.profile(rows, NOW))

    def test_a_phone_charger_still_is_not_one(self):
        # 3 W to 9 W never clears the noise floor, however often it runs.
        self.assertIsNone(appliances.profile(
            light_use(20, busy_w=9.0, idle_w=3.0), NOW))

    def test_a_motor_phase_is_running_and_not_a_lull(self):
        """The busy level is the middle of the running readings, so a
        washer's 2 kW heater does not put the threshold above the 300 W
        motor phase that is just as much the machine working."""
        rows = light_use(6)
        heat = 0
        for r in rows:
            if r["mean"] == 500.0:
                if heat < 3:
                    r["mean"] = 2000.0
                heat = (heat + 1) % 18
        shape = appliances.profile(rows, NOW)
        self.assertLess(shape["threshold_w"], 500.0)


def power(name: str) -> dict:
    return {"state": "3", "attributes": {"device_class": "power",
                                         "state_class": "measurement",
                                         "friendly_name": name}}


class TestTheCapTakesTheChoreMachinesFirst(unittest.TestCase):

    def house(self) -> dict:
        states = {f"sensor.circuit_{i:02d}_power": power(f"Circuit {i}")
                  for i in range(appliances.MAX_ENTITIES + 5)}
        states["sensor.washer_power"] = power("Washer power")
        states["sensor.utility_plug_power"] = power("Tumble dryer plug")
        return states

    def test_a_washer_sorting_last_is_read_first(self):
        chosen = appliances.select(self.house())
        self.assertEqual(len(chosen["ids"]), appliances.MAX_ENTITIES)
        self.assertEqual(chosen["ids"][:2], ["sensor.utility_plug_power",
                                             "sensor.washer_power"])
        self.assertEqual(chosen["eligible"], appliances.MAX_ENTITIES + 7)
        self.assertEqual(len(chosen["cut"]), 7)

    def test_the_old_order_cut_it(self):
        ids = sorted(self.house())[:appliances.MAX_ENTITIES]
        self.assertNotIn("sensor.washer_power", ids)

    def test_the_rest_keep_a_stable_order(self):
        a = appliances.select(self.house())["ids"]
        b = appliances.select(dict(reversed(list(self.house().items()))))["ids"]
        self.assertEqual(a, b)

    def test_the_cut_is_written_down_and_said(self):
        async def fetch(session, ids, start, end=None):
            return {eid: light_use(6) for eid in ids[:2]}

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "appliances.json")
            with mock.patch.object(appliances, "fetch", fetch):
                payload = asyncio.run(appliances.build(
                    None, self.house(), NOW, path))
            self.assertEqual(payload["cut_count"], 7)
            self.assertEqual(len(payload["cut"]), 7)
            self.assertIn("sensor.washer_power", payload["entities"])
            said = appliances.progress(path=path, now=NOW)
            self.assertIn("7 more power sensors", said["summary"])
            self.assertEqual(said["detail"]["cut"], 7)


if __name__ == "__main__":
    unittest.main()
