#!/usr/bin/env python3
"""Eight things a real house's reports filed that were not right.

Each case is the shape the house reported, driven through the real code,
and each keeps the case the code is FOR beside it — a narrowing that also
silenced the real thing would be the same bug in the other direction.

  1. `auto.dead_ref` read an id a template BUILDS (a prefix glued to a
     `{{ }}`, a `+`, a `.format`, a `%`) as a missing entity — and a row a
     look set aside still said brAIn could fix it.
  2. The room heat model took an HVAC supply-air probe for a room.
  3. The overnight check filed a browser script error under a phone,
     because the phone's model was in the error's user agent.
  4. The Resident read a sensor coming back from `unavailable` as a change.
  5. A fix run's "also found" notes were filed as findings about devices
     the house no longer has, and about the run itself.
  6. `auto.trace_error` put dotted entity ids in the sentence a person reads.
  7. One error in several automations was one row per automation.
  8. A card's bare-string finding was filed with nothing to do.
"""

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import checks  # noqa: E402
import findings_store  # noqa: E402
import fixer  # noqa: E402
import signals  # noqa: E402
import sre  # noqa: E402
import thermal  # noqa: E402
from test_cases import StoresCase  # noqa: E402
from test_house_checks import NOW, core_run, house  # noqa: E402
from test_sre import collected  # noqa: E402
from test_sre import NOW as SRE_NOW  # noqa: E402

automations = checks.automations
_util = checks._util


# ---------------------------------------------------------------------------
# 1. An id a template builds is not a reference
# ---------------------------------------------------------------------------

class TestABuiltIdIsNotMissing(unittest.TestCase):

    def script_house(self, value):
        snap = house()
        snap["scripts"] = {"water_zone": {
            "alias": "Water zone",
            "sequence": [{"action": "switch.turn_on",
                          "target": {"entity_id": value}}]}}
        snap["states"]["script.water_zone"] = {
            "state": "off", "attributes": {"friendly_name": "Water zone"}}
        return snap

    def test_every_way_of_building_an_id_is_not_a_reference(self):
        for value in (
                "switch.bruh_pump_zone{{ repeat.index }}",
                "{% for i in range(1, 8) %}switch.x_zone{{ i }}{% endfor %}",
                "{{ 'switch.x_zone' + i|string }}",
                "{{ 'switch.x_zone{}'.format(i) }}",
                "{{ 'switch.x_zone%d' % i }}"):
            with self.subTest(value):
                self.assertEqual(
                    automations.dead_ref(self.script_house(value), NOW), [])

    def test_a_states_call_is_still_a_reference(self):
        found = automations.dead_ref(self.script_house(
            "{{ states('switch.vanished') }}"), NOW)
        self.assertEqual(len(found), 1)
        self.assertIn("switch.vanished",
                      [e["entity"] for e in found[0]["evidence"]])

    def test_a_whole_id_in_a_template_is_still_a_reference(self):
        found = automations.dead_ref(self.script_house(
            "{{ 'switch.vanished' if x else 'switch.kitchen' }}"), NOW)
        self.assertEqual(len(found), 1)


class TestAHeldRowOffersNoFix(StoresCase):

    def test_a_row_a_look_set_aside_is_not_fixable(self):
        [row] = findings_store.add_many([{
            "text": "Water zone refers to something missing",
            "source": "check:auto.dead_ref", "entity_id": "script.water_zone",
            "fixable": True, "status": "triaging"}])
        findings_store.hold_after_look(
            row["ts"], "The ids are built by the template.", run_id="inv")
        self.assertFalse(findings_store.get(row["ts"])["fixable"])

    def test_an_open_row_still_is(self):
        [row] = findings_store.add_many([{
            "text": "Water zone refers to something missing",
            "source": "check:auto.dead_ref", "entity_id": "script.water_zone",
            "fixable": True}])
        self.assertTrue(findings_store.get(row["ts"])["fixable"])


# ---------------------------------------------------------------------------
# 2. A machine's air is not a room's
# ---------------------------------------------------------------------------

def thermometer(name, value="21.0"):
    return {"state": value, "attributes": {
        "friendly_name": name, "device_class": "temperature",
        "state_class": "measurement", "unit_of_measurement": "°C"}}


