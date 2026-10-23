#!/usr/bin/env python3
"""Three ways an overnight cause was wrong on a real house.

  * **No entity.** A cause about one device or one sensor whose log line
    names it was filed with `entity_id: ""` — so it could not be ignored per
    entity, linked to the device, or matched with another check's row. A
    log record now carries the entities (and the devices, by name) its
    message names, and a cause whose cited records name exactly one is
    filed under it.
  * **Somebody else's template.** A log-spam cause told the owner to add a
    default to "the template" reading an entity that belongs only to an
    integration, with nothing of theirs referring to it. A log record now
    says whether anything the owner wrote refers to the entity it names
    (`referenced_by_you`), the prompt says what that means, and a fix that
    tells them to edit a template over a record saying nothing of theirs
    refers to it is replaced with one naming the integration.
  * **One card, three problems.** A cause titled about one Z-Wave node also
    carried a second node's decode errors and a third device's errors, with
    a fix for the first. A cause is one problem: cited records about other
    devices are taken off it (and the sentences about them out of its
    detail), and counted.
"""

import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import sre  # noqa: E402
from test_sre import NOW, collected  # noqa: E402


def log_row(message, logger="homeassistant.components.forecast_solar",
            level="WARNING", count=12):
    return {"name": logger, "message": [message], "level": level,
            "source": ["x.py", 1], "timestamp": NOW - 60, "count": count}


ENTITIES = [
    {"entity_id": "switch.landing_plug", "device_id": "dev-plug",
     "platform": "zha"},
    {"entity_id": "sensor.aaa_forecast_tomorrow", "device_id": "dev-solar",
     "platform": "forecast_solar"},
    {"entity_id": "sensor.solar_forecast_today", "device_id": "dev-solar",
     "platform": "forecast_solar"},
    {"entity_id": "switch.garage_plug", "device_id": "dev-garage",
     "platform": "tplink"},
    {"entity_id": "sensor.garage_plug_power", "device_id": "dev-garage",
     "platform": "tplink"},
]
DEVICES = [{"id": "dev-garage", "name": "Garage Plug"},
           {"id": "dev-solar", "name": "Solar forecast"}]


def house(log, **over):
    return collected(log=log, entities=list(ENTITIES), devices=list(DEVICES),
                     **over)


def one_row(h, records_of, **cause):
    dig = sre.digest(h, NOW)
    recs = records_of(dig)
    parsed = sre.parse_causes({"causes": [{"title": "A cause",
                                           "records": recs, **cause}]}, dig)
    return dig, parsed, sre.rows(parsed["causes"], dig, {"anchors": {}}, NOW)


def logs(dig):
    return [r["id"] for r in dig["records"] if r["kind"] == "log"]


class TestALogLineNamesItsEntity(unittest.TestCase):
    def test_the_entity_the_message_names_is_the_subject(self):
        h = house([log_row("Error fetching sensor.solar_forecast_today: "
                           "rate limited")])
        row = one_row(h, logs)[2][0]
        self.assertEqual(row["entity_id"], "sensor.solar_forecast_today")

    def test_a_template_warning_with_no_integration_still_names_one(self):
        h = house([log_row("Template variable warning: 'None' has no "
                           "attribute 'x' when rendering "
                           "'{{ states.sensor.solar_forecast_today.attributes.x }}'",
                           logger="homeassistant.helpers.template")])
        row = one_row(h, logs)[2][0]
        self.assertEqual(row["entity_id"], "sensor.solar_forecast_today")

    def test_a_device_named_in_the_message_is_mapped_to_its_entity(self):
        h = house([log_row("Garage Plug did not respond at 10.0.0.1",
                           logger="homeassistant.components.tplink",
                           level="ERROR", count=3)])
        row = one_row(h, logs)[2][0]
        self.assertIn(row["entity_id"],
                      ("switch.garage_plug", "sensor.garage_plug_power"))

    def test_the_model_may_name_the_logs_entity(self):
        h = house([log_row("Error fetching sensor.solar_forecast_today")])
        _dig, parsed, _rows = one_row(
            h, logs, entity_id="sensor.solar_forecast_today")
        self.assertEqual(parsed["causes"][0]["entity_id"],
                         "sensor.solar_forecast_today")

    def test_a_message_naming_nothing_known_names_nothing(self):
        h = house([log_row("Error fetching sensor.not_in_this_house",
                           logger="custom_components.nobody")])
        dig = sre.digest(h, NOW)
        [rec] = [r for r in dig["records"] if r["kind"] == "log"]
        self.assertEqual(rec.get("entities") or [], [])


