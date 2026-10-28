#!/usr/bin/env python3
"""`integ.log_flood` files a flood that persists, not a burst that passed.

"Errors in the log" cards were filed for a hundred errors in the twenty
minutes around a restart, long over by the time anybody read them. A
logger now has to still be erroring in the latest window AND have gone on
for `FLOOD_SPAN_H` hours inside the day read — more than one pass's worth
— before it is a card; a burst is held, with why on the decision trail.
And the card's fix offers the reload as brAIn's step, not the owner's.

Driven through the real `summarise_log` over Core's own log lines, with
loggers and shapes the reports did not name: an MQTT broker restarting,
a Ring doorbell polling all day, and Ecobee starting to fail an hour ago.
"""

import datetime as dt
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

from checks import integrations  # noqa: E402
from test_house_checks import NOW, house  # noqa: E402
from test_network_checks import log_line  # noqa: E402

H = 3600
MQTT = "homeassistant.components.mqtt.client"
RING = "homeassistant.components.ring.coordinator"
ECOBEE = "homeassistant.components.ecobee"


def burst(logger, message, start_ago, every_s, n):
    return [log_line(start_ago - i * every_s, logger, message) for i in range(n)]


def snap_with(lines):
    snap = house()
    snap["core_log"] = integrations.summarise_log("\n".join(lines), NOW,
                                                  dt.timezone.utc)
    snap["available"]["core_log"] = True
    snap["_trail"] = []
    return snap


class TestABurstIsNotAFlood(unittest.TestCase):

    def test_a_broker_restart_burst_hours_ago_files_nothing(self):
        snap = snap_with(burst(MQTT, "Disconnected from MQTT server mqtt:1883 (7)",
                               start_ago=5 * H, every_s=4, n=300))
        self.assertEqual(integrations.log_flood(snap, NOW), [])
        [row] = [t for t in snap["_trail"] if t["check"] == "integ.log_flood"]
        self.assertEqual(row["kind"], "transient")
        self.assertTrue(row["reason"])

    def test_a_flood_that_began_an_hour_ago_waits_for_the_next_window(self):
        snap = snap_with(burst(ECOBEE, "Error updating ecobee thermostat: 500",
                               start_ago=1 * H, every_s=20, n=170))
        self.assertEqual(integrations.log_flood(snap, NOW), [])
        self.assertEqual(snap["_trail"][0]["kind"], "transient")

    def test_the_summary_says_when_a_group_began(self):
        snap = snap_with(burst(ECOBEE, "Error updating ecobee thermostat: 500",
                               start_ago=1 * H, every_s=20, n=170))
        [group] = snap["core_log"]["groups"]
        self.assertAlmostEqual(group["first"], NOW - H, delta=1)


class TestAFloodThatPersistsIsFiled(unittest.TestCase):

    def setUp(self):
        self.snap = snap_with(burst(RING, "Error fetching ring devices data: 429",
                                    start_ago=20 * H, every_s=420, n=171))

    def test_all_day_and_still_going_is_a_card(self):
        [row] = integrations.log_flood(self.snap, NOW)
        self.assertIn("Ring", row["text"])

    def test_its_fix_offers_the_reload_as_brains(self):
        [row] = integrations.log_flood(self.snap, NOW)
        for sentence in row["fix"].split(". "):
            if "reload" in sentence.lower():
                self.assertIn("brAIn", sentence, row["fix"])


if __name__ == "__main__":
    unittest.main()