class TestASupplyAirProbeIsNotARoom(unittest.TestCase):

    def test_only_the_room_thermometer_is_a_candidate(self):
        states = {
            "sensor.hall_supply_air": thermometer("Supply air temperature"),
            "sensor.hall_air_handler": thermometer("Hall air handler"),
            "sensor.hall_duct": thermometer("Hall duct temperature"),
            "sensor.hall_temperature": thermometer("Hall temperature"),
        }
        areas = {eid: "Hall" for eid in states}
        rooms, why = thermal.room_candidates_why(
            states, "sensor.outdoor", "°C", areas)
        self.assertEqual(rooms, ["sensor.hall_temperature"])
        for eid in ("sensor.hall_supply_air", "sensor.hall_air_handler",
                    "sensor.hall_duct"):
            self.assertIn("measures a machine", why[eid])


# ---------------------------------------------------------------------------
# 3. A browser's user agent names no device
# ---------------------------------------------------------------------------

class TestAFrontendErrorNamesNoDevice(unittest.TestCase):

    def house(self):
        snap = collected()
        snap["log"] = [{
            "name": "frontend.js.latest.202610010",
            "message": ["Uncaught TypeError: x is undefined at morph-panel.js "
                        "(Mozilla/5.0 (Linux; Android 15; Pixel 9 Pro) "
                        "Home Assistant/2026.9)"],
            "level": "ERROR", "source": ["morph-panel.js", 1],
            "timestamp": SRE_NOW - 600, "count": 3}]
        snap["devices"] = [{"id": "dev-phone", "name": "Pixel 9 Pro"}]
        snap["entities"] = snap["entities"] + [
            {"entity_id": "device_tracker.pixel_9_pro",
             "device_id": "dev-phone", "platform": "mobile_app"}]
        return snap

    def test_the_record_has_no_device_and_the_cause_no_entity(self):
        dig = sre.digest(self.house(), SRE_NOW)
        [rec] = [r for r in dig["records"] if r["kind"] == "log"]
        self.assertFalse(rec.get("devices"))
        parsed = sre.parse_causes({"causes": [{
            "title": "A dashboard script fails", "records": [rec["id"]],
            "severity": "warning", "fix": "Update the card."}]}, dig)
        [row] = sre.rows(parsed["causes"], dig, {"anchors": {}}, SRE_NOW)
        self.assertEqual(row["entity_id"], "")

    def test_a_device_prefers_an_entity_that_is_not_its_tracker(self):
        devices, _ = sre._representatives([
            {"entity_id": "device_tracker.a_phone", "device_id": "d"},
            {"entity_id": "sensor.a_phone_battery", "device_id": "d"}])
        self.assertEqual(devices["d"], "sensor.a_phone_battery")


# ---------------------------------------------------------------------------
# 4. Coming back is not changing
# ---------------------------------------------------------------------------

def state_change(entity_id, to, was, **attrs):
    return {"entity_id": entity_id,
            "old_state": {"entity_id": entity_id, "state": was,
                          "attributes": dict(attrs)},
            "new_state": {"entity_id": entity_id, "state": to,
                          "attributes": dict(attrs)},
            "context": {"id": "01ABC"}}


class TestComingBackIsNotAChange(unittest.TestCase):
    TAMPER = "binary_sensor.hall_tamper"

    def ctx(self):
        return signals.RegistryContext(known={self.TAMPER})

    def test_a_tamper_sensor_coming_back_on_makes_no_signal(self):
        for was in ("unavailable", "unknown"):
            with self.subTest(was):
                self.assertIsNone(signals.from_state_change(
                    state_change(self.TAMPER, "on", was,
                                 device_class="tamper"), self.ctx(), NOW))

    def test_a_tamper_sensor_tripping_still_does(self):
        self.assertIsNotNone(signals.from_state_change(
            state_change(self.TAMPER, "on", "off", device_class="tamper"),
            self.ctx(), NOW))

    def test_a_smoke_detector_coming_back_tripped_still_does(self):
        sig = signals.from_state_change(
            state_change("binary_sensor.hall_smoke", "on", "unavailable",
                         device_class="smoke"),
            signals.RegistryContext(), NOW)
        self.assertIsNotNone(sig)
        self.assertTrue(sig["hot"])


# ---------------------------------------------------------------------------
# 5. "Also found" is about the house
# ---------------------------------------------------------------------------