TEMPLATE_FIX = ("Add a default to the template that reads "
                "sensor.solar_forecast_today so it stops warning.")


class TestNotYourTemplate(unittest.TestCase):
    def cause_for(self, user_text):
        h = house([log_row("Template variable warning: 'None' has no "
                           "attribute 'x' when rendering "
                           "'{{ states.sensor.solar_forecast_today.attributes.x }}'")],
                  user_text=user_text)
        dig = sre.digest(h, NOW)
        parsed = sre.parse_causes({"causes": [{
            "title": "A template keeps warning about the solar forecast",
            "detail": "The log repeats twelve times. Your template reads an "
                      "attribute that is missing.",
            "fix": TEMPLATE_FIX, "records": logs(dig)}]}, dig)
        return dig, parsed

    def test_the_record_says_nothing_of_yours_refers_to_it(self):
        dig, _ = self.cause_for("automation:\n  - id: x\n")
        [rec] = [r for r in dig["records"] if r["kind"] == "log"]
        self.assertIs(rec["referenced_by_you"], False)
        self.assertIn("referenced_by_you", sre.SYSTEM)

    def test_the_fix_names_the_integration_not_a_template(self):
        _dig, parsed = self.cause_for("automation:\n  - id: x\n")
        [cause] = parsed["causes"]
        self.assertNotIn("template", cause["fix"].lower())
        # Named as Home Assistant shows it, never by its domain (#340).
        self.assertIn("Forecast Solar", cause["fix"])
        self.assertNotIn("forecast_solar", cause["fix"])
        self.assertNotIn("template", cause["detail"].lower())
        self.assertEqual(parsed["rewritten"], 1)

    def test_a_template_of_yours_that_reads_it_keeps_the_fix(self):
        dig, parsed = self.cause_for(
            "template:\n  - sensor:\n      - state: "
            "\"{{ states('sensor.solar_forecast_today') }}\"\n")
        [rec] = [r for r in dig["records"] if r["kind"] == "log"]
        self.assertIs(rec["referenced_by_you"], True)
        self.assertEqual(parsed["causes"][0]["fix"], TEMPLATE_FIX)

    def test_configs_that_could_not_be_read_change_nothing(self):
        dig, parsed = self.cause_for(None)
        [rec] = [r for r in dig["records"] if r["kind"] == "log"]
        self.assertNotIn("referenced_by_you", rec)
        self.assertEqual(parsed["causes"][0]["fix"], TEMPLATE_FIX)

    def test_a_template_entity_is_the_owners_own(self):
        h = house([log_row("Error rendering sensor.my_template_total",
                           logger="homeassistant.helpers.template")],
                  user_text="")
        h["entities"].append({"entity_id": "sensor.my_template_total",
                              "platform": "template"})
        [rec] = [r for r in sre.digest(h, NOW)["records"] if r["kind"] == "log"]
        self.assertIs(rec["referenced_by_you"], True)


class TestTheUserTextReader(unittest.TestCase):
    def test_reads_the_owners_yaml_and_not_secrets(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "configuration.yaml").write_text("template: !include t.yaml\n")
            (root / "t.yaml").write_text("- sensor: sensor.mine\n")
            (root / "secrets.yaml").write_text("k: sensor.secret_one\n")
            (root / "packages").mkdir()
            (root / "packages" / "p.yaml").write_text("x: sensor.in_package\n")
            (root / ".storage").mkdir()
            (root / ".storage" / "core.config_entries").write_text(
                '{"data": {"entries": [{"domain": "template", "options": '
                '{"state": "{{ states(\'sensor.ui_helper_reads\') }}"}}, '
                '{"domain": "zha", "options": {"x": "sensor.not_yours"}}]}}')
            text = sre.read_user_text(str(root))
        self.assertIn("sensor.mine", text)
        self.assertIn("sensor.in_package", text)
        self.assertIn("sensor.ui_helper_reads", text)
        self.assertNotIn("sensor.secret_one", text)
        self.assertNotIn("sensor.not_yours", text)

    def test_no_config_dir_is_could_not_tell(self):
        self.assertIsNone(sre.read_user_text("/nonexistent/brain-test"))


