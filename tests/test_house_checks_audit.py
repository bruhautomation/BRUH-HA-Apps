#!/usr/bin/env python3
"""The parts of Home Assistant no check read, and the record of what was.

The owner's rule: *leave no part of Home Assistant unexamined, by default.*
Two halves, both driven here.

* New checks for the areas nothing looked at — open repairs, the Energy
  dashboard, what places people, custom integrations nothing sets up, an
  add-on an integration needs that is stopped, HACS, Matter and
  Bluetooth — each silent on the healthy house `test_house_checks`
  builds, each finding its planted row, and each holding the stand-down
  that keeps it from firing on a healthy house. `sys.backup_stale` also
  reads Home Assistant's own backup sensor, because a house that backs up
  to the cloud keeps no copy in the Supervisor's list.
* The coverage record: every catalog entry names its area, each pass
  records per check when it ran, whether it could look and what it found,
  and every area answers one of "found", "checked, nothing wrong", "could
  not look" (with the reason), "not set up here" or "not checked yet" —
  in /api/diagnostics, in the report text and in `brain doctor`, and on
  the decision trail as one "checked" row per clean area per day.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import checks  # noqa: E402
import decision_trail  # noqa: E402
import reports  # noqa: E402
from test_house_checks import DAY, NOW, house, iso  # noqa: E402

audit = checks.audit
coverage = checks.coverage
network = checks.network
system = checks.system
snapshot = checks.snapshot


def run(snap, *ids):
    result = checks.run_all(snap, NOW, only=list(ids))
    return result


def rows_of(result, cid):
    return [f for f in result["findings"] if f["source"] == f"check:{cid}"]


def add_entry(snap, domain, title, **extra):
    snap["config_entries"].append({"entry_id": f"e-{domain}", "domain": domain,
                                   "title": title, "state": "loaded",
                                   "source": "user", **extra})


class TestEveryCheckHasAnArea(unittest.TestCase):
    def test_every_catalog_entry_names_one_of_the_areas(self):
        for c in checks.CHECKS:
            self.assertIn(c.get("area"), coverage.AREA_IDS, c["id"])

    def test_every_area_the_owner_listed_has_a_check(self):
        areas = {c["area"] for c in checks.CHECKS}
        for area in coverage.AREA_IDS:
            self.assertIn(area, areas, area)

    def test_every_new_check_names_its_area_on_the_card(self):
        for cid, title in (("repairs.stale", "Repairs"),
                           ("energy.missing_stat", "Energy"),
                           ("people.phone_silent", "People"),
                           ("hacs.update_pending", "HACS"),
                           ("addon.needed_stopped", "Add-ons"),
                           ("integ.custom_unused", "Custom integrations"),
                           ("net.bluetooth_faint", "Network (Bluetooth)"),
                           ("net.matter_empty", "Network (Matter)")):
            self.assertEqual(checks.title_for(cid), title)


class TestRepairs(unittest.TestCase):
    def test_a_repair_left_a_week_is_found_and_names_its_integration(self):
        snap = house()
        snap["repairs"].append({"domain": "zwave_js",
                                "translation_key": "invalid_server_version",
                                "issue_id": "x", "created": iso(9 * DAY),
                                "severity": "error", "ignored": False})
        got = rows_of(run(snap, "repairs.stale"), "repairs.stale")
        self.assertEqual(len(got), 1)
        self.assertIn("Z-Wave (invalid server version", got[0]["detail"])
        self.assertEqual(got[0]["severity"], "warning")
        self.assertNotIn("zwave_js", got[0]["detail"])

    def test_ignored_dismissed_new_and_brains_own_are_left_alone(self):
        snap = house()
        snap["repairs"] += [
            {"domain": "hue", "issue_id": "d", "created": iso(30 * DAY),
             "dismissed_version": "2026.8.0"},
            {"domain": "x", "issue_domain": "brain", "issue_id": "b",
             "created": iso(30 * DAY)},
            {"domain": "hue", "issue_id": "n", "created": iso(6 * DAY)}]
        self.assertEqual(rows_of(run(snap, "repairs.stale"), "repairs.stale"), [])


class TestEnergy(unittest.TestCase):
    def prefs(self, *stats):
        return {"configured": True, "prefs": {"energy_sources": [
            {"type": "grid", "flow_from": [{"stat_energy_from": s}
                                           for s in stats], "flow_to": []}]}}

    def test_a_sensor_that_no_longer_exists_is_found(self):
        snap = house(energy_prefs=self.prefs("sensor.old_meter_energy"))
        got = rows_of(run(snap, "energy.missing_stat"), "energy.missing_stat")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["entity_id"], "sensor.old_meter_energy")
        self.assertNotIn("sensor.old_meter_energy", got[0]["detail"])

    def test_a_power_reading_where_a_total_belongs_is_found(self):
        snap = house(energy_prefs=self.prefs("sensor.oven_power"))
        snap["states"]["sensor.oven_power"] = {
            "state": "1200", "attributes": {"friendly_name": "Oven power",
                                            "device_class": "power",
                                            "unit_of_measurement": "W",
                                            "state_class": "measurement"},
            "last_changed": iso(60)}
        got = rows_of(run(snap, "energy.rate_sensor"), "energy.rate_sensor")
        self.assertEqual(len(got), 1)
        self.assertIn("Oven power", got[0]["detail"])
        # It exists, so it is not also "missing".
        self.assertEqual(rows_of(run(snap, "energy.missing_stat"),
                                 "energy.missing_stat"), [])

    def test_a_total_and_a_live_power_field_are_not_rates(self):
        snap = house()
        snap["states"]["sensor.grid_energy"] = {
            "state": "123", "attributes": {"device_class": "energy",
                                           "unit_of_measurement": "kWh",
                                           "state_class": "total_increasing"}}
        snap["states"]["sensor.grid_power"] = {
            "state": "300", "attributes": {"device_class": "power",
                                           "unit_of_measurement": "W"}}
        snap["energy_prefs"] = {"configured": True, "prefs": {"energy_sources": [
            {"type": "grid", "stat_rate": "sensor.grid_power",
             "flow_from": [{"stat_energy_from": "sensor.grid_energy"}]}]}}
        self.assertEqual(rows_of(run(snap, "energy.rate_sensor"),
                                 "energy.rate_sensor"), [])

    def test_no_energy_dashboard_is_not_set_up_rather_than_clean(self):
        snap = house(energy_prefs={"configured": False, "prefs": {}})
        result = run(snap, "energy.missing_stat", "energy.rate_sensor")
        self.assertIn("energy.missing_stat", result["ran"])
        self.assertIn("not been set up", result["absent"]["energy.missing_stat"])

    def test_core_saying_no_prefs_is_an_answer_and_a_refusal_is_not(self):
        self.assertEqual(snapshot.energy_prefs(
            {"ok": False, "result": None, "error": "No prefs"}),
            {"configured": False, "prefs": {}})
        self.assertIsNone(snapshot.energy_prefs(
            {"ok": False, "result": None, "error": "timeout"}))
        self.assertTrue(snapshot.energy_prefs(
            {"ok": True, "result": {"energy_sources": []}})["configured"])


def add_phone(snap, *, seen_ago, person=True, gps=True, sensors=2):
    snap["devices"].append({"id": "dev-phone", "name": "Ben's phone"})
    eids = ["device_tracker.bens_phone"] + [f"sensor.bens_phone_s{i}"
                                             for i in range(sensors)]
    for eid in eids:
        snap["entities"].append({"entity_id": eid, "platform": "mobile_app",
                                 "device_id": "dev-phone"})
        attrs = {"friendly_name": eid.split(".")[1].replace("_", " ")}
        if eid.startswith("device_tracker.") and gps:
            attrs["source_type"] = "gps"
        snap["states"][eid] = {"state": "home" if "tracker" in eid else "50",
                               "attributes": attrs,
                               "last_updated": iso(seen_ago),
                               "last_reported": iso(seen_ago)}
    if person:
        snap["states"]["person.ben"] = {
            "state": "home", "attributes": {
                "friendly_name": "Ben",
                "device_trackers": ["device_tracker.bens_phone"]},
            "last_changed": iso(DAY)}
    return eids


class TestPeople(unittest.TestCase):
    def test_a_phone_whose_app_stopped_reporting_is_one_card(self):
        snap = house()
        add_phone(snap, seen_ago=10 * DAY)
        result = run(snap, "people.phone_silent", "people.tracker_stale")
        phones = rows_of(result, "people.phone_silent")
        self.assertEqual(len(phones), 1)
        self.assertIn("Ben's phone", phones[0]["text"])
        # Its own tracker is the phone's card, never a second one.
        self.assertEqual(rows_of(result, "people.tracker_stale"), [])

    def test_a_tracker_placing_a_person_that_went_quiet_is_found(self):
        snap = house()
        add_phone(snap, seen_ago=10 * DAY)
        # The phone's sensors are fine; only its location stopped.
        for eid in ("sensor.bens_phone_s0", "sensor.bens_phone_s1"):
            snap["states"][eid]["last_reported"] = iso(600)
        result = run(snap, "people.phone_silent", "people.tracker_stale")
        self.assertEqual(rows_of(result, "people.phone_silent"), [])
        got = rows_of(result, "people.tracker_stale")
        self.assertEqual(len(got), 1)
        self.assertIn("where Ben is", got[0]["text"])

    def test_a_router_tracker_reading_home_all_week_is_not_stale(self):
        snap = house()
        add_phone(snap, seen_ago=10 * DAY, gps=False)
        for eid in ("sensor.bens_phone_s0", "sensor.bens_phone_s1"):
            snap["states"][eid]["last_reported"] = iso(600)
        self.assertEqual(rows_of(run(snap, "people.tracker_stale"),
                                 "people.tracker_stale"), [])

    def test_a_phone_reporting_today_is_fine(self):
        snap = house()
        add_phone(snap, seen_ago=600)
        result = run(snap, "people.phone_silent", "people.tracker_stale")
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["absent"], {})

    def test_a_house_with_no_people_says_so(self):
        result = run(house(), "people.phone_silent")
        self.assertIn("nobody is set up", result["absent"]["people.phone_silent"])


class TestCustomIntegrations(unittest.TestCase):
    def cc(self, *integrations, referenced=()):
        return {"integrations": list(integrations), "referenced": list(referenced)}

    def test_one_nothing_sets_up_is_found_and_brains_own_never(self):
        snap = house(custom_components=self.cc(
            {"domain": "brain", "name": "brAIn", "mtime": NOW - 90 * DAY},
            {"domain": "old_thing", "name": "Old Thing", "mtime": NOW - 90 * DAY}))
        got = rows_of(run(snap, "integ.custom_unused"), "integ.custom_unused")
        self.assertEqual(len(got), 1)
        self.assertIn("Old Thing", got[0]["detail"])
        self.assertNotIn("brAIn", got[0]["detail"])

    def test_an_entry_a_yaml_mention_a_dependent_or_a_new_install_stands_down(self):
        snap = house(custom_components=self.cc(
            {"domain": "hue", "name": "Hue (custom)", "mtime": NOW - 90 * DAY},
            {"domain": "yamlish", "name": "Yamlish", "mtime": NOW - 90 * DAY},
            {"domain": "libby", "name": "Libby", "mtime": NOW - 90 * DAY},
            {"domain": "user_of", "name": "User", "mtime": NOW - 90 * DAY,
             "dependencies": ["libby"]},
            {"domain": "fresh", "name": "Fresh", "mtime": NOW - 2 * DAY},
            referenced=["yamlish", "user_of"]))
        self.assertEqual(rows_of(run(snap, "integ.custom_unused"),
                                 "integ.custom_unused"), [])

    def test_the_folder_is_read_off_real_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            cc = Path(tmp, "custom_components")
            for dom in ("used_yaml", "used_platform", "unused", "in_package"):
                (cc / dom).mkdir(parents=True)
                (cc / dom / "manifest.json").write_text(json.dumps(
                    {"domain": dom, "name": dom.title()}))
            Path(tmp, "configuration.yaml").write_text(
                "used_yaml:\n  host: x\nsensor:\n  - platform: used_platform\n"
                "homeassistant:\n  packages: !include_dir_named packages\n")
            Path(tmp, "packages").mkdir()
            Path(tmp, "packages", "p.yaml").write_text("in_package:\n  a: 1\n")
            Path(tmp, "secrets.yaml").write_text("unused: hunter2\n")
            got = snapshot.load_custom_components(tmp)
        self.assertEqual(sorted(c["domain"] for c in got["integrations"]),
                         ["in_package", "unused", "used_platform", "used_yaml"])
        self.assertEqual(got["referenced"],
                         ["in_package", "used_platform", "used_yaml"])

    def test_no_folder_is_an_empty_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(snapshot.load_custom_components(tmp),
                             {"integrations": [], "referenced": []})


class TestAddonAnIntegrationNeeds(unittest.TestCase):
    def plant(self, snap, *, boot="manual", state="stopped", source="hassio"):
        snap["supervisor"]["addons"].append(
            {"slug": "mqtt", "name": "Mosquitto broker", "installed": True,
             "state": state, "boot": boot, "discovery": ["mqtt"]})
        snap["config_entries"].append(
            {"entry_id": "e-mqtt", "domain": "mqtt", "title": "MQTT",
             "state": "setup_retry", "source": source,
             "failing_since": NOW - 3 * DAY})

    def test_a_stopped_add_on_an_integration_was_set_up_from_is_found(self):
        snap = house()
        self.plant(snap)
        result = run(snap, "addon.needed_stopped", "sys.entry_failed",
                     "sys.addon_down")
        got = rows_of(result, "addon.needed_stopped")
        self.assertEqual(len(got), 1)
        self.assertIn("MQTT needs the Mosquitto broker add-on", got[0]["text"])
        # The integration failing IS this: one card, with the fix that works.
        self.assertEqual(rows_of(result, "sys.entry_failed"), [])

    def test_one_set_to_start_on_boot_is_sys_addon_downs(self):
        snap = house()
        self.plant(snap, boot="auto")
        result = run(snap, "addon.needed_stopped", "sys.addon_down")
        self.assertEqual(rows_of(result, "addon.needed_stopped"), [])
        self.assertEqual(len(rows_of(result, "sys.addon_down")), 1)

    def test_an_integration_pointed_elsewhere_or_a_running_add_on_is_fine(self):
        for kwargs in ({"source": "user"}, {"state": "started"}):
            snap = house()
            self.plant(snap, **kwargs)
            self.assertEqual(rows_of(run(snap, "addon.needed_stopped"),
                                     "addon.needed_stopped"), [], kwargs)

    def test_the_add_ons_discovery_is_read_off_its_info(self):
        self.assertIn('"discovery")', Path(snapshot.__file__).read_text())


class TestHacs(unittest.TestCase):
    def plant(self, snap, *, waiting_days):
        add_entry(snap, "hacs", "HACS")
        snap["entities"].append({"entity_id": "update.mushroom_update",
                                 "platform": "hacs"})
        snap["states"]["update.mushroom_update"] = {
            "state": "on", "attributes": {"title": "Mushroom",
                                          "latest_version": "v4.1.0"},
            "last_changed": iso(waiting_days * DAY)}

    def test_an_update_waiting_two_weeks_is_found(self):
        snap = house()
        self.plant(snap, waiting_days=20)
        got = rows_of(run(snap, "hacs.update_pending"), "hacs.update_pending")
        self.assertEqual(len(got), 1)
        self.assertIn("Mushroom (v4.1.0)", got[0]["detail"])

    def test_a_new_one_says_nothing_and_no_hacs_is_not_set_up(self):
        snap = house()
        self.plant(snap, waiting_days=3)
        self.assertEqual(rows_of(run(snap, "hacs.update_pending"),
                                 "hacs.update_pending"), [])
        result = run(house(), "hacs.update_pending")
        self.assertEqual(result["absent"]["hacs.update_pending"],
                         "HACS is not installed")


class TestMatterAndBluetooth(unittest.TestCase):
    def test_matter_with_nothing_on_it_is_found_and_with_a_device_is_not(self):
        snap = house()
        add_entry(snap, "matter", "Matter", created_at=NOW - 30 * DAY)
        self.assertEqual(len(rows_of(run(snap, "net.matter_empty"),
                                     "net.matter_empty")), 1)
        snap["devices"].append({"id": "dev-m", "name": "Plug",
                                "config_entries": ["e-matter"]})
        self.assertEqual(rows_of(run(snap, "net.matter_empty"),
                                 "net.matter_empty"), [])

    def test_a_matter_fabric_made_this_week_is_given_time(self):
        snap = house()
        add_entry(snap, "matter", "Matter", created_at=NOW - 2 * DAY)
        self.assertEqual(rows_of(run(snap, "net.matter_empty"),
                                 "net.matter_empty"), [])

    def test_a_ble_device_heard_faintly_is_found(self):
        snap = house()
        add_entry(snap, "bluetooth", "Bluetooth")
        snap["devices"].append({"id": "dev-ble", "name": "Fridge thermometer",
                                "connections": [["bluetooth", "AA:BB:CC:00:00:01"]]})
        snap["entities"].append({"entity_id": "sensor.fridge_temp",
                                 "device_id": "dev-ble", "platform": "xiaomi_ble"})
        snap["bluetooth"] = {"rssi": {"aa:bb:cc:00:00:01": -96}}
        got = rows_of(run(snap, "net.bluetooth_faint"), "net.bluetooth_faint")
        self.assertEqual(len(got), 1)
        self.assertIn("Fridge thermometer", got[0]["text"])
        snap["bluetooth"] = {"rssi": {"aa:bb:cc:00:00:01": -70}}
        self.assertEqual(rows_of(run(snap, "net.bluetooth_faint"),
                                 "net.bluetooth_faint"), [])


class TestBackupsReadHomeAssistantsOwnRecord(unittest.TestCase):
    """The Supervisor's list holds what is stored HERE; a house backing up
    to the cloud with no local copy has a recent backup it never shows."""

    def sensor(self, snap, ago):
        snap["entities"].append({
            "entity_id": "sensor.backup_last_successful_automatic_backup",
            "platform": "backup",
            "unique_id": "last_successful_automatic_backup"})
        snap["states"]["sensor.backup_last_successful_automatic_backup"] = {
            "state": iso(ago), "attributes": {"device_class": "timestamp"}}

    def test_a_cloud_backup_last_night_is_not_never_backed_up(self):
        snap = house()
        snap["supervisor"]["backups"] = []
        self.sensor(snap, DAY)
        self.assertEqual(rows_of(run(snap, "sys.backup_stale"),
                                 "sys.backup_stale"), [])

    def test_a_cloud_backup_last_night_answers_a_stale_local_list(self):
        snap = house()
        snap["supervisor"]["backups"] = [{"slug": "a", "name": "Old",
                                          "date": iso(30 * DAY)}]
        self.sensor(snap, DAY)
        self.assertEqual(rows_of(run(snap, "sys.backup_stale"),
                                 "sys.backup_stale"), [])

    def test_both_old_is_still_stale(self):
        snap = house()
        snap["supervisor"]["backups"] = []
        self.sensor(snap, 20 * DAY)
        got = rows_of(run(snap, "sys.backup_stale"), "sys.backup_stale")
        self.assertEqual(len(got), 1)
        self.assertIn("more than a week old", got[0]["text"])


class TestCoverage(unittest.TestCase):
    def test_a_clean_pass_says_checked_nothing_wrong_for_every_examined_area(self):
        result = checks.run_all(house(), NOW)
        record = coverage.record({}, result, NOW, {})
        view = {a["id"]: a for a in coverage.area_view(record, checks.CHECKS, NOW)}
        self.assertEqual(set(view), set(coverage.AREA_IDS))
        for area in ("integrations", "addons", "backups", "recorder",
                     "automations", "dashboards", "repairs", "devices",
                     "networks", "host", "energy"):
            self.assertEqual(view[area]["state"], "clear", view[area]["line"])
            self.assertIn("checked, nothing wrong", view[area]["line"])
        # What the house does not have is said in those words, never as
        # "nothing wrong".
        for area in ("hacs", "people", "custom_integrations"):
            self.assertEqual(view[area]["state"], "absent", view[area]["line"])
            self.assertIn("not set up in this house", view[area]["line"])

    def test_a_check_that_could_not_look_says_why_in_words(self):
        snap = house()
        snap["available"]["repairs"] = False
        snap["errors"]["repairs"] = "Home Assistant did not list its repairs"
        result = checks.run_all(snap, NOW)
        record = coverage.record({}, result, NOW, snap["errors"])
        repairs = {a["id"]: a for a in coverage.area_view(
            record, checks.CHECKS, NOW)}["repairs"]
        self.assertEqual(repairs["state"], "could_not_look")
        self.assertIn("could not look", repairs["line"])
        self.assertIn("did not list its repairs", repairs["line"])
        self.assertNotIn("snapshot is missing", repairs["line"])
        self.assertNotIn("nothing wrong", repairs["line"])

    def test_a_skip_keeps_the_last_good_run_and_a_restart_keeps_the_record(self):
        result = checks.run_all(house(), NOW)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "coverage.json")
            self.assertTrue(coverage.save(coverage.record({}, result, NOW), path))
            later = coverage.load(path)
        snap = house()
        snap["available"]["supervisor"] = False
        record = coverage.record(later, checks.run_all(snap, NOW + 3600),
                                 NOW + 3600, {})
        rec = record["checks"]["sys.backup_stale"]
        self.assertEqual(rec["ran_at"], int(NOW))
        self.assertTrue(rec["skipped"])

    def test_a_finding_and_a_week_without_a_look_are_said(self):
        snap = house()
        snap["repairs"].append({"domain": "hue", "issue_id": "z",
                                "created": iso(9 * DAY)})
        record = coverage.record({}, checks.run_all(snap, NOW), NOW)
        view = {a["id"]: a for a in coverage.area_view(record, checks.CHECKS, NOW)}
        self.assertEqual(view["repairs"]["state"], "found")
        self.assertIn("1 finding", view["repairs"]["line"])
        old = {a["id"]: a for a in coverage.area_view(
            record, checks.CHECKS, NOW + 8 * DAY)}
        self.assertEqual(old["backups"]["state"], "could_not_look")
        self.assertIn("last ran", old["backups"]["line"])

    def test_nothing_recorded_is_not_checked_yet_and_gaps_are_named(self):
        view = {a["id"]: a for a in coverage.area_view({}, checks.CHECKS, NOW)}
        self.assertTrue(all(a["state"] == "never" for a in view.values()))
        record = coverage.record({}, checks.run_all(house(), NOW), NOW)
        host = {a["id"]: a for a in coverage.area_view(
            record, checks.CHECKS, NOW)}["host"]
        self.assertIn("Not looked at: storage wear", host["line"])

    def test_the_file_is_never_created_where_its_folder_is_not(self):
        self.assertFalse(coverage.save({"checks": {}},
                                       "/nonexistent-dir-xyz/coverage.json"))
        self.assertEqual(coverage.load("/nonexistent-dir-xyz/c.json"),
                         {"checks": {}})


class TestTheTrailCanAnswerDidYouLook(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old = decision_trail.TRAIL_FILE
        decision_trail.TRAIL_FILE = os.path.join(self.tmp.name, "d.jsonl")
        self.addCleanup(setattr, decision_trail, "TRAIL_FILE", self.old)
        decision_trail.clear_memory()
        self.addCleanup(decision_trail.clear_memory)

    def areas(self, now):
        record = coverage.record({}, checks.run_all(house(), NOW), NOW)
        return coverage.area_view(record, checks.CHECKS, now)

    def test_one_checked_row_per_clean_area_folded_within_a_day(self):
        import datetime as dt
        tz = dt.timezone.utc
        areas = self.areas(NOW)
        decision_trail.note_many(coverage.checked_rows(areas, NOW, tz), NOW)
        decision_trail.note_many(coverage.checked_rows(areas, NOW + 6 * 3600, tz),
                                 NOW + 6 * 3600)
        rows, _ = decision_trail.read()
        recorder = [r for r in rows if r["check"] == "area.recorder"]
        self.assertEqual(len(recorder), 1)
        self.assertEqual(recorder[0]["count"], 2)
        # The next day is its own row.
        decision_trail.note_many(coverage.checked_rows(areas, NOW + DAY, tz),
                                 NOW + DAY)
        rows, _ = decision_trail.read()
        self.assertEqual(len([r for r in rows if r["check"] == "area.recorder"]), 2)
        # An area not set up here writes no "nothing wrong".
        self.assertFalse([r for r in rows if r["check"] == "area.hacs"])

    def test_asking_about_one_check_finds_its_areas_row(self):
        import datetime as dt
        decision_trail.note_many(coverage.checked_rows(
            self.areas(NOW), NOW, dt.timezone.utc), NOW)
        got = decision_trail.for_subject("sys.recorder_size")
        self.assertEqual(got["kinds"], ["checked"])
        self.assertIn("nothing wrong", got["rows"][0]["meaning"])
        self.assertEqual(decision_trail.for_subject("area.repairs")["kinds"],
                         ["checked"])


class TestAnAreaThatCouldNotLookNeverSaysNothingWrong(unittest.TestCase):
    """A pass where Home Assistant answered 502 to the states and registry
    reads: the devices checks are skipped, the few that need neither run.
    The trail must not read that as a clean bill of health."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old = decision_trail.TRAIL_FILE
        decision_trail.TRAIL_FILE = os.path.join(self.tmp.name, "d.jsonl")
        self.addCleanup(setattr, decision_trail, "TRAIL_FILE", self.old)
        decision_trail.clear_memory()
        self.addCleanup(decision_trail.clear_memory)

    def test_devices_with_502s_is_a_could_not_check_row(self):
        import datetime as dt
        snap = house()
        snap["available"] = {**(snap.get("available") or {}),
                             "states": False, "registry": False}
        errs = {"states": "502, message='Invalid response status'",
                "registry": "502, message='Invalid response status'"}
        record = coverage.record({}, checks.run_all(snap, NOW), NOW, errs)
        areas = coverage.area_view(record, checks.CHECKS, NOW)
        dev = [a for a in areas if a["id"] == "devices"][0]
        self.assertIn(dev["state"], ("partial", "could_not_look"))
        decision_trail.note_many(coverage.checked_rows(
            areas, NOW, dt.timezone.utc), NOW)
        got = decision_trail.for_subject("area.devices")
        self.assertEqual(got["kinds"], ["unchecked"])
        text = " ".join(str(r.get("text") or "") + str(r.get("meaning") or "")
                        + str(r.get("reason") or "") for r in got["rows"])
        self.assertNotIn("nothing wrong", text)
        self.assertIn("could not check", text)
        self.assertIn("502", text)