class TestAlsoFoundIsAboutTheHouse(unittest.TestCase):
    KNOWN = frozenset({"light.kitchen", "switch.pump"})

    def test_a_deleted_device_and_a_note_about_the_run_file_nothing(self):
        self.assertEqual(fixer.house_problems([
            "sensor.old_plug_power and sensor.old_plug_energy still have "
            + "statistics but no entity",
            "I changed only the ids; the rest of the automation is as it was",
        ], self.KNOWN), [])

    def test_a_real_problem_in_the_house_still_files(self):
        real = "light.kitchen turns on at 3am from a second automation"
        self.assertEqual(fixer.house_problems([real], self.KNOWN), [real])

    def test_no_registry_filters_only_the_first_person(self):
        self.assertEqual(fixer.house_problems(
            ["sensor.gone is stale", "I left it alone"], None),
            ["sensor.gone is stale"])

    def test_the_fixer_is_told(self):
        self.assertIn("only problems in the house", fixer.FIX_SYSTEM)

    def test_the_server_files_through_it(self):
        src = (BASE_DIR / "brain" / "panel" / "server.py").read_text()
        self.assertNotIn("for extra in also]", src)
        self.assertNotIn('for extra in parsed["also_found"]', src)
        self.assertIn("fixer.house_problems(", src)
        self.assertEqual(src.count("_also_found_rows("), 3)


# ---------------------------------------------------------------------------
# 6 and 7. A trace error, in plain words and once per error
# ---------------------------------------------------------------------------

class TestTraceErrorsInPlainWords(unittest.TestCase):

    def three(self, errors):
        snap = house()
        for i, err in enumerate(errors, start=1):
            cid = f"rule-{i}"
            eid = f"automation.rule_{i}"
            snap["states"][eid] = {"state": "on", "attributes": {
                "friendly_name": f"Rule {i}", "id": cid,
                "last_triggered": None}}
            snap["entities"].append({"entity_id": eid,
                                     "platform": "automation",
                                     "unique_id": cid})
            snap["traces"][f"automation.{cid}"] = [
                core_run("1", "error", 30, item_id=cid, error=err)]
        return snap

    def test_an_entity_id_in_the_error_is_a_name(self):
        snap = self.three(["Entity switch.x_zone_9 is unavailable"])
        found = [r for r in automations.trace_error(snap, NOW)
                 if r["entity_id"] == "automation.rule_1"]
        self.assertEqual(len(found), 1)
        self.assertNotIn("switch.x_zone_9", found[0]["detail"])
        self.assertNotIn("switch.x_zone_9", found[0]["fix"])
        self.assertIn("switch.x_zone_9",
                      [e["entity"] for e in found[0]["evidence"]])

    def test_one_error_in_three_automations_is_one_row(self):
        snap = self.three(["Template variable error: 'None' has no attribute"] * 3)
        found = automations.trace_error(snap, NOW)
        rules = [r for r in found if "rule" in " ".join(r.get("items") or [])]
        self.assertEqual(len(rules), 1)
        row = rules[0]
        self.assertEqual(sorted(row["items"]), [
            "automation.rule_1", "automation.rule_2", "automation.rule_3"])
        for name in ("Rule 1", "Rule 2", "Rule 3"):
            self.assertIn(name, row["detail"])
        again = automations.trace_error(self.three(
            ["Template variable error: 'None' has no attribute"] * 3), NOW)
        self.assertEqual(row["text"],
                         [r for r in again if r.get("items")][0]["text"])

    def test_two_different_errors_are_two_rows(self):
        snap = self.three(["Timeout talking to the hub",
                           "Timeout talking to the hub", "Service not found"])
        found = [r for r in automations.trace_error(snap, NOW)
                 if r["entity_id"].startswith("automation.rule_")]
        self.assertEqual(len(found), 2)


# ---------------------------------------------------------------------------
# 8. A card's finding says what to do
# ---------------------------------------------------------------------------

class TestACardsFindingSaysWhatToDo(unittest.TestCase):

    def test_a_bare_string_is_filed_with_something_to_do(self):
        import server  # noqa: PLC0415 — heavy, and only this test needs it
        out = server._model_findings(["The garage freezer is drifting warmer"])
        for row in out:
            self.assertTrue(str(row.get("fix") or "").strip(), row)

    def test_a_fix_the_card_wrote_is_kept(self):
        import server  # noqa: PLC0415
        [row] = server._model_findings([{"text": "Hall battery low",
                                         "fix": "Replace the CR2032."}])
        self.assertEqual(row["fix"], "Replace the CR2032.")

    def test_the_overnight_check_never_hands_over_a_look(self):
        self.assertIn("brAIn has already read", sre.SYSTEM)


if __name__ == "__main__":
    unittest.main()
