#!/usr/bin/env python3
"""Three house checks the producer scorecard said were wrong about a house.

Each is driven through the real check over a snapshot shaped like the
house that marked it Wrong, and each keeps a test that the thing the check
is FOR still fires — a narrowing that also silenced the real case would
be the same bug in the other direction.

  * `auto.conflict` — an automation a person sets off by pressing a wall
    button (a scene controller's `event` entity, a device press trigger, a
    Z-Wave value notification) is the person acting, relayed through a
    rule. Its move is a person's move and ends the pairing, exactly as a
    press on the light itself would. A room-mode selector a person picked
    in the UI is the same thing one hop further back. And a Wrong on one
    conflict row has to stop that pairing, whichever of the two rules the
    next row happens to be filed under.
  * `dev.frozen` — a sensor that says it is an estimate publishes one
    figure by design.
  * `forecast.decline` — a drift with an outside cause (the grid's carbon
    intensity, a phone or a car somebody drove, the soil drying out) is not
    a device going wrong.
"""

import asyncio
import importlib
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL))

import actions  # noqa: E402
import corrections  # noqa: E402
import facts_store  # noqa: E402
import findings_store  # noqa: E402
from checks import automations as auto  # noqa: E402
from checks import devices, forecasts  # noqa: E402

NOW = 1_789_800_000.0


# ---------------------------------------------------------------------------
# auto.conflict
# ---------------------------------------------------------------------------

def act(ts, entity_id, state, cause, by="", by_name=""):
    return {"ts": ts, "entity_id": entity_id, "name": entity_id,
            "state": state, "cause": cause, "by": by,
            "by_name": by_name or by, "root_user": "", "root_user_name": ""}


def automation(cid, alias, trigger):
    return {"id": cid, "alias": alias, "triggers": [trigger],
            "actions": [{"action": "light.turn_on",
                         "target": {"entity_id": "light.room"}}]}


def conflict_house(configs, acts, extra_states=None, extra_entities=None):
    states = {"light.room": {"state": "off", "attributes": {}}}
    entities = [{"entity_id": "light.room", "platform": "hue"}]
    for cfg, eid in configs:
        states[eid] = {"state": "on", "attributes": {"id": cfg["id"],
                                                     "friendly_name": cfg["alias"]}}
        entities.append({"entity_id": eid, "platform": "automation",
                         "unique_id": cfg["id"]})
    states.update(extra_states or {})
    entities.extend(extra_entities or [])
    return {
        "now": NOW, "states": states, "entities": entities,
        "devices": [], "areas": [],
        "automations": [cfg for cfg, _eid in configs],
        "actions": {"available": True, "actions": acts,
                    "conflicts": actions.find_conflicts(acts),
                    "overrides": actions.find_overrides(acts),
                    "moves": actions.automation_moves(acts)},
        "available": {}, "errors": {},
    }


MOTION = automation("1001", "Room occupancy",
                    {"trigger": "state", "entity_id": "binary_sensor.room_motion",
                     "to": "off", "for": "00:05:00"})


def fight_with(by):
    """The pressed rule and the motion rule undoing each other both ways
    round, twice — which today is a disagreement by every rule the check
    has."""
    return [
        act(NOW - 7200, "light.room", "on", "automation", by),
        act(NOW - 7140, "light.room", "off", "automation", "automation.room_occupancy"),
        act(NOW - 3600, "light.room", "on", "automation", "automation.room_occupancy"),
        act(NOW - 3570, "light.room", "off", "automation", by),
    ]


