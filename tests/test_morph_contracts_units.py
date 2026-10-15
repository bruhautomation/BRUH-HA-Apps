#!/usr/bin/env python3
"""The pure halves of brAIn's wire to Morph (Morph 1.0 / brAIn 3.0).

The interpreter's `morph` surface, the three new request shapes and the
integration's writer driven straight into the panel's reader, the To Do
sentence every finding carries and the producers that write it, and the two
files Morph draws (`feed.json`, `cases.json`) built from plain stores.

Mutations each test names:

  a surface leaks          put `dashboard` in `ALLOWED["ask_bar"]` -> the ask
                           bar test sees it
  the old schema moves     add the Tell's kinds to `SCHEMA` -> the byte-for-
                           byte test fails
  a guessed number         let `normal_rows` take `overall` -> a sensor with
                           no bucket for this hour is in the feed
  a question on To Do      drop the `?` refusal in `clean_todo_text`
"""
from __future__ import annotations

import asyncio
import datetime as dt
import importlib
import json
import os
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL = BASE_DIR / "brain" / "panel"
INTEGRATION_DIR = BASE_DIR / "brain" / "custom_components" / "brain"
sys.path.insert(0, str(PANEL))
sys.path.insert(0, str(BASE_DIR / "tests"))

import checks  # noqa: E402
import closures  # noqa: E402
import finding_requests  # noqa: E402
import findings_store  # noqa: E402
import health  # noqa: E402
import interpret  # noqa: E402
import morph_bridge  # noqa: E402
import resident  # noqa: E402

if "homeassistant" not in sys.modules:
    sys.modules["homeassistant"] = types.ModuleType("homeassistant")
if "homeassistant.core" not in sys.modules:
    _core = types.ModuleType("homeassistant.core")
    _core.HomeAssistant = type("HomeAssistant", (), {})
    sys.modules["homeassistant.core"] = _core
_pkg = types.ModuleType("brain_cc")
_pkg.__path__ = [str(INTEGRATION_DIR)]
sys.modules.setdefault("brain_cc", _pkg)
brain_requests = importlib.import_module("brain_cc.requests")  # noqa: E402


class _Hass:
    def __init__(self, base: str):
        self.config = types.SimpleNamespace(
            path=lambda *parts: os.path.join(base, *parts))


class TestTheMorphSurface(unittest.TestCase):
    def test_the_tells_two_kinds_and_the_new_endings_are_morphs_alone(self):
        data = {"routes": [{"kind": "dashboard", "text": "move the kitchen"},
                           {"kind": "remember", "text": "beer fridge"}]}
        got = interpret.parse(data, "morph", "x")
        self.assertEqual([r["kind"] for r in got], ["dashboard", "remember"])
        ask = interpret.parse(data, "ask_bar", "x")
        self.assertEqual([r["kind"] for r in ask], ["remember"])
        consent = {"routes": [{"kind": "case_ending", "ending": "consent",
                               "change": "  call it   Sump Pump "}]}
        self.assertIsNone(interpret.parse(consent, "reply", "yes"))
        [route] = interpret.parse(consent, "morph", "yes")
        self.assertEqual(route["change"], "call it Sump Pump")
        self.assertIn("morph", interpret.PRESSED)

    def test_every_other_surface_keeps_its_schema(self):
        for surface in ("ask_bar", "reply", "repairs", "service"):
            self.assertIs(interpret.schema_for(surface), interpret.SCHEMA)
        kinds = interpret.SCHEMA["properties"]["routes"]["items"][
            "properties"]["kind"]["enum"]
        self.assertEqual(kinds, list(interpret.KINDS))
        self.assertNotIn("dashboard", kinds)
        morph = interpret.schema_for("morph")["properties"]["routes"][
            "items"]["properties"]
        self.assertIn("code", morph["kind"]["enum"])
        self.assertIn("consent", morph["ending"]["enum"])
        self.assertIn("change", morph)

    def test_the_rules_say_house_change_from_page_change(self):
        self.assertIn("warmer-looking", interpret.SYSTEM)
        self.assertIn("- dashboard:", interpret.SYSTEM)
        self.assertIn("- code:", interpret.SYSTEM)
        self.assertIn("Morph", interpret.prompt("hi", "morph"))


