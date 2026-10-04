"""The decision trail: why brAIn said nothing, written by the code that chose.

Driven against the real module over a temp file, and against the real
`checks.run_all` for the two producers inside a checks pass — a cap and a
correction — because "the check withheld a row" and "the trail heard about
it" are different claims and only the second answers a person.
"""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "brain" / "panel"))
sys.path.insert(0, str(HERE))

import checks  # noqa: E402
import decision_trail as trail  # noqa: E402
from test_house_checks import house, iso  # noqa: E402

NOW = 1_790_000_000.0


class TrailCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._old = trail.TRAIL_FILE
        trail.TRAIL_FILE = os.path.join(self.tmp.name, "decisions.jsonl")
        self.addCleanup(setattr, trail, "TRAIL_FILE", self._old)
        trail.clear_memory()
        self.addCleanup(trail.clear_memory)


class TestWriting(TrailCase):
    def test_a_decision_is_one_line_with_its_reason(self):
        n = trail.note("mute", "sensor.porch", "you muted Sensors frozen",
                       check="dev.frozen", now=NOW)
        self.assertEqual(n, 1)
        rows, readable = trail.read()
        self.assertTrue(readable)
        self.assertEqual(rows[0]["kind"], "mute")
        self.assertEqual(rows[0]["subject"], "sensor.porch")
        self.assertEqual(rows[0]["entities"], ["sensor.porch"])
        self.assertEqual(rows[0]["ts"], int(NOW))

    def test_the_same_decision_inside_the_window_is_written_once(self):
        trail.note("gate_hold", "sensor.a", "paused", now=NOW)
        trail.note("gate_hold", "sensor.a", "paused", now=NOW + 60)
        trail.note("gate_hold", "sensor.a", "paused",
                   now=NOW + trail.MERGE_S + 1)
        rows, _ = trail.read()
        self.assertEqual([r["ts"] for r in rows],
                         [int(NOW), int(NOW + trail.MERGE_S + 1)])

    def test_a_kind_outside_the_vocabulary_is_dropped(self):
        self.assertEqual(trail.note("because", "sensor.a", "x", now=NOW), 0)
        self.assertEqual(trail.read(), ([], True))

    def test_it_never_creates_its_own_directory(self):
        trail.TRAIL_FILE = os.path.join(self.tmp.name, "nope", "d.jsonl")
        self.assertEqual(trail.note("mute", "sensor.a", "x", now=NOW), 0)
        self.assertFalse(os.path.exists(os.path.dirname(trail.TRAIL_FILE)))
        self.assertFalse(trail.summary(now=NOW)["writable"])

    def test_it_is_capped(self):
        rows = [{"kind": "cap", "subject": f"sensor.s{i}", "reason": "many"}
                for i in range(trail.MAX_LINES + trail.MAX_LINES // 4 + 5)]
        trail.note_many(rows, now=NOW)
        kept, _ = trail.read()
        self.assertEqual(len(kept), trail.MAX_LINES)
        self.assertEqual(kept[-1]["subject"], rows[-1]["subject"])

    def test_it_never_raises_on_junk(self):
        self.assertEqual(trail.note_many([None, "x", {"kind": None}], now=NOW), 0)
        self.assertEqual(trail.note_many(object(), now=NOW), 0)


class TestReading(TrailCase):
    def test_for_subject_is_newest_first_and_words_each_kind(self):
        trail.note("cap", "sensor.a", "a dozen at once", check="dev.frozen",
                   now=NOW)
        trail.note("quiet_hold", "", "quiet hours", entities=["sensor.a"],
                   now=NOW + 10)
        trail.note("mute", "sensor.b", "muted", now=NOW + 20)
        got = trail.for_subject("sensor.a")
        self.assertTrue(got["readable"])
        self.assertEqual([r["kind"] for r in got["rows"]], ["quiet_hold", "cap"])
        self.assertEqual(got["rows"][0]["meaning"], trail.KINDS["quiet_hold"])
        self.assertEqual(got["kinds"], ["cap", "quiet_hold"])
        # A check id is a subject too: "why does this rule never say anything".
        self.assertEqual(len(trail.for_subject("dev.frozen")["rows"]), 1)

    def test_no_record_is_readable_and_empty(self):
        got = trail.for_subject("sensor.nothing")
        self.assertEqual((got["readable"], got["rows"]), (True, []))

    def test_a_file_that_cannot_be_read_says_so(self):
        os.mkdir(trail.TRAIL_FILE)   # a directory where the file should be
        got = trail.for_subject("sensor.a")
        self.assertFalse(got["readable"])
        self.assertFalse(trail.summary(now=NOW)["readable"])

    def test_summary_counts_the_last_day_by_kind(self):
        trail.note("cap", "sensor.old", "x", now=NOW - 2 * 86400)
        trail.note("cap", "sensor.a", "x", now=NOW)
        trail.note("mute", "sensor.a", "y", now=NOW)
        got = trail.summary(now=NOW)
        self.assertEqual(got["day"], {"cap": 1, "mute": 1})
        self.assertEqual(got["rows"], 3)
        self.assertEqual(got["last"], int(NOW))
        lines = Path(trail.TRAIL_FILE).read_text().splitlines()
        self.assertTrue(all(json.loads(line)["kind"] for line in lines))


class TestChecksHandItBack(unittest.TestCase):
    """`run_all` returns what the checks withheld, and never writes into the
    caller's snapshot to do it."""

    def test_a_correction_leaves_a_line_with_the_persons_reason(self):
        snap = house()
        snap["automations"][0]["actions"][0]["target"]["entity_id"] = "light.gone"
        self.assertEqual(len(checks.run_all(snap, NOW, only=["auto.dead_ref"])
                             ["findings"]), 1)
        snap["corrections"] = {
            "entity": {"automation.morning": {
                "auto.dead_ref": {"text": "it is parked for the winter",
                                  "until": "2027-03-01"}}},
            "area": {}, "check": {}, "never": {}}
        before = json.dumps(snap, sort_keys=True, default=str)
        result = checks.run_all(snap, NOW, only=["auto.dead_ref"])
        self.assertEqual(result["findings"], [])
        self.assertEqual(json.dumps(snap, sort_keys=True, default=str), before)
        withheld = result["withheld"]
        self.assertEqual(len(withheld), 1)
        self.assertEqual(withheld[0]["kind"], "exception")
        self.assertEqual(withheld[0]["subject"], "automation.morning")
        self.assertEqual(withheld[0]["check"], "auto.dead_ref")
        self.assertEqual(withheld[0]["reason"], "it is parked for the winter")
        self.assertIn("until 2027-03-01", withheld[0]["text"])
        # ...and the trail takes the row the checks handed back as written.
        with tempfile.TemporaryDirectory() as tmp:
            old = trail.TRAIL_FILE
            trail.TRAIL_FILE = os.path.join(tmp, "d.jsonl")
            try:
                trail.clear_memory()
                self.assertEqual(trail.note_many(withheld, now=NOW), 1)
                got = trail.for_subject("automation.morning")
            finally:
                trail.TRAIL_FILE = old
                trail.clear_memory()
        self.assertEqual(got["rows"][0]["reason"], "it is parked for the winter")

    def test_a_cap_names_every_entity_it_left_unsaid(self):
        from checks import devices
        snap = house()
        snap["stats"] = {}
        wanted = []
        for i in range(devices.FROZEN_MAX_ROWS + 1):
            eid = f"sensor.stuck_{i}"
            wanted.append(eid)
            snap["states"][eid] = {
                "state": "12", "last_updated": iso(60),
                "attributes": {"state_class": "measurement",
                               "device_class": "temperature",
                               "unit_of_measurement": "°C",
                               "friendly_name": eid}}
            snap["entities"].append({"entity_id": eid, "platform": "demo"})
            snap["stats"][eid] = [
                {"start": NOW - d * 86400, "mean": 12, "min": 12, "max": 12}
                for d in range(7)]
        result = checks.run_all(snap, NOW, only=["dev.frozen"])
        self.assertEqual(result["findings"], [])
        caps = [w for w in result["withheld"] if w["kind"] == "cap"]
        self.assertEqual(sorted(c["subject"] for c in caps), sorted(wanted))
        self.assertTrue(all(c["check"] == "dev.frozen" for c in caps))
        self.assertTrue(all(c["reason"] for c in caps))


if __name__ == "__main__":
    unittest.main()


class TestPassRows(unittest.TestCase):
    """What a checks pass withheld, read off what it already holds."""

    def test_withheld_muted_answered_and_on_trial(self):
        result = {
            "withheld": [{"kind": "cap", "subject": "sensor.a",
                          "check": "dev.frozen", "reason": "a dozen"}],
            "findings": [
                {"text": "Muted one", "source": "check:forecast.decline",
                 "entity_id": "sensor.b"},
                {"text": "Answered one", "source": "check:dev.frozen",
                 "entity_id": "sensor.c"},
                {"text": "New one", "source": "check:dev.frozen",
                 "entity_id": "sensor.d"},
                {"text": "Already open", "source": "check:dev.frozen",
                 "entity_id": "sensor.e"},
            ],
            "shadow": [{"text": "Trial", "source": "check:sys.update_pending",
                        "entity_id": ""}],
        }
        rows = trail.pass_rows(
            result, created_keys={"new one"},
            settled={"answered one": "ignored"},
            muted={"check:forecast.decline"},
            normalize=lambda t: t.lower())
        kinds = {(r["kind"], r["subject"] or r["check"]) for r in rows}
        self.assertEqual(kinds, {("cap", "sensor.a"), ("mute", "sensor.b"),
                                 ("dedupe", "sensor.c"),
                                 ("shadow", "sys.update_pending")})
        dedupe = next(r for r in rows if r["kind"] == "dedupe")
        self.assertEqual(dedupe["reason"], "you marked it Not a problem")


class TestTheServerWritesIt(TrailCase):
    """The notifier and the Resident put their silences on the trail."""

    @classmethod
    def setUpClass(cls):
        import importlib
        cls.server = importlib.import_module("server")

    def setUp(self):
        super().setUp()
        self.server.decision_trail.TRAIL_FILE = trail.TRAIL_FILE
        self._target = self.server._findings_notify_target

    def tearDown(self):
        self.server._findings_notify_target = self._target
        super().tearDown()

    def test_no_notification_service_is_a_reason(self):
        self.server._findings_notify_target = lambda: ("", "warning")
        row = {"ts": 1, "text": "Garage door left open", "severity": "serious",
               "source": "check:evening.left_open",
               "entity_id": "cover.garage"}
        asyncio.run(self.server._announce_findings([row]))
        got = trail.for_subject("cover.garage")
        self.assertEqual(got["rows"][0]["kind"], "no_target")
        self.assertEqual(got["rows"][0]["check"], "evening.left_open")

    def test_below_the_floor_is_a_reason(self):
        self.server._findings_notify_target = lambda: (
            "notify.mobile_app_phone", "critical")
        row = {"ts": 2, "text": "Battery low", "severity": "warning",
               "source": "check:dev.battery_low", "entity_id": "sensor.bat"}
        asyncio.run(self.server._announce_findings([row]))
        self.assertEqual(trail.for_subject("sensor.bat")["kinds"],
                         ["notify_quiet"])

    def test_a_signal_the_look_let_go(self):
        rows = self.server._signal_decisions(
            [{"subject": "binary_sensor.hall", "kind": "state",
              "text": "hall motion at 03:00"},
             {"subject": "checks pass", "kind": "time", "text": "x"}],
            "look_ignore", "a cat")
        self.assertEqual(rows[0]["subject"], "binary_sensor.hall")
        self.assertEqual(rows[1]["subject"], "")
        self.assertEqual(trail.note_many(rows, now=NOW), 2)
