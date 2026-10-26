#!/usr/bin/env python3
"""The network and integrations checks — the owner's three standing asks.

* Wi-Fi (UniFi): a device UniFi still holds while its own entities are
  gone (grouped by access point), a device that keeps dropping, and the
  integration itself dropping every tracker at once — never counted as a
  device's drop, and never a restart.
* Z-Wave and Zigbee: a battery node silent past its wake-ups (off Z-Wave
  JS's own "last seen", never `last_changed`), a weak link, a weak Zigbee
  router and a Zigbee device quiet for hours — one device under one check.
* Integrations: an entry stuck for a day, a battery from any integration
  and a logger repeating an error.

Each is driven over the healthy house `test_house_checks` builds, with
the defect planted, and with the stand-down that must hold.
"""

import datetime as dt
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import checks  # noqa: E402
from test_house_checks import DAY, NOW, house, iso  # noqa: E402

network = checks.network
integrations = checks.integrations
devices = checks.devices
system = checks.system

AP_MAC = "aa:aa:aa:00:00:01"
AP2_MAC = "aa:aa:aa:00:00:02"


def add_ap(snap, mac=AP_MAC, name="Garage access point", dev_id="dev-ap1"):
    snap["devices"].append({"id": dev_id, "name": name,
                            "connections": [["mac", mac]]})
    eid = f"device_tracker.{dev_id.replace('-', '_')}"
    snap["entities"].append({"entity_id": eid, "platform": "unifi",
                             "device_id": dev_id})
    snap["states"][eid] = {"state": "home",
                           "attributes": {"friendly_name": name, "mac": mac},
                           "last_changed": iso(DAY)}
    return eid


def add_client(snap, n, *, ap=AP_MAC, down_for=5 * 3600, tracker="home",
               platform="shelly", radio="ng", device_state=None):
    """A plug on Wi-Fi: its own switch (another integration) and UniFi's
    tracker, joined on one device by its MAC connection."""
    mac = f"bb:bb:bb:00:00:{n:02x}"
    dev = f"dev-plug{n}"
    snap["devices"].append({"id": dev, "name": f"Plug {n}",
                            "connections": [["mac", mac]]})
    switch = f"switch.plug_{n}"
    tracker_id = f"device_tracker.plug_{n}_client"
    snap["entities"] += [
        {"entity_id": switch, "platform": platform, "device_id": dev},
        {"entity_id": tracker_id, "platform": "unifi", "device_id": dev}]
    snap["states"][switch] = {
        "state": device_state or ("unavailable" if down_for else "on"),
        "attributes": {"friendly_name": f"Plug {n}"},
        "last_changed": iso(down_for or 600)}
    snap["states"][tracker_id] = {
        "state": tracker,
        "attributes": {"friendly_name": f"Plug {n}", "mac": mac,
                       "ap_mac": ap, "essid": "House", "is_wired": False,
                       "radio": radio, "ip": f"10.0.0.{n}"},
        "last_changed": iso(DAY)}
    return switch, tracker_id


