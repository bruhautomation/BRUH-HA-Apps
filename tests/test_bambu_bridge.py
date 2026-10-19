#!/usr/bin/env python3
"""The HA bridge forwards to the panel and brings the panel's own words back."""
import asyncio
import importlib.util
import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
import unittest.mock as mock

PATH = os.path.join(os.path.dirname(__file__), "..", "bruh-bambu-studio",
                    "integrations", "ha-bridge.py")
spec = importlib.util.spec_from_file_location("bambu_ha_bridge", PATH)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class Panel(BaseHTTPRequestHandler):
    seen = []

    def _answer(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802 - http.server's name
        Panel.seen.append(("GET", self.path, None))
        if self.path == "/api/state":
            self._answer(200, {"ok": True, "studio": {"installed": True, "version": "v2",
                                                       "running": True, "install": {"phase": "ready"}},
                               "printers": [{"id": "a", "name": "X1C", "state": "idle",
                                             "secret": "no"}], "jobs": []})
        else:
            self._answer(200, {"ok": True, "files": []})

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Panel.seen.append(("POST", self.path, body))
        if body.get("action") == "stop":
            self._answer(409, {"ok": False, "error": "X1C: Not connected to the printer."})
        else:
            self._answer(200, {"ok": True})

    def log_message(self, *args):
        pass  # a test server has nobody to log to


class TestBridge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = HTTPServer(("127.0.0.1", 0), Panel)
        threading.Thread(target=cls.http.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.http.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()

    def ask(self, kind, payload=None):
        Panel.seen.clear()
        with mock.patch.object(bridge, "PANEL_URL", self.url):
            return asyncio.run(bridge.handle({"id": "1", "kind": kind, "payload": payload or {}}))

    def test_the_names_people_use_reach_the_panel_as_its_own(self):
        self.ask("set_speed", {"printer": "X1C", "speed": "sport"})
        self.assertEqual(Panel.seen[-1], ("POST", "/api/printer/command",
                                          {"printer": "X1C", "action": "speed", "value": "sport"}))
        self.ask("set_temperature", {"target": "bed", "temperature": 60})
        self.assertEqual(Panel.seen[-1][2], {"printer": "", "action": "temperature",
                                             "value": 60, "target": "bed"})

    def test_a_print_waits_for_its_job(self):
        self.ask("print_file", {"file": "a.3mf"})
        self.assertEqual(Panel.seen[-1][2]["wait"], bridge.PRINT_WAIT_S)

    def test_a_refusal_comes_back_in_the_panels_words(self):
        answer = self.ask("stop_print")
        self.assertEqual(answer, {"ok": False, "error": "X1C: Not connected to the printer."})

    def test_status_is_trimmed_to_what_a_caller_reads(self):
        answer = self.ask("get_status")
        self.assertEqual(answer["printers"], [{**{k: None for k in answer["printers"][0]},
                                               "id": "a", "name": "X1C", "state": "idle"}])
        self.assertNotIn("secret", answer["printers"][0])
        self.assertEqual(answer["studio"]["install"], "ready")

    def test_an_unknown_kind_is_refused_by_name(self):
        answer = self.ask("launch_rocket")
        self.assertIn("launch_rocket", answer["error"])

    def test_a_panel_that_is_down_says_so(self):
        with mock.patch.object(bridge, "PANEL_URL", "http://127.0.0.1:1"):
            answer = asyncio.run(bridge.handle({"id": "1", "kind": "pause_print"}))
        self.assertIn("not answering", answer["error"])


if __name__ == "__main__":
    unittest.main()
