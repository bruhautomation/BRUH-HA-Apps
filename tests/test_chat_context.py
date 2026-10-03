#!/usr/bin/env python3
"""The chat is told who it is, what it remembers, and how this house works.

It used to start as Claude Code's own software-engineering prompt plus the
boot-time ``/config/CLAUDE.md``, which had no area map (the computed
``areas`` was a count nothing printed), named none of brAIn's measurement
tools, and taught "edit automations.yaml, then ``ha reload automations``"
— a path that skips the replay, the grade and the protected-entities
check every other way of adding an automation goes through. And nothing
was fetched for the message being typed, where every scheduled run is
handed the facts about what it reads.

Four pieces, each driven:

* the ``UserPromptSubmit`` hook script, run as the CLI runs it — against a
  real HTTP server standing in for the panel, and against no panel at all,
  because for this event exit 2 BLOCKS the message;
* the panel's retrieval behind it, over a real facts store, including that
  a conversation is handed each fact once rather than with every message;
* the appended system prompt's text;
* the context generator's area map, lifted out of the script and run
  against a stub of the MCP server module it imports.
"""

import importlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
HOOK = BASE_DIR / "brain" / "scripts" / "brain-chat-context.py"
CONTEXT_GEN = BASE_DIR / "brain" / "scripts" / "ha-context-gen.sh"

sys.path.insert(0, str(PANEL_DIR))