class TestHungAssociation(unittest.TestCase):
    def test_four_hung_on_one_access_point_are_one_row_naming_it(self):
        snap = house()
        add_ap(snap)
        for n in range(1, 5):
            add_client(snap, n)
        rows = network.wifi_hung(snap, NOW)
        self.assertEqual(len(rows), 1, rows)
        row = rows[0]
        self.assertIn("Garage access point", row["text"])
        for n in range(1, 5):
            self.assertIn(f"Plug {n}", row["detail"])
        self.assertIn("2.4 GHz", row["detail"])
        self.assertEqual(row["entity_id"], "device_tracker.dev_ap1")

    def test_through_run_all_it_is_a_wifi_finding(self):
        snap = house()
        add_ap(snap)
        add_client(snap, 1)
        result = checks.run_all(snap, NOW)
        rows = [f for f in result["findings"]
                if f["source"] == "check:net.wifi_hung"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_title"], "Network (Wi-Fi)")

    def test_dev_unavailable_stands_down_for_a_hung_device(self):
        snap = house()
        add_ap(snap)
        add_client(snap, 1, down_for=3 * DAY)
        self.assertEqual(devices.unavailable(snap, NOW), [])
        self.assertEqual(len(network.wifi_hung(snap, NOW)), 1)

    def test_healthy_left_and_fresh_say_nothing(self):
        snap = house()
        add_ap(snap)
        add_client(snap, 1, down_for=0)               # answering
        add_client(snap, 2, tracker="not_home")       # really gone
        add_client(snap, 3, down_for=1800)            # only half an hour
        self.assertEqual(network.wifi_hung(snap, NOW), [])

    def test_an_integration_down_everywhere_is_the_integration(self):
        snap = house()
        add_ap(snap)
        add_ap(snap, AP2_MAC, "Lounge access point", "dev-ap2")
        add_client(snap, 1)
        add_client(snap, 2)
        add_client(snap, 3, ap=AP2_MAC)
        self.assertEqual(network.wifi_hung(snap, NOW), [])

    def test_a_wrong_on_the_client_stands_it_down(self):
        snap = house()
        add_ap(snap)
        _sw, tracker = add_client(snap, 1)
        snap["facts"] = {tracker: {"net.wifi_hung"}}
        self.assertEqual(network.wifi_hung(snap, NOW), [])

    def test_a_client_named_by_its_address_is_not_spelled_out(self):
        snap = house()
        add_ap(snap)
        add_client(snap, 1)
        snap["devices"][-1]["name"] = "bb:bb:bb:00:00:01"
        row = network.wifi_hung(snap, NOW)[0]
        self.assertNotIn("bb:bb:bb", row["detail"])
        self.assertIn("A device with no name", row["detail"])

    def test_a_device_labelled_not_in_use_says_nothing(self):
        snap = house()
        add_ap(snap)
        add_client(snap, 1)
        snap["devices"][-1]["labels"] = ["not_in_use"]
        self.assertEqual(network.wifi_hung(snap, NOW), [])


def series(eid, changes):
    """A minimal-response history series: `[(seconds_ago, state), ...]`."""
    rows = []
    for i, (ago, state) in enumerate(sorted(changes, key=lambda c: -c[0])):
        row = {"state": state, "last_changed": iso(ago)}
        if i == 0:
            row["entity_id"] = eid
        rows.append(row)
    return rows


def flaps(n, start_ago=6 * DAY, step=3 * 3600):
    out = [(start_ago + 600, "on")]
    for i in range(n):
        t = start_ago - i * step
        out += [(t, "unavailable"), (t - 300, "on")]
    return out


class TestFlapping(unittest.TestCase):
    def wifi_house(self, plug1_changes, mass=0):
        snap = house()
        add_ap(snap)
        for n in (1, 2, 3):
            add_client(snap, n, down_for=0)
        hist = {}
        for n in (1, 2, 3):
            changes = list(plug1_changes) if n == 1 else [(6.5 * DAY, "on")]
            tracker = [(6.5 * DAY, "home")]
            for k in range(mass):
                # Home Assistant restarting: every entity, every tracker.
                t = 2 * DAY - k * 3600
                changes += [(t, "unavailable"), (t - 60, "on")]
                tracker += [(t, "unavailable"), (t - 60, "home")]
            hist[f"switch.plug_{n}"] = series(f"switch.plug_{n}", changes)
            hist[f"device_tracker.plug_{n}_client"] = series(
                f"device_tracker.plug_{n}_client", tracker)
        snap["wifi_history"] = {"days": 7, "entities": hist}
        snap["available"]["wifi_history"] = True
        return snap

    def test_twelve_drops_with_the_tracker_home_is_a_row(self):
        snap = self.wifi_house(flaps(12))
        rows = network.wifi_flapping(snap, NOW)
        self.assertEqual(len(rows), 1, rows)
        self.assertIn("Plug 1", rows[0]["text"])
        self.assertIn("12 separate times", rows[0]["detail"])
        self.assertEqual(rows[0]["entity_id"], "switch.plug_1")

    def test_restart_minutes_are_not_counted(self):
        snap = self.wifi_house(flaps(8), mass=5)
        self.assertEqual(network.wifi_flapping(snap, NOW), [])
        # And they are a restart, so not UniFi's row either.
        self.assertEqual(network.unifi_dropped(snap, NOW), [])

    def test_a_tracker_that_left_is_not_flapping(self):
        snap = self.wifi_house(flaps(12))
        rows = snap["wifi_history"]["entities"]["device_tracker.plug_1_client"]
        rows.append({"state": "not_home", "last_changed": iso(3 * DAY)})
        self.assertEqual(network.wifi_flapping(snap, NOW), [])

    def test_the_candidates_are_one_probe_and_the_tracker(self):
        snap = self.wifi_house(flaps(1))
        cands = network.wifi_history_candidates(snap)
        self.assertEqual({c["probe"] for c in cands},
                         {"switch.plug_1", "switch.plug_2", "switch.plug_3"})

    def test_unifi_dropping_every_tracker_is_its_own_single_row(self):
        snap = self.wifi_house(flaps(0))
        for n in (1, 2, 3):
            tracker = [(6.5 * DAY, "home")]
            for k in range(4):
                t = 3 * DAY - k * 7200
                tracker += [(t, "unavailable"), (t - 120, "home")]
            snap["wifi_history"]["entities"][
                f"device_tracker.plug_{n}_client"] = series(
                f"device_tracker.plug_{n}_client", tracker)
        rows = network.unifi_dropped(snap, NOW)
        self.assertEqual(len(rows), 1, rows)
        self.assertIn("4 times", rows[0]["detail"])
        self.assertEqual(network.wifi_flapping(snap, NOW), [])


def zwave_house(**node):
    snap = house()
    snap["devices"].append({"id": "dev-zw1", "name": "Shed door sensor",
                            "identifiers": [["zwave_js", "1-7"]]})
    snap["entities"].append({"entity_id": "sensor.shed_door_node_status",
                             "platform": "zwave_js", "device_id": "dev-zw1",
                             "translation_key": "node_status"})
    snap["states"]["sensor.shed_door_node_status"] = {
        "state": "asleep", "attributes": {}, "last_changed": iso(600)}
    entry = {"status": {"status": 1, "is_controller_node": False},
             "statistics": {"last_seen": iso(4 * DAY), "commands_tx": 40,
                            "rssi": -70, "rtt": 40}}
    for key, value in node.items():
        entry[key].update(value)
    snap["zwave_nodes"] = {"dev-zw1": entry}
    snap["available"]["zwave_nodes"] = True
    return snap


class TestZWave(unittest.TestCase):
    def test_a_battery_node_silent_for_days_is_raised_unasked(self):
        snap = zwave_house()
        result = checks.run_all(snap, NOW)
        rows = [f for f in result["findings"]
                if f["source"] == "check:net.zwave_silent"]
        self.assertEqual(len(rows), 1, result["findings"])
        self.assertIn("Shed door sensor", rows[0]["text"])
        self.assertEqual(rows[0]["source_title"], "Network (Z-Wave)")

    def test_three_wake_intervals_is_the_bar_when_it_is_known(self):
        snap = zwave_house(status={"wake_up_interval": 3600},
                           statistics={"last_seen": iso(4 * 3600)})
        self.assertEqual(len(network.zwave_silent(snap, NOW)), 1)
        snap = zwave_house(status={"wake_up_interval": 3600},
                           statistics={"last_seen": iso(2.5 * 3600)})
        self.assertEqual(network.zwave_silent(snap, NOW), [])

    def test_a_restart_does_not_hide_it_and_last_changed_is_never_read(self):
        # The node status sensor changed ten minutes ago (a restart), and
        # Z-Wave JS's own record still says four days.
        snap = zwave_house()
        self.assertEqual(len(network.zwave_silent(snap, NOW)), 1)
        # No "last seen" anywhere: could not tell, so nothing.
        snap = zwave_house(statistics={"last_seen": None})
        self.assertEqual(network.zwave_silent(snap, NOW), [])

    def test_disabled_labelled_and_dead_nodes_are_not_raised(self):
        snap = zwave_house()
        snap["devices"][-1]["disabled_by"] = "user"
        self.assertEqual(network.zwave_silent(snap, NOW), [])
        snap = zwave_house()
        snap["devices"][-1]["labels"] = ["spare"]
        self.assertEqual(network.zwave_silent(snap, NOW), [])
        snap = zwave_house()
        snap["labels"] = [{"label_id": "lbl1", "name": "Not in use"}]
        snap["devices"][-1]["labels"] = ["lbl1"]
        self.assertEqual(network.zwave_silent(snap, NOW), [])
        snap = zwave_house(status={"status": 3})
        self.assertEqual(network.zwave_silent(snap, NOW), [])

    def test_a_weak_link_is_raised_and_no_reading_is_not(self):
        snap = zwave_house(status={"status": 4},
                           statistics={"last_seen": iso(60), "rssi": -94})
        rows = network.zwave_link(snap, NOW)
        self.assertEqual(len(rows), 1)
        self.assertIn("-94 dBm", rows[0]["detail"])
        snap = zwave_house(status={"status": 4},
                           statistics={"last_seen": iso(60), "rssi": 127,
                                       "rtt": 210})
        rows = network.zwave_link(snap, NOW)
        self.assertEqual(len(rows), 1)
        self.assertIn("210 ms", rows[0]["detail"])
        snap = zwave_house(status={"status": 4},
                           statistics={"last_seen": iso(60), "rssi": 127})
        self.assertEqual(network.zwave_link(snap, NOW), [])

    def test_battery_low_stands_down_for_a_silent_node(self):
        snap = zwave_house()
        snap["entities"].append({"entity_id": "sensor.shed_door_battery",
                                 "platform": "zwave_js",
                                 "device_id": "dev-zw1"})
        snap["states"]["sensor.shed_door_battery"] = {
            "state": "5", "attributes": {"device_class": "battery",
                                         "unit_of_measurement": "%"},
            "last_updated": iso(4 * DAY), "last_reported": iso(4 * DAY)}
        self.assertEqual(devices.battery_low(snap, NOW), [])


def zha(name, *, lqi=200, seen=60, power="Mains", kind="Router", reg=None):
    return {"name": name, "ieee": "00:11:22:33:44:55:66:77", "lqi": lqi,
            "available": True, "last_seen": iso(seen),
            "power_source": power, "device_type": kind,
            "device_reg_id": reg}


class TestZigbee(unittest.TestCase):
    def zha_house(self, *rows):
        snap = house()
        for i, row in enumerate(rows):
            dev = f"dev-zb{i}"
            snap["devices"].append({"id": dev, "name": row["name"]})
            snap["entities"].append({"entity_id": f"light.zb_{i}",
                                     "platform": "zha", "device_id": dev})
            row["device_reg_id"] = dev
        snap["zha_devices"] = list(rows)
        return snap

    def test_a_weak_router_is_raised_unasked(self):
        snap = self.zha_house(zha("Landing plug", lqi=30))
        result = checks.run_all(snap, NOW)
        rows = [f for f in result["findings"]
                if f["source"] == "check:net.zigbee_weak"]
        self.assertEqual(len(rows), 1, result["findings"])
        self.assertEqual(rows[0]["source_title"], "Network (Zigbee)")
        self.assertIn("30 out of 255", rows[0]["detail"])

    def test_a_strong_router_and_an_end_device_say_nothing(self):
        snap = self.zha_house(zha("Landing plug", lqi=120),
                              zha("Hall button", lqi=20, power="Battery",
                                  kind="EndDevice"))
        self.assertEqual(network.zigbee_weak(snap, NOW), [])

    def test_quiet_by_power_source(self):
        snap = self.zha_house(zha("Landing plug", seen=8 * 3600),
                              zha("Hall button", seen=10 * 3600,
                                  power="Battery", kind="EndDevice"),
                              zha("Porch button", seen=30 * 3600,
                                  power="Battery", kind="EndDevice"))
        names = sorted(r["text"] for r in network.zigbee_silent(snap, NOW))
        self.assertEqual(len(names), 2, names)
        self.assertTrue(names[0].startswith("Landing plug"))
        self.assertTrue(names[1].startswith("Porch button"))

    def test_a_week_is_zha_unseen_and_never_both(self):
        snap = self.zha_house(zha("Porch button", seen=8 * DAY,
                                  power="Battery", kind="EndDevice"))
        self.assertEqual(network.zigbee_silent(snap, NOW), [])
        self.assertEqual(len(devices.zha_unseen(snap, NOW)), 1)

    def test_dev_unavailable_stands_down_for_a_quiet_zigbee_device(self):
        snap = self.zha_house(zha("Landing plug", seen=2 * DAY))
        snap["states"]["light.zb_0"] = {"state": "unavailable",
                                        "attributes": {},
                                        "last_changed": iso(2 * DAY)}
        self.assertEqual(devices.unavailable(snap, NOW), [])
        self.assertEqual(len(network.zigbee_silent(snap, NOW)), 1)

    def test_a_disabled_or_spare_device_says_nothing(self):
        snap = self.zha_house(zha("Landing plug", lqi=30))
        snap["devices"][-1]["disabled_by"] = "user"
        self.assertEqual(network.zigbee_weak(snap, NOW), [])
        snap = self.zha_house(zha("Landing plug", lqi=30))
        snap["devices"][-1]["labels"] = ["in_storage"]
        self.assertEqual(network.zigbee_weak(snap, NOW), [])


class TestEntriesStuckForADay(unittest.TestCase):
    def failing(self, since):
        snap = house()
        entry = {"entry_id": "e9", "domain": "roku", "title": "Living room TV",
                 "state": "setup_retry", "source": "user",
                 "reason": "Connection refused"}
        if since is not None:
            entry["failing_since"] = since
        snap["config_entries"].append(entry)
        return snap

    def test_the_day_floor_holds(self):
        self.assertEqual(system.entry_failed(self.failing(NOW - 7200), NOW), [])
        rows = system.entry_failed(self.failing(NOW - 30 * 3600), NOW)
        self.assertEqual(len(rows), 1)
        result = checks.run_all(self.failing(NOW - 30 * 3600), NOW)
        row = [f for f in result["findings"]
               if f["source"] == "check:sys.entry_failed"][0]
        self.assertEqual(row["source_title"], "Integrations")

    def test_the_ledger_stamps_a_new_failure_now_and_keeps_an_old_one(self):
        entries = [{"entry_id": "a", "state": "setup_retry"},
                   {"entry_id": "b", "state": "loaded"},
                   {"entry_id": "c", "state": "setup_error"}]
        ledger = system.stamp_failing(entries, {"a": NOW - DAY * 3}, NOW)
        self.assertEqual(ledger, {"a": NOW - DAY * 3, "c": NOW})
        self.assertEqual(entries[2]["failing_since"], NOW)
        self.assertNotIn("failing_since", entries[1])

    def test_the_first_pass_does_not_restart_the_clock_on_old_failures(self):
        entries = [{"entry_id": "a", "state": "setup_retry"},
                   {"entry_id": "c", "state": "setup_error",
                    "created_at": iso(3600)}]
        ledger = system.stamp_failing(entries, None, NOW)
        self.assertEqual(ledger["a"], 0)
        self.assertAlmostEqual(ledger["c"], NOW - 3600, delta=1)

    def test_the_collector_keeps_the_ledger_across_passes(self):
        import tempfile
        snapshot = checks.snapshot
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "ledger.json")
            first = [{"entry_id": "a", "state": "setup_retry"}]
            snapshot._stamp_entries(first, NOW - 2 * DAY, path)
            later = [{"entry_id": "a", "state": "setup_retry"},
                     {"entry_id": "n", "state": "setup_retry"}]
            snapshot._stamp_entries(later, NOW, path)
            self.assertEqual(later[0]["failing_since"], 0)
            self.assertEqual(later[1]["failing_since"], NOW)

    def test_ignored_and_disabled_still_say_nothing(self):
        snap = house()
        snap["config_entries"] += [
            {"entry_id": "x1", "domain": "roku", "title": "Roku",
             "state": "setup_retry", "source": "ignore", "failing_since": 0},
            {"entry_id": "x2", "domain": "hue", "title": "Hue",
             "state": "setup_error", "disabled_by": "user", "failing_since": 0}]
        self.assertEqual(system.entry_failed(snap, NOW), [])