class TestTheRequests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = finding_requests.REQUEST_DIR
        finding_requests.REQUEST_DIR = (Path(self.tmp.name) / ".brain"
                                        / "finding-requests")
        self.hass = _Hass(self.tmp.name)
        self._shared = brain_requests.SHARED_DIR
        brain_requests.SHARED_DIR = ".brain"

    def tearDown(self):
        finding_requests.REQUEST_DIR = self._old
        brain_requests.SHARED_DIR = self._shared
        self.tmp.cleanup()

    def test_the_writer_and_the_reader_agree(self):
        bodies = [
            {"kind": "morph", "case": "f:1720", "action": "reply",
             "text": "yes, but call it Sump Pump", "via": "morph"},
            {"kind": "morph", "case": "h:12", "action": "snooze", "hours": 48},
            {"kind": "todo", "action": "snooze", "id": 12, "days": 7},
            {"kind": "morph_case", "action": "file", "key": "sug-abc",
             "case_kind": "opportunity", "claim": "Move Kitchen above Dining.",
             "detail": "You open it first.", "ask": "Should I move it?",
             "entity_id": "", "via": "morph"},
            {"kind": "morph_case", "action": "withdraw", "key": "sug-abc"},
        ]
        for body in bodies:
            self.assertTrue(brain_requests.write_morph_request(self.hass, body),
                            body)
        got = finding_requests.collect()
        self.assertEqual([(r["kind"], r["action"]) for r in got],
                         [("morph", "reply"), ("morph", "snooze"),
                          ("todo", "snooze"), ("morph_case", "file"),
                          ("morph_case", "withdraw")])
        self.assertEqual(got[0]["case"], "f:1720")
        self.assertEqual(got[1]["hours"], 48.0)
        self.assertEqual(got[2]["days"], 7.0)
        self.assertEqual(got[3]["claim"], "Move Kitchen above Dining.")

    def test_what_could_never_be_applied_is_not_written(self):
        for bad in ({"kind": "morph", "case": "x:1", "action": "reply",
                     "text": "hi"},
                    {"kind": "morph", "case": "f:1", "action": "reply",
                     "text": "  "},
                    {"kind": "morph", "case": "f:1", "action": "delete"},
                    {"kind": "morph_case", "action": "file", "key": "a b",
                     "claim": "x"},
                    {"kind": "morph_case", "action": "file", "key": "k"},
                    {"kind": "todo", "action": "snooze"},
                    {"kind": "finding", "ts": 1, "action": "wrong"},
                    "not a dict"):
            self.assertFalse(brain_requests.write_morph_request(self.hass, bad),
                             bad)
            if isinstance(bad, dict) and bad.get("kind") != "finding":
                self.assertIsNone(finding_requests.parse(bad), bad)
        self.assertEqual(finding_requests.collect(), [])

    def test_the_entity_on_a_suggestion_must_be_one(self):
        got = finding_requests.parse({
            "kind": "morph_case", "action": "file", "key": "k",
            "claim": "x", "entity_id": "rm -rf"})
        self.assertEqual(got["entity_id"], "")


