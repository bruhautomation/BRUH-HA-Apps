#!/usr/bin/env python3
"""Five house checks a real house filed rows against that were not faults.

Each case is the shape the house reported, driven through the real check
over the suite's own fixture house (`test_house_checks.house`), and each
keeps the case the check is FOR — a narrowing that also silenced the real
fault would be the same bug in the other direction.

  * `auto.dead_ref` read template text as entity ids: a string glued into
    an id the template builds (`"switch.pump_" ~ zone`), a method call on
    a loop variable named after a domain, and a script field's example.
  * `auto.already_running` warned an automation that says
    `max_exceeded: silent` — the author's own "drop these quietly".
  * `auto.conflict` read one rule handing over to another (A sets the
    selector B is triggered by) as two rules fighting.
  * `dev.battery_low` told somebody to replace the battery of a mains
    meter whose battery field has never read anything but 0.
  * The history probe called every entity a restart re-stamped "cut",
    which stood `dev.frozen` down while `sys.history_incomplete` said the
    recorder was missing rows it was not.
"""

import datetime as dt
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import actions  # noqa: E402
import checks  # noqa: E402
import ha_data  # noqa: E402
from test_house_checks import DAY, NOW, core_run, house  # noqa: E402

automations = checks.automations
devices = checks.devices
_util = checks._util


# ---------------------------------------------------------------------------
# A. auto.dead_ref and template text
# ---------------------------------------------------------------------------

class TestTemplateTextIsNotAReference(unittest.TestCase):

    def script_house(self, script):
        snap = house()
        snap["scripts"] = {"water_zone": script}
        snap["states"]["script.water_zone"] = {
            "state": "off", "attributes": {"friendly_name": "Water zone"}}
        return snap

    def test_a_string_glued_into_a_built_id_is_not_missing(self):
        snap = self.script_house({
            "alias": "Water zone",
            "sequence": [{"action": "switch.turn_on", "target": {
                "entity_id": '{{ "switch.switch_436" ~ sub_zone }}'}}]})
        self.assertEqual(automations.dead_ref(snap, NOW), [])

    def test_a_method_on_a_loop_variable_is_not_missing(self):
        snap = self.script_house({
            "alias": "Water zone",
            "sequence": [{"variables": {"parts": (
                "{% for zone in zones %}{{ zone.zone_03('-') }}"
                "{% endfor %}")}}]})
        self.assertEqual(automations.dead_ref(snap, NOW), [])

    def test_an_attribute_of_a_loop_variable_is_not_missing(self):
        snap = self.script_house({
            "alias": "Water zone",
            "sequence": [{"variables": {"names": (
                "{% for zone in zones %}{{ zone.friendly_label }}"
                "{% endfor %}")}}]})
        self.assertEqual(automations.dead_ref(snap, NOW), [])

    def test_a_field_example_and_default_are_not_references(self):
        snap = self.script_house({
            "alias": "Water zone",
            "fields": {"sensor": {"example": "sensor.soil_prefix",
                                  "default": "sensor.soil_default",
                                  "selector": {"entity": {"domain": "sensor"}}}},
            "sequence": [{"action": "light.turn_on",
                          "target": {"entity_id": "light.kitchen"}}]})
        self.assertEqual(automations.dead_ref(snap, NOW), [])

    def test_a_real_reference_in_a_template_is_still_reported(self):
        snap = self.script_house({
            "alias": "Water zone",
            "sequence": [{"variables": {"wet": (
                "{% for zone in zones %}{{ states('sensor.vanished') }}"
                "{% endfor %}")}}]})
        found = automations.dead_ref(snap, NOW)
        self.assertEqual(len(found), 1)
        self.assertIn("sensor.vanished", found[0]["detail"])

    def test_a_plain_string_outside_a_template_is_still_a_reference(self):
        # `~` and `(` mean something only inside a template.
        snap = self.script_house({
            "alias": "Water zone",
            "sequence": [{"action": "switch.turn_on",
                          "target": {"entity_id": "switch.switch_436"}}]})
        found = automations.dead_ref(snap, NOW)
        self.assertEqual(len(found), 1)
        self.assertIn("switch.switch_436", found[0]["detail"])

    def test_a_field_example_in_an_automation_is_untouched(self):
        # Only a SCRIPT's fields are hints; nothing else is trimmed.
        snap = house()
        snap["automations"][0]["actions"][0]["target"]["entity_id"] = "light.gone"
        found = automations.dead_ref(snap, NOW)
        self.assertIn("light.gone", found[0]["detail"])


