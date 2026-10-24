#!/usr/bin/env python3
"""A thermometer on a heating or cooling machine is not a room.

A house had one area whose only "room" was a heat pump's coil probe, which
jumps by about 25 °C at the same hour every morning when the machine starts,
and `climate.heat_loss` filed "this room loses heat much faster than the
rest of the house" about it. The thermal model leaves out printer probes
and ductwork by name; the refrigerant line, the flue and the rest of a
heating or cooling machine's parts are named now too, and a reading that
jumps far faster than any room can warm, at the same clock hour day after
day, is left out by what it does whatever it is called. The area is then
measured from its ordinary air sensor, or not at all.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import thermal  # noqa: E402
from test_thermal import START, _build, simulate, state  # noqa: E402

UTC = dt.timezone.utc


def jumping(low=9.0, high=34.0, hour=6, days=28):
    """Flat at `low`, then at `high` from `hour` for three hours, daily."""
    rows = []
    for i in range(days * 24):
        ts = START + i * 3600
        h = dt.datetime.fromtimestamp(ts, UTC).hour
        rows.append({"start": ts,
                     "mean": high if hour <= h < hour + 3 else low})
    return rows


def built(states, areas, rows):
    with tempfile.TemporaryDirectory() as tmp:
        return asyncio.run(_build(states, areas, rows,
                                  path=os.path.join(tmp, "t.json")))


class TestMachinePartsByName(unittest.TestCase):
    def test_hvac_parts_are_not_rooms(self):
        for name in ("Loft refrigerant line temperature",
                     "Utility flue temperature",
                     "Plant room suction line temperature"):
            states = {"sensor.garden": state("Outside", "4"),
                      "sensor.x": state(name, "20")}
            ids, why = thermal.room_candidates_why(
                states, "sensor.garden", "°C", {"sensor.x": "Utility"})
            self.assertEqual(ids, [], name)
            self.assertIn("machine", why["sensor.x"], name)

    def test_a_room_whose_name_only_contains_the_letters_is_kept(self):
        states = {"sensor.garden": state("Outside", "4"),
                  "sensor.x": state("Airline lounge temperature", "20")}
        ids, _why = thermal.room_candidates_why(
            states, "sensor.garden", "°C", {"sensor.x": "Lounge"})
        self.assertEqual(ids, ["sensor.x"])


class TestMachinePartsByWhatTheyDo(unittest.TestCase):
    def test_a_daily_jump_at_one_hour_is_equipment(self):
        reason = thermal.equipment_jumps(jumping(), UTC, "°C")
        self.assertIn("06:00", reason)
        self.assertIn("equipment", reason)

    def test_the_same_in_fahrenheit(self):
        reason = thermal.equipment_jumps(jumping(49.0, 92.0, hour=7), UTC,
                                         "°F")
        self.assertIn("07:00", reason)

    def test_a_heated_room_is_not(self):
        room, _out = simulate()
        self.assertEqual(thermal.equipment_jumps(room, UTC, "°C"), "")

    def test_a_jump_at_a_different_hour_each_day_is_not(self):
        rows = jumping(days=0)
        for d in range(28):
            for i in range(24):
                ts = START + (d * 24 + i) * 3600
                hot = (d * 5) % 24 <= i < (d * 5) % 24 + 2
                rows.append({"start": ts, "mean": 30.0 if hot else 18.0})
        self.assertEqual(thermal.equipment_jumps(rows, UTC, "°C"), "")

    def test_the_area_is_measured_from_its_air_sensor_instead(self):
        """A second example: a probe named like a room's own thermometer,
        beside the room's real one in the same area."""
        room, out = simulate()
        states = {"sensor.garden": state("Outside", "4"),
                  "sensor.utility_temperature": state("Utility temperature",
                                                      "20"),
                  "sensor.utility_air": state("Utility air", "20")}
        areas = {"sensor.utility_temperature": "Utility",
                 "sensor.utility_air": "Utility"}
        rows = {"sensor.garden": out, "sensor.utility_air": room,
                "sensor.utility_temperature": jumping()}
        payload = built(states, areas, rows)
        self.assertEqual(sorted(payload["rooms"]), ["sensor.utility_air"])
        left = payload["unmeasured"]["sensor.utility_temperature"]["reason"]
        self.assertIn("equipment", left)


if __name__ == "__main__":
    unittest.main()