class TestTheToDoSentence(unittest.TestCase):
    def test_derived_from_the_fix_with_the_name(self):
        self.assertEqual(findings_store.derive_todo_text(
            {"fix": "Replace its battery. It is a CR2032.",
             "entity_id": "sensor.hall"}, "Hall motion sensor"),
            "Replace the Hall motion sensor's battery.")
        self.assertEqual(findings_store.derive_todo_text(
            {"fix": "Nothing is needed.", "entity_id": "sensor.hall"},
            "Hall motion sensor"), "Look at Hall motion sensor.")
        self.assertEqual(findings_store.derive_todo_text(
            {"fix": "Reset the Z-Wave node", "entity_id": "sensor.hall"},
            "Garage node"), "Garage node: reset the Z-Wave node.")

    def test_an_errand_not_a_statement(self):
        # The audit's "battery is low" items: a fix that only says what is
        # wrong becomes an errand naming the thing, and the "it" after a
        # statement is the statement's subject, not the device.
        self.assertEqual(findings_store.derive_todo_text(
            {"fix": "The battery is low.", "entity_id": "s.h"}, "Hall sensor"),
            "Look at Hall sensor: the battery is low.")
        self.assertEqual(findings_store.derive_todo_text(
            {"fix": "The battery is low. Replace it.", "entity_id": "s.h"},
            "Hall sensor"), "Hall sensor: replace it — the battery is low.")
        self.assertEqual(findings_store.derive_todo_text(
            {"fix": "It is unplugged on purpose? Plug it in.", "entity_id": "s.h"},
            "Lamp"), "Plug the Lamp in.")

    def test_not_garbled_and_not_cut_off(self):
        self.assertEqual(findings_store.derive_todo_text(
            {"fix": "Turn it on.", "entity_id": "scene.x"},
            "the scene “before movie”"), "Turn the scene “before movie” on.")
        self.assertEqual(findings_store.derive_todo_text(
            {"fix": "Check the hub, e.g. the coordinator. Then reload.",
             "entity_id": "s.h"}, "Hall sensor"),
            "Hall sensor: check the hub, e.g. the coordinator.")

    def test_an_item_filed_as_a_claim_reads_as_an_errand(self):
        names = {"sensor.hb": {"name": "Hall battery"}}
        self.assertEqual(findings_store.todo_item_text(
            {"text": "Hall battery is low", "entity_id": "sensor.hb",
             "origin": "finding"}, names), "Look at Hall battery: it is low.")
        self.assertEqual(findings_store.todo_item_text(
            {"text": "Buy milk", "origin": "hand"}, names), "Buy milk")
        self.assertEqual(findings_store.todo_item_text(
            {"text": "The kettle is descaled", "origin": "hand"}, names),
            "The kettle is descaled", "a person's own words are theirs")
        rows = morph_bridge.todo_rows(
            [{"id": 1, "text": "Hall battery is low", "entity_id": "sensor.hb",
              "origin": "finding"}], {}, lambda e: "",
            lambda item: findings_store.todo_item_text(item, names))
        self.assertEqual(rows[0]["text"], "Look at Hall battery: it is low.")

    def test_never_a_question_and_kept_when_written(self):
        self.assertEqual(findings_store.clean_todo_text(
            "Is the freezer meant to be off?"), "")
        entry = findings_store.coerce({
            "text": "x", "todo_text": "replace the battery"})
        self.assertEqual(entry["todo_text"], "Replace the battery.")
        bare = findings_store.coerce({"text": "y"})
        self.assertNotIn("todo_text", bare)
        self.assertNotIn("todo_text", findings_store._shape(bare))

    def test_a_check_writes_it_from_its_own_fix(self):
        snap = {"states": {"sensor.hall_battery": {
                    "entity_id": "sensor.hall_battery", "state": "5",
                    "attributes": {"friendly_name": "Hall battery"}}},
                "available": {"states": True}}
        fake = {"id": "dev.morph_fake", "title": "Fake", "needs": ("states",),
                "run": lambda snap, now: [{
                    "text": "Hall battery is low", "severity": "warning",
                    "entity_id": "sensor.hall_battery",
                    "fix": "Replace it."}]}
        checks.CHECKS.append(fake)
        try:
            out = checks.run_all(snap, time.time(), only=["dev.morph_fake"])
        finally:
            checks.CHECKS.remove(fake)
        self.assertEqual(out["findings"][0]["todo_text"],
                         "Replace the Hall battery.")

    def test_the_resident_writes_it_and_a_look_rewrites_it(self):
        self.assertIn("todo_text", resident.CASE_SCHEMA["properties"])
        self.assertIn('"todo_text"', resident.INVESTIGATE_SYSTEM)
        with tempfile.TemporaryDirectory() as tmp:
            old = (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
                   findings_store.STATE_FILE)
            findings_store.FINDINGS_FILE = Path(tmp) / "f.json"
            findings_store.SETTLED_FILE = Path(tmp) / "s.json"
            findings_store.STATE_FILE = Path(tmp) / "no" / ".brain" / "m.json"
            try:
                [row] = findings_store.add_many([{
                    "text": "Freezer warming", "source": "check:dev.x",
                    "fix": "Check it", "status": "open"}])
                findings_store.refine(row["ts"], {
                    "claim": "The garage freezer door is ajar",
                    "todo_text": "Close the garage freezer door."})
                self.assertEqual(findings_store.get(row["ts"])["todo_text"],
                                 "Close the garage freezer door.")
                findings_store.append_thread(row["ts"], "you", "why?")
                for i in range(20):
                    findings_store.append_thread(row["ts"], "brain", f"t{i}")
                thread = findings_store.get(row["ts"])["thread"]
                self.assertEqual(len(thread), findings_store.MAX_THREAD_TURNS)
                self.assertEqual(thread[-1]["text"], "t19")
                self.assertIsNone(findings_store.append_thread(
                    row["ts"], "someone", "x"))
            finally:
                (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
                 findings_store.STATE_FILE) = old


TZ = dt.timezone.utc
# Monday 2026-10-12 09:30 UTC: hour-of-week 9.
NOW = dt.datetime(2026, 10, 12, 9, 30, tzinfo=TZ).timestamp()