# ---------------------------------------------------------------------------
# B. auto.already_running and max_exceeded: silent
# ---------------------------------------------------------------------------

class TestSilentSkipsAreTheAuthorsChoice(unittest.TestCase):

    def busy_house(self, **cfg):
        snap = house()
        snap["automations"][0].update(cfg)
        snap["traces"]["automation.morning-1"] = [
            core_run(str(i), "failed_single", i * 600) for i in range(3)]
        return snap

    def test_max_exceeded_silent_is_not_reported(self):
        snap = self.busy_house(mode="single", max_exceeded="silent")
        self.assertEqual(automations.already_running(snap, NOW), [])

    def test_core_s_upper_case_spelling_too(self):
        snap = self.busy_house(mode="single", max_exceeded="SILENT")
        self.assertEqual(automations.already_running(snap, NOW), [])

    def test_without_it_the_skips_are_still_reported(self):
        self.assertEqual(len(automations.already_running(
            self.busy_house(mode="single"), NOW)), 1)
        self.assertEqual(len(automations.already_running(
            self.busy_house(max_exceeded="warning"), NOW)), 1)


# ---------------------------------------------------------------------------
# C. auto.conflict and a planned hand-over
# ---------------------------------------------------------------------------

def act(ts, entity_id, state, by):
    return {"ts": ts, "entity_id": entity_id, "name": entity_id,
            "state": state, "cause": "automation", "by": by,
            "by_name": by, "root_user": "", "root_user_name": ""}


BEDTIME = {"id": "3001", "alias": "Bedtime",
           "triggers": [{"trigger": "time", "at": "22:30:00"}],
           "actions": [{"action": "input_select.select_option",
                        "target": {"entity_id": "input_select.house_mode"},
                        "data": {"option": "night"}},
                       {"action": "light.turn_on",
                        "target": {"entity_id": "light.room"}}]}
NIGHT = {"id": "3002", "alias": "Night mode",
         "triggers": [{"trigger": "state",
                       "entity_id": "input_select.house_mode",
                       "to": "night"}],
         "actions": [{"action": "light.turn_off",
                      "target": {"entity_id": "light.room"}}]}
OTHER = {"id": "3003", "alias": "Hall timer",
         "triggers": [{"trigger": "time", "at": "06:00:00"}],
         "actions": [{"action": "light.turn_off",
                      "target": {"entity_id": "light.room"}}]}


def conflict_house(configs, acts):
    states = {"light.room": {"state": "off", "attributes": {}},
              "input_select.house_mode": {"state": "night", "attributes": {}}}
    entities = [{"entity_id": "light.room", "platform": "hue"},
                {"entity_id": "input_select.house_mode",
                 "platform": "input_select"}]
    for cfg, eid in configs:
        states[eid] = {"state": "on", "attributes": {
            "id": cfg["id"], "friendly_name": cfg["alias"]}}
        entities.append({"entity_id": eid, "platform": "automation",
                         "unique_id": cfg["id"]})
    return {"now": NOW, "states": states, "entities": entities,
            "devices": [], "areas": [],
            "automations": [cfg for cfg, _ in configs],
            "actions": {"available": True, "actions": acts,
                        "conflicts": actions.find_conflicts(acts),
                        "overrides": []},
            "available": {}, "errors": {}}


def nights(first, second, nights_=3, gap=2.0):
    """`first` turns the light on and `second` turns it off `gap` seconds
    later, once a night — inside `RACE_S`, so the miner calls each one a
    race the check would report."""
    out = []
    for n in range(nights_):
        t = NOW - (n + 1) * 3600
        out += [act(t, "light.room", "on", first),
                act(t + gap, "light.room", "off", second)]
    return out


class TestAHandOverIsNotAFight(unittest.TestCase):

    def test_a_rule_triggered_by_what_the_first_set_is_its_follow_on(self):
        acts = nights("automation.bedtime", "automation.night_mode")
        snap = conflict_house([(BEDTIME, "automation.bedtime"),
                               (NIGHT, "automation.night_mode")], acts)
        # The miner on its own still calls it a race.
        self.assertEqual(len(snap["actions"]["conflicts"]), 3)
        self.assertEqual(automations.conflicting(snap, NOW), [])

    def test_two_rules_with_no_hand_over_still_race(self):
        acts = nights("automation.bedtime", "automation.hall_timer")
        snap = conflict_house([(BEDTIME, "automation.bedtime"),
                               (OTHER, "automation.hall_timer")], acts)
        self.assertEqual(len(automations.conflicting(snap, NOW)), 1)

    def test_the_miner_reads_the_hand_over_through_its_own_rules(self):
        acts = nights("automation.bedtime", "automation.night_mode")
        feeds = {"automation.bedtime": {"input_select.house_mode",
                                        "light.room"}}
        watches = {"automation.night_mode": {"input_select.house_mode"}}
        self.assertEqual(actions.find_conflicts(
            acts, triggers=watches, feeds=feeds), [])
        # The other way round is not a hand-over: Bedtime does not watch
        # what Night mode sets.
        back = nights("automation.night_mode", "automation.bedtime")
        self.assertEqual(len(actions.find_conflicts(
            back, triggers=watches, feeds=feeds)), 3)