ZW_ENTITIES = [
    {"entity_id": "sensor.cellar_pump_status", "device_id": "dev-a",
     "platform": "zwave_js", "unique_id": "1.2-node_status",
     "translation_key": "node_status", "entity_category": "diagnostic"},
    {"entity_id": "switch.cellar_pump", "device_id": "dev-a",
     "platform": "zwave_js", "unique_id": "1.2-37"},
    {"entity_id": "sensor.attic_fan_status", "device_id": "dev-b",
     "platform": "zwave_js", "unique_id": "1.3-node_status",
     "translation_key": "node_status", "entity_category": "diagnostic"},
    {"entity_id": "switch.attic_fan", "device_id": "dev-b",
     "platform": "zwave_js", "unique_id": "1.3-37"},
]


def zw_house(**over):
    return collected(
        entities=list(ZW_ENTITIES) + list(ENTITIES),
        devices=[{"id": "dev-a", "name": "Cellar pump"},
                 {"id": "dev-b", "name": "Attic fan"}] + list(DEVICES),
        states={"sensor.cellar_pump_status": {"state": "dead"},
                "sensor.attic_fan_status": {"state": "dead"}}, **over)


class TestOneCauseIsOneProblem(unittest.TestCase):
    def test_a_second_node_is_taken_off_the_cause(self):
        dig = sre.digest(zw_house(), NOW)
        parsed = sre.parse_causes({"causes": [{
            "title": "The cellar pump node is dead",
            "detail": "The Cellar pump node is marked dead. The Attic fan "
                      "node shows decode errors too.",
            "fix": "Re-interview the cellar pump.",
            "records": ["zw:dev-a", "zw:dev-b"]}]}, dig)
        [cause] = parsed["causes"]
        self.assertEqual(cause["records"], ["zw:dev-a"])
        self.assertNotIn("Attic", cause["detail"])
        self.assertIn("Cellar pump", cause["detail"])
        self.assertEqual(parsed["bundled"], 1)

    def test_a_log_about_a_third_device_is_taken_off_too(self):
        h = zw_house(log=[log_row("Garage Plug did not respond",
                                  logger="homeassistant.components.tplink",
                                  level="ERROR", count=3)])
        dig = sre.digest(h, NOW)
        parsed = sre.parse_causes({"causes": [{
            "title": "The cellar pump node is dead",
            "records": ["zw:dev-a"] + logs(dig)}]}, dig)
        self.assertEqual(parsed["causes"][0]["records"], ["zw:dev-a"])

    def test_the_models_entity_decides_which_device_it_is_about(self):
        dig = sre.digest(zw_house(), NOW)
        parsed = sre.parse_causes({"causes": [{
            "title": "The attic fan node is dead",
            "records": ["zw:dev-a", "zw:dev-b"],
            "entity_id": "switch.attic_fan"}]}, dig)
        self.assertEqual(parsed["causes"][0]["records"], ["zw:dev-b"])

    def test_an_entity_none_of_its_records_name_is_not_believed(self):
        dig = sre.digest(zw_house(), NOW)
        parsed = sre.parse_causes({"causes": [{
            "title": "The cellar pump node is dead",
            "records": ["zw:dev-a"], "entity_id": "switch.landing_plug"}]}, dig)
        [cause] = parsed["causes"]
        self.assertEqual(cause["entity_id"], "")
        [row] = sre.rows(parsed["causes"], dig, {"anchors": {}}, NOW)
        self.assertEqual(row["entity_id"], "switch.cellar_pump")

    def test_a_router_and_the_sensors_behind_it_are_one_problem(self):
        dig = sre.digest(collected(), NOW)
        auto = next(r["id"] for r in dig["records"] if r["kind"] == "automation")
        recs = [auto, "zha:aa:aa:aa:aa:aa:aa:aa:01",
                "zha:bb:bb:bb:bb:bb:bb:bb:02"]
        parsed = sre.parse_causes({"causes": [{
            "title": "Bedtime switches off the only router upstairs",
            "records": recs}]}, dig)
        self.assertEqual(parsed["causes"][0]["records"], recs)
        self.assertEqual(parsed["bundled"], 0)

    def test_the_prompt_says_one_cause_per_problem(self):
        self.assertIn("one problem", sre.SYSTEM.lower())


if __name__ == "__main__":
    unittest.main()
