#!/usr/bin/env python3
"""A washer mid-cycle is not an unusual reading, profiled or not.

A washer's power sensor read 178 W against a usual 8 W while the
washer's own status sensor on the same device read "spinning": an
ordinary wash, filed by `base.unusual` as "554 spreads out", and it
would have been filed every wash. The appliance store had no profile
for the sensor, so the profiled-sensor skip in `not_a_house_reading`
never applied. Two halves, both driven here:

* `not_a_house_reading` (shared by `base.unusual` and `forecast.decline`)
  skips a power or energy sensor that is a cycling machine by its name,
  its device's name, or a status entity on its device — with the chore
  vocabulary `checks.chores` already owns, not a second copy of it.
* `appliances.select` ranks such a sensor ahead of the cap, reading the
  device as well as the sensor's own name, so the nightly pass profiles
  it rather than cutting it behind an inverter's circuits.
"""

import datetime as dt
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))

import appliances  # noqa: E402
import baselines  # noqa: E402
from checks import baseline as band  # noqa: E402
from checks import forecasts  # noqa: E402

NOW = dt.datetime(2026, 1, 5, 10, 0, tzinfo=dt.timezone.utc).timestamp()

POWER = {"unit_of_measurement": "W", "device_class": "power"}


def snapshot(rows, *, devices=(), extra_states=(), trend=None):
    """rows: (entity id, friendly name, device id, attrs, value, median)."""
    bucket = str(baselines.hour_of_week(NOW, dt.timezone.utc))
    states, registry, store = {}, [], {}
    for eid, name, device, attrs, value, median in rows:
        states[eid] = {"state": str(value), "attributes": {
            "state_class": "measurement", "friendly_name": name, **attrs},
            "last_changed": "", "last_updated": ""}
        registry.append({"entity_id": eid, "name": None,
                         "original_name": name, "platform": "",
                         "device_id": device})
        entry = {"unit": attrs.get("unit_of_measurement", ""),
                 "samples": 672,
                 "overall": {"median": median, "spread": 0.3, "n": 672},
                 "buckets": {bucket: {"median": median, "spread": 0.3,
                                      "n": 4}}}
        if trend:
            entry["trend"] = dict(trend)
        store[eid] = entry
    for eid, name, device, state, attrs in extra_states:
        states[eid] = {"state": state, "attributes": {
            "friendly_name": name, **attrs},
            "last_changed": "", "last_updated": ""}
        registry.append({"entity_id": eid, "original_name": name,
                         "platform": "", "device_id": device})
    return {"now": NOW, "states": states, "entities": registry,
            "devices": list(devices), "areas": [],
            "appliances": {"entities": {}},
            "baselines": {"built_at": int(NOW - 3600), "tz": "UTC",
                          "days": 28, "entities": store}}


DRIFT = {"per_day": -3.0, "move": -90.0, "days": 28.0, "noise": 1.0,
         "spreads": -20.0, "consistent": True, "points": 672}

# The washer from the report: its plug says nothing about laundry, its
# device is named for the brand, and only the status sensor beside it
# says what it is doing.
WASHER_PLUG = ("sensor.plug_power", "Utility plug power", "dev_washer",
               POWER, 178, 8.0)
WASHER_DEVICE = {"id": "dev_washer", "name": "LG F4V5", "name_by_user": None}
WASHER_STATUS = ("sensor.lg_f4v5_run_state", "LG F4V5 run state",
                 "dev_washer", "spinning", {})
# The case nobody reported: a dishwasher on a smart plug, no status
# sensor, named only on its device.
DISH_PLUG = ("sensor.kitchen_plug_power", "Kitchen plug power", "dev_dish",
             POWER, 1900, 2.0)
DISH_DEVICE = {"id": "dev_dish", "name": "Smart plug",
               "name_by_user": "Dishwasher plug"}
# And one named on the sensor itself, the way most are.
DRYER_PLUG = ("sensor.dryer_energy_now", "Dryer power", None,
              POWER, 2400, 1.0)
# A real fault on an ordinary sensor, in the same pass.
FREEZER = ("sensor.freezer", "Freezer", None,
           {"unit_of_measurement": "°C", "device_class": "temperature"},
           -2, -18.0)


def house_snap():
    return snapshot([WASHER_PLUG, DISH_PLUG, DRYER_PLUG, FREEZER],
                    devices=[WASHER_DEVICE, DISH_DEVICE],
                    extra_states=[WASHER_STATUS])


