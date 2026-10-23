#!/usr/bin/env python3
"""Designing and printing a part from anywhere: Home Assistant's services
(`design_part`, `design_status`, `print_part`), answered by the panel's own
design routes through the real HA bridge.

The bridge and the panel are both the real code: the bridge's request is
forwarded over HTTP to the panel's aiohttp app, on the loop that serves it,
so what is under test is the same path a service call takes in the
add-on. brAIn is faked at its task folder (test_bambu_design's FakeBrain)
and the CAD build at `runner.build`.
"""
import asyncio
import importlib.util
import os
import sys
import time
import types
import unittest
import unittest.mock as mock

sys.path.insert(0, os.path.dirname(__file__))
# Its modules, not a second load of them: Isolated patches those objects.
from test_bambu_design import (EXAMPLE, FakeBrain, Isolated, ok_build,  # noqa: E402
                               parts, runner, server)

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

BRIDGE_PATH = os.path.join(os.path.dirname(__file__), "..", "bruh-bambu-studio",
                           "integrations", "ha-bridge.py")
_spec = importlib.util.spec_from_file_location("bambu_ha_bridge_anywhere", BRIDGE_PATH)
bridge = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bridge)

DRAFT = {"reply": "Here is a 4 cm wall hook. It takes two screws.", "name": "Wall hook",
         "design_py": EXAMPLE, "change_summary": "First draft"}


class Through(Isolated):
    """The panel served on a loop, the bridge forwarding to it."""

    def setUp(self):
        super().setUp()
        self.panel = server.Panel(start_clients=False)
        self.loop = asyncio.new_event_loop()
        self.addCleanup(self.loop.close)
        self.http = TestClient(TestServer(server.build_app(self.panel, ticker=False)),
                               loop=self.loop)
        self.loop.run_until_complete(self.http.start_server())
        self.addCleanup(lambda: self.loop.run_until_complete(self.http.close()))
        url = str(self.http.make_url("")).rstrip("/")
        p = mock.patch.object(bridge, "PANEL_URL", url)
        p.start()
        self.addCleanup(p.stop)
        b = mock.patch.object(runner, "build", side_effect=ok_build)
        b.start()
        self.addCleanup(b.stop)

    def ask(self, kind, payload=None):
        return self.loop.run_until_complete(
            bridge.handle({"id": "1", "kind": kind, "payload": payload or {}}))

    def wait_idle(self, part_id, seconds=10):
        deadline = time.time() + seconds
        while time.time() < deadline:
            if parts.load(part_id)["state"] in ("idle", "failed"):
                return
            self.loop.run_until_complete(asyncio.sleep(0.05))
        self.fail("the turn never finished")


class TestDesignPart(Through):
    def test_without_brain_it_says_brain_is_needed_and_makes_no_part(self):
        answer = self.ask("design_part", {"description": "a 4 cm wall hook"})
        self.assertFalse(answer["ok"])
        self.assertIn("brAIn", answer["error"])
        self.assertEqual(parts.listing(), [])

    def test_a_new_part_starts_a_turn_and_answers_at_once(self):
        fake = FakeBrain(self.brain, [DRAFT])
        self.addCleanup(fake.stop)
        started = time.time()
        answer = self.ask("design_part", {"description": "a 4 cm wall hook"})
        self.assertLess(time.time() - started, 5)
        self.assertTrue(answer["ok"], answer)
        self.assertTrue(answer["started"])
        self.assertTrue(parts.ID.match(answer["part"]))
        self.assertIn("name", answer)
        self.assertIn("version", answer)
        self.assertTrue(answer["sentence"])
        self.wait_idle(answer["part"])
        status = self.ask("design_status", {"part": answer["part"]})
        self.assertTrue(status["ok"], status)
        self.assertEqual((status["name"], status["version"], status["built"], status["working"]),
                         ("Wall hook", 1, True, False))
        self.assertEqual(status["reply"], "Here is a 4 cm wall hook.")
        self.assertTrue(status["file"].endswith("cable_clip.3mf"))
        self.assertIsNone(status["print"])
        # A successful read carries no `error` key for a caller to misread.
        self.assertNotIn("error", status)
        task = fake.tasks[0]
        self.assertIn("a 4 cm wall hook", task["prompt"])

    def test_a_message_continues_a_part_found_by_name(self):
        fake = FakeBrain(self.brain, [DRAFT, {**DRAFT, "reply": "Longer now. Done."}])
        self.addCleanup(fake.stop)
        first = self.ask("design_part", {"description": "a wall hook"})
        self.wait_idle(first["part"])
        again = self.ask("design_part", {"part": "wall HOOK", "message": "make it 6 cm"})
        self.assertTrue(again["ok"], again)
        self.assertEqual(again["part"], first["part"])
        self.wait_idle(first["part"])
        status = self.ask("design_status", {"part": first["part"]})
        self.assertEqual(status["version"], 2)
        self.assertEqual(status["reply"], "Longer now.")

    def test_a_part_that_does_not_exist_is_refused_in_words(self):
        FakeBrain(self.brain, []).stop()
        answer = self.ask("design_part", {"part": "nothing-here", "message": "bigger"})
        self.assertFalse(answer["ok"])
        self.assertIn("No such part", answer["error"])

    def test_status_of_every_part(self):
        parts.create("Hook")
        parts.create("Clip")
        answer = self.ask("design_status")
        self.assertTrue(answer["ok"])
        self.assertEqual(sorted(p["name"] for p in answer["parts"]), ["Clip", "Hook"])
        self.assertEqual(answer["brain"]["state"], "missing")


