#!/usr/bin/env python3
"""Tests for the house checks — findings that cost nothing.

Every check is a pure function over a snapshot, so every one is driven
here against a hand-built house with a planted defect, and against the
same house with the defect removed. Two things matter beyond "it finds
the planted row":

  * a check that fires on a healthy house is worse than no check, so each
    one is asserted silent on the clean fixture;
  * a check that did not run must not clear anything — the panel clears
    open rows only for checks that ran, and the run/skip bookkeeping in
    ``run_all`` is what it keys on.

The snapshot loaders are exercised on real files (a YAML with HA's tags,
a traces store in both shapes HA has used) rather than described.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))

import checks  # noqa: E402
import findings_store  # noqa: E402
from checks import automations, devices, forecasts, snapshot  # noqa: E402
from checks import _util  # noqa: E402

NOW = 1_800_000_000.0
DAY = 86400.0


def iso(seconds_ago: float) -> str:
    import datetime as dt
    return dt.datetime.fromtimestamp(NOW - seconds_ago, tz=dt.timezone.utc).isoformat()


def house(**over) -> dict:
    """A small, healthy house. Every planted defect is an override."""
    snap = {
        "now": NOW,
        "available": {k: True for k in (
            "states", "registry", "services", "automations", "traces",
            "stats", "battery_stats", "dashboards")},
        "errors": {},
        "blueprints_dir": "",
        "states": {
            "automation.morning": {
                "state": "on",
                "attributes": {"friendly_name": "Morning lights",
                               "last_triggered": iso(3600)},
                "last_changed": iso(30 * DAY)},
            "light.kitchen": {
                "state": "on", "attributes": {"friendly_name": "Kitchen"},
                "last_changed": iso(60)},
            "sensor.back_door_battery": {
                "state": "88",
                "attributes": {"device_class": "battery",
                               "unit_of_measurement": "%",
                               "friendly_name": "Back Door Battery",
                               "state_class": "measurement"},
                "last_updated": iso(600), "last_reported": iso(600)},
            "sensor.hall_temp": {
                "state": "21.4",
                "attributes": {"device_class": "temperature",
                               "unit_of_measurement": "°C",
                               "friendly_name": "Hall Temperature",
                               "state_class": "measurement"},
                "last_updated": iso(60), "last_changed": iso(60)},
        },
        "entities": [
            {"entity_id": "automation.morning", "platform": "automation",
             "unique_id": "morning-1", "created_at": NOW - 90 * DAY},
            {"entity_id": "light.kitchen", "platform": "hue",
             "device_id": "dev-hue-1", "area_id": "kitchen"},
            {"entity_id": "sensor.back_door_battery", "platform": "zha",
             "device_id": "dev-door-1"},
            {"entity_id": "sensor.hall_temp", "platform": "zha",
             "device_id": "dev-temp-1", "area_id": "hall"},
        ],
        "devices": [
            {"id": "dev-hue-1", "name": "Hue bulb", "area_id": "kitchen"},
            {"id": "dev-door-1", "name": "Back Door sensor", "area_id": "hall"},
            {"id": "dev-temp-1", "name": "Hall climate"},
        ],
        "areas": [{"area_id": "kitchen", "name": "Kitchen"},
                  {"area_id": "hall", "name": "Hall"}],
        "services": {"light.turn_on", "light.turn_off", "notify.mobile_app_phone"},
        "automations": [{
            "id": "morning-1", "alias": "Morning lights",
            "triggers": [{"trigger": "time", "at": "07:00:00"}],
            "actions": [{"action": "light.turn_on",
                         "target": {"entity_id": "light.kitchen"}},
                        {"action": "notify.mobile_app_phone",
                         "data": {"message": "Morning"}}],
        }],
        "scripts": {},
        "scenes": [],
        "traces": {"automation.morning": [
            {"run_id": "1", "script_execution": "finished",
             "timestamp": {"start": iso(3600)}}]},
        "stats": {"sensor.hall_temp": [
            {"start": NOW - d * DAY, "mean": 21 + d * 0.3, "min": 20 + d * 0.2,
             "max": 22 + d * 0.1} for d in range(7)]},
        "battery_stats": {"sensor.back_door_battery": [
            {"start": NOW - d * DAY, "mean": 88.0} for d in range(40, 0, -1)]},
        "dashboards": [{"url_path": "lovelace", "title": "Home", "config": {
            "views": [{"cards": [{"type": "entities",
                                  "entities": ["light.kitchen",
                                               {"entity": "sensor.hall_temp"}]}]}]}}],
    }
    snap.update(over)
    return snap


def by_source(result: dict) -> dict:
    out: dict[str, list] = {}
    for f in result["findings"]:
        out.setdefault(f["source"], []).append(f)
    return out


class TestCleanHouseIsSilent(unittest.TestCase):
    def test_no_check_fires_on_the_healthy_fixture(self):
        result = checks.run_all(house(), NOW)
        self.assertEqual(result["findings"], [], result["findings"])
        self.assertEqual(result["errors"], {})
        self.assertEqual(result["skipped"], {})
        self.assertEqual(sorted(result["ran"]), sorted(checks.CHECK_IDS))

    def test_every_check_in_the_catalog_has_a_unique_id_and_a_runner(self):
        ids = [c["id"] for c in checks.CHECKS]
        self.assertEqual(len(ids), len(set(ids)))
        for c in checks.CHECKS:
            self.assertTrue(callable(c["run"]), c["id"])
            self.assertTrue(c.get("needs"), c["id"])
            self.assertIn(c["id"].split(".")[0], checks.GROUP_TITLES, c["id"])


class TestAutomationChecks(unittest.TestCase):
    def test_dead_reference_is_found_and_service_names_are_not_entities(self):
        snap = house()
        snap["automations"][0]["actions"][0]["target"]["entity_id"] = "light.gone"
        found = automations.dead_ref(snap, NOW)
        self.assertEqual(len(found), 1)
        self.assertIn("light.gone", found[0]["detail"])
        # light.turn_on is a service and must not be reported as a missing entity
        self.assertNotIn("turn_on", found[0]["detail"])
        self.assertEqual(found[0]["entity_id"], "automation.morning")
        self.assertEqual(found[0]["severity"], "serious")

    def test_dead_reference_inside_a_template_string(self):
        snap = house()
        snap["automations"][0]["conditions"] = [
            {"condition": "template",
             "value_template": "{{ states('sensor.vanished') == 'on' }}"}]
        found = automations.dead_ref(snap, NOW)
        self.assertEqual(len(found), 1)
        self.assertIn("sensor.vanished", found[0]["detail"])

    def test_an_automation_naming_itself_is_not_a_dead_reference(self):
        snap = house()
        snap["automations"][0]["actions"].append(
            {"action": "automation.turn_off",
             "target": {"entity_id": "automation.morning"}})
        snap["services"].add("automation.turn_off")
        self.assertEqual(automations.dead_ref(snap, NOW), [])

    def test_dead_service_names_the_replacement_when_there_is_one(self):
        snap = house()
        snap["automations"][0]["actions"][1]["action"] = "notify.mobile_app_old_phone"
        found = automations.dead_service(snap, NOW)
        self.assertEqual(len(found), 1)
        self.assertIn("notify.mobile_app_old_phone", found[0]["detail"])
        self.assertIn("notify.mobile_app_phone", found[0]["fix"])

    def test_dead_service_skips_templated_calls_and_needs_a_services_list(self):
        snap = house()
        snap["automations"][0]["actions"][1]["action"] = "{{ my_service }}"
        self.assertEqual(automations.dead_service(snap, NOW), [])
        snap = house(services=set())
        snap["automations"][0]["actions"][1]["action"] = "notify.nope"
        self.assertEqual(automations.dead_service(snap, NOW), [])

    def test_trace_error_reports_only_the_latest_run(self):
        snap = house()
        snap["traces"]["automation.morning"] = [
            {"run_id": "1", "script_execution": "error", "error": "boom",
             "last_step": "action/0", "timestamp": {"start": iso(7200)}},
            {"run_id": "2", "script_execution": "finished",
             "timestamp": {"start": iso(60)}},
        ]
        self.assertEqual(automations.trace_error(snap, NOW), [])
        snap["traces"]["automation.morning"].reverse()
        snap["traces"]["automation.morning"][1]["timestamp"]["start"] = iso(30)
        found = automations.trace_error(snap, NOW)
        self.assertEqual(len(found), 1)
        self.assertIn("boom", found[0]["detail"])
        self.assertIn("action/0", found[0]["detail"])

    def test_condition_never_passes_needs_every_recent_run_to_stop_there(self):
        snap = house()
        snap["traces"]["automation.morning"] = [
            {"run_id": str(i), "script_execution": "failed_conditions",
             "timestamp": {"start": iso(i * 3600)}} for i in range(4)]
        found = automations.condition_never_passes(snap, NOW)
        self.assertEqual(len(found), 1)
        self.assertIn("last 4 runs", found[0]["detail"])
        snap["traces"]["automation.morning"][0]["script_execution"] = "finished"
        self.assertEqual(automations.condition_never_passes(snap, NOW), [])

    def test_condition_check_stays_quiet_on_a_disabled_automation(self):
        snap = house()
        snap["states"]["automation.morning"]["state"] = "off"
        snap["traces"]["automation.morning"] = [
            {"run_id": str(i), "script_execution": "failed_conditions",
             "timestamp": {"start": iso(i * 3600)}} for i in range(4)]
        self.assertEqual(automations.condition_never_passes(snap, NOW), [])

    def test_already_running_counts_only_the_last_day(self):
        snap = house()
        snap["traces"]["automation.morning"] = [
            {"run_id": str(i), "script_execution": "failed_single",
             "timestamp": {"start": iso(i * 600)}} for i in range(3)]
        found = automations.already_running(snap, NOW)
        self.assertEqual(len(found), 1)
        self.assertIn("mode: queued", found[0]["fix"])
        for row in snap["traces"]["automation.morning"]:
            row["timestamp"]["start"] = iso(3 * DAY)
        self.assertEqual(automations.already_running(snap, NOW), [])

    def test_never_fired_needs_age_and_an_ordinary_trigger(self):
        snap = house()
        snap["states"]["automation.morning"]["attributes"]["last_triggered"] = None
        found = automations.never_fired(snap, NOW)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["severity"], "info")
        # created last week: still being written
        snap["entities"][0]["created_at"] = NOW - 5 * DAY
        self.assertEqual(automations.never_fired(snap, NOW), [])
        # a webhook automation legitimately waits months
        snap["entities"][0]["created_at"] = NOW - 90 * DAY
        snap["automations"][0]["triggers"] = [{"trigger": "webhook", "webhook_id": "x"}]
        self.assertEqual(automations.never_fired(snap, NOW), [])
        # no created_at at all: cannot tell, so silent
        snap["automations"][0]["triggers"] = [{"trigger": "time", "at": "07:00:00"}]
        del snap["entities"][0]["created_at"]
        self.assertEqual(automations.never_fired(snap, NOW), [])

    def test_forgotten_off_has_a_floor(self):
        snap = house()
        snap["states"]["automation.morning"]["state"] = "off"
        snap["states"]["automation.morning"]["last_changed"] = iso(45 * DAY)
        self.assertEqual(len(automations.forgotten_off(snap, NOW)), 1)
        snap["states"]["automation.morning"]["last_changed"] = iso(2 * DAY)
        self.assertEqual(automations.forgotten_off(snap, NOW), [])

    def test_duplicate_reports_the_copy_not_the_original(self):
        snap = house()
        copy = json.loads(json.dumps(snap["automations"][0]))
        copy["id"] = "morning-2"
        copy["alias"] = "Morning lights (copy)"
        snap["automations"].append(copy)
        found = automations.duplicate(snap, NOW)
        self.assertEqual(len(found), 1)
        self.assertIn("Morning lights (copy)", found[0]["text"])
        self.assertIn("'Morning lights'", found[0]["text"])

    def test_blueprint_missing_reads_the_filesystem(self):
        with tempfile.TemporaryDirectory() as tmp:
            snap = house(blueprints_dir=tmp)
            snap["automations"][0]["use_blueprint"] = {"path": "vendor/thing.yaml"}
            self.assertEqual(len(automations.blueprint_missing(snap, NOW)), 1)
            os.makedirs(os.path.join(tmp, "automation", "vendor"))
            Path(tmp, "automation", "vendor", "thing.yaml").write_text("x: 1\n")
            self.assertEqual(automations.blueprint_missing(snap, NOW), [])


class TestDeviceChecks(unittest.TestCase):
    def test_unavailable_groups_by_device_and_has_a_floor(self):
        snap = house()
        snap["states"]["light.kitchen"].update(state="unavailable",
                                               last_changed=iso(3 * DAY))
        snap["states"]["light.kitchen_2"] = {
            "state": "unavailable", "attributes": {}, "last_changed": iso(3 * DAY)}
        snap["entities"].append({"entity_id": "light.kitchen_2", "platform": "hue",
                                 "device_id": "dev-hue-1"})
        found = devices.unavailable(snap, NOW)
        self.assertEqual(len(found), 1)
        self.assertIn("Hue bulb", found[0]["text"])
        self.assertIn("2 of its entities", found[0]["detail"])
        self.assertIn("in the Kitchen", found[0]["detail"])
        snap["states"]["light.kitchen"]["last_changed"] = iso(3600)
        snap["states"]["light.kitchen_2"]["last_changed"] = iso(3600)
        self.assertEqual(devices.unavailable(snap, NOW), [])

    def test_unavailable_skips_software_domains_and_restored_entities(self):
        snap = house()
        snap["states"]["automation.morning"].update(state="unavailable",
                                                    last_changed=iso(3 * DAY))
        snap["states"]["light.kitchen"].update(
            state="unavailable", last_changed=iso(3 * DAY),
            attributes={"restored": True})
        self.assertEqual(devices.unavailable(snap, NOW), [])

    def test_battery_low_threshold_and_the_silent_case(self):
        snap = house()
        snap["states"]["sensor.back_door_battery"]["state"] = "9"
        found = devices.battery_low(snap, NOW)
        self.assertEqual(len(found), 1)
        self.assertIn("Back Door sensor", found[0]["text"])
        self.assertIn("9%", found[0]["detail"])
        # healthy level, but nothing heard for ten days
        snap["states"]["sensor.back_door_battery"]["state"] = "100"
        snap["states"]["sensor.back_door_battery"]["last_reported"] = iso(10 * DAY)
        found = devices.battery_low(snap, NOW)
        self.assertEqual(len(found), 1)
        self.assertIn("stopped reporting", found[0]["text"])
        # no last_reported at all (older core): cannot tell, so silent
        del snap["states"]["sensor.back_door_battery"]["last_reported"]
        self.assertEqual(devices.battery_low(snap, NOW), [])

    def test_implausible_uses_the_unit(self):
        snap = house()
        snap["states"]["sensor.hall_temp"]["state"] = "99"
        found = devices.implausible(snap, NOW)
        self.assertEqual(len(found), 1)
        self.assertIn("99°C", found[0]["detail"])
        snap["states"]["sensor.hall_temp"]["attributes"]["unit_of_measurement"] = "°F"
        self.assertEqual(devices.implausible(snap, NOW), [])

    def test_frozen_needs_a_flat_week_and_ignores_zero_and_batteries(self):
        snap = house()
        snap["stats"]["sensor.hall_temp"] = [
            {"start": NOW - d * DAY, "mean": 21, "min": 21, "max": 21}
            for d in range(7)]
        found = devices.frozen(snap, NOW)
        self.assertEqual(len(found), 1)
        self.assertIn("21°C", found[0]["detail"])
        # four days is not a week
        snap["stats"]["sensor.hall_temp"] = snap["stats"]["sensor.hall_temp"][:4]
        self.assertEqual(devices.frozen(snap, NOW), [])
        # a flat zero is an idle plug, not a stuck sensor
        snap["stats"]["sensor.hall_temp"] = [
            {"start": NOW - d * DAY, "mean": 0, "min": 0, "max": 0} for d in range(7)]
        self.assertEqual(devices.frozen(snap, NOW), [])
        # a battery at 100 for a week is a good battery
        snap["stats"] = {"sensor.back_door_battery": [
            {"start": NOW - d * DAY, "mean": 100, "min": 100, "max": 100}
            for d in range(7)]}
        self.assertEqual(devices.frozen(snap, NOW), [])

    def test_restored_groups_by_platform(self):
        snap = house()
        for eid in ("sensor.old_a", "sensor.old_b"):
            snap["states"][eid] = {"state": "unavailable",
                                   "attributes": {"restored": True}}
            snap["entities"].append({"entity_id": eid, "platform": "gone_integration"})
        found = devices.restored(snap, NOW)
        self.assertEqual(len(found), 1)
        self.assertIn("gone_integration", found[0]["text"])
        self.assertIn("sensor.old_a, sensor.old_b", found[0]["detail"])


class TestDashboardCheck(unittest.TestCase):
    def test_dead_reference_in_a_card(self):
        snap = house()
        snap["dashboards"][0]["config"]["views"][0]["cards"].append(
            {"type": "button", "entity": "switch.vanished"})
        result = checks.run_all(snap, NOW, only=["org.dashboard_dead_ref"])
        self.assertEqual(len(result["findings"]), 1)
        self.assertIn("switch.vanished", result["findings"][0]["detail"])
        self.assertIn("Dashboard 'Home'", result["findings"][0]["text"])


class TestForecasts(unittest.TestCase):
    def test_battery_runway_from_a_slope(self):
        snap = house()
        snap["states"]["sensor.back_door_battery"]["state"] = "12"
        snap["battery_stats"]["sensor.back_door_battery"] = [
            {"start": NOW - d * DAY, "mean": 12 + d * 1.5} for d in range(30, 0, -1)]
        found = forecasts.battery_runway(snap, NOW)
        self.assertEqual(len(found), 1)
        self.assertIn("running down", found[0]["text"])
        self.assertIn("About 8 days", found[0]["detail"])
        self.assertIn("1.5% a day", found[0]["detail"])

    def test_battery_runway_is_silent_on_a_flat_or_distant_battery(self):
        snap = house()
        self.assertEqual(forecasts.battery_runway(snap, NOW), [])
        snap["states"]["sensor.back_door_battery"]["state"] = "80"
        snap["battery_stats"]["sensor.back_door_battery"] = [
            {"start": NOW - d * DAY, "mean": 80 + d * 0.5} for d in range(30, 0, -1)]
        # 160 days left is not news
        self.assertEqual(forecasts.battery_runway(snap, NOW), [])

    def test_the_text_is_stable_and_the_number_is_in_the_detail(self):
        snap = house()
        snap["states"]["sensor.back_door_battery"]["state"] = "12"
        snap["battery_stats"]["sensor.back_door_battery"] = [
            {"start": NOW - d * DAY, "mean": 12 + d * 1.5} for d in range(30, 0, -1)]
        a = forecasts.battery_runway(snap, NOW)[0]
        snap["states"]["sensor.back_door_battery"]["state"] = "6"
        b = forecasts.battery_runway(snap, NOW)[0]
        self.assertEqual(a["text"], b["text"])
        self.assertNotEqual(a["detail"], b["detail"])


class TestRunAllBookkeeping(unittest.TestCase):
    def test_a_check_whose_data_is_missing_is_skipped_not_run(self):
        snap = house()
        snap["available"]["traces"] = False
        result = checks.run_all(snap, NOW)
        self.assertIn("auto.trace_error", result["skipped"])
        self.assertNotIn("auto.trace_error", result["ran"])
        self.assertIn("traces", result["skipped"]["auto.trace_error"])
        self.assertIn("auto.dead_ref", result["ran"])

    def test_a_raising_check_is_reported_and_does_not_count_as_run(self):
        def boom(snap, now):
            raise ValueError("bad rule")
        original = checks.CHECKS[0]["run"]
        checks.CHECKS[0]["run"] = boom
        try:
            result = checks.run_all(house(), NOW)
        finally:
            checks.CHECKS[0]["run"] = original
        cid = checks.CHECKS[0]["id"]
        self.assertIn("bad rule", result["errors"][cid])
        self.assertNotIn(cid, result["ran"])
        self.assertEqual(len(result["ran"]), len(checks.CHECKS) - 1)

    def test_findings_carry_the_source_and_title(self):
        snap = house()
        snap["states"]["sensor.hall_temp"]["state"] = "99"
        result = checks.run_all(snap, NOW)
        f = by_source(result)["check:dev.implausible"][0]
        self.assertEqual(f["source_title"], "Device check")
        self.assertEqual(checks.title_for("forecast.battery"), "Forecast")


class TestFindingsStoreIntegration(unittest.TestCase):
    """The three moves the panel makes after a pass."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = (findings_store.FINDINGS_FILE, findings_store.INBOX_DIR,
                     findings_store.SETTLED_FILE, findings_store.STATE_FILE)
        findings_store.FINDINGS_FILE = Path(self.tmp.name) / "findings.json"
        findings_store.INBOX_DIR = Path(self.tmp.name) / "inbox"
        findings_store.SETTLED_FILE = Path(self.tmp.name) / "settled.json"
        findings_store.STATE_FILE = (
            Path(self.tmp.name) / "config" / ".brain" / "findings_state.json")

    def tearDown(self):
        (findings_store.FINDINGS_FILE, findings_store.INBOX_DIR,
         findings_store.SETTLED_FILE, findings_store.STATE_FILE) = self._old
        self.tmp.cleanup()

    def _pass(self, snap):
        result = checks.run_all(snap, NOW)
        created = findings_store.add_many(result["findings"])
        refreshed = findings_store.refresh_details(result["findings"])
        cleared = findings_store.clear_resolved(
            {checks.source_for(c) for c in result["ran"]},
            {findings_store.normalize(f["text"]) for f in result["findings"]})
        return created, refreshed, cleared

    def test_file_refresh_and_clear(self):
        snap = house()
        # 18% on a 1.5%/day slope: twelve days out, and still above the
        # low-battery threshold so only the forecast fires.
        snap["states"]["sensor.back_door_battery"]["state"] = "18"
        snap["battery_stats"]["sensor.back_door_battery"] = [
            {"start": NOW - d * DAY, "mean": 18 + d * 1.5} for d in range(30, 0, -1)]
        created, refreshed, cleared = self._pass(snap)
        self.assertEqual([f["source"] for f in created], ["check:forecast.battery"])
        self.assertEqual((refreshed, cleared), (0, []))
        self.assertIn("About 12 days", created[0]["detail"])
        # next pass: same problem, fewer days — the row is refreshed, not re-filed
        snap["states"]["sensor.back_door_battery"]["state"] = "15.5"
        created, refreshed, cleared = self._pass(snap)
        self.assertEqual(created, [])
        self.assertEqual(refreshed, 1)
        row = findings_store.list_all("open")[0]
        self.assertIn("About 10 days", row["detail"])
        # the battery was changed: the check stops reporting, the row goes
        snap = house()
        created, refreshed, cleared = self._pass(snap)
        self.assertEqual(len(cleared), 1)
        self.assertEqual(findings_store.list_all("open"), [])
        # and nothing was written to the settled ledger — it can come back
        self.assertEqual(findings_store.settled_listing(), [])

    def test_a_skipped_check_clears_nothing(self):
        snap = house()
        snap["states"]["sensor.hall_temp"]["state"] = "99"
        self._pass(snap)
        self.assertEqual(len(findings_store.list_all("open")), 1)
        # the states fetch fails on the next pass: every check needing states is skipped
        snap["available"]["states"] = False
        created, refreshed, cleared = self._pass(snap)
        self.assertEqual(cleared, [])
        self.assertEqual(len(findings_store.list_all("open")), 1)

    def test_clear_leaves_rows_a_person_or_the_fixer_owns(self):
        snap = house()
        snap["states"]["sensor.hall_temp"]["state"] = "99"
        self._pass(snap)
        row = findings_store.list_all("open")[0]
        findings_store.set_status(row["ts"], "fixing")
        _, _, cleared = self._pass(house())
        self.assertEqual(cleared, [])
        self.assertEqual(findings_store.list_all("fixing")[0]["ts"], row["ts"])

    def test_clear_never_touches_another_producers_rows(self):
        findings_store.add("Study found the fridge is dying", source="study:devices",
                           source_title="Study: Device reliability")
        _, _, cleared = self._pass(house())
        self.assertEqual(cleared, [])
        self.assertEqual(len(findings_store.list_all("open")), 1)

    def test_scorecard_reads_the_producer_off_the_settled_entry(self):
        for i in range(3):
            entry, _ = findings_store.add(f"Battery {i} is low", source="check:dev.battery_low",
                                          source_title="Device check")
            findings_store.settle_and_clear(entry["ts"], "fixed")
        entry, _ = findings_store.add("Fridge is haunted", source="health",
                                      source_title="Device Health")
        findings_store.settle_and_clear(entry["ts"], "ignored", note="it is fine")
        card = findings_store.scorecard()
        self.assertEqual(card[0]["source"], "check:dev.battery_low")
        self.assertEqual((card[0]["confirmed"], card[0]["wrong"], card[0]["total"]), (3, 0, 3))
        self.assertEqual(card[1]["title"], "Device Health")
        self.assertEqual((card[1]["confirmed"], card[1]["wrong"]), (0, 1))
        # an entry with no producer scores nothing rather than everything
        findings_store._remember_settled({"text": "anon", "source": ""}, "fixed")
        self.assertEqual(len(findings_store.scorecard()), 2)


