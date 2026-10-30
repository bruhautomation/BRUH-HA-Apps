#!/usr/bin/env python3
"""`net.zigbee_weak` cites each router's own link and its own two days."""

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import checks  # noqa: E402
from test_house_checks import NOW, house, iso  # noqa: E402
from test_network_checks import zha  # noqa: E402

network = checks.network
HOUR = 3600


def build(*rows):
    snap = house()
    for i, row in enumerate(rows):
        dev = f"dev-zr{i}"
        snap["devices"].append({"id": dev, "name": row["name"]})
        snap["entities"].append({"entity_id": f"light.zr_{i}",
                                 "platform": "zha", "device_id": dev})
        row["device_reg_id"] = dev
    snap["zha_devices"] = list(rows)
    return snap


def series(*points):
    return [{"state": st, "last_changed": iso(ago * HOUR)}
            for ago, st in points]


class TestZigbeeWeakHistory(unittest.TestCase):
    def test_each_card_cites_its_own_device_link_and_dropouts(self):
        snap = build(zha("Cellar plug", lqi=12), zha("Attic plug", lqi=33))
        snap["zigbee_history"] = {"hours": 48, "entities": {
            "light.zr_0": series((40, "on"), (30, "unavailable"), (29, "on")),
            "light.zr_1": series((40, "on"), (6, "unavailable"), (5, "on"),
                                 (3, "unavailable"), (2, "on"))}}
        rows = {r["entity_id"]: r for r in network.zigbee_weak(snap, NOW)}
        self.assertEqual(set(rows), {"light.zr_0", "light.zr_1"})
        self.assertIn("Cellar plug", rows["light.zr_0"]["text"])
        self.assertIn("12 out of 255", rows["light.zr_0"]["detail"])
        self.assertIn("1 time", rows["light.zr_0"]["detail"])
        self.assertIn("Attic plug", rows["light.zr_1"]["text"])
        self.assertIn("33 out of 255", rows["light.zr_1"]["detail"])
        self.assertIn("2 times", rows["light.zr_1"]["detail"])
        self.assertNotEqual(rows["light.zr_0"]["detail"],
                            rows["light.zr_1"]["detail"])

    def test_a_router_with_no_dropouts_in_two_days_is_not_filed(self):
        snap = build(zha("Cellar plug", lqi=12), zha("Attic plug", lqi=33))
        snap["zigbee_history"] = {"hours": 48, "entities": {
            "light.zr_0": series((47, "on")),
            # a drop three days ago is outside the window
            "light.zr_1": series((80, "unavailable"), (75, "on"))}}
        self.assertEqual(network.zigbee_weak(snap, NOW), [])

    def test_no_history_goes_on_the_live_reading(self):
        snap = build(zha("Cellar plug", lqi=12))
        self.assertEqual(len(network.zigbee_weak(snap, NOW)), 1)

    def test_the_collector_asks_for_plugged_in_devices_only(self):
        snap = build(zha("Cellar plug", lqi=12),
                     zha("Hall button", lqi=12, power="Battery",
                         kind="EndDevice"))
        self.assertEqual(network.zigbee_history_candidates(snap),
                         ["light.zr_0"])


if __name__ == "__main__":
    unittest.main()
