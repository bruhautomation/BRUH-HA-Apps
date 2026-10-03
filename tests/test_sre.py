#!/usr/bin/env python3
"""The overnight health check — root causes that must cite their records.

What is driven:

  * the digest over a mesh copied in shape from `zha/devices` (lqi, rssi,
    device_type, neighbors, device_reg_id) and a system log in the shape
    `system_log/list` answers — routers always, end devices only when
    struggling, and the automation that switches a router off;
  * `parse_causes` refusing a cause that cites no record that exists, and
    dropping (and counting) an invented id beside a real one;
  * the pass through the real `_run_sre` into the real findings store with
    only `engine.run_claude` and the collector stubbed: one row per cause,
    filed through `triage.gate` (so `triaging`), carrying its records as
    evidence; the text reused by anchor on the next night; a night whose
    log could not be read clearing nothing; a night ZHA did not answer
    keeping a mesh-anchored row;
  * the collector against a real WebSocket server: no ZHA is "not
    available", never an empty mesh.
"""

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))
sys.path.insert(0, str(BASE_DIR / "tests"))

import ha_data  # noqa: E402
import sre  # noqa: E402
from fake_core_ws import FakeCore, ok, refused  # noqa: E402

NOW = 1_800_000_000.0


def iso(ago: float) -> str:
    import datetime as dt
    return dt.datetime.fromtimestamp(NOW - ago, tz=dt.timezone.utc).isoformat()


def collected(**over) -> dict:
    """A house whose only router upstairs is a plug the bedtime automation
    switches off, and the two sensors behind it have gone quiet."""
    base = {
        "available": {"log": True, "zha": True, "registry": True, "states": True},
        "errors": {},
        "log": [
            {"name": "homeassistant.components.zha.core.device",
             "message": ["Device 00:11:22 did not respond (token=abcdEF1234567890abcdEF1234567890)"],
             "level": "WARNING", "source": ["components/zha/core/device.py", 412],
             "timestamp": NOW - 600, "count": 14, "first_occurred": NOW - 80000},
            {"name": "homeassistant.components.hue", "message": ["one blip"],
             "level": "WARNING", "source": ["components/hue/bridge.py", 9],
             "timestamp": NOW - 600, "count": 1},
        ],
        "zha": [
            {"ieee": "00:00:00:00:00:00:00:01", "name": "Coordinator",
             "device_type": "Coordinator", "available": True, "lqi": 255},
            {"ieee": "aa:aa:aa:aa:aa:aa:aa:01", "name": "Landing plug",
             "user_given_name": "Landing plug", "device_type": "Router",
             "power_source": "Mains", "available": False, "lqi": 0,
             "last_seen": iso(9 * 3600), "device_reg_id": "dev-plug",
             "area_id": "landing",
             "neighbors": [{"ieee": "bb:bb", "relationship": "Child", "lqi": 120}]},
            {"ieee": "bb:bb:bb:bb:bb:bb:bb:02", "name": "Bedroom motion",
             "device_type": "EndDevice", "available": True, "lqi": 30,
             "last_seen": iso(8 * 3600)},
            {"ieee": "cc:cc:cc:cc:cc:cc:cc:03", "name": "Kitchen sensor",
             "device_type": "EndDevice", "available": True, "lqi": 200,
             "last_seen": iso(300)},
        ],
        "entities": [
            {"entity_id": "switch.landing_plug", "device_id": "dev-plug",
             "platform": "zha"},
        ],
        "devices": [],
        "areas": {"landing": "Landing"},
        "states": {},
        "automations": [
            {"id": "bedtime", "alias": "Bedtime",
             "actions": [{"action": "switch.turn_off",
                          "target": {"entity_id": ["switch.landing_plug"]}}]},
        ],
    }
    base.update(over)
    return base