class TestAPressedButtonIsAPerson(unittest.TestCase):
    def assert_quiet(self, pressed_cfg, pressed_eid, **house):
        acts = fight_with(pressed_eid)
        snap = conflict_house([(pressed_cfg, pressed_eid),
                               (MOTION, "automation.room_occupancy")], acts, **house)
        # The miner on its own still calls it a fight; the check knows
        # which rule is a person's hand.
        self.assertEqual(len(snap["actions"]["conflicts"]), 2)
        self.assertEqual(auto.conflicting(snap, NOW), [])

    def test_a_scene_controller_event_entity(self):
        cfg = automation("2001", "Wall switch scenes",
                         {"trigger": "state",
                          "entity_id": "event.wall_switch_scene_001"})
        self.assert_quiet(cfg, "automation.wall_switch_scenes",
                          extra_states={"event.wall_switch_scene_001": {
                              "state": "2026-10-07T20:00:00+00:00",
                              "attributes": {"event_type": "KeyPressed"}}})

    def test_a_z_wave_value_notification(self):
        cfg = automation("2002", "Wall switch scenes",
                         {"trigger": "event",
                          "event_type": "zwave_js_value_notification",
                          "event_data": {"command_class": 91}})
        self.assert_quiet(cfg, "automation.wall_switch_scenes")

    def test_the_z_wave_integration_trigger(self):
        cfg = automation("2003", "Wall switch scenes",
                         {"platform": "zwave_js.value_notification",
                          "command_class": 91, "property": "scene"})
        self.assert_quiet(cfg, "automation.wall_switch_scenes")

    def test_a_device_press_trigger(self):
        cfg = automation("2004", "Remote",
                         {"platform": "device", "domain": "zha",
                          "device_id": "abc", "type": "remote_button_short_press",
                          "subtype": "button_1"})
        self.assert_quiet(cfg, "automation.remote")

    def test_a_mode_a_person_picked_in_the_ui(self):
        mode = automation("2005", "Room mode",
                          {"trigger": "state", "entity_id": "input_select.room_mode"})
        acts = fight_with("automation.room_mode")
        # Each of the mode rule's moves follows a person choosing a mode.
        acts += [act(NOW - 7202, "input_select.room_mode", "Bright", "person", "u1"),
                 act(NOW - 3572, "input_select.room_mode", "Off", "person", "u1")]
        acts.sort(key=lambda a: a["ts"])
        snap = conflict_house([(mode, "automation.room_mode"),
                               (MOTION, "automation.room_occupancy")], acts)
        self.assertEqual(len(snap["actions"]["conflicts"]), 2)
        self.assertEqual(auto.conflicting(snap, NOW), [])

    # -- and what it is for, still ----------------------------------------

    def test_a_mode_another_rule_set_is_still_a_rule(self):
        mode = automation("2005", "Room mode",
                          {"trigger": "state", "entity_id": "input_select.room_mode"})
        acts = fight_with("automation.room_mode")
        acts += [act(NOW - 7202, "input_select.room_mode", "Bright",
                     "automation", "automation.schedule"),
                 act(NOW - 3572, "input_select.room_mode", "Off",
                     "automation", "automation.schedule")]
        acts.sort(key=lambda a: a["ts"])
        snap = conflict_house([(mode, "automation.room_mode"),
                               (MOTION, "automation.room_occupancy")], acts)
        self.assertEqual(len(auto.conflicting(snap, NOW)), 1)

    def test_two_ordinary_rules_still_fight(self):
        sunset = automation("2006", "Sunset",
                            {"trigger": "sun", "event": "sunset"})
        snap = conflict_house([(sunset, "automation.sunset"),
                               (MOTION, "automation.room_occupancy")],
                              fight_with("automation.sunset"))
        self.assertEqual(len(auto.conflicting(snap, NOW)), 1)

    def test_a_press_mixed_with_a_timer_is_not_only_a_person(self):
        cfg = automation("2007", "Scenes or bedtime",
                         {"trigger": "state", "entity_id": "event.wall_switch_scene_001"})
        cfg["triggers"].append({"trigger": "time", "at": "23:00:00"})
        snap = conflict_house([(cfg, "automation.scenes_or_bedtime"),
                               (MOTION, "automation.room_occupancy")],
                              fight_with("automation.scenes_or_bedtime"))
        self.assertEqual(len(auto.conflicting(snap, NOW)), 1)


