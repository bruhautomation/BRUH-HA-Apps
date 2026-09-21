#!/usr/bin/env python3
"""The measurements as MCP tools (2.2).

Every store the checks read is readable by a run now, over the panel's own
routes. These tests drive each tool with `_panel_get` (and the one POST)
stubbed to answer what the panel's routes really answer — the payload
shapes are copied off `_thermal_payload`, `_appliance_detail`,
`_closure_rows` and `_facts_payload` rather than invented — and assert
what a model is told, including the sentence a store that has not
measured yet says instead of a number.
"""

import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "brain", "ha-mcp-server"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "brain", "panel"))

import ha_mcp_server  # noqa: E402

NEW_TOOLS = ("what_is_normal", "room_physics", "appliance_status",
             "house_rhythm", "door_habits", "habits", "simulate_automation",
             "recall")


class TestRegistered(unittest.TestCase):
    def test_every_new_tool_is_a_schema_an_implementation_and_allowed(self):
        import engine
        names = {t["name"] for t in ha_mcp_server.TOOLS}
        for name in NEW_TOOLS:
            with self.subTest(tool=name):
                self.assertIn(name, names)
                self.assertIn(name, ha_mcp_server.TOOL_IMPLEMENTATIONS)
                self.assertTrue(callable(getattr(ha_mcp_server, name)))
                self.assertIn(f"{engine.MCP}{name}", engine.ANALYST_TOOLS)
                self.assertNotIn(f"{engine.MCP}{name}", engine.ANALYST_DENIED)

    def test_remember_fact_takes_a_subject_and_a_person(self):
        spec = next(t for t in ha_mcp_server.TOOLS if t["name"] == "remember_fact")
        props = spec["inputSchema"]["properties"]
        self.assertIn("subject", props)
        self.assertIn("person", props)


class TestEntityArguments(unittest.TestCase):
    def test_a_non_entity_is_refused_before_any_request(self):
        with patch.object(ha_mcp_server, "_panel_get") as get:
            for fn in (ha_mcp_server.what_is_normal, ha_mcp_server.appliance_status,
                       ha_mcp_server.door_habits, ha_mcp_server.habits):
                with self.subTest(tool=fn.__name__):
                    out = fn("not an id")
                    self.assertIn("error", out)
            get.assert_not_called()


class TestRoomPhysics(unittest.TestCase):
    PAYLOAD = {"outdoor": "sensor.outside_temp", "unit": "°C", "rooms": [
        {"id": "sensor.lounge_temp", "name": "Lounge", "area": "lounge",
         "k": 0.12, "tau_h": 8.3, "gain": 1.4, "warmest": 21.5, "coolest": 17.0,
         "hours_to_warm": 3.2},
        {"id": "sensor.loft_temp", "name": "Loft", "area": "loft",
         "k": 0.4, "tau_h": 2.5, "gain": 0.8, "warmest": 19.0, "coolest": 12.0,
         "hours_to_warm": 8.7}]}

    def test_a_room_by_area_name(self):
        with patch.object(ha_mcp_server, "_panel_get", return_value=self.PAYLOAD):
            out = ha_mcp_server.room_physics("Lounge")
        self.assertEqual([r["id"] for r in out["rooms"]], ["sensor.lounge_temp"])
        self.assertEqual(out["outdoor_reference"], "sensor.outside_temp")
        self.assertIn("tau_h", out["note"])

    def test_an_unknown_room_names_the_known_ones(self):
        with patch.object(ha_mcp_server, "_panel_get", return_value=self.PAYLOAD):
            out = ha_mcp_server.room_physics("Cellar")
        self.assertEqual(out["rooms"], [])
        self.assertEqual(sorted(out["known_rooms"]), ["loft", "lounge"])

    def test_no_model_yet_is_a_sentence_not_a_number(self):
        with patch.object(ha_mcp_server, "_panel_get",
                          return_value={"outdoor": "", "unit": "", "rooms": []}):
            out = ha_mcp_server.room_physics("Lounge")
        self.assertEqual(out["rooms"], [])
        self.assertIn("not fitted", out["note"])

    def test_a_panel_that_is_down_is_reported_as_such(self):
        with patch.object(ha_mcp_server, "_panel_get",
                          return_value={"error": "the brAIn panel did not answer: x"}):
            out = ha_mcp_server.room_physics("Lounge")
        self.assertIn("did not answer", out["error"])