class TestItIsSaidWhereAPersonReads(unittest.TestCase):
    def test_the_report_text_carries_one_line_per_area(self):
        record = coverage.record({}, checks.run_all(house(), NOW), NOW)
        diag = {"coverage": coverage.summary(record, checks.CHECKS, NOW)}
        text = reports.compose("manual", "h", "w", "l", now=NOW, run=None,
                               health=None, extra_text="", diagnostics=diag,
                               log_text="")
        self.assertIn("--- what brAIn looked at ---", text)
        self.assertIn("Recorder: checked, nothing wrong", text)
        self.assertIn("HACS: not set up in this house", text)

    def test_brain_doctor_prints_the_lines(self):
        script = (BASE_DIR / "brain" / "scripts" / "ha-selftest.sh").read_text()
        self.assertIn(".coverage.lines[]?", script)



class TestTheServerRecordsEachPass(unittest.TestCase):
    """`run_checks` hands every pass to `_note_coverage`, and the payload
    `/api/diagnostics` serves reads the record back — driven, not grepped."""

    @classmethod
    def setUpClass(cls):
        import importlib
        cls.server = importlib.import_module("server")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for mod, name, value in (
                (coverage, "COVERAGE_FILE", os.path.join(self.tmp.name, "c.json")),
                (decision_trail, "TRAIL_FILE", os.path.join(self.tmp.name, "d.jsonl"))):
            self.addCleanup(setattr, mod, name, getattr(mod, name))
            setattr(mod, name, value)
        decision_trail.clear_memory()
        self.addCleanup(decision_trail.clear_memory)

    def test_a_pass_is_recorded_and_its_clean_areas_reach_the_trail(self):
        snap = house()
        result = checks.run_all(snap, NOW)
        self.assertGreater(self.server._note_coverage(result, snap, NOW), 0)
        self.assertTrue(coverage.load()["checks"])
        self.assertEqual(decision_trail.for_subject("area.recorder")["kinds"],
                         ["checked"])
        cov = self.server._diagnostics_payload()["coverage"]
        lines = cov["lines"]
        self.assertEqual(len(lines), len(coverage.AREAS))
        self.assertTrue(any(line.startswith("Repairs: checked, nothing wrong")
                            for line in lines), lines)

    def test_a_record_that_cannot_be_written_never_fails_the_pass(self):
        coverage.COVERAGE_FILE = "/nonexistent-dir-xyz/c.json"
        snap = house()
        self.server._note_coverage(checks.run_all(snap, NOW), snap, NOW)