class TestBatteryFromAnyIntegration(unittest.TestCase):
    def test_a_low_battery_flag_is_a_battery_row(self):
        snap = house()
        snap["devices"].append({"id": "dev-smoke", "name": "Landing smoke alarm"})
        snap["entities"].append({"entity_id": "binary_sensor.landing_battery",
                                 "platform": "nest", "device_id": "dev-smoke"})
        snap["states"]["binary_sensor.landing_battery"] = {
            "state": "on", "attributes": {"device_class": "battery"},
            "last_changed": iso(DAY)}
        rows = devices.battery_low(snap, NOW)
        self.assertEqual([r["text"] for r in rows],
                         ["Landing smoke alarm battery is low"])

    def test_a_flag_beside_a_percentage_is_not_said_twice(self):
        snap = house()
        snap["entities"].append({"entity_id": "binary_sensor.back_door_low",
                                 "platform": "zha", "device_id": "dev-door-1"})
        snap["states"]["binary_sensor.back_door_low"] = {
            "state": "on", "attributes": {"device_class": "battery"},
            "last_changed": iso(DAY)}
        self.assertEqual(devices.battery_low(snap, NOW), [])

    def test_a_flag_that_is_off_or_answered_wrong_says_nothing(self):
        snap = house()
        snap["entities"].append({"entity_id": "binary_sensor.lock_battery",
                                 "platform": "august", "device_id": "dev-lock"})
        snap["devices"].append({"id": "dev-lock", "name": "Front lock"})
        snap["states"]["binary_sensor.lock_battery"] = {
            "state": "off", "attributes": {"device_class": "battery"},
            "last_changed": iso(DAY)}
        self.assertEqual(devices.battery_low(snap, NOW), [])
        snap["states"]["binary_sensor.lock_battery"]["state"] = "on"
        snap["facts"] = {"binary_sensor.lock_battery": {"dev.battery_low"}}
        self.assertEqual(devices.battery_low(snap, NOW), [])


