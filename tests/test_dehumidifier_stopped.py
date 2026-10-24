#!/usr/bin/env python3
"""A dehumidifier that stopped while its room is still damp.

The appliance store measured a dehumidifier's plug like any other machine
and gave it no chore kind, so a unit that stopped with a full tank went
unnoticed for six days. A measured machine named or registered as a
dehumidifier, with a humidity sensor in the same area (or on the same
device), now gets the kind `dehumidifier` and the humidity it measurably
starts running at (from its own runs over ten days). `chore.dehumidifier`
reports one that is switched on, has stayed at standby for hours, and
reads well above that level; it says nothing once the machine runs again
or the air dries.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import appliances  # noqa: E402
import checks  # noqa: E402

chores = checks.chores

NOW = 1_790_000_000.0
STEP = 300.0
POWER = "sensor.basement_dehumidifier_power"
RH = "sensor.basement_humidity"
SWITCH = "switch.basement_dehumidifier"


def power_rows(days=10, every_h=6, run_min=60, busy=280.0, idle=2.0):
    """A dehumidifier cycling: on for an hour every six hours."""
    rows, t = [], NOW - days * 86400
    while t < NOW:
        phase = (t - (NOW - days * 86400)) % (every_h * 3600)
        rows.append({"start": t, "mean": busy if phase < run_min * 60 else idle})
        t += STEP
    return rows


def rh_rows(days=10, every_h=6, start_rh=62.0):
    """Humidity climbing to `start_rh` as each run starts, falling during it."""
    rows, t = [], NOW - days * 86400
    period = every_h * 3600
    while t < NOW:
        phase = (t - (NOW - days * 86400)) % period
        if phase < 3600:
            value = start_rh - 8 * phase / 3600
        else:
            value = start_rh - 8 + 8 * (phase - 3600) / (period - 3600)
        rows.append({"start": t, "mean": round(value, 1)})
        t += STEP
    return rows


class FakeWS:
    def __init__(self, rows):
        self.rows = rows

    async def __call__(self, session, commands):
        wanted = commands[0]["statistic_ids"]
        return [{k: v for k, v in self.rows.items() if k in wanted}]


def states(power_name="Basement dehumidifier power"):
    return {
        POWER: {"state": "2.0", "attributes": {
            "device_class": "power", "state_class": "measurement",
            "unit_of_measurement": "W", "friendly_name": power_name}},
        RH: {"state": "70", "attributes": {
            "device_class": "humidity", "state_class": "measurement",
            "unit_of_measurement": "%", "friendly_name": "Basement humidity"}},
        SWITCH: {"state": "on", "attributes": {"friendly_name": "Basement plug"}},
        "sensor.attic_humidity": {"state": "40", "attributes": {
            "device_class": "humidity", "friendly_name": "Attic humidity"}},
    }


def registries(registered: bool = False):
    entities = [
        {"entity_id": POWER, "device_id": "dev-plug"},
        {"entity_id": SWITCH, "device_id": "dev-plug"},
        {"entity_id": RH, "device_id": "dev-th", "area_id": "basement"},
        {"entity_id": "sensor.attic_humidity", "device_id": "dev-a",
         "area_id": "attic"},
    ]
    devices = [{"id": "dev-plug", "name": "Utility plug", "area_id": "basement"},
               {"id": "dev-th", "name": "Basement sensor", "area_id": "basement"},
               {"id": "dev-a", "name": "Attic sensor", "area_id": "attic"}]
    if registered:
        entities.append({"entity_id": "humidifier.utility",
                         "device_id": "dev-plug"})
    return entities, devices


class TestTheStoreKnowsItIsADehumidifier(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "appliances.json")

    def build(self, st, ents, devs):
        import ha_data
        real = ha_data._ws_commands
        ha_data._ws_commands = FakeWS({POWER: power_rows(), RH: rh_rows()})
        try:
            return asyncio.run(appliances.build(None, st, NOW, self.path,
                                                entities=ents, devices=devs))
        finally:
            ha_data._ws_commands = real

    def test_named_for_it(self):
        ents, devs = registries()
        shape = self.build(states(), ents, devs)["entities"][POWER]
        self.assertEqual(shape["kind"], "dehumidifier")
        self.assertEqual(shape["humidity_entity"], RH)
        self.assertAlmostEqual(shape["runs_from_rh"], 62.0, delta=1.5)

    def test_a_second_example_registered_rather_than_named(self):
        st = states(power_name="Utility plug power")
        st["humidifier.utility"] = {"state": "on", "attributes": {
            "device_class": "dehumidifier", "friendly_name": "Utility"}}
        ents, devs = registries(registered=True)
        shape = self.build(st, ents, devs)["entities"][POWER]
        self.assertEqual(shape["kind"], "dehumidifier")
        self.assertEqual(shape["humidity_entity"], RH)

    def test_a_plug_that_is_not_one_gets_no_kind(self):
        # Nothing about it says dehumidifier: not its name, not its id,
        # not its device.
        st = states(power_name="Utility plug power")
        plain = "sensor.utility_plug_power"
        st[plain] = st.pop(POWER)
        ents, devs = registries()
        for e in ents:
            if e["entity_id"] == POWER:
                e["entity_id"] = plain
        import ha_data
        real = ha_data._ws_commands
        ha_data._ws_commands = FakeWS({plain: power_rows(), RH: rh_rows()})
        try:
            got = asyncio.run(appliances.build(None, st, NOW, self.path,
                                               entities=ents, devices=devs))
        finally:
            ha_data._ws_commands = real
        self.assertIn(plain, got["entities"])
        self.assertNotIn("kind", got["entities"][plain])


def recent(standby_h: float, running_now: bool = False):
    """Fourteen hours of five-minute readings ending now."""
    rows, t = [], NOW - 14 * 3600
    stopped = NOW - standby_h * 3600
    while t < NOW:
        on = (t < stopped and (t - (NOW - 14 * 3600)) % (6 * 3600) < 3600) \
            or (running_now and t > NOW - 1800)
        rows.append({"start": t, "mean": 280.0 if on else 2.0})
        t += STEP
    return rows


def snap(standby_h=5.0, rh="70", switch="on", running_now=False):
    st = states()
    st[RH]["state"] = rh
    st[SWITCH]["state"] = switch
    ents, devs = registries()
    shape = {"idle_w": 2.0, "busy_w": 280.0, "threshold_w": 71.5,
             "settle_min": 10.0, "measured_settle": False, "draws": 40,
             "typical_run_min": 60.0, "built_at": int(NOW - 3600),
             "name": "Basement dehumidifier power", "kind": "dehumidifier",
             "humidity_entity": RH, "runs_from_rh": 62.0, "rh_runs": 40}
    return {"now": NOW,
            "available": {"states": True, "registry": True, "appliances": True},
            "errors": {}, "states": st, "entities": ents, "devices": devs,
            "areas": [{"area_id": "basement", "name": "Basement"}],
            "appliances": {"entities": {POWER: shape}, "built_at": NOW,
                           "recent": {POWER: recent(standby_h, running_now)}}}


class TestTheCheck(unittest.TestCase):
    def test_stopped_while_damp_is_raised(self):
        got = chores.dehumidifier(snap(), NOW)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["entity_id"], POWER)
        self.assertIn("70", got[0]["detail"])
        self.assertIn("62", got[0]["detail"])

    def test_dry_air_is_not(self):
        self.assertEqual(chores.dehumidifier(snap(rh="58"), NOW), [])

    def test_switched_off_is_not(self):
        self.assertEqual(chores.dehumidifier(snap(switch="off"), NOW), [])

    def test_a_short_pause_is_not(self):
        self.assertEqual(chores.dehumidifier(snap(standby_h=1.0), NOW), [])

    def test_it_clears_when_it_runs_again(self):
        before = checks.run_all(snap(), NOW, only=["chore.dehumidifier"])
        self.assertEqual(len(before["findings"]), 1)
        after = checks.run_all(snap(running_now=True), NOW,
                               only=["chore.dehumidifier"])
        self.assertIn("chore.dehumidifier", after["ran"])
        self.assertEqual(after["findings"], [])

    def test_a_house_with_no_dehumidifier_says_nothing(self):
        s = snap()
        s["appliances"]["entities"][POWER].pop("kind")
        self.assertEqual(chores.dehumidifier(s, NOW), [])


if __name__ == "__main__":
    unittest.main()
