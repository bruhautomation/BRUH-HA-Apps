#!/usr/bin/env python3
"""A command the printer refused is said as a refusal, and names Developer Mode.

Report #368: an A1 on Bambu's authorization firmware answers an unsigned
command from a LAN client with an ordinary echo and then, a moment later,
raises HMS 0500-0500-0001-0007 ("MQTT Command verification failed") in its
pushed report — unless Developer Mode is on (Settings › LAN only mode ›
Developer mode). The panel read the echo, reported the command as done, and
the printer's own message tells people to update Bambu Studio or Handy.

The printer is faked at paho's client (FakeMQTT, which echoes the way a
printer does), and the HMS entry arrives in the report after the echo.
"""
import json
import threading
import os
import sys
import time
import unittest
import unittest.mock

sys.path.insert(0, os.path.dirname(__file__))
from test_bambu_panel import (  # noqa: E402
    FakeMQTT, RouteTest, client_mod, make_3mf, protocol, server)

# 0500-0500-0001-0007 as the printer sends it: attr then code.
VERIFY_FAILED = {"attr": 0x05000500, "code": 0x00010007}


class RefusingMQTT(FakeMQTT):
    """Echoes success, then raises the verification-failed HMS."""

    def __init__(self, owner, hms_after=0.2):
        super().__init__(owner, "success")
        self.hms_after = hms_after

    def publish(self, topic, body):
        super().publish(topic, body)
        if "pushing" in json.loads(body):
            return

        def later():
            time.sleep(self.hms_after)
            report = {"print": {"hms": [VERIFY_FAILED], "command": "push_status"}}
            self.owner._on_message(None, None, unittest.mock.Mock(
                payload=json.dumps(report).encode()))
        threading.Thread(target=later, daemon=True).start()


def refusing_client():
    c = client_mod.PrinterClient("10.0.0.3", "BBBB11112222", "abcd1234")
    c._client = RefusingMQTT(c)
    c.connected = True
    return c


class TestTheClientSaysItWasRefused(unittest.TestCase):
    def test_a_command_followed_by_the_verification_hms_is_a_refusal(self):
        c = refusing_client()
        with self.assertRaises(RuntimeError) as caught:
            c.send(protocol.simple("pause"))
        words = str(caught.exception)
        self.assertIn("refused", words)
        self.assertIn("Developer Mode", words)
        self.assertNotIn("Handy", words)

    def test_an_old_verification_hms_does_not_refuse_a_new_command(self):
        """The entry stays in the report until it is cleared; a command sent
        after it, that raised nothing new, was not refused."""
        c = client_mod.PrinterClient("10.0.0.3", "BBBB11112222", "abcd1234")
        c._client = FakeMQTT(c)
        c.connected = True
        c._on_message(None, None, unittest.mock.Mock(payload=json.dumps(
            {"print": {"hms": [VERIFY_FAILED]}}).encode()))
        with unittest.mock.patch.object(client_mod, "REFUSAL_WAIT_S", 0.3):
            self.assertTrue(c.send(protocol.simple("pause"))["acknowledged"])

    def test_the_summary_explains_the_code_in_plain_words(self):
        c = refusing_client()
        c._on_message(None, None, unittest.mock.Mock(payload=json.dumps(
            {"print": {"hms": [VERIFY_FAILED]}}).encode()))
        out = c.summary()
        self.assertIn("0500_0500_0001_0007", out["hms"])
        note = out["hms_notes"]["0500_0500_0001_0007"]
        self.assertIn("Developer Mode", note)


class TestTheRoutesSayItToo(RouteTest):
    def setUp(self):
        super().setUp()
        self.real = refusing_client()
        self.panel.clients["aaaa11112222"] = self.real

    def test_a_refused_command_is_an_error_naming_developer_mode(self):
        status, body = self.call("POST", "/api/printer/command", json={"action": "pause"})
        self.assertEqual(status, 409, body)
        self.assertIn("Developer Mode", body["error"])
        self.assertNotIn("acknowledged", body)

    def test_a_refused_print_start_fails_the_job_in_those_words(self):
        make_3mf(self.lib / "sliced" / "benchy.gcode.3mf", plates=(1,))

        class Storage:
            def __init__(self, host, code):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def upload(self, local, name, progress=None):
                return 10

        self.real.status = {"print": {"gcode_state": "IDLE"}}
        with unittest.mock.patch.object(server.ftps, "Storage", Storage):
            _status, body = self.call("POST", "/api/print", json={
                "file": "sliced/benchy.gcode.3mf", "wait": 15})
        self.assertEqual(body["job"]["state"], "failed", body)
        self.assertIn("Developer Mode", body["job"]["error"])
        self.assertNotEqual(body["job"].get("phase"), "started")


if __name__ == "__main__":
    unittest.main()