def log_line(ago, logger, message, level="ERROR"):
    stamp = dt.datetime.fromtimestamp(NOW - ago, tz=dt.timezone.utc)
    return (f"\x1b[31m{stamp:%Y-%m-%d %H:%M:%S}.123 {level} (MainThread) "
            f"[{logger}] {message}\x1b[0m")


class TestLogFlood(unittest.TestCase):
    def logs(self, extra=()):
        lines = []
        for i in range(150):
            lines.append(log_line(60 + i * 300,
                                  "homeassistant.components.shelly.coordinator",
                                  f"Error fetching Plug 1 data from 10.0.0.1: "
                                  f"timed out after {5 + i % 3} s"))
            lines.append("Traceback (most recent call last):")
        for i in range(150):
            lines.append(log_line(60 + i * 300,
                                  "custom_components.brain.bridge",
                                  "brAIn's own trouble"))
        for i in range(50):
            lines.append(log_line(60 + i * 300,
                                  "homeassistant.components.roku",
                                  "Roku went away"))
        for i in range(150):
            lines.append(log_line(2 * DAY + i, "homeassistant.components.hue",
                                  "Old trouble"))
        lines += list(extra)
        return "\n".join(lines)

    def summary(self, text):
        return integrations.summarise_log(text, NOW, dt.timezone.utc)

    def test_the_folding_groups_repeats_and_counts_a_day(self):
        groups = {g["logger"]: g for g in self.summary(self.logs())["groups"]}
        shelly = groups["homeassistant.components.shelly.coordinator"]
        self.assertEqual(shelly["count"], 150)
        self.assertEqual(shelly["domain"], "shelly")
        self.assertIn("an address", shelly["message"])
        self.assertNotIn("\x1b", shelly["message"])
        self.assertNotIn("homeassistant.components.hue", groups)

    def test_a_flooding_integration_is_raised_naming_the_device(self):
        snap = house()
        add_ap(snap)
        add_client(snap, 1, down_for=0)
        snap["core_log"] = self.summary(self.logs())
        snap["available"]["core_log"] = True
        result = checks.run_all(snap, NOW)
        rows = [f for f in result["findings"]
                if f["source"] == "check:integ.log_flood"]
        self.assertEqual(len(rows), 1, rows)
        row = rows[0]
        self.assertEqual(row["source_title"], "Integrations")
        self.assertIn("Shelly", row["text"])
        self.assertIn("150 times", row["detail"])
        self.assertIn("Plug 1", row["detail"])
        # Filed under the logging integration's own entity on that device,
        # never the router's tracker that happened to report the address
        # (#434): a Shelly error is about the Shelly switch.
        self.assertEqual(row["entity_id"], "switch.plug_1")

    def test_a_secret_in_a_message_is_scrubbed(self):
        text = "\n".join(log_line(60 + i, "homeassistant.components.foo",
                                  "login failed api_key=sk-ant-abcdef0123456789"
                                  "abcdef0123456789") for i in range(5))
        message = self.summary(text)["groups"][0]["message"]
        self.assertNotIn("sk-ant-abcdef0123456789", message)

    def test_answered_wrong_about_the_device_it_stands_down(self):
        snap = house()
        add_ap(snap)
        add_client(snap, 1, down_for=0)
        snap["core_log"] = self.summary(self.logs())
        snap["facts"] = {"device_tracker.plug_1_client": {"integ.log_flood"}}
        self.assertEqual(integrations.log_flood(snap, NOW), [])


class TestTheCatalog(unittest.TestCase):
    def test_brain_check_list_carries_the_network_checks(self):
        ids = set(checks.CHECK_IDS)
        for cid in ("net.wifi_hung", "net.wifi_flapping", "net.unifi_dropped",
                    "net.zwave_silent", "net.zwave_link", "net.zigbee_silent",
                    "net.zigbee_weak", "integ.log_flood"):
            self.assertIn(cid, ids)
            self.assertFalse(checks.is_shadow(cid), cid)
        self.assertEqual(checks.title_for("net.zwave_link"), "Network (Z-Wave)")
        self.assertEqual(checks.title_for("dev.frozen"), "Device check")

    def test_an_unreadable_source_skips_only_its_own_checks(self):
        snap = house()
        snap["available"]["zwave_nodes"] = False
        result = checks.run_all(snap, NOW)
        self.assertIn("net.zwave_silent", result["skipped"])
        self.assertIn("net.zwave_link", result["skipped"])
        self.assertIn("net.wifi_hung", result["ran"])
        self.assertIn("integ.log_flood", result["ran"])


if __name__ == "__main__":
    unittest.main()
