"""Which cameras brAIn may look at on its own, and how often.

Two paths looked through cameras with nobody's agreement — the voice
prompt told every Assist turn to check a camera whenever it liked, and the
`camera_check` insight preset looked at every camera on a timer — and the
Resident had no way to confirm a smoke alarm or an open door by looking.
Now there is one list (`settings_store.camera_confirm`, empty by default),
one daily count, and one chokepoint (the MCP server's snapshot tool), and
the Resident's investigation gets a GRANT of cameras only for a safety
trip or a closure.

The load-bearing test drives the real MCP tool into the real panel route
over a real socket, because the two halves are different processes and a
fake panel that answers what the test expects proves only that it agrees
with itself.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
PANEL = REPO / "brain" / "panel"
MCP_DIR = REPO / "brain" / "ha-mcp-server"
sys.path.insert(0, str(PANEL))
sys.path.insert(0, str(MCP_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import camera_policy  # noqa: E402
import settings_store  # noqa: E402
from test_resident_loop import LoopCase  # noqa: E402

DAY = "2026-10-04"
NOW = 1_790_000_000.0


class LedgerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._ledger = camera_policy.LEDGER
        camera_policy.LEDGER = self.root / "camera-uses.json"
        self._settings = settings_store.SETTINGS_FILE
        settings_store.SETTINGS_FILE = str(self.root / "settings.json")

    def tearDown(self):
        camera_policy.LEDGER = self._ledger
        settings_store.SETTINGS_FILE = self._settings
        self.tmp.cleanup()


class TestTheList(LedgerCase):
    def test_no_camera_is_allowed_until_somebody_ticks_one(self):
        self.assertEqual(settings_store.load()["camera_confirm"], [])

    def test_only_camera_ids_are_kept_and_the_list_is_capped(self):
        saved = settings_store.save({"camera_confirm": [" Camera.Porch ", "camera.porch",
                                                        "camera.drive"]})
        self.assertEqual(saved["camera_confirm"], ["camera.porch", "camera.drive"])
        with self.assertRaises(ValueError):
            settings_store.save({"camera_confirm": ["light.hall"]})
        with self.assertRaises(ValueError):
            settings_store.save({"camera_confirm": [f"camera.c{i}" for i in range(30)]})

    def test_a_list_that_cannot_be_read_allows_no_camera(self):
        Path(settings_store.SETTINGS_FILE).write_text(
            json.dumps({"camera_confirm": ["camera.porch", "lock.front"]}))
        self.assertEqual(settings_store.load()["camera_confirm"], [])


class TestOneLook(LedgerCase):
    def test_a_camera_nobody_allowed_is_refused_with_where_to_allow_it(self):
        ok, why = camera_policy.permit("camera.porch", "voice", None, [], DAY, NOW)
        self.assertFalse(ok)
        self.assertIn("Cameras", why)
        self.assertFalse(camera_policy.LEDGER.exists())

    def test_an_allowed_camera_is_looked_at_and_counted(self):
        ok, why = camera_policy.permit("camera.porch", "voice", None,
                                       ["camera.porch"], DAY, NOW)
        self.assertEqual((ok, why), (True, ""))
        self.assertEqual(camera_policy.used(DAY), (1, ""))

    def test_the_day_has_a_cap(self):
        with patch.object(camera_policy, "PER_DAY", 2):
            for _ in range(2):
                self.assertTrue(camera_policy.permit(
                    "camera.porch", "task", None, ["camera.porch"], DAY, NOW)[0])
            ok, why = camera_policy.permit("camera.porch", "task", None,
                                           ["camera.porch"], DAY, NOW)
        self.assertFalse(ok)
        self.assertIn("tomorrow", why)
        # Yesterday's looks are yesterday's.
        self.assertTrue(camera_policy.permit("camera.porch", "task", None,
                                             ["camera.porch"], "2026-10-05", NOW)[0])

    def test_a_grant_narrows_and_never_widens(self):
        ok, why = camera_policy.permit("camera.drive", "resident", ["camera.porch"],
                                       ["camera.porch", "camera.drive"], DAY, NOW)
        self.assertFalse(ok)
        self.assertIn("camera.porch", why)
        ok, _ = camera_policy.permit("camera.attic", "resident", ["camera.attic"],
                                     ["camera.porch"], DAY, NOW)
        self.assertFalse(ok, "a grant may not reach a camera nobody allowed")

    def test_a_count_that_cannot_be_read_refuses(self):
        camera_policy.LEDGER.write_text("{nope")
        ok, why = camera_policy.permit("camera.porch", "voice", None,
                                       ["camera.porch"], DAY, NOW)
        self.assertFalse(ok)
        self.assertIn("could not count", why)

    def test_a_look_that_cannot_be_recorded_is_not_taken(self):
        def boom(*a, **k):
            raise OSError("read-only file system")
        with patch.object(camera_policy.atomic_write, "write_text", boom):
            ok, why = camera_policy.permit("camera.porch", "voice", None,
                                           ["camera.porch"], DAY, NOW)
        self.assertFalse(ok)
        self.assertIn("could not record", why)


class TestWhenTheResidentMayLook(unittest.TestCase):
    def test_safety_and_closures_and_nothing_else(self):
        kind = camera_policy.trip_kind
        self.assertEqual(kind({"subject": "binary_sensor.leak", "safety": True}), "safety")
        self.assertEqual(kind({"subject": "x", "source": "safety"}), "safety")
        self.assertEqual(kind({"subject": "sensor.loft", "source": "check:climate.freeze"}),
                         "safety")
        self.assertEqual(kind({"subject": "binary_sensor.smoke"},
                              safety_subjects={"binary_sensor.smoke": 1}), "safety")
        self.assertEqual(kind({"subject": "lock.front"}), "closure")
        self.assertEqual(kind({"subject": "cover.garage"}), "closure")
        self.assertEqual(kind({"subject": "x", "source": "check:evening.left_open"}),
                         "closure")
        self.assertEqual(kind({"subject": "binary_sensor.back_door"},
                              closure_subjects={"binary_sensor.back_door": 1}), "closure")
        self.assertEqual(kind({"subject": "sensor.freezer_temp", "source": "check:base.unusual"}),
                         "")
        self.assertEqual(kind({"subject": "light.hall", "kind": "state"}), "")

    def test_the_grant_is_the_room_first(self):
        areas = {"binary_sensor.kitchen_smoke": "kitchen", "camera.kitchen": "kitchen",
                 "camera.porch": "porch"}
        self.assertEqual(camera_policy.grant_for(
            "binary_sensor.kitchen_smoke", ["camera.porch", "camera.kitchen"], areas),
            ["camera.kitchen"])
        self.assertEqual(camera_policy.grant_for(
            "binary_sensor.loft_smoke", ["camera.porch", "camera.kitchen"], areas),
            ["camera.porch", "camera.kitchen"])


class TestTheRunIsHandedOnlyItsGrant(unittest.TestCase):
    """`engine.run_analyst(camera_grant=...)`: the tool and the env, per run."""

    def setUp(self):
        import engine
        self.engine = engine
        self.calls = []

        def spawn(argv, prompt, timeout, message):
            self.calls.append({"argv": list(argv), "env": engine._claude_env()})
            return {"ok": True, "text": "x", "meta": {}}

        self._spawn = engine._spawn_cli
        engine._spawn_cli = spawn

    def tearDown(self):
        self.engine._spawn_cli = self._spawn

    def flag(self, call, name):
        argv = call["argv"]
        return argv[argv.index(name) + 1].split(",")

    def test_no_grant_keeps_the_camera_denied_and_no_grant_in_the_env(self):
        with patch.dict(os.environ, {"BRAIN_CAMERA_GRANT": "camera.stray"}):
            self.engine.run_analyst("p", "s", "sonnet", 10, 4, "card")
        [call] = self.calls
        self.assertIn(self.engine.CAMERA_TOOL, self.flag(call, "--disallowedTools"))
        self.assertNotIn(self.engine.CAMERA_TOOL, self.flag(call, "--allowedTools"))
        self.assertNotIn("BRAIN_CAMERA_GRANT", call["env"],
                         "a grant the panel inherited reached a run nobody granted")

    def test_a_grant_lifts_the_tool_for_this_run_and_names_the_cameras(self):
        self.engine.run_analyst("p", "s", "sonnet", 10, 4, "resident",
                                camera_grant=("camera.kitchen", "light.not_a_camera"))
        self.engine.run_analyst("p", "s", "sonnet", 10, 4, "card")
        granted, plain = self.calls
        self.assertIn(self.engine.CAMERA_TOOL, self.flag(granted, "--allowedTools"))
        self.assertNotIn(self.engine.CAMERA_TOOL, self.flag(granted, "--disallowedTools"))
        self.assertEqual(granted["env"]["BRAIN_CAMERA_GRANT"], "camera.kitchen")
        # The next run, on the same thread, carries none of it.
        self.assertNotIn("BRAIN_CAMERA_GRANT", plain["env"])
        self.assertIn(self.engine.CAMERA_TOOL, self.flag(plain, "--disallowedTools"))


class PanelThread:
    """The REAL panel route on a real socket, in a thread of its own."""

    def __init__(self, server):
        from aiohttp import web
        self.loop = asyncio.new_event_loop()
        self.ready = threading.Event()
        app = web.Application()
        app.router.add_post("/api/camera/permit", server.h_camera_permit)

        async def start():
            self.runner = web.AppRunner(app)
            await self.runner.setup()
            site = web.TCPSite(self.runner, "127.0.0.1", 0)
            await site.start()
            self.port = site._server.sockets[0].getsockname()[1]
            self.ready.set()

        def run():
            asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(start())
            self.loop.run_forever()

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        self.ready.wait(5)

    def stop(self):
        async def down():
            await self.runner.cleanup()
        asyncio.run_coroutine_threadsafe(down(), self.loop).result(5)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)


class TestTheChokepointAsksThePanel(LedgerCase):
    """`ha_mcp_server.get_camera_snapshot` into the real `h_camera_permit`."""

    @classmethod
    def setUpClass(cls):
        cls.server = importlib.import_module("server")
        cls.mcp = importlib.import_module("ha_mcp_server")

    def setUp(self):
        super().setUp()
        self.panel = PanelThread(self.server)
        self._url = self.mcp.PANEL_URL
        self.mcp.PANEL_URL = f"http://127.0.0.1:{self.panel.port}"
        self.fetched = []

        def raw(path, *a, **k):
            self.fetched.append(path)
            return b"\xff\xd8\xff\xe0 not really a jpeg"

        self._raw = self.mcp.ha_api_request_raw
        self.mcp.ha_api_request_raw = raw
        self.env = patch.dict(os.environ, {}, clear=False)
        self.env.start()
        for key in ("BRAIN_CHANNEL", "BRAIN_ASSIST_ACCESS", "BRAIN_EXPOSED_ONLY",
                    "BRAIN_CAMERA_GRANT"):
            os.environ.pop(key, None)

    def tearDown(self):
        self.env.stop()
        self.mcp.PANEL_URL = self._url
        self.mcp.ha_api_request_raw = self._raw
        self.panel.stop()
        super().tearDown()

    def snap(self, entity="camera.porch"):
        return self.mcp.get_camera_snapshot(entity)

    def test_voice_is_refused_a_camera_nobody_allowed_and_nothing_is_fetched(self):
        os.environ["BRAIN_CHANNEL"] = "voice"
        got = self.snap()
        self.assertIn("error", got)
        self.assertIn("not been allowed", got["error"])
        self.assertEqual(self.fetched, [])

    def test_voice_sees_an_allowed_camera_and_the_look_is_counted(self):
        settings_store.save({"camera_confirm": ["camera.porch"]})
        os.environ["BRAIN_CHANNEL"] = "voice"
        got = self.snap()
        self.assertIn("_mcp_image", got)
        self.assertEqual(self.fetched, ["/api/camera_proxy/camera.porch"])
        rows = json.loads(camera_policy.LEDGER.read_text())["uses"]
        self.assertEqual([(r["entity_id"], r["channel"]) for r in rows],
                         [("camera.porch", "voice")])

    def test_a_task_is_governed_too_and_the_cap_holds(self):
        settings_store.save({"camera_confirm": ["camera.porch"]})
        os.environ["BRAIN_CHANNEL"] = "task"
        with patch.object(camera_policy, "PER_DAY", 1):
            self.assertIn("_mcp_image", self.snap())
            again = self.snap()
        self.assertIn("tomorrow", again["error"])
        self.assertEqual(len(self.fetched), 1)

    def test_a_granted_run_reaches_only_its_grant(self):
        settings_store.save({"camera_confirm": ["camera.porch", "camera.kitchen"]})
        os.environ["BRAIN_CAMERA_GRANT"] = "camera.kitchen"
        self.assertIn("error", self.snap("camera.porch"))
        self.assertIn("_mcp_image", self.snap("camera.kitchen"))
        rows = json.loads(camera_policy.LEDGER.read_text())["uses"]
        self.assertEqual(rows[-1]["channel"], "resident")

    def test_a_person_in_the_chat_is_not_asked(self):
        got = self.snap()
        self.assertIn("_mcp_image", got)
        self.assertFalse(camera_policy.LEDGER.exists(),
                         "a person looking was counted against the house's cap")

    def test_a_panel_that_does_not_answer_refuses(self):
        os.environ["BRAIN_CHANNEL"] = "voice"
        self.mcp.PANEL_URL = "http://127.0.0.1:9"
        got = self.snap()
        self.assertIn("could not ask", got["error"])
        self.assertEqual(self.fetched, [])


class TestTheInvestigationGetsTheGrant(LoopCase):
    """`_resident_investigate`, driven over the real stores."""

    def run_with(self, signal, cameras, **subjects):
        tmp = tempfile.TemporaryDirectory()
        old = camera_policy.LEDGER
        camera_policy.LEDGER = Path(tmp.name) / "uses.json"
        srv = self.server
        try:
            settings_store.save({"onboarded": True, "auto_enabled": True,
                                 "camera_confirm": cameras})
            srv.SAFETY_SUBJECTS.update(subjects.get("safety", {}))
            srv._FACTS_CTX["entity_areas"] = subjects.get("areas", {})
            asyncio.run(srv._resident_investigate(signal, NOW, "normal"))
            return self.analyst_calls
        finally:
            srv.SAFETY_SUBJECTS.clear()
            srv._FACTS_CTX["entity_areas"] = {}
            camera_policy.LEDGER = old
            tmp.cleanup()

    def test_a_tripped_leak_sensor_hands_the_run_the_room_camera(self):
        calls = self.run_with(
            {"kind": "state", "subject": "binary_sensor.kitchen_leak", "safety": True,
             "salience": 0.9, "text": "Kitchen leak dry → wet", "evidence": []},
            ["camera.kitchen", "camera.porch"],
            areas={"binary_sensor.kitchen_leak": "kitchen", "camera.kitchen": "kitchen"})
        [call] = calls
        self.assertEqual(call["camera_grant"], ("camera.kitchen",))
        self.assertIn("get_camera_snapshot", call["prompt"])
        self.assertIn("never describe a person", call["prompt"])

    def test_an_ordinary_signal_gets_no_camera(self):
        calls = self.run_with(
            {"kind": "check", "subject": "sensor.freezer_temp", "source": "check:base.unusual",
             "salience": 0.5, "text": "Freezer warm", "evidence": []},
            ["camera.kitchen"])
        [call] = calls
        self.assertEqual(call["camera_grant"], ())
        self.assertNotIn("get_camera_snapshot", call["prompt"])

    def test_no_camera_allowed_is_no_camera_granted(self):
        calls = self.run_with(
            {"kind": "state", "subject": "lock.front", "salience": 0.7,
             "text": "Front door unlocked", "evidence": []}, [])
        self.assertEqual(calls[0]["camera_grant"], ())


class TestTheListenerLiftsOnlyTheCameraTool(unittest.TestCase):
    def flags(self, mode, cameras=""):
        from test_task_tool_scope import lift
        harness = lift("task_tool_flags") + f'\ntask_tool_flags "{mode}" "{cameras}"\n'
        out = subprocess.run(["bash", "-c", harness], capture_output=True, text=True,
                             env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                                  "BRAIN_PANEL_DIR": str(PANEL)}, check=False)
        lines = [ln for ln in out.stdout.splitlines() if ln]
        return dict(zip(lines[::2], (ln.split(",") for ln in lines[1::2])))

    def test_read_only_denies_it_unless_the_task_asked(self):
        import engine
        plain = self.flags("read_only")
        self.assertIn(engine.CAMERA_TOOL, plain["--disallowedTools"])
        asked = self.flags("read_only", "true")
        self.assertIn(engine.CAMERA_TOOL, asked["--allowedTools"])
        self.assertNotIn(engine.CAMERA_TOOL, asked["--disallowedTools"])
        # Nothing else moved.
        self.assertEqual(set(plain["--disallowedTools"]) - {engine.CAMERA_TOOL},
                         set(asked["--disallowedTools"]))


class TestTheUngovernedPathsAreClosed(unittest.TestCase):
    def test_the_voice_prompts_no_longer_send_turns_to_cameras(self):
        for path in (REPO / "brain" / "integrations" / "assist-worker-pool.py",
                     REPO / "brain" / "integrations" / "assist-listener.sh"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("To CHECK A CAMERA", text, path.name)
            self.assertIn("allowed brAIn to look at it", text, path.name)

    def test_the_camera_preset_asks_for_the_tool_and_says_it_is_governed(self):
        sys.path.insert(0, str(REPO / "brain" / "custom_components" / "brain"))
        import insight_format
        self.assertIn("camera_check", insight_format.CAMERA_TEMPLATES)
        text = insight_format.INSIGHT_TEMPLATES["camera_check"]
        self.assertIn("allowed", text)
        self.assertIn("Never describe a person", text)


class TestTheInsightPresetAsksForTheCamera(unittest.TestCase):
    def test_only_the_preset_text_gets_the_flag(self):
        from test_ha_service_gates import TestInsightJobs

        class Case(TestInsightJobs):
            def runTest(self):  # pragma: no cover
                pass

        case = Case()
        case.setUp()
        try:
            case.entry.data = {"entry_type": "insight", "insight_template": "camera_check"}
            case.run_insight()
            self.assertIs(case.sent[-1]["cameras"], True)
            case.entry.data = {"entry_type": "insight",
                               "insight_template": "camera_check",
                               "insight_prompt": "Summarise the night."}
            case.run_insight()
            self.assertIs(case.sent[-1]["cameras"], False)
        finally:
            case.doCleanups()


if __name__ == "__main__":
    unittest.main()
