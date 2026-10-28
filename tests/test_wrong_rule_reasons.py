#!/usr/bin/env python3
"""The reasons a household gave when it marked two rules Wrong, read as
classes rather than one entity at a time.

`dev.frozen` was marked Wrong six times of six — "it's still reading,
probably low battery", "its battery is dead and I do not plan to replace
it". A stuck reading on a device whose own low-battery flag is on is the
battery's card (`dev.battery_low` files that flag), and a stuck reading on
a sensor whose own battery attribute reads low says so in its fix rather
than sending somebody to rewire it. A plain stuck sensor with a healthy
battery still files.

`dev.unavailable` was marked Wrong "unpowered unless we're using it" and
"expected: unpowered most of the year". A reason that says the device is
normally without power describes exactly the state this check reports, so
it is written as the rule, not parked as a fact and a question the way an
unwatchable condition on another check is (`_unwatchable_condition`, 4.0.3).
A condition on any other check is still a question.
"""

import asyncio
import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "brain" / "panel"))
sys.path.insert(0, str(TESTS_DIR))

import corrections  # noqa: E402
import findings_store  # noqa: E402
from checks import devices  # noqa: E402
from test_house_checks import DAY, NOW, house, iso  # noqa: E402
from test_scoped_corrections import RouteCase  # noqa: E402

PROBE = "sensor.cellar_humidity"


def stuck(battery=None, flag=None):
    snap = house()
    snap["devices"].append({"id": "dev-cellar", "name": "Cellar sensor",
                            "manufacturer": "Aqara", "model": "WSDCGQ11LM"})
    attrs = {"device_class": "humidity", "unit_of_measurement": "%",
             "friendly_name": "Cellar humidity", "state_class": "measurement"}
    if battery is not None:
        attrs["battery_level"] = battery
    snap["states"][PROBE] = {"state": "64", "attributes": attrs,
                             "last_updated": iso(60),
                             "last_changed": iso(9 * DAY)}
    snap["entities"].append({"entity_id": PROBE, "platform": "zha",
                             "device_id": "dev-cellar"})
    if flag is not None:
        snap["states"]["binary_sensor.cellar_battery_low"] = {
            "state": flag, "attributes": {"device_class": "battery",
                                          "friendly_name": "Cellar battery"},
            "last_updated": iso(60), "last_changed": iso(60)}
        snap["entities"].append({"entity_id": "binary_sensor.cellar_battery_low",
                                 "platform": "zha", "device_id": "dev-cellar"})
    snap["stats"] = {PROBE: [{"start": NOW - d * DAY, "mean": 64, "min": 64,
                              "max": 64} for d in range(7)]}
    snap["_trail"] = []
    return snap


def frozen_ids(snap):
    return [r["entity_id"] for r in devices.frozen(snap, NOW)]


class TestAStuckReadingBesideAFlatBattery(unittest.TestCase):
    def test_a_low_battery_flag_on_the_device_owns_it(self):
        snap = stuck(flag="on")
        self.assertEqual(frozen_ids(snap), [])
        self.assertTrue(any(t["subject"] == PROBE and t["kind"] == "dedupe"
                            for t in snap["_trail"]))
        # And the flag's own card is the one filed.
        self.assertIn("binary_sensor.cellar_battery_low",
                      [r["entity_id"] for r in devices.battery_low(snap, NOW)])

    def test_a_flag_that_is_off_owns_nothing(self):
        self.assertEqual(frozen_ids(stuck(flag="off")), [PROBE])

    def test_its_own_battery_reading_low_is_named_in_the_fix(self):
        rows = devices.frozen(stuck(battery=4), NOW)
        self.assertEqual([r["entity_id"] for r in rows], [PROBE])
        self.assertIn("4%", rows[0]["fix"])
        self.assertIn("battery", rows[0]["fix"].lower())

    def test_a_healthy_battery_is_the_ordinary_fix(self):
        rows = devices.frozen(stuck(battery=88), NOW)
        self.assertEqual([r["entity_id"] for r in rows], [PROBE])
        self.assertNotIn("88%", rows[0]["fix"])


class TestNormallyUnpoweredIsTheRule(unittest.TestCase):
    def test_the_words(self):
        for said in ("unpowered unless we're using it",
                     "expected: unpowered most of the year",
                     "It's unplugged except when we need it",
                     "switched off at the wall unless guests are staying"):
            self.assertTrue(corrections.normally_unpowered(said), said)
        for said in ("I'll plug it back in soon",
                     "Normal while the printer is printing",
                     "only matters while the dryer is running",
                     "it's a dummy"):
            self.assertFalse(corrections.normally_unpowered(said), said)


class TestThePress(RouteCase):
    ENTITY = "switch.pool_pump"

    def press(self, check, note):
        row = self.check_row(check)

        async def body(client):
            res = await client.post(f"/api/finding/{row['ts']}/wrong",
                                    json={"note": note})
            self.assertEqual(res.status, 200)
            await asyncio.gather(*list(self.server._CORRECTION_TASKS))

        self.drive(body)
        return row

    def questions(self):
        return [f for f in findings_store.list_all()
                if f["source"] == corrections.SOURCE]

    def test_unavailable_unless_used_is_a_rule_and_asks_nothing(self):
        self.press("dev.unavailable", "unpowered unless we're using it")
        self.assertEqual([r["subject"] for r in self.rules()], [self.ENTITY])
        self.assertEqual(self.questions(), [])

    def test_the_same_words_on_another_check_are_still_a_question(self):
        self.press("base.unusual", "unpowered unless we're using it")
        self.assertEqual(self.rules(), [])
        self.assertEqual(len(self.questions()), 1)


if __name__ == "__main__":
    unittest.main()