class TestApplianceStatus(unittest.TestCase):
    PAYLOAD = {"built_at": 1, "asked": 3, "days": 10, "hours": 14,
               "live_error": "", "appliances": [
                   {"entity_id": "sensor.dishwasher_power", "name": "Dishwasher",
                    "idle_w": 1.2, "running_w": 900.0, "threshold_w": 25.0,
                    "settle_min": 22.0, "cycles": 14, "chore_kind": "dishwasher",
                    "now": {"state": "finished", "since": 1789800000,
                            "quiet_min": 41}}]}

    def test_the_state_is_the_machines_own(self):
        with patch.object(ha_mcp_server, "_panel_get", return_value=self.PAYLOAD):
            out = ha_mcp_server.appliance_status("sensor.dishwasher_power")
        self.assertEqual(out["state"], "finished")
        self.assertEqual(out["thresholds"]["threshold_w"], 25.0)
        self.assertIn("emptied", out["note"])

    def test_an_unprofiled_sensor_says_why(self):
        with patch.object(ha_mcp_server, "_panel_get", return_value=self.PAYLOAD):
            out = ha_mcp_server.appliance_status("sensor.router_power")
        self.assertIsNone(out["state"])
        self.assertIn("two-level", out["note"])


class TestDoorHabits(unittest.TestCase):
    ROWS = [{"entity_id": "binary_sensor.back_door", "name": "Back door",
             "overall": 0.04, "buckets": {"18": 0.3, "19": 0.5}}]

    def test_the_buckets_come_back_with_the_key_explained(self):
        with patch.object(ha_mcp_server, "_panel_get", return_value=self.ROWS):
            out = ha_mcp_server.door_habits("binary_sensor.back_door")
        self.assertEqual(out["buckets"], {"18": 0.3, "19": 0.5})
        self.assertIn("never watched", out["note"])

    def test_an_unmeasured_closure(self):
        with patch.object(ha_mcp_server, "_panel_get", return_value=self.ROWS):
            out = ha_mcp_server.door_habits("binary_sensor.side_gate")
        self.assertIsNone(out["buckets"])


class TestHabitsAndRhythm(unittest.TestCase):
    def test_habits_asks_the_panel_for_that_entity(self):
        answer = {"entity_id": "light.porch", "habit": {"shape": "weekdays"},
                  "overrides": [], "odd": [], "automated": False,
                  "sentence": "You switch Porch on most weekday evenings around 18:40."}
        with patch.object(ha_mcp_server, "_panel_get", return_value=answer) as get:
            out = ha_mcp_server.habits("light.porch")
        get.assert_called_once_with("/api/habits?entity_id=light.porch")
        self.assertEqual(out["habit"]["shape"], "weekdays")
        self.assertIn("automated", out["note"])

    def test_rhythm_carries_the_profile_and_the_floor_note(self):
        profile = {"weekday": {"wake": "06:50", "settle": None},
                   "weekend": {"wake": None, "settle": None}}
        with patch.object(ha_mcp_server, "_panel_get", return_value=profile):
            out = ha_mcp_server.house_rhythm()
        self.assertEqual(out["weekday"]["wake"], "06:50")
        self.assertIn("PERSON", out["note"])


