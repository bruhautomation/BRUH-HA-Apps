#!/usr/bin/env python3
"""Every device dropping off the network is ONE card, kept up to date.

The owner got a card per device from `net.wifi_flapping`, `net.zwave_silent`,
`net.zigbee_silent`, `net.wifi_hung` and `net.unifi_dropped`, most of them
from failures that had passed. Those producers are one check now,
`net.connectivity`: one row with one stable text, so the store's own
machinery keeps it in place — `add_many` dedupes it, `refresh_details`
rewrites what it lists, `items` carry the devices so a Wrong answers each
of them and a device that turns up later is not swallowed by that answer,
and `clear_resolved` takes it off when nothing is left. A device is listed
only once it has been gone for hours or has dropped again and again
recently; a phone or a tracker is never listed; and a moment many devices
went at once is the house restarting or the network, not the devices.

The examples are a Zigbee bulb and a Z-Wave leak sensor beside a Wi-Fi
plug, a phone on Wi-Fi, and a coordinator restart — not the reports' own.
"""

import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import checks  # noqa: E402
import findings_store  # noqa: E402
from test_house_checks import DAY, NOW, house, iso  # noqa: E402
from test_network_checks import (add_ap, add_client, flaps,  # noqa: E402
                                 series, zha)

network = checks.network
H = 3600


def zigbee(snap, name, i, *, seen, power="Mains", kind="Router"):
    dev = f"dev-zbc{i}"
    snap["devices"].append({"id": dev, "name": name})
    eid = f"light.zbc_{i}"
    snap["entities"].append({"entity_id": eid, "platform": "zha",
                             "device_id": dev})
    row = zha(name, seen=seen, power=power, kind=kind, reg=dev)
    row["ieee"] = f"00:11:22:33:44:55:66:{i:02x}"
    snap.setdefault("zha_devices", []).append(row)
    snap["available"]["zha_devices"] = True
    return eid


def leak_node(snap, last_seen_ago):
    snap["devices"].append({"id": "dev-leak", "name": "Utility leak sensor",
                            "identifiers": [["zwave_js", "1-9"]]})
    snap["entities"].append({"entity_id": "sensor.leak_node_status",
                             "platform": "zwave_js", "device_id": "dev-leak",
                             "translation_key": "node_status"})
    snap["states"]["sensor.leak_node_status"] = {
        "state": "asleep", "attributes": {}, "last_changed": iso(600)}
    snap["zwave_nodes"] = {"dev-leak": {
        "status": {"status": 1, "is_controller_node": False},
        "statistics": {"last_seen": iso(last_seen_ago), "commands_tx": 40}}}
    snap["available"]["zwave_nodes"] = True
    return "sensor.leak_node_status"


def flapping_plug(snap, start_ago):
    add_ap(snap)
    for n in (1, 2, 3):
        add_client(snap, n, down_for=0)
    hist = {}
    for n in (1, 2, 3):
        changes = flaps(12, start_ago=start_ago) if n == 1 else [(6.5 * DAY, "on")]
        hist[f"switch.plug_{n}"] = series(f"switch.plug_{n}", changes)
        hist[f"device_tracker.plug_{n}_client"] = series(
            f"device_tracker.plug_{n}_client", [(6.5 * DAY, "home")])
    snap["wifi_history"] = {"days": 7, "entities": hist}
    snap["available"]["wifi_history"] = True


def three_down():
    snap = house()
    bulb = zigbee(snap, "Hall pendant", 0, seen=9 * H)
    for i in range(1, 6):
        zigbee(snap, f"Fine bulb {i}", i, seen=120)
    leak = leak_node(snap, 3 * DAY)
    flapping_plug(snap, start_ago=40 * H)
    return snap, bulb, leak


def back(snap, name):
    """The Zigbee device called ``name`` talks again."""
    [row] = [d for d in snap["zha_devices"] if d.get("name") == name]
    row["last_seen"] = iso(60)


def card(snap):
    rows = network.connectivity(snap, NOW)
    return rows[0] if rows else None


class TestOneCard(unittest.TestCase):

    def test_three_networks_three_devices_one_row(self):
        snap, bulb, leak = three_down()
        result = checks.run_all(snap, NOW)
        drops = [f for f in result["findings"] if f["source"] in (
            "check:net.connectivity", "check:net.wifi_flapping",
            "check:net.zwave_silent", "check:net.zigbee_silent",
            "check:net.wifi_hung", "check:net.unifi_dropped")]
        self.assertEqual(len(drops), 1, drops)
        [row] = drops
        self.assertEqual(row["source"], "check:net.connectivity")
        self.assertEqual(sorted(row["items"]),
                         sorted([bulb, leak, "switch.plug_1"]))
        for name in ("Hall pendant", "Utility leak sensor", "Plug 1"):
            self.assertIn(name, row["detail"])
        self.assertNotIn("Fine bulb", row["detail"])

    def test_the_old_per_device_checks_are_gone(self):
        ids = {c["id"] for c in checks.CHECKS}
        self.assertIn("net.connectivity", ids)
        for gone in ("net.wifi_flapping", "net.zwave_silent",
                     "net.zigbee_silent", "net.wifi_hung", "net.unifi_dropped"):
            self.assertNotIn(gone, ids)

    def test_its_rows_still_fold_as_drop_reports(self):
        self.assertIn("check:net.connectivity", findings_store.DROP_CHECKS)