class TestTheFeed(unittest.TestCase):
    def feed(self, **over):
        args = dict(
            now=NOW, tz=TZ, tz_name="UTC",
            baselines_store={"entities": {
                "sensor.a": {"buckets": {"9": {"median": 20.0, "spread": 0.5,
                                               "n": 4}},
                             "overall": {"median": 19, "spread": 1, "n": 99},
                             "unit": "°C"},
                "sensor.b": {"buckets": {"30": {"median": 1, "spread": 1,
                                                "n": 4}},
                             "overall": {"median": 1, "spread": 1, "n": 9}}}},
            closures_store={"entities": {
                "binary_sensor.back": {"buckets": {"9": {"open": 0.7},
                                                   "10": {"open": 0.4}}},
                "binary_sensor.side": {"buckets": {}}}},
            usual_open=closures.usual_open,
            rhythm_profile={"weekday": {"wakes": {"minute": 412.2},
                                        "settles": {"minute": 1335}},
                            "weekend": {"wakes": None, "settles": None}},
            routines=[{"entity_id": "light.master", "state": "off",
                       "minute": 1300, "spread_min": 7, "when_days":
                       "weekdays", "share": 0.82, "days": 23}],
            states=[{"entity_id": "person.cailin", "state": "home",
                     "attributes": {"friendly_name": "Cailin",
                                    "user_id": "abc"}}])
        args.update(over)
        return morph_bridge.build_feed(**args)

    def test_the_shape(self):
        feed = self.feed()
        self.assertEqual(feed["bucket"], {"now": 9, "next": 10,
                                          "until": int(NOW + 1800)})
        self.assertEqual(feed["normal"], {"sensor.a": {
            "now": [20.0, 0.5, 4], "next": None, "unit": "°C"}})
        self.assertEqual(feed["doors"], {"binary_sensor.back":
                                         {"now": 0.7, "next": 0.4}})
        self.assertEqual(feed["rhythm"]["weekday"], {"wake": 412,
                                                     "settle": 1335})
        self.assertEqual(feed["rhythm"]["weekend"], {"wake": None,
                                                     "settle": None})
        self.assertEqual(feed["habits"][0]["days_seen"], 23)
        self.assertIsNone(feed["habits"][0]["person"])
        self.assertEqual(feed["people"]["person.cailin"],
                         {"name": "Cailin", "user_id": "abc"})
        self.assertEqual(feed["stale_after_s"], 7200)
        self.assertNotIn("appliances", feed)
        json.dumps(feed)

    def test_a_store_that_could_not_be_read_is_absent_not_empty(self):
        feed = self.feed(baselines_store=None, routines=None, states=None)
        for key in ("normal", "habits", "people"):
            self.assertNotIn(key, feed)

    def test_published_only_where_there_is_a_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = morph_bridge.MORPH_DIR
            morph_bridge.MORPH_DIR = Path(tmp) / "config" / ".brain" / "morph"
            try:
                self.assertFalse(morph_bridge.publish_feed(self.feed()))
                (Path(tmp) / "config").mkdir()
                self.assertTrue(morph_bridge.publish_feed(self.feed()))
                written = json.loads((morph_bridge.MORPH_DIR / "feed.json")
                                     .read_text())
                self.assertEqual(written["v"], 1)
            finally:
                morph_bridge.MORPH_DIR = old


class TestTheCaseRow(unittest.TestCase):
    def test_answers_are_the_presses_morph_can_carry(self):
        got = morph_bridge.morph_answers([
            {"verb": "fix", "label": "Fix"}, {"verb": "recheck"},
            {"verb": "dismiss", "label": "Dismiss"},
            {"verb": "not_now", "label": "Snooze"},
            {"verb": "wrong", "label": "Ignore"}])
        # No Snooze: Morph's face is Fix · Dismiss · To Do (§13.2).
        self.assertEqual([a["action"] for a in got], ["fix", "dismiss"])

    def test_the_ask_line(self):
        self.assertEqual(morph_bridge.ask_line(
            {"kind": "question", "claim": "Is the shed heater meant to run?"},
            "question"), "Is the shed heater meant to run?")
        self.assertEqual(morph_bridge.ask_line(
            {"kind": "problem", "fixable": False,
             "fix": "Replace its battery."}, "battery"),
            "Replace its battery.")
        self.assertEqual(morph_bridge.ask_line(
            {"kind": "problem"}, "fixing"), "")


class TestTheLoopIsWatched(unittest.TestCase):
    def test_a_health_row_names_it(self):
        self.assertIn("morph", health.LOOPS)
        server = importlib.import_module("server")
        self.assertTrue(asyncio.iscoroutinefunction(server._morph_loop))


if __name__ == "__main__":
    unittest.main()
