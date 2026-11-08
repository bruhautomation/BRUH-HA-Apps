#!/usr/bin/env python3
"""A logged "failed to load" is re-checked against the house before it is
filed (#723).

The overnight check turned ONE Home Assistant log line into a serious
finding that a sensor "cannot load" because of a typo at a named file and
line, while the sensor existed, reported a state, and the error was not
logged again. Before a load-failure cause is filed the check now confirms
two things: what the line names is unavailable or missing NOW, and the
error came back after the thing last (re)loaded. A cause whose entity is
healthy is held, with why on the decision trail; one that cannot be
confirmed is filed as information, with no file path and no line number.
A load failure that is both is filed as the run wrote it.
"""
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import sre  # noqa: E402
from test_sre import NOW, collected  # noqa: E402

H = 3600.0
LOGGER = "homeassistant.config"


def iso(seconds_ago):
    import datetime as dt
    return dt.datetime.fromtimestamp(NOW - seconds_ago,
                                     dt.timezone.utc).isoformat()


def typo(eid, *, count=1, last_ago=9 * H):
    return {"name": LOGGER, "level": "ERROR",
            "message": [f"Invalid config for 'template' at templates.yaml, "
                        f"line 27: invalid template for {eid}: unexpected "
                        "'}'"],
            "source": ["config.py", 1], "timestamp": NOW - last_ago,
            "first_occurred": NOW - last_ago - 60, "count": count}


ENTITIES = [{"entity_id": "sensor.attic_fan_speed", "platform": "template"},
            {"entity_id": "sensor.cellar_humidity", "platform": "template"}]


def judged(log, states):
    h = collected(log=log, entities=list(ENTITIES), devices=[],
                  states=states, zha=[], automations=[])
    dig = sre.digest(h, NOW)
    recs = [r["id"] for r in dig["records"] if r["kind"] == "log"]
    parsed = sre.parse_causes({"causes": [{
        "title": "A template sensor cannot load because of a typo in "
                 "templates.yaml at line 27",
        "records": recs[:1], "severity": "serious",
        "detail": "Home Assistant could not load it: templates.yaml line 27 "
                  "has a stray brace.",
        "fix": "Remove the stray brace at templates.yaml line 27, then "
               "reload templates."}]}, dig)
    return sre.hold_transient(parsed["causes"], dig, NOW)


def words(cause):
    return " ".join(str(cause.get(k) or "") for k in ("title", "detail",
                                                       "fix"))


class TestALoadErrorIsReadAgainstTheHouse(unittest.TestCase):
    def test_a_one_off_error_about_a_healthy_sensor_is_not_filed(self):
        kept, held = judged([typo("sensor.attic_fan_speed")], {
            "sensor.attic_fan_speed": {"state": "42", "attributes": {},
                                       "last_changed": iso(2 * H)}})
        self.assertEqual(kept, [])
        self.assertEqual(len(held), 1)
        self.assertIn("reports", held[0]["reason"])
        # The trail row carries no file or line either.
        self.assertNotIn("line 27", sre.trail_rows(held)[0]["reason"])

    def test_a_sensor_back_after_a_reload_is_not_filed_even_if_logged_twice(
            self):
        # Logged twice, then reloaded: it has reported since.
        kept, held = judged([typo("sensor.attic_fan_speed", count=2)], {
            "sensor.attic_fan_speed": {"state": "40", "attributes": {},
                                       "last_changed": iso(1 * H)}})
        self.assertEqual(kept, [])
        self.assertEqual(len(held), 1)

    def test_a_missing_sensor_logged_once_is_information_without_a_place(
            self):
        # Not in the report: the sensor is missing, but the error was logged
        # once and never again, so that it still fails is not confirmed.
        kept, held = judged([typo("sensor.garage_door_angle")], {})
        self.assertEqual(held, [])
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["severity"], "info")
        said = words(kept[0])
        self.assertNotIn("templates.yaml", said)
        self.assertNotIn("line 27", said)

    def test_an_unavailable_sensor_that_keeps_failing_is_filed(self):
        kept, held = judged(
            [typo("sensor.cellar_humidity", count=4, last_ago=0.5 * H)],
            {"sensor.cellar_humidity": {"state": "unavailable",
                                        "attributes": {},
                                        "last_changed": iso(30 * H)}})
        self.assertEqual(held, [])
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["severity"], "serious")


if __name__ == "__main__":
    unittest.main()