class TestWhatBluetoothHearsIsReadOffTheSubscription(unittest.IsolatedAsyncioTestCase):
    """`bluetooth/subscribe_advertisements` answers a result and then one
    event carrying everything Core holds; a Core without the command
    refuses it, which is "could not look", never "heard nothing"."""

    SUPPORTED = True

    async def asyncSetUp(self):
        import ha_data
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
        supported = self.SUPPORTED

        async def ws_handler(request):
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            await ws.send_json({"type": "auth_required"})
            async for msg in ws:
                data = msg.json()
                if data.get("type") == "auth":
                    await ws.send_json({"type": "auth_ok"})
                elif not supported:
                    await ws.send_json({"id": data["id"], "type": "result",
                                        "success": False, "error": {
                                            "code": "unknown_command"}})
                else:
                    await ws.send_json({"id": data["id"], "type": "result",
                                        "success": True, "result": None})
                    await ws.send_json({"id": data["id"], "type": "event",
                                        "event": {"add": [
                                            {"address": "AA:BB:CC:00:00:01",
                                             "rssi": -96, "source": "hci0"},
                                            {"address": "AA:BB:CC:00:00:01",
                                             "rssi": -80, "source": "proxy"},
                                        ]}})
            return ws

        app = web.Application()
        app.router.add_get("/websocket", ws_handler)
        self.server = TestServer(app)
        self.client = TestClient(self.server)
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)
        self.addCleanup(setattr, ha_data, "CORE_WS", ha_data.CORE_WS)
        ha_data.CORE_WS = str(self.server.make_url("/websocket"))

    async def test_the_strongest_receiver_is_what_counts(self):
        got = await snapshot.bluetooth_heard(self.client.session)
        self.assertEqual(got, {"aa:bb:cc:00:00:01": -80.0})


class TestAnOlderCoreIsCouldNotLook(TestWhatBluetoothHearsIsReadOffTheSubscription):
    SUPPORTED = False

    async def test_the_strongest_receiver_is_what_counts(self):
        self.assertIsNone(await snapshot.bluetooth_heard(self.client.session))


if __name__ == "__main__":
    unittest.main()