# ---------------------------------------------------------------------------
# D. dev.battery_low and a battery that has only ever read 0
# ---------------------------------------------------------------------------

class TestABatteryThatNeverReadAnything(unittest.TestCase):

    def meter_house(self, means):
        snap = house()
        snap["states"]["sensor.back_door_battery"]["state"] = "0"
        snap["battery_stats"] = {"sensor.back_door_battery": [
            {"start": NOW - d * DAY, "mean": m}
            for d, m in zip(range(len(means), 0, -1), means)]}
        return snap

    def test_zero_all_along_is_not_a_dying_battery(self):
        snap = self.meter_house([0.0] * 60)
        self.assertEqual(devices.battery_low(snap, NOW), [])

    def test_a_battery_that_went_flat_is_still_reported(self):
        snap = self.meter_house([80.0 - d for d in range(55)] + [0.0] * 5)
        found = devices.battery_low(snap, NOW)
        self.assertEqual(len(found), 1)
        self.assertIn("battery is low", found[0]["text"])

    def test_no_history_is_could_not_tell(self):
        snap = self.meter_house([])
        self.assertEqual(len(devices.battery_low(snap, NOW)), 1)
        snap = self.meter_house([0.0] * 3)
        self.assertEqual(len(devices.battery_low(snap, NOW)), 1)


# ---------------------------------------------------------------------------
# E. A restart re-stamps last_changed; it does not cut history
# ---------------------------------------------------------------------------

UTC = dt.timezone.utc
END = dt.datetime.fromtimestamp(NOW, tz=UTC)


def at(seconds_ago: float, micro: int = 0) -> str:
    return (END - dt.timedelta(seconds=seconds_ago)
            ).replace(microsecond=micro).isoformat()


class TestARestartIsNotAHole(unittest.TestCase):

    def restart_house(self, n):
        """`n` sensors whose live clock a restart 2 hours ago reset, each
        with history that last moved two days ago — plus one thermostat
        that really changed after its history stopped."""
        live, series = {}, {}
        for i in range(n):
            eid = f"sensor.re_stamped_{i}"
            live[eid] = {"state": "1", "last_changed": at(7200, micro=i * 10)}
            series[eid] = [{"entity_id": eid, "state": "1",
                            "last_changed": at(2 * DAY)}]
        live["climate.downstairs"] = {"state": "heat",
                                      "last_changed": at(3000)}
        series["climate.downstairs"] = [{"entity_id": "climate.downstairs",
                                         "state": "heat",
                                         "last_changed": at(3 * DAY)}]
        return series, live

    def test_entities_sharing_the_restart_second_are_not_cut(self):
        series, live = self.restart_house(12)
        cut = ha_data.history_cutoffs(series, live, NOW)
        self.assertEqual(set(cut), {"climate.downstairs"})

    def test_a_couple_sharing_a_second_are_still_judged(self):
        series, live = self.restart_house(2)
        cut = ha_data.history_cutoffs(series, live, NOW)
        self.assertEqual(set(cut), {"sensor.re_stamped_0",
                                    "sensor.re_stamped_1",
                                    "climate.downstairs"})

    def test_frozen_and_history_incomplete_agree_after_a_restart(self):
        series, live = self.restart_house(12)
        snap = house()
        snap["history_health"] = {
            "probed": 13, "hours": 96,
            "cut": ha_data.history_cutoffs(series, live, NOW)}
        # One entity is one integration writing late, not the recorder.
        self.assertEqual(_util.history_cut(snap), {})
        result = checks.run_all(snap, NOW, only=["dev.frozen",
                                                 "sys.history_incomplete"])
        self.assertIn("dev.frozen", result["ran"])
        self.assertFalse([r for r in result["findings"]
                          if r["source"] == "check:sys.history_incomplete"])


if __name__ == "__main__":
    unittest.main()