class TestTheDigest(unittest.TestCase):
    def test_routers_always_end_devices_only_when_struggling(self):
        dig = sre.digest(collected(), NOW)
        ids = {r["id"] for r in dig["records"]}
        self.assertIn("zha:aa:aa:aa:aa:aa:aa:aa:01", ids)
        self.assertIn("zha:bb:bb:bb:bb:bb:bb:bb:02", ids)       # weak + unseen
        self.assertNotIn("zha:cc:cc:cc:cc:cc:cc:cc:03", ids)    # healthy
        plug = next(r for r in dig["records"] if r["id"].endswith(":01")
                    and r["kind"] == "zigbee" and r["type"] == "Router")
        self.assertEqual(plug["area"], "Landing")
        self.assertEqual(plug["entities"], ["switch.landing_plug"])
        self.assertEqual(plug["neighbours"][0]["relationship"], "Child")

    def test_the_automation_that_switches_a_router_off_is_a_record(self):
        dig = sre.digest(collected(), NOW)
        auto = [r for r in dig["records"] if r["kind"] == "automation"]
        self.assertEqual(len(auto), 1)
        self.assertEqual(auto[0]["automation"], "Bedtime")
        self.assertEqual(auto[0]["routers"], ["zha:aa:aa:aa:aa:aa:aa:aa:01"])

    def test_a_one_off_warning_is_noise_and_a_token_never_leaves(self):
        dig = sre.digest(collected(), NOW)
        logs = [r for r in dig["records"] if r["kind"] == "log"]
        self.assertEqual(len(logs), 1)
        self.assertNotIn("abcdEF1234567890", json.dumps(dig))
        # Stable across nights: the same complaint is the same id.
        again = sre.digest(collected(), NOW + 86400)
        self.assertEqual(logs[0]["id"],
                         [r for r in again["records"] if r["kind"] == "log"][0]["id"])

    def test_a_healthy_night_is_not_worth_a_run(self):
        quiet = collected(log=[], zha=[{"ieee": "x", "device_type": "Router",
                                        "available": True, "lqi": 200,
                                        "last_seen": iso(60)}],
                          automations=[])
        self.assertFalse(sre.worth_a_run(sre.digest(quiet, NOW)))
        self.assertTrue(sre.worth_a_run(sre.digest(collected(), NOW)))


class TestACauseMustCiteRecords(unittest.TestCase):
    def setUp(self):
        self.dig = sre.digest(collected(), NOW)
        self.router = "zha:aa:aa:aa:aa:aa:aa:aa:01"
        self.auto = next(r["id"] for r in self.dig["records"]
                         if r["kind"] == "automation")

    def test_a_cited_cause_stands(self):
        out = sre.parse_causes({"causes": [{
            "title": "Your bedtime automation switches off the only router upstairs",
            "records": [self.auto, self.router], "severity": "warning",
            "entity_id": "switch.landing_plug"}]}, self.dig)
        self.assertEqual(len(out["causes"]), 1)
        self.assertEqual(out["causes"][0]["anchor"], self.auto)
        self.assertEqual(out["causes"][0]["entity_id"], "switch.landing_plug")

    def test_a_cause_citing_nothing_real_is_refused(self):
        out = sre.parse_causes({"causes": [{
            "title": "The mesh is unhappy", "records": ["zha:made:up"]}]},
            self.dig)
        self.assertEqual(out["causes"], [])
        self.assertEqual((out["refused"], out["invented"]), (1, 1))

    def test_an_invented_id_beside_a_real_one_is_dropped_and_counted(self):
        out = sre.parse_causes({"causes": [{
            "title": "Router down", "records": ["log:nope", self.router]}]},
            self.dig)
        self.assertEqual(out["causes"][0]["records"], [self.router])
        self.assertEqual(out["invented"], 1)

    def test_an_entity_not_in_the_records_is_not_believed(self):
        out = sre.parse_causes({"causes": [{
            "title": "Router down", "records": [self.router],
            "entity_id": "lock.front_door", "severity": "critical"}]}, self.dig)
        self.assertEqual(out["causes"][0]["entity_id"], "")
        # Never critical from a model: the safety lane owns that word.
        self.assertEqual(out["causes"][0]["severity"], "warning")


class PassCase(unittest.TestCase):
    """`_run_sre` over the real findings store, the CLI stubbed."""

    def setUp(self):
        import server
        self.server = server
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "inbox").mkdir()
        fs = server.findings_store
        self._fs = {k: getattr(fs, k) for k in
                    ("FINDINGS_FILE", "INBOX_DIR", "SETTLED_FILE", "STATE_FILE")}
        fs.FINDINGS_FILE = root / "findings.json"
        fs.INBOX_DIR = root / "inbox"
        fs.SETTLED_FILE = root / "settled.json"
        fs.STATE_FILE = root / "config" / ".brain" / "state.json"
        self._sre = sre.STORE
        sre.STORE = str(root / "sre.json")
        self._old = (server.engine.run_claude, server.sre.collect,
                     server._offer_findings)
        self.collected = collected()
        self.replies: list[dict] = []
        self.calls: list[dict] = []

        def run_claude(prompt, system, *a, **k):
            self.calls.append({"prompt": prompt, **k})
            return self.replies.pop(0) if self.replies else {
                "ok": False, "error": "no reply"}

        async def collect(session):
            return self.collected

        server.engine.run_claude = run_claude
        server.sre.collect = collect
        server._offer_findings = lambda rows, now: len(rows)

    def tearDown(self):
        fs = self.server.findings_store
        for k, v in self._fs.items():
            setattr(fs, k, v)
        sre.STORE = self._sre
        (self.server.engine.run_claude, self.server.sre.collect,
         self.server._offer_findings) = self._old
        self.tmp.cleanup()

    def reply(self, causes):
        self.replies.append({"ok": True, "meta": {"session_id": "s1"},
                             "data": {"causes": causes}})

    def run_pass(self):
        asyncio.run(self.server._run_sre("test"))

    def rows(self):
        return [f for f in self.server.findings_store.list_all()
                if f.get("source") == sre.SOURCE]