def load_hook():
    spec = importlib.util.spec_from_file_location("brain_chat_context", HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakePanel:
    """`POST /api/chat/context`, answering what it is told to."""

    def __init__(self, answer=None, raw=None, delay=0.0):
        self.seen: list[dict] = []
        panel = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 — http.server's spelling
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                panel.seen.append({"path": self.path, "body": body})
                if delay:
                    time.sleep(delay)
                payload = raw if raw is not None else json.dumps(answer).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class TestTheHook(unittest.TestCase):
    def run_hook(self, stdin: str, panel_url: str, budget="2.0"):
        env = {**os.environ, "BRAIN_PANEL_URL": panel_url,
               "BRAIN_CHAT_CONTEXT_BUDGET": budget}
        return subprocess.run([sys.executable, str(HOOK)], input=stdin,
                              capture_output=True, text=True, env=env,
                              timeout=20)

    def test_it_hands_the_panels_answer_to_the_turn(self):
        panel = FakePanel({"context": "The kitchen light is on a timer."})
        try:
            out = self.run_hook(json.dumps({
                "session_id": "abc-123", "hook_event_name": "UserPromptSubmit",
                "prompt": "why is the kitchen light on?"}), panel.url)
        finally:
            panel.close()
        self.assertEqual(out.returncode, 0, out.stderr)
        payload = json.loads(out.stdout)
        self.assertEqual(payload["hookSpecificOutput"]["hookEventName"],
                         "UserPromptSubmit")
        self.assertEqual(payload["hookSpecificOutput"]["additionalContext"],
                         "The kitchen light is on a timer.")
        self.assertEqual(panel.seen[0]["path"], "/api/chat/context")
        self.assertEqual(panel.seen[0]["body"],
                         {"prompt": "why is the kitchen light on?",
                          "session_id": "abc-123"})

    def test_nothing_to_say_adds_nothing(self):
        panel = FakePanel({"context": ""})
        try:
            out = self.run_hook(json.dumps({"prompt": "hello"}), panel.url)
        finally:
            panel.close()
        self.assertEqual((out.returncode, out.stdout), (0, ""))

    def test_no_panel_never_blocks_the_message(self):
        """Exit 2 from this hook refuses what somebody typed. A panel that
        is down is a message with no context, never a refused one."""
        out = self.run_hook(json.dumps({"prompt": "hello"}),
                            "http://127.0.0.1:9")
        self.assertEqual((out.returncode, out.stdout), (0, ""))

    def test_a_slow_panel_is_given_up_on_inside_the_budget(self):
        panel = FakePanel({"context": "late"}, delay=3.0)
        try:
            started = time.monotonic()
            out = self.run_hook(json.dumps({"prompt": "hello"}), panel.url,
                                budget="0.5")
            took = time.monotonic() - started
        finally:
            panel.close()
        self.assertEqual((out.returncode, out.stdout), (0, ""))
        self.assertLess(took, 2.5)

    def test_garbage_in_and_garbage_back_are_both_nothing(self):
        panel = FakePanel(raw=b"<html>not json</html>")
        try:
            for stdin in ("", "not json", "[]", json.dumps({"prompt": 7})):
                out = self.run_hook(stdin, panel.url)
                self.assertEqual((out.returncode, out.stdout), (0, ""), stdin)
            out = self.run_hook(json.dumps({"prompt": "hi"}), panel.url)
            self.assertEqual((out.returncode, out.stdout), (0, ""))
        finally:
            panel.close()

    def test_why_the_hook_is_only_named_when_the_script_exists(self):
        """The reason `chat_session._settings` checks the file: Python's
        own answer to a missing script is exit 2, which for this event is
        the CLI refusing the prompt."""
        missing = subprocess.run([sys.executable, "/nonexistent/hook.py"],
                                 capture_output=True, timeout=20)
        self.assertEqual(missing.returncode, 2)

    def test_main_can_be_driven_in_process(self):
        hook = load_hook()
        out = io.StringIO()
        self.assertEqual(hook.main(io.StringIO("{}"), out), 0)
        self.assertEqual(out.getvalue(), "")


class TestTheRetrievalBehindIt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = importlib.import_module("server")
        cls.facts = importlib.import_module("facts_store")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._olds = (self.facts.FACTS_FILE, dict(self.server._NAMES),
                      dict(self.server._FACTS_CTX))
        self.facts.FACTS_FILE = Path(self.tmp.name) / "facts.json"
        self.server._NAMES.clear()
        self.server._NAMES.update({
            "light.kitchen_ceiling": {"name": "Kitchen ceiling", "area": "Kitchen"},
            "switch.porch": {"name": "Porch light", "area": "Outside"}})
        self.server._FACTS_CTX["areas"] = {"garage": "Garage"}
        self.server._CHAT_CONTEXT_GIVEN.clear()
        self.facts.add("The kitchen ceiling light is on a timer until 23:00.",
                       subject="light.kitchen_ceiling", source="person")
        self.facts.add("The garage freezer is the old one and runs warm.",
                       subject="area:garage", source="card")
        self.facts.add("Nobody is home on Tuesday afternoons.",
                       subject="house", source="person")
        self.facts.add("The pool pump runs on cheap-rate electricity.",
                       subject="switch.pool_pump", source="study")

    def tearDown(self):
        self.facts.FACTS_FILE = self._olds[0]
        self.server._NAMES.clear()
        self.server._NAMES.update(self._olds[1])
        self.server._FACTS_CTX.clear()
        self.server._FACTS_CTX.update(self._olds[2])
        self.server._CHAT_CONTEXT_GIVEN.clear()
        self.tmp.cleanup()

    def test_a_friendly_name_in_the_message_finds_its_facts(self):
        text = self.server._chat_context(
            "is the kitchen ceiling still coming on late?", "s1")
        self.assertIn("on a timer until 23:00", text)
        # The core facts ride along; another entity's do not.
        self.assertIn("Nobody is home on Tuesday afternoons", text)
        self.assertNotIn("pool pump", text)

    def test_an_area_named_in_the_message_finds_its_facts(self):
        text = self.server._chat_context("what is up with the garage?", "s1")
        self.assertIn("runs warm", text)

    def test_a_message_naming_nothing_falls_back_to_the_words(self):
        text = self.server._chat_context("when does the pump run?", "s1")
        self.assertIn("cheap-rate electricity", text)

    def test_a_conversation_is_handed_each_fact_once(self):
        """The context is added to the turn and stays in the conversation;
        handing the same core facts with every message is paying for them
        again on every turn after."""
        first = self.server._chat_context("kitchen ceiling light?", "s1")
        self.assertIn("on a timer", first)
        again = self.server._chat_context("and the kitchen ceiling light?", "s1")
        self.assertEqual(again, "")
        other = self.server._chat_context("kitchen ceiling light?", "s2")
        self.assertIn("on a timer", other)
        # A CLI that sends no session id is told everything, every time.
        self.assertIn("on a timer",
                      self.server._chat_context("kitchen ceiling light?", ""))

    def test_the_remembered_conversations_are_bounded(self):
        for n in range(self.server.CHAT_CONTEXT_SESSIONS + 10):
            self.server._chat_context("kitchen ceiling light?", f"s{n}")
        self.assertLessEqual(len(self.server._CHAT_CONTEXT_GIVEN),
                             self.server.CHAT_CONTEXT_SESSIONS)

    def test_an_empty_message_is_nothing(self):
        self.assertEqual(self.server._chat_context("   ", "s1"), "")

    def test_a_store_that_cannot_be_read_is_nothing_not_an_error(self):
        self.facts.FACTS_FILE = Path(self.tmp.name) / "missing" / "facts.json"
        self.assertEqual(self.server._chat_context("kitchen ceiling?", "s1"), "")


class TestTheRoute(unittest.IsolatedAsyncioTestCase):
    async def test_the_route_answers_with_a_context_and_never_an_error(self):
        server = importlib.import_module("server")
        seen = []
        old = server._chat_context
        server._chat_context = lambda prompt, sid="": seen.append(
            (prompt, sid)) or "remembered"
        from aiohttp.test_utils import TestClient, TestServer
        client = TestClient(TestServer(server.make_app()))
        await client.start_server()
        try:
            res = await client.post("/api/chat/context",
                                    json={"prompt": "hi", "session_id": "x"})
            self.assertEqual(await res.json(), {"context": "remembered"})
            res = await client.post("/api/chat/context", data=b"not json")
            self.assertEqual(res.status, 200)
        finally:
            server._chat_context = old
            await client.close()
        self.assertEqual(seen[0], ("hi", "x"))


class TestTheAppendedPrompt(unittest.TestCase):
    def test_it_names_brain_the_tools_and_the_way_to_add_a_rule(self):
        server = importlib.import_module("server")
        text = server._chat_system_prompt(None)
        self.assertTrue(text.startswith("You are brAIn"))
        for tool in ("what_is_normal", "room_physics", "recall",
                     "get_findings", "get_health", "simulate_automation"):
            self.assertIn(tool, text)
        self.assertIn('service "intent"', text)
        self.assertIn("Do not write automations.yaml", text)

    def test_the_house_lines_are_labelled_as_a_snapshot(self):
        server = importlib.import_module("server")
        old = server._chat_house_lines
        server._chat_house_lines = lambda: ["3 things waiting"]
        try:
            text = server._chat_system_prompt(None)
        finally:
            server._chat_house_lines = old
        self.assertIn("When this conversation started: 3 things waiting", text)
        self.assertIn("That is a snapshot", text)


class TestTheContextFile(unittest.TestCase):
    """`ha-context-gen.sh` is the project CLAUDE.md the terminal and the
    chat both read."""

    @classmethod
    def setUpClass(cls):
        source = CONTEXT_GEN.read_text(encoding="utf-8")
        match = re.search(
            r"area_map=\$\(python3 - 2>/dev/null <<'PYEOF'\n(.*?)\nPYEOF\n",
            source, re.S)
        assert match, "ha-context-gen.sh no longer builds the area map"
        cls.source = source
        cls.recipe = match.group(1)

    def run_recipe(self, stub: str):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "ha_mcp_server.py").write_text(stub)
            env = {**os.environ, "PYTHONPATH": tmp}
            return subprocess.run([sys.executable, "-c", self.recipe],
                                  capture_output=True, text=True, env=env,
                                  timeout=20)

    def test_the_map_lists_each_room_and_what_is_in_it(self):
        out = self.run_recipe(
            "def get_areas():\n"
            "    return {'areas': [\n"
            "        {'area_id': 'kitchen', 'name': 'Kitchen',\n"
            "         'entities': ['light.kitchen_ceiling', 'switch.kettle']},\n"
            "        {'area_id': 'hall', 'name': 'Hall',\n"
            "         'entities': ['binary_sensor.hall_motion_%d' % n\n"
            "                      for n in range(14)]},\n"
            "        {'area_id': 'loft', 'name': 'Loft', 'entities': []}]}\n")
        self.assertEqual(out.returncode, 0, out.stderr)
        lines = out.stdout.splitlines()
        self.assertIn("  - Kitchen (`kitchen`): light.kitchen_ceiling, "
                      "switch.kettle", lines)
        self.assertTrue(any(line.startswith("  - Hall (`hall`)")
                            and line.endswith("(+4 more)") for line in lines),
                        lines)
        self.assertIn("  - Loft (`loft`): no entities", lines)

    def test_a_house_with_no_areas_says_so(self):
        out = self.run_recipe("def get_areas():\n    return {'areas': []}\n")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("no areas are set up", out.stdout)

    def test_a_lookup_that_failed_is_not_read_as_a_house_with_no_rooms(self):
        """The recipe exits non-zero, and the script's `||` then writes the
        marker that names the tool to ask instead."""
        for stub in ("def get_areas():\n    return {'error': 'no token'}\n",
                     "def get_areas():\n    raise RuntimeError('down')\n",
                     "raise ImportError('nope')\n"):
            out = self.run_recipe(stub)
            self.assertNotEqual(out.returncode, 0, stub)
            self.assertEqual(out.stdout, "", stub)
        self.assertIn('|| area_map="  - (lookup failed — use the get_areas '
                      'MCP tool)"', self.source)

    def test_the_file_teaches_the_tools_and_the_way_to_add_a_rule(self):
        """Prose the generated file carries — what Claude reads to learn
        how to work here — so a read of the text is the honest check."""
        for tool in ("what_is_normal", "room_physics", "appliance_status",
                     "house_rhythm", "door_habits", "habits", "recall",
                     "get_findings", "get_health", "simulate_automation"):
            self.assertIn(f"\\`{tool}\\`", self.source, tool)
        self.assertIn("\\`brain.intent\\`", self.source)
        self.assertIn("${area_map}", self.source)
        # The unconditional instruction to edit-then-reload is gone.
        self.assertNotIn("Always run \\`ha reload automations\\` after editing",
                         self.source)

    def test_the_script_still_parses(self):
        out = subprocess.run(["bash", "-n", str(CONTEXT_GEN)],
                             capture_output=True, text=True, timeout=20)
        self.assertEqual(out.returncode, 0, out.stderr)


if __name__ == "__main__":
    unittest.main()