class TestWhoIsListed(unittest.TestCase):

    def test_minutes_gone_is_not_listed(self):
        snap = house()
        zigbee(snap, "Hall pendant", 0, seen=20 * 60)
        for i in range(1, 6):
            zigbee(snap, f"Fine bulb {i}", i, seen=120)
        self.assertIsNone(card(snap))

    def test_drops_that_stopped_days_ago_are_old_news(self):
        snap = house()
        flapping_plug(snap, start_ago=6 * DAY)     # last drop ~4.6 days ago
        self.assertIsNone(card(snap))

    def test_a_phone_is_never_listed(self):
        snap = house()
        add_ap(snap)
        switch, _tracker = add_client(snap, 7, platform="mobile_app")
        snap["states"][switch]["attributes"]["friendly_name"] = "Ana's phone"
        self.assertIsNone(card(snap))

    def test_a_coordinator_restart_is_not_six_devices(self):
        snap = house()
        for i in range(6):
            zigbee(snap, f"Bulb {i}", i, seen=8 * H)
        self.assertIsNone(card(snap))
        self.assertTrue(any(t["check"] == "net.connectivity"
                            for t in checks.run_all(snap, NOW)["withheld"]))

    def test_a_wrong_given_to_the_old_check_still_stands(self):
        snap = house()
        bulb = zigbee(snap, "Hall pendant", 0, seen=9 * H)
        for i in range(1, 6):
            zigbee(snap, f"Fine bulb {i}", i, seen=120)
        snap["facts"] = {bulb: {"net.zigbee_silent"}}
        self.assertIsNone(card(snap))
        snap["facts"] = {bulb: {"net.connectivity"}}
        self.assertIsNone(card(snap))

    def test_a_house_without_zwave_still_runs_it(self):
        snap = house()
        zigbee(snap, "Hall pendant", 0, seen=9 * H)
        for i in range(1, 6):
            zigbee(snap, f"Fine bulb {i}", i, seen=120)
        snap["available"]["zwave_nodes"] = False
        snap["available"]["wifi_history"] = False
        result = checks.run_all(snap, NOW)
        self.assertIn("net.connectivity", result["ran"])

    def test_an_unreadable_mesh_the_house_has_is_could_not_look(self):
        snap, _bulb, _leak = three_down()
        snap["available"]["zha_devices"] = False
        result = checks.run_all(snap, NOW)
        self.assertIn("net.connectivity", result["skipped"])


class TestKeptUpToDateInPlace(unittest.TestCase):
    """Through the real store, the way the checks pass files."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self._old = (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
                     findings_store.STATE_FILE)
        findings_store.FINDINGS_FILE = root / "findings.json"
        findings_store.SETTLED_FILE = root / "settled.json"
        findings_store.STATE_FILE = root / "nowhere" / ".brain" / "s.json"

    def tearDown(self):
        (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
         findings_store.STATE_FILE) = self._old
        self.tmp.cleanup()

    def file(self, snap):
        result = checks.run_all(snap, NOW)
        found = result["findings"]
        created = findings_store.add_many(found)
        findings_store.refresh_details(found)
        findings_store.clear_resolved(
            checks.sources_ran(result["ran"]),
            {findings_store.normalize(f["text"]) for f in found})
        return created

    def drops(self):
        return [f for f in findings_store.list_all()
                if f.get("source") == "check:net.connectivity"]

    def test_a_device_coming_back_updates_the_one_row(self):
        snap, bulb, leak = three_down()
        self.file(snap)
        [first] = self.drops()
        # The bulb comes back.
        back(snap, "Hall pendant")
        self.assertEqual([f for f in self.file(snap)
                          if f["source"] == "check:net.connectivity"], [],
                         "nothing new is filed")
        [row] = self.drops()
        self.assertEqual(row["ts"], first["ts"], "the same row, in place")
        self.assertEqual(row["text"], first["text"])
        self.assertNotIn(bulb, row.get("items") or [])
        self.assertNotIn("Hall pendant", row["detail"])
        self.assertIn("Utility leak sensor", row["detail"])
        # What the card shows under Details follows what it lists.
        self.assertNotIn(bulb, [e["entity"] for e in row.get("evidence") or []])

    def test_it_clears_when_nothing_is_left(self):
        snap, _bulb, _leak = three_down()
        self.file(snap)
        back(snap, "Hall pendant")
        snap["zwave_nodes"]["dev-leak"]["statistics"]["last_seen"] = iso(60)
        snap["wifi_history"]["entities"]["switch.plug_1"] = series(
            "switch.plug_1", [(6.5 * DAY, "on")])
        self.file(snap)
        self.assertEqual(self.drops(), [])

    def test_a_retired_checks_row_clears_when_the_new_check_runs(self):
        findings_store.add_many([{
            "text": "Plug 9 keeps dropping off the network", "detail": "x",
            "severity": "warning", "source": "check:net.wifi_flapping",
            "source_title": "Network (Wi-Fi)", "entity_id": "switch.plug_9"}])
        snap = house()
        self.file(snap)
        self.assertEqual([f for f in findings_store.list_all()
                          if f.get("source") == "check:net.wifi_flapping"], [])


if __name__ == "__main__":
    unittest.main()