class TestACyclingMachineIsNotAnUnusualReading(unittest.TestCase):

    def test_unusual_skips_the_machines_and_keeps_the_freezer(self):
        found = band.unusual(house_snap(), NOW)
        self.assertEqual([r["entity_id"] for r in found], ["sensor.freezer"])

    def test_each_machine_is_refused_on_its_own(self):
        for row, devices, extra in (
                (WASHER_PLUG, [WASHER_DEVICE], [WASHER_STATUS]),
                (DISH_PLUG, [DISH_DEVICE], []),
                (DRYER_PLUG, [], [])):
            with self.subTest(row=row[0]):
                snap = snapshot([row], devices=devices, extra_states=extra)
                self.assertEqual(band.unusual(snap, NOW), [])

    def test_washer_between_150_and_250_watts_while_spinning(self):
        for watts in (150, 178, 210, 250):
            for status in ("spinning", "running", "Washing"):
                with self.subTest(watts=watts, status=status):
                    row = (*WASHER_PLUG[:4], watts, 8.0)
                    snap = snapshot([row], devices=[WASHER_DEVICE],
                                    extra_states=[(*WASHER_STATUS[:3],
                                                   status, {})])
                    self.assertEqual(band.unusual(snap, NOW), [])

    def test_decline_skips_them_too(self):
        snap = snapshot([WASHER_PLUG, DISH_PLUG],
                        devices=[WASHER_DEVICE, DISH_DEVICE],
                        extra_states=[WASHER_STATUS], trend=DRIFT)
        self.assertEqual(forecasts.decline(snap, NOW), [])

    def test_the_reason_is_said(self):
        from checks._util import House  # noqa: PLC0415
        snap = house_snap()
        house = House(snap)
        for eid in ("sensor.plug_power", "sensor.kitchen_plug_power",
                    "sensor.dryer_energy_now"):
            with self.subTest(eid=eid):
                self.assertTrue(band.not_a_house_reading(
                    house, eid, snap["states"][eid]))

    def test_an_ordinary_power_sensor_is_still_a_reading(self):
        """No chore name, no status beside it: a server rack drawing ten
        times its usual is exactly what the check is for."""
        from checks._util import House  # noqa: PLC0415
        rack = ("sensor.rack_power", "Rack power", "dev_rack", POWER,
                900, 80.0)
        snap = snapshot([rack], devices=[{"id": "dev_rack", "name": "Rack"}],
                        extra_states=[("sensor.rack_mode", "Rack mode",
                                       "dev_rack", "eco", {})])
        self.assertEqual(band.not_a_house_reading(
            House(snap), "sensor.rack_power",
            snap["states"]["sensor.rack_power"]), "")
        self.assertEqual([r["entity_id"] for r in band.unusual(snap, NOW)],
                         ["sensor.rack_power"])

    def test_a_status_beside_a_thermometer_does_not_hide_it(self):
        """Only a power or energy reading is the machine's own draw: a
        temperature sensor on a washer is not its cycle."""
        from checks._util import House  # noqa: PLC0415
        temp = ("sensor.lg_f4v5_temp", "LG F4V5 temperature", "dev_washer",
                {"unit_of_measurement": "°C", "device_class": "temperature"},
                90, 20.0)
        snap = snapshot([temp], devices=[WASHER_DEVICE],
                        extra_states=[WASHER_STATUS])
        self.assertEqual(band.not_a_house_reading(
            House(snap), "sensor.lg_f4v5_temp",
            snap["states"]["sensor.lg_f4v5_temp"]), "")


class TestTheCapReadsTheDevice(unittest.TestCase):
    """The washer got no profile because the cap never read it."""

    def states(self):
        out = {}
        # An inverter's circuits: forty-five power sensors that sort
        # before the washer's plug and are named for nothing.
        for i in range(45):
            out[f"sensor.circuit_{i:02d}_power"] = {
                "state": "40", "attributes": {
                    "device_class": "power", "state_class": "measurement",
                    "friendly_name": f"Circuit {i} power"}}
        out["sensor.plug_power"] = {"state": "8", "attributes": {
            "device_class": "power", "state_class": "measurement",
            "friendly_name": "Utility plug power"}}
        out["sensor.kitchen_plug_power"] = {"state": "2", "attributes": {
            "device_class": "power", "state_class": "measurement",
            "friendly_name": "Kitchen plug power"}}
        out["sensor.lg_f4v5_run_state"] = {"state": "spinning",
                                           "attributes": {}}
        return out

    def registries(self):
        entities = [{"entity_id": "sensor.plug_power",
                     "device_id": "dev_washer"},
                    {"entity_id": "sensor.lg_f4v5_run_state",
                     "device_id": "dev_washer"},
                    {"entity_id": "sensor.kitchen_plug_power",
                     "device_id": "dev_dish"}]
        return entities, [WASHER_DEVICE, DISH_DEVICE]

    def test_without_registries_the_old_ranking_stands(self):
        chosen = appliances.select(self.states())
        self.assertNotIn("sensor.plug_power", chosen["ids"])

    def test_the_machines_are_read_ahead_of_the_cap(self):
        entities, devices = self.registries()
        chosen = appliances.select(self.states(), entities=entities,
                                   devices=devices)
        self.assertIn("sensor.plug_power", chosen["ids"])
        self.assertIn("sensor.kitchen_plug_power", chosen["ids"])
        self.assertEqual(len(chosen["ids"]), appliances.MAX_ENTITIES)


if __name__ == "__main__":
    unittest.main()