class TestPrintPart(Through):
    def built(self):
        part = parts.create("Hook")
        vdir = parts.version_dir(part["id"], 1)
        ok_build(None, vdir)
        part["versions"] = [{"n": 1, "ok": True, "files": {"3mf": "cable_clip.3mf"}}]
        part["current"] = 1
        parts.save(part)
        return part

    def test_print_part_goes_through_start_design_print(self):
        part = self.built()
        seen = {}

        def fake_start(panel, part_id, **kw):
            seen.update(kw, part_id=part_id)
            job = panel.new_job("print", printer="X1C", file="x.3mf", part=part_id)
            return job, {"machine": "m", "process": "p", "filament": "f", "material": "PLA"}, \
                "version 1 on X1C, from AMS 1 (black PLA)"

        with mock.patch.object(server, "start_design_print", side_effect=fake_start):
            answer = self.ask("print_part", {"part": "hook", "printer": "X1C", "copies": 3,
                                             "settings": {"infill_density": 20}})
        self.assertTrue(answer["ok"], answer)
        self.assertEqual(seen["part_id"], part["id"])
        self.assertEqual(seen["printer"], "X1C")
        self.assertEqual(seen["settings"], {"infill_density": 20, "copies": 3})
        self.assertIn("version 1 on X1C", answer["sentence"])
        status = self.ask("design_status", {"part": part["id"]})
        self.assertEqual(status["print"]["state"], "running")
        self.assertEqual(status["print"]["printer"], "X1C")

    def test_the_same_refusals_as_the_design_tab(self):
        self.built()
        answer = self.ask("print_part", {"part": "hook", "printer": "Nope"})
        self.assertFalse(answer["ok"])
        self.assertTrue(answer["error"])
        unbuilt = parts.create("Clip")
        answer = self.ask("print_part", {"part": unbuilt["id"]})
        self.assertFalse(answer["ok"])
        self.assertIn("no built version", answer["error"])


# -- the integration's services ------------------------------------------

sys.path.insert(0, os.path.dirname(__file__))
from test_addon_service_responses import _stubs, registered  # noqa: E402


class TestServices(unittest.TestCase):
    def setUp(self):
        self.seen = registered("bruh_bambu")

    def call(self, name, data, answer=None):
        stubs = _stubs()
        saved = {k: sys.modules.get(k) for k in stubs}
        sys.modules.update(stubs)
        sent = []

        async def fake_forward(kind, payload):
            sent.append((kind, payload))
            return answer or {"part": "hook-abc123"}

        handler = self.seen[name][1]
        old = handler.__globals__["_forward"]
        try:
            handler.__globals__["_forward"] = fake_forward
            got = asyncio.run(handler(types.SimpleNamespace(data=data)))
        finally:
            handler.__globals__["_forward"] = old
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
        return got, sent

    def test_they_answer_with_data(self):
        for name in ("design_part", "design_status", "print_part"):
            with self.subTest(service=name):
                self.assertEqual(self.seen[name][0], "only")

    def test_design_part_reaches_the_add_on(self):
        got, sent = self.call("design_part", {"description": "a hook"})
        self.assertEqual(sent, [("design_part", {"description": "a hook"})])
        self.assertEqual(got, {"part": "hook-abc123"})

    def test_design_part_needs_a_description_or_a_part_and_a_message(self):
        handler = self.seen["design_part"][1]
        error = handler.__globals__["HomeAssistantError"]
        for data in ({}, {"part": "hook"}, {"message": "bigger"}):
            with self.subTest(data=data), self.assertRaises(error):
                self.call("design_part", data)

    def test_print_part_and_status_reach_the_add_on(self):
        _got, sent = self.call("print_part", {"part": "hook", "copies": 2})
        self.assertEqual(sent, [("print_part", {"part": "hook", "copies": 2})])
        _got, sent = self.call("design_status", {})
        self.assertEqual(sent, [("design_status", {})])


if __name__ == "__main__":
    unittest.main()