class TestAWrongOnAConflictSticks(unittest.TestCase):
    """Through the real ending into the real check, as the collector builds
    the snapshot: a Wrong on one pair stands down that pair, and the rule
    the homeowner keeps answering about, whichever of the two the next row
    is filed under."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self._facts_old = (facts_store.FACTS_FILE, facts_store.INGEST_STATE_FILE)
        facts_store.FACTS_FILE = root / "facts.json"
        facts_store.INGEST_STATE_FILE = root / "facts-ingest.json"
        self._store_old = (findings_store.FINDINGS_FILE,
                           findings_store.SETTLED_FILE, findings_store.STATE_FILE)
        findings_store.FINDINGS_FILE = root / "findings.json"
        findings_store.SETTLED_FILE = root / "findings-settled.json"
        findings_store.STATE_FILE = root / "findings-state.json"
        self.server = importlib.import_module("server")
        self._facts_srv = self.server.facts_store
        self.server.facts_store = facts_store
        self._inbox_old = self.server.MEMORY_INBOX_DIR
        self.server.MEMORY_INBOX_DIR = root / "inbox"

    def tearDown(self):
        facts_store.FACTS_FILE, facts_store.INGEST_STATE_FILE = self._facts_old
        (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
         findings_store.STATE_FILE) = self._store_old
        self.server.facts_store = self._facts_srv
        self.server.MEMORY_INBOX_DIR = self._inbox_old
        self.tmp.cleanup()

    def snap(self, *pairs):
        acts = []
        base = NOW - 20000
        for i, (a, b) in enumerate(pairs):
            t = base + i * 5000
            acts += [act(t, "light.room", "on", "automation", a),
                     act(t + 60, "light.room", "off", "automation", b),
                     act(t + 1000, "light.room", "on", "automation", b),
                     act(t + 1030, "light.room", "off", "automation", a)]
        snap = {"now": NOW, "states": {}, "entities": [], "devices": [],
                "areas": [],
                "actions": {"available": True, "actions": acts,
                            "conflicts": actions.find_conflicts(acts),
                            "overrides": []}}
        snap["facts"] = facts_store.exception_map(NOW)
        snap["corrections"] = corrections.scope_map(NOW, protected=[])
        return snap

    def press_wrong(self, row):
        entry, _ = findings_store.add(
            row["text"], detail=row["detail"], fix=row["fix"],
            severity=row["severity"], source="check:auto.conflict",
            source_title="Automations undoing each other",
            entity_id=row["entity_id"], evidence=row.get("evidence"))
        asyncio.run(self.server._end_finding(
            findings_store.get(entry["ts"]), self.server.FINDING_VERBS["wrong"],
            "That's okay"))

    def test_the_same_rule_answered_once_is_answered(self):
        # The recurring rule sorts second in every pair, so every row is
        # filed under its partner — the shape that took six presses.
        [row] = auto.conflicting(self.snap(("automation.a_one", "automation.m_rule")), NOW)
        self.press_wrong(row)
        again = auto.conflicting(self.snap(("automation.a_two", "automation.m_rule")), NOW)
        self.assertEqual(again, [])

    def test_a_wrong_written_under_the_second_rule_is_read_for_the_first(self):
        [row] = auto.conflicting(self.snap(("automation.m_rule", "automation.z_rule")), NOW)
        self.assertEqual(row["entity_id"], "automation.m_rule")
        self.press_wrong(row)
        self.assertEqual(
            auto.conflicting(self.snap(("automation.a_one", "automation.m_rule")), NOW), [])

    def test_an_unrelated_pair_still_reports(self):
        [row] = auto.conflicting(self.snap(("automation.a_one", "automation.m_rule")), NOW)
        self.press_wrong(row)
        found = auto.conflicting(self.snap(("automation.x_rule", "automation.y_rule")), NOW)
        self.assertEqual(len(found), 1)


# ---------------------------------------------------------------------------
# dev.frozen
# ---------------------------------------------------------------------------

def frozen_house(attrs, registry=None, value="104"):
    days = [{"start": NOW - (8 - i) * 86400, "mean": 104.0, "min": 104.0,
             "max": 104.0} for i in range(8)]
    eid = "sensor.plug_current"
    return {"now": NOW,
            "states": {eid: {"state": value,
                             "last_changed": "2026-09-01T10:00:00+00:00",
                             "last_reported": "2026-09-19T10:00:00+00:00",
                             "last_updated": "2026-09-19T10:00:00+00:00",
                             "attributes": {"device_class": "current",
                                            "unit_of_measurement": "mA",
                                            "state_class": "measurement",
                                            **attrs}}},
            "entities": [{"entity_id": eid, **(registry or {})}],
            "stats": {eid: days}, "available": {}, "errors": {}}


class TestAnEstimateIsConstantByDesign(unittest.TestCase):
    def test_a_sensor_named_as_an_estimate(self):
        snap = frozen_house({"friendly_name": "Plug Estimated current"})
        self.assertEqual(devices.frozen(snap, NOW), [])

    def test_an_estimate_named_by_its_integration(self):
        snap = frozen_house({"friendly_name": "Plug current"},
                            {"original_name": "Estimated current"})
        self.assertEqual(devices.frozen(snap, NOW), [])

    def test_a_nominal_or_rated_figure(self):
        for name in ("Charger nominal current", "Rated current"):
            snap = frozen_house({"friendly_name": name})
            self.assertEqual(devices.frozen(snap, NOW), [], name)

    def test_a_real_stuck_current_sensor_is_still_reported(self):
        snap = frozen_house({"friendly_name": "Plug current"})
        self.assertEqual(len(devices.frozen(snap, NOW)), 1)

    def test_a_word_inside_another_word_is_not_the_word(self):
        # "estimate" inside a longer word is not a claim about the figure.
        snap = frozen_house({"friendly_name": "Underestimatedpump current"})
        self.assertEqual(len(devices.frozen(snap, NOW)), 1)


# ---------------------------------------------------------------------------
# forecast.decline
# ---------------------------------------------------------------------------

def drift_house(eid, attrs, registry=None, unit="°C", devices_=None,
                more_entities=None):
    import datetime as dt

    import baselines
    bucket = str(baselines.hour_of_week(NOW, dt.timezone.utc))
    states = {eid: {"state": "20.0",
                    "attributes": {"state_class": "measurement",
                                   "unit_of_measurement": unit, **attrs},
                    "last_changed": "", "last_updated": ""}}
    entities = [{"entity_id": eid, **(registry or {})}]
    for extra in more_entities or []:
        entities.append(extra)
        states.setdefault(extra["entity_id"], {"state": "home", "attributes": {}})
    store = {eid: {"unit": unit, "samples": 672,
                   "overall": {"median": 20.0, "spread": 0.5, "n": 672},
                   "buckets": {bucket: {"median": 20.0, "spread": 0.5, "n": 4}},
                   "trend": {"per_day": -0.3, "move": -8.0, "days": 28.0,
                             "noise": 0.4, "spreads": 9.0, "consistent": True,
                             "points": 672}}}
    return {"now": NOW, "states": states, "entities": entities,
            "devices": devices_ or [], "areas": [],
            "baselines": {"built_at": int(NOW - 3600), "tz": "UTC",
                          "days": 28, "entities": store}}


class TestADriftWithAnOutsideCause(unittest.TestCase):
    def test_grid_carbon_intensity(self):
        snap = drift_house("sensor.grid_carbon_intensity",
                           {"friendly_name": "Grid carbon intensity"},
                           {"platform": "co2signal"}, unit="gCO2eq/kWh")
        self.assertEqual(forecasts.decline(snap, NOW), [])

    def test_a_price_per_kwh(self):
        snap = drift_house("sensor.tariff", {"friendly_name": "Tariff"},
                           unit="EUR/kWh")
        self.assertEqual(forecasts.decline(snap, NOW), [])

    def test_a_reading_from_something_a_person_carries(self):
        # A car or a phone: the device also reports where it is.
        snap = drift_house(
            "sensor.car_charge_level", {"friendly_name": "Car charge level"},
            {"device_id": "car1", "platform": "car_brand"}, unit="%",
            devices_=[{"id": "car1", "name": "Car"}],
            more_entities=[{"entity_id": "device_tracker.car",
                            "device_id": "car1", "platform": "car_brand"}])
        self.assertEqual(forecasts.decline(snap, NOW), [])

    def test_a_phone_sensor(self):
        snap = drift_house("sensor.phone_storage", {"friendly_name": "Phone storage"},
                           {"platform": "mobile_app"}, unit="%")
        self.assertEqual(forecasts.decline(snap, NOW), [])

    def test_soil_drying_out(self):
        snap = drift_house("sensor.bed_soil_moisture",
                           {"friendly_name": "Bed soil moisture",
                            "device_class": "moisture"}, unit="%")
        self.assertEqual(forecasts.decline(snap, NOW), [])

    def test_the_weather(self):
        for cls in ("precipitation", "wind_speed", "irradiance",
                    "atmospheric_pressure"):
            snap = drift_house("sensor.outside_thing",
                               {"friendly_name": "Thing", "device_class": cls},
                               unit="x")
            self.assertEqual(forecasts.decline(snap, NOW), [], cls)

    def test_a_weather_integration(self):
        snap = drift_house("sensor.home_temperature",
                           {"friendly_name": "Home temperature",
                            "device_class": "temperature"},
                           {"platform": "met"})
        self.assertEqual(forecasts.decline(snap, NOW), [])

    # -- and what it is for, still ----------------------------------------

    def test_a_freezer_warming_still_fires(self):
        snap = drift_house("sensor.freezer_temperature",
                           {"friendly_name": "Freezer temperature",
                            "device_class": "temperature"},
                           {"platform": "zha"})
        self.assertEqual(len(forecasts.decline(snap, NOW)), 1)

    def test_indoor_humidity_still_fires(self):
        snap = drift_house("sensor.bathroom_humidity",
                           {"friendly_name": "Bathroom humidity",
                            "device_class": "humidity"}, unit="%")
        self.assertEqual(len(forecasts.decline(snap, NOW)), 1)


if __name__ == "__main__":
    unittest.main()
