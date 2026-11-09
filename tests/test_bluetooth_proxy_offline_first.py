#!/usr/bin/env python3
"""A faint Bluetooth device beside a proxy that is offline: bring it back (#770).

`net.bluetooth_faint` told the owner to add an ESPHome Bluetooth proxy near
a device while the house already had one in that room, offline. Before it
suggests new hardware the check lists the house's proxies (an ESPHome
device carrying a Bluetooth address) and whether each answers. Devices
heard faintly in the room of an offline proxy are one cause: one row about
the proxy, naming them, whose step is to bring the proxy back. A faint
device elsewhere is told about an offline proxy before any new one.

The second examples are ones the report never named: an offline proxy
with no room set, and a house whose proxies all answer.
"""
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

from checks import network  # noqa: E402
from test_house_checks import NOW, house  # noqa: E402


def ble_house():
    snap = house()
    snap["config_entries"] += [
        {"entry_id": "e-bt", "domain": "bluetooth", "title": "Bluetooth",
         "state": "loaded", "source": "user"},
        {"entry_id": "e-esp-g", "domain": "esphome", "title": "Garage proxy",
         "state": "loaded", "source": "user"},
        {"entry_id": "e-esp-k", "domain": "esphome", "title": "Kitchen proxy",
         "state": "loaded", "source": "user"}]
    snap["areas"].append({"area_id": "garage", "name": "Garage"})
    snap["bluetooth"] = {"rssi": {}}
    return snap


def proxy(snap, dev_id, name, area, up, mac):
    snap["devices"].append({
        "id": dev_id, "name": name, "area_id": area,
        "config_entries": [f"e-esp-{dev_id[-1]}"],
        "connections": [["mac", mac], ["bluetooth", mac]]})
    eid = f"sensor.{name.lower().replace(' ', '_')}_status"
    snap["entities"].append({"entity_id": eid, "device_id": dev_id,
                             "platform": "esphome"})
    snap["states"][eid] = {"state": "on" if up else "unavailable",
                           "attributes": {"friendly_name": f"{name} status"}}


def faint(snap, dev_id, name, area, mac, rssi=-95):
    snap["devices"].append({"id": dev_id, "name": name, "area_id": area,
                            "connections": [["bluetooth", mac]]})
    eid = f"sensor.{name.lower().replace(' ', '_')}"
    snap["entities"].append({"entity_id": eid, "device_id": dev_id,
                             "platform": "xiaomi_ble"})
    snap["states"][eid] = {"state": "4", "attributes": {"friendly_name": name}}
    snap["bluetooth"]["rssi"][mac.lower()] = rssi
    return eid


def the_house(garage_area="garage", garage_up=False):
    snap = ble_house()
    proxy(snap, "dev-g", "Garage proxy", garage_area, garage_up,
          "AA:00:00:00:00:0G")
    proxy(snap, "dev-k", "Kitchen proxy", "kitchen", True, "AA:00:00:00:00:0K")
    freezer = faint(snap, "dev-f", "Freezer thermometer", "garage",
                    "BB:00:00:00:00:01")
    bike = faint(snap, "dev-b", "Bike tag", "garage", "BB:00:00:00:00:02")
    return snap, freezer, bike


class TestTwoDevicesBesideAnOfflineProxy(unittest.TestCase):
    def test_one_row_about_the_proxy_naming_both(self):
        snap, freezer, bike = the_house()
        [row] = network.bluetooth_faint(snap, NOW)
        self.assertIn("Garage proxy", row["text"])
        self.assertEqual(sorted(row["items"]), sorted([freezer, bike]))
        said = row["detail"] + " " + row["fix"]
        self.assertIn("Freezer thermometer", said)
        self.assertIn("Bike tag", said)
        self.assertIn("Garage proxy", row["fix"])
        self.assertNotIn("add a proxy", row["fix"].lower())
        self.assertNotIn("sensor.", said)

    def test_the_proxy_itself_is_not_a_faint_device(self):
        snap, _f, _b = the_house()
        snap["bluetooth"]["rssi"]["aa:00:00:00:00:0g"] = -99
        rows = network.bluetooth_faint(snap, NOW)
        self.assertEqual(len(rows), 1)


class TestAnOfflineProxyWithNoRoom(unittest.TestCase):
    def test_each_faint_device_is_told_to_bring_it_back_first(self):
        snap, _f, _b = the_house(garage_area=None)
        rows = network.bluetooth_faint(snap, NOW)
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertIn("Garage proxy", row["fix"])
            self.assertIn("first", row["fix"])
            self.assertIn("Garage proxy (offline)", row["detail"])


class TestEveryProxyAnswers(unittest.TestCase):
    def test_the_proxies_are_listed_and_a_new_one_may_be_suggested(self):
        snap, _f, _b = the_house(garage_up=True)
        rows = network.bluetooth_faint(snap, NOW)
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertIn("Garage proxy (answering)", row["detail"])
            self.assertIn("Kitchen proxy (answering)", row["detail"])
            self.assertNotIn("first", row["fix"])


if __name__ == "__main__":
    unittest.main()