class TestSnapshotLoaders(unittest.TestCase):
    def test_yaml_with_home_assistant_tags_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "automations.yaml")
            path.write_text(
                "- id: a1\n  alias: Secret user\n  triggers:\n"
                "    - trigger: time\n      at: !secret wake_time\n"
                "  actions:\n    - action: notify.phone\n      data: !include msg.yaml\n")
            data = snapshot.load_yaml_file(str(path))
            self.assertEqual(data[0]["id"], "a1")
            self.assertIsNone(data[0]["triggers"][0]["at"])
            self.assertIsNone(snapshot.load_yaml_file(str(Path(tmp, "missing.yaml"))))
            Path(tmp, "broken.yaml").write_text("- [unclosed\n")
            self.assertIsNone(snapshot.load_yaml_file(str(Path(tmp, "broken.yaml"))))

    def test_load_configs_only_accepts_the_right_shapes(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "automations.yaml").write_text("key: not-a-list\n")
            Path(tmp, "scripts.yaml").write_text("wake:\n  alias: Wake\n")
            cfg = snapshot.load_configs(tmp)
            self.assertIsNone(cfg["automations"])
            self.assertEqual(cfg["scripts"]["wake"]["alias"], "Wake")
            self.assertIsNone(cfg["scenes"])

    def test_traces_in_both_shapes_home_assistant_has_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            flat = Path(tmp, "flat.json")
            flat.write_text(json.dumps({"data": {
                "automation.a": [{"run_id": "1", "script_execution": "finished"}]}}))
            self.assertEqual(snapshot.load_traces(str(flat))["automation.a"][0]["run_id"], "1")
            nested = Path(tmp, "nested.json")
            nested.write_text(json.dumps({"data": {
                "automation": {"b": {"r1": {"run_id": "r1"}, "r2": {"run_id": "r2"}}}}}))
            rows = snapshot.load_traces(str(nested))["automation.b"]
            self.assertEqual({r["run_id"] for r in rows}, {"r1", "r2"})
            self.assertIsNone(snapshot.load_traces(str(Path(tmp, "nope.json"))))

    def test_statistics_candidates_split_batteries_from_the_rest(self):
        numeric, batteries = snapshot._stat_candidates(house()["states"])
        self.assertEqual(numeric, ["sensor.hall_temp"])
        self.assertEqual(batteries, ["sensor.back_door_battery"])


class TestUtil(unittest.TestCase):
    def test_timestamps_in_every_shape(self):
        self.assertAlmostEqual(_util.parse_ts("2027-01-15T10:00:00+00:00"),
                               1800180000.0 + 0, delta=2e6)
        self.assertEqual(_util.parse_ts(NOW), NOW)
        self.assertEqual(_util.parse_ts(NOW * 1000), NOW)
        self.assertIsNone(_util.parse_ts("yesterday"))
        self.assertIsNone(_util.parse_ts(None))
        self.assertIsNotNone(_util.parse_ts("2026-09-01T00:00:00Z"))

    def test_entity_refs_ignore_service_names_and_prose(self):
        h = _util.House({"states": {"light.kitchen": {}},
                         "services": {"light.turn_on"}})
        refs = h.entity_refs({"action": "light.turn_on",
                              "target": {"entity_id": ["light.kitchen", "light.gone"]},
                              "note": "see v2.0 and e.g. this; states.sensor.x too"})
        self.assertEqual(refs, {"light.kitchen", "light.gone", "sensor.x"})


if __name__ == "__main__":
    unittest.main()
