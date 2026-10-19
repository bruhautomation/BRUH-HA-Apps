#!/usr/bin/env python3
"""A cause names only what its own records are about (#284, #285).

The overnight check filed a template-error finding whose title named a
different sensor from the one the template reads, and a fix that named an
integration entry that was nowhere in the finding's own records. A
cause's detail and fix lose the sentence that names a device, an entity or
an integration its cited records are not about, a title that does is
replaced by one naming the cause's own record, and each such cause is
counted (`unrelated`).
"""

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import sre  # noqa: E402
from test_sre import NOW  # noqa: E402
from test_sre_causes import house, log_row  # noqa: E402

TEMPLATE_LOG = log_row(
    "Template variable warning: 'None' has no attribute 'x' when rendering "
    "'{{ states.sensor.solar_forecast_today.attributes.x }}'",
    logger="homeassistant.helpers.template")
GARAGE_LOG = log_row("Garage Plug did not respond at 10.0.0.1",
                     logger="homeassistant.components.tplink",
                     level="ERROR", count=3)


def states():
    return {
        "sensor.solar_forecast_today": {"attributes": {
            "friendly_name": "Solar forecast today"}},
        "sensor.garage_plug_power": {"attributes": {
            "friendly_name": "Garage Plug power"}},
        "sensor.outdoor_temperature": {"attributes": {
            "friendly_name": "Outdoor temperature"}},
    }


def template_cause(dig, **cause):
    [rid] = [r["id"] for r in dig["records"] if r["kind"] == "log"
             and "Template" in r["message"]]
    base = {"title": "A template keeps warning about the solar forecast",
            "detail": "The log repeats twelve times.",
            "fix": "Give the template a default for the missing attribute.",
            "records": [rid]}
    base.update(cause)
    return sre.parse_causes({"causes": [base]}, dig)


class TestACauseNamesOnlyItsOwnRecords(unittest.TestCase):
    def setUp(self):
        self.dig = sre.digest(house([TEMPLATE_LOG, GARAGE_LOG],
                                    states=states()), NOW)

    def test_a_fix_naming_another_integration_entry_loses_that_sentence(self):
        parsed = template_cause(
            self.dig, fix="Give the template a default for the missing "
            "attribute. Then reload the Garage Plug integration entry.")
        [cause] = parsed["causes"]
        self.assertNotIn("Garage Plug", cause["fix"])
        self.assertIn("default", cause["fix"])
        self.assertEqual(parsed["unrelated"], 1)

    def test_a_detail_naming_another_entity_loses_that_sentence(self):
        parsed = template_cause(
            self.dig, detail="The log repeats twelve times. It reads "
            "sensor.outdoor_temperature, which is unavailable.")
        [cause] = parsed["causes"]
        self.assertNotIn("outdoor", cause["detail"].lower())
        self.assertIn("twelve", cause["detail"])

    def test_a_title_naming_a_different_sensor_names_the_one_read(self):
        parsed = template_cause(
            self.dig, title="The Outdoor temperature template keeps failing")
        [cause] = parsed["causes"]
        self.assertNotIn("Outdoor", cause["title"])
        self.assertIn("Solar forecast today", cause["title"])
        self.assertEqual(parsed["unrelated"], 1)

    def test_a_cause_about_its_own_records_is_left_alone(self):
        parsed = template_cause(
            self.dig, detail="The Solar forecast today template reads "
            "sensor.solar_forecast_today and the attribute is missing.")
        [cause] = parsed["causes"]
        self.assertIn("sensor.solar_forecast_today", cause["detail"])
        self.assertEqual(parsed["unrelated"], 0)


if __name__ == "__main__":
    unittest.main()