class TestThePass(PassCase):
    def setUp(self):
        super().setUp()
        dig = sre.digest(self.collected, NOW)
        self.router = "zha:aa:aa:aa:aa:aa:aa:aa:01"
        self.auto = next(r["id"] for r in dig["records"] if r["kind"] == "automation")

    def test_one_row_per_cause_through_the_gate_with_its_evidence(self):
        self.reply([{"title": "Your bedtime automation switches off the only "
                              "Zigbee router upstairs",
                     "detail": "The landing plug routes for the bedroom sensors.",
                     "fix": "Leave the landing plug on overnight.",
                     "records": [self.auto, self.router]}])
        self.run_pass()
        [row] = self.rows()
        self.assertEqual(row["status"], "triaging")
        self.assertEqual(row["source_title"], sre.SOURCE_TITLE)
        self.assertEqual([e["entity"] for e in row["evidence"]],
                         [self.auto, self.router])
        self.assertEqual(self.calls[0]["job"], "sre")
        self.assertIn("RECORDS:", self.calls[0]["prompt"])

    def test_the_same_cause_tomorrow_in_new_words_is_the_same_row(self):
        self.reply([{"title": "Bedtime switches off the upstairs router",
                     "records": [self.auto, self.router]}])
        self.run_pass()
        self.reply([{"title": "The landing plug router is turned off nightly",
                     "records": [self.auto]}])
        self.run_pass()
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.rows()[0]["text"],
                         "Bedtime switches off the upstairs router")

    def test_a_night_that_could_not_read_the_log_clears_nothing(self):
        self.reply([{"title": "Router down", "records": [self.router]}])
        self.run_pass()
        self.collected = collected(available={"log": False, "zha": True,
                                              "registry": True})
        self.run_pass()
        self.assertEqual(len(self.rows()), 1)
        self.assertIn("could not be read", sre.load()["last"]["note"])

    def test_a_healthy_night_clears_and_spends_nothing(self):
        self.reply([{"title": "Router down", "records": [self.log_id()]}])
        self.run_pass()
        self.assertEqual(len(self.rows()), 1)
        self.collected = collected(log=[], zha=[], automations=[])
        calls = len(self.calls)
        self.run_pass()
        self.assertEqual(self.rows(), [])
        self.assertEqual(len(self.calls), calls)

    def test_a_night_zha_did_not_answer_keeps_a_mesh_row(self):
        self.reply([{"title": "Router down", "records": [self.router]}])
        self.run_pass()
        self.collected = collected(
            log=[], zha=[], automations=[],
            available={"log": True, "zha": False, "registry": True})
        self.run_pass()
        self.assertEqual(len(self.rows()), 1)

    def test_a_run_that_failed_files_and_clears_nothing(self):
        self.reply([{"title": "Router down", "records": [self.router]}])
        self.run_pass()
        with self.assertRaises(RuntimeError):
            self.run_pass()   # no reply queued: the run fails
        self.assertEqual(len(self.rows()), 1)

    def log_id(self):
        return next(r["id"] for r in sre.digest(self.collected, NOW)["records"]
                    if r["kind"] == "log")


class TestTheCollector(unittest.IsolatedAsyncioTestCase):
    async def test_no_zha_is_not_available_not_an_empty_mesh(self):
        core = await FakeCore({
            "system_log/list": ok([]),
            "zha/devices": refused("Unknown command."),
            "config/entity_registry/list": ok([]),
            "config/device_registry/list": ok([]),
            "config/area_registry/list": ok([]),
        }).start()
        old_ws, old_api = ha_data.CORE_WS, ha_data.CORE_API
        ha_data.CORE_WS = core.url
        ha_data.CORE_API = "http://127.0.0.1:9/api"   # REST refused: states unread
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                got = await sre.collect(session)
        finally:
            ha_data.CORE_WS, ha_data.CORE_API = old_ws, old_api
            await core.close()
        self.assertTrue(got["available"]["log"])
        self.assertFalse(got["available"]["zha"])
        self.assertFalse(got["available"]["states"])
        self.assertEqual(got["zha"], [])


if __name__ == "__main__":
    unittest.main()