class TestWhatIsNormal(unittest.TestCase):
    def test_the_reading_is_placed_in_its_own_spreads(self):
        base = {"entity_id": "sensor.freezer_temp", "unit": "°C",
                "overall": {"median": -18.0, "spread": 0.5, "n": 700},
                "trend": None, "measured_over_days": 30, "stale": False,
                "by_hour_of_week": {}}
        with patch.object(ha_mcp_server, "get_baseline", return_value=base), \
                patch.object(ha_mcp_server, "ha_api_request",
                             return_value={"state": "-14.5"}):
            out = ha_mcp_server.what_is_normal("sensor.freezer_temp")
        self.assertEqual(out["reading_now"], -14.5)
        self.assertEqual(out["spreads_from_usual"], 7.0)

    def test_no_baseline_passes_the_baselines_own_sentence_through(self):
        none = {"entity_id": "sensor.x", "baseline": None, "note": "no baseline"}
        with patch.object(ha_mcp_server, "get_baseline", return_value=none):
            out = ha_mcp_server.what_is_normal("sensor.x")
        self.assertEqual(out, none)


class TestRecall(unittest.TestCase):
    def test_facts_are_trimmed_to_what_a_model_acts_on(self):
        payload = {"facts": [{"id": "abc", "text": "The porch sensor reads on",
                              "subject": "binary_sensor.porch", "subjects": [],
                              "source": "correction", "observed": "2026-09-19",
                              "confidence": 0.95, "run_id": "", "predicate": "",
                              "run_source": "", "first_seen": 1}],
                   "summary": {}, "count": 1}
        with patch.object(ha_mcp_server, "_panel_get", return_value=payload) as get:
            out = ha_mcp_server.recall(subject="binary_sensor.porch")
        self.assertIn("subject=binary_sensor.porch", get.call_args[0][0])
        self.assertEqual(out["facts"][0]["source"], "correction")
        self.assertNotIn("first_seen", out["facts"][0])

    def test_nothing_remembered_says_where_facts_come_from(self):
        with patch.object(ha_mcp_server, "_panel_get",
                          return_value={"facts": [], "summary": {}, "count": 0}):
            out = ha_mcp_server.recall(query="boot room")
        self.assertEqual(out["facts"], [])
        self.assertIn("remember_fact", out["note"])


class TestSimulate(unittest.TestCase):
    def test_a_refusal_is_whole(self):
        class Resp:
            def __init__(self, body):
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps(self.body).encode()

        refused = {"days": 7, "refused": True,
                   "replay": {"refused": True, "error": "webhook triggers cannot be replayed"}}
        with patch.object(ha_mcp_server.urllib.request, "urlopen",
                          return_value=Resp(refused)) as opened:
            out = ha_mcp_server.simulate_automation(
                {"trigger": [{"platform": "webhook"}], "action": []}, days=99)
        self.assertTrue(out["refused"])
        self.assertIn("webhook", out["error"])
        sent = json.loads(opened.call_args[0][0].data.decode())
        self.assertEqual(sent["days"], 28, "days is clamped before it is sent")

    def test_a_non_object_config_is_refused_before_any_request(self):
        with patch.object(ha_mcp_server.urllib.request, "urlopen") as opened:
            out = ha_mcp_server.simulate_automation("turn the light on")
        self.assertIn("error", out)
        opened.assert_not_called()


class TestRememberFactCarriesTheSubject(unittest.TestCase):
    def test_the_inbox_line_names_the_subject(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(ha_mcp_server, "MEMORY_DIR", tmp):
            out = ha_mcp_server.remember_fact(
                "Ben likes the lounge warm", subject="area:lounge", person="ben")
            self.assertEqual(out["status"], "remembered")
            files = sorted(os.listdir(os.path.join(tmp, "inbox")))
            self.assertEqual(len(files), 1)
            with open(os.path.join(tmp, "inbox", files[0]), encoding="utf-8") as fh:
                rec = json.loads(fh.readline())
        self.assertEqual(rec["subject"], "area:lounge")
        self.assertEqual(rec["person"], "ben")
        self.assertEqual(rec["source"], "assist")


if __name__ == "__main__":
    unittest.main()
