#!/usr/bin/env python3
"""A passing error is not a problem, and "reload it" is not the owner's job.

The overnight check filed "needs you" problems for one-off log bursts
around restarts — a cloud reconnect, a Bluetooth drop, a Cast retry, an
add-on restarting — while every entity of the integration was working by
the time anybody read the card, and its fix told the owner to reload the
integration. Before a log cause is filed, brAIn now asks two things of the
house as it is at the review: are the integration's entities working, and
is it still logging the error now. A cause that fails either is held, with
why on the decision trail; one whose things have been down for hours and
which is still erroring is filed, and its fix never hands the owner a
reload brAIn can make itself. An integration whose setup failed is
`sys.entry_failed`'s (which brAIn's own overnight healing reloads), not a
second card.

The examples are deliberately not the ones the report named: a Tuya cloud
burst, a Roborock vacuum gone for the afternoon, a Ring doorbell that came
back, and log lines from a library logger that names no entities.
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


def iso(seconds_ago):
    import datetime as dt
    return dt.datetime.fromtimestamp(NOW - seconds_ago, dt.timezone.utc).isoformat()


def log_row(message, logger, *, last_ago, first_ago, count=40, level="ERROR"):
    return {"name": logger, "message": [message], "level": level,
            "source": ["x.py", 1], "timestamp": NOW - last_ago,
            "first_occurred": NOW - first_ago, "count": count}


ENTITIES = [
    {"entity_id": "switch.tuya_heater", "device_id": "dev-heater", "platform": "tuya"},
    {"entity_id": "sensor.tuya_heater_power", "device_id": "dev-heater", "platform": "tuya"},
    {"entity_id": "vacuum.roborock_s7", "device_id": "dev-robo", "platform": "roborock"},
    {"entity_id": "sensor.roborock_s7_battery", "device_id": "dev-robo", "platform": "roborock"},
    {"entity_id": "camera.ring_front", "device_id": "dev-ring", "platform": "ring"},
]
DEVICES = [{"id": "dev-heater", "name": "Study heater"},
           {"id": "dev-robo", "name": "Roborock S7"},
           {"id": "dev-ring", "name": "Front doorbell"}]


def state(value, changed_ago):
    return {"state": value, "last_changed": iso(changed_ago), "attributes": {}}


def house(log, states, entries=()):
    h = collected(log=log, entities=list(ENTITIES), devices=list(DEVICES),
                  states=states)
    h["config_entries"] = list(entries)
    return h


def judged(h, fix="Reload the integration from Settings > Devices & services."):
    dig = sre.digest(h, NOW)
    recs = [r["id"] for r in dig["records"] if r["kind"] == "log"]
    parsed = sre.parse_causes({"causes": [{
        "title": "The integration keeps failing", "records": recs[:1],
        "detail": "It logged errors.", "fix": fix}]}, dig)
    kept, held = sre.hold_transient(parsed["causes"], dig, NOW)
    return parsed, kept, held


TUYA = "homeassistant.components.tuya"
ROBO = "homeassistant.components.roborock"
RING = "homeassistant.components.ring"


class TestABurstThatIsOverIsHeld(unittest.TestCase):

    def test_a_cloud_burst_hours_ago_with_everything_working_is_held(self):
        h = house([log_row("Error communicating with Tuya cloud: Connection reset",
                           TUYA, last_ago=8 * H, first_ago=8.2 * H)],
                  {"switch.tuya_heater": state("on", 30 * H),
                   "sensor.tuya_heater_power": state("812", 60)})
        _parsed, kept, held = judged(h)
        self.assertEqual(kept, [])
        [one] = held
        self.assertEqual(one["kind"], "transient")
        self.assertIn("working", one["reason"])

    def test_still_logging_but_every_entity_works_is_held(self):
        """A retry loop that keeps the entities fed is noise, not a fault."""
        h = house([log_row("Error communicating with Tuya cloud: Connection reset",
                           TUYA, last_ago=120, first_ago=20 * H, count=300)],
                  {"switch.tuya_heater": state("off", 2 * H),
                   "sensor.tuya_heater_power": state("0", 300)})
        _parsed, kept, held = judged(h)
        self.assertEqual(kept, [])
        self.assertEqual(held[0]["kind"], "transient")

    def test_down_now_but_quiet_in_the_latest_window_is_held(self):
        """Down, and no error since: the log is not what to file it on."""
        h = house([log_row("Ring doorbell went away: timed out", RING,
                           last_ago=6 * H, first_ago=7 * H)],
                  {"camera.ring_front": state("unavailable", 7 * H)})
        _parsed, kept, held = judged(h)
        self.assertEqual(kept, [])
        self.assertIn("since", held[0]["reason"])

    def test_down_and_erroring_but_only_for_minutes_is_held(self):
        h = house([log_row("Failed to connect to Roborock: timeout", ROBO,
                           last_ago=60, first_ago=0.3 * H)],
                  {"vacuum.roborock_s7": state("unavailable", 0.3 * H),
                   "sensor.roborock_s7_battery": state("unavailable", 0.3 * H)})
        _parsed, kept, held = judged(h)
        self.assertEqual(kept, [])
        self.assertEqual(held[0]["kind"], "transient")

    def test_a_library_logger_naming_nothing_is_judged_by_its_own_span(self):
        """No entity to ask: a burst that ended is held on the log alone."""
        h = house([log_row("Connection lost to broker", "paho.mqtt.client",
                           last_ago=9 * H, first_ago=9.1 * H)], {})
        _parsed, kept, held = judged(h)
        self.assertEqual(kept, [])
        self.assertEqual(held[0]["kind"], "transient")


class TestABrokenIntegrationIsFiled(unittest.TestCase):

    def roborock_down(self, fix="Reload the integration from Settings > Devices & services."):
        h = house([log_row("Failed to connect to Roborock: timeout", ROBO,
                           last_ago=300, first_ago=6 * H, count=200)],
                  {"vacuum.roborock_s7": state("unavailable", 6 * H),
                   "sensor.roborock_s7_battery": state("unavailable", 6 * H)})
        return judged(h, fix)

    def test_down_for_hours_and_still_erroring_is_kept(self):
        _parsed, kept, held = self.roborock_down()
        self.assertEqual(held, [])
        self.assertEqual(len(kept), 1)

    def test_its_fix_never_hands_the_owner_a_reload(self):
        [cause] = self.roborock_down()[1]
        for sentence in cause["fix"].split(". "):
            if "reload" in sentence.lower():
                self.assertIn("brAIn", sentence, cause["fix"])

    def test_the_fix_written_by_code_does_not_either(self):
        [cause] = self.roborock_down(fix="")[1]
        for sentence in cause["fix"].split(". "):
            if "reload" in sentence.lower():
                self.assertIn("brAIn", sentence, cause["fix"])

    def test_a_state_list_that_could_not_be_read_holds_nothing(self):
        h = house([log_row("Error communicating with Tuya cloud", TUYA,
                           last_ago=8 * H, first_ago=8.2 * H)], {})
        h["available"]["states"] = False
        _parsed, kept, held = judged(h)
        self.assertEqual(held, [])
        self.assertEqual(len(kept), 1)

    def test_a_failed_setup_is_the_entry_checks_and_healings(self):
        h = house([log_row("Failed to connect to Roborock: timeout", ROBO,
                           last_ago=300, first_ago=30 * H, count=200)],
                  {}, entries=[{"entry_id": "e1", "domain": "roborock",
                                "title": "Roborock", "state": "setup_retry"}])
        _parsed, kept, held = judged(h)
        self.assertEqual(kept, [])
        self.assertEqual(held[0]["kind"], "claimed")


class TestTheTrailSaysWhy(unittest.TestCase):

    def test_held_causes_are_trail_rows(self):
        h = house([log_row("Error communicating with Tuya cloud", TUYA,
                           last_ago=8 * H, first_ago=8.2 * H)],
                  {"switch.tuya_heater": state("on", 30 * H),
                   "sensor.tuya_heater_power": state("812", 60)})
        _parsed, _kept, held = judged(h)
        [row] = sre.trail_rows(held)
        self.assertEqual(row["kind"], "transient")
        self.assertEqual(row["source"], sre.SOURCE)
        self.assertTrue(row["reason"])
        self.assertTrue(row["text"])
        import decision_trail
        self.assertIn("transient", decision_trail.KINDS)


from test_sre import PassCase  # noqa: E402


class TestThroughThePass(PassCase):
    """`_run_sre` files nothing for a held cause and writes the trail."""

    def setUp(self):
        super().setUp()
        import decision_trail
        self.trail = decision_trail
        self._trail_file = decision_trail.TRAIL_FILE
        decision_trail.TRAIL_FILE = str(Path(self.tmp.name) / "decisions.jsonl")
        decision_trail._RECENT.clear()
        self.addCleanup(setattr, decision_trail, "TRAIL_FILE", self._trail_file)
        self.collected = house(
            [log_row("Error communicating with Tuya cloud: Connection reset",
                     TUYA, last_ago=8 * H, first_ago=8.2 * H)],
            {"switch.tuya_heater": state("on", 30 * H),
             "sensor.tuya_heater_power": state("812", 60)})

    def test_a_held_cause_files_nothing_and_says_why(self):
        dig = sre.digest(self.collected, NOW)
        [rid] = [r["id"] for r in dig["records"] if r["kind"] == "log"
                 and r["integration"] == "tuya"]
        self.reply([{"title": "Tuya keeps losing the cloud", "records": [rid],
                     "fix": "Reload the Tuya integration."}])
        self.run_pass()
        self.assertEqual(self.rows(), [])
        rows, readable = self.trail.read()
        self.assertTrue(readable)
        self.assertEqual([r["kind"] for r in rows], ["transient"])
        self.assertEqual(rows[0]["source"], sre.SOURCE)
        self.assertEqual(sre.load()["last"]["transient"], 1)


if __name__ == "__main__":
    unittest.main()
