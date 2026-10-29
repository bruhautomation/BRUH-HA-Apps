#!/usr/bin/env python3
""""I can't confirm it arrived", said twice in two conversations.

Filed as an unmet request with no more context. Traced in the code to what
the chat is actually handed after it sends something:

* the MCP `send_notification` returned Home Assistant's REST answer to a
  service call verbatim — `[]` for a notify — which says nothing: not the
  service, not the time, not even that it was accepted, so the only honest
  sentence a model could build on it was "I can't confirm it arrived";
* `ha notify` ran `curl -s` with no status check and printed "Notification
  sent" whatever Home Assistant answered — a refused service and a missing
  phone read as sent;
* brAIn's OWN messages are in a delivery ledger (`deliveries.py`: when,
  where, sent or failed with the error, answered or cleared where the phone
  says so) that no tool a conversation has could read.

Now: the tool's result is a receipt (the service, the time Home Assistant
accepted it, and in plain words what no receipt exists for and what the
person can check), `ha notify` fails on a refusal and prints the same
receipt, and `notification_history` reads the ledger over loopback so
"did my phone get the freezer alert" has an answer with a time on it.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))
sys.path.insert(0, str(BASE_DIR / "brain" / "ha-mcp-server"))

import deliveries  # noqa: E402

from test_todo_list import PanelCase  # noqa: E402

NOTIFY_SH = BASE_DIR / "brain" / "scripts" / "ha-notify.sh"


class TestTheToolHandsBackAReceipt(unittest.TestCase):
    def setUp(self):
        import ha_mcp_server
        self.mcp = ha_mcp_server
        self._call = ha_mcp_server.call_service
        self.calls = []
        self.answer = []

        def fake(domain, service, data=None, return_response=False):
            self.calls.append((domain, service, data))
            return self.answer

        ha_mcp_server.call_service = fake

    def tearDown(self):
        self.mcp.call_service = self._call

    def test_a_phone_send_says_where_and_when_and_what_cannot_be_known(self):
        got = self.mcp.send_notification("Bins out", target="mobile_app_pixel")
        self.assertEqual(self.calls[0][:2], ("notify", "mobile_app_pixel"))
        self.assertTrue(got["sent"])
        self.assertEqual(got["service"], "notify.mobile_app_pixel")
        self.assertRegex(got["accepted_at"], r"^\d{4}-\d\d-\d\d \d\d:\d\d$")
        receipt = got["receipt"]
        self.assertIn("notify.mobile_app_pixel", receipt)
        self.assertIn(got["accepted_at"], receipt)
        # The part no receipt exists for, said, and what to check.
        self.assertIn("does not report", receipt)
        self.assertIn("phone", receipt)

    def test_a_refusal_is_not_a_receipt(self):
        self.answer = {"error": "Service notify.mobile_app_gone not found"}
        got = self.mcp.send_notification("Bins out", target="mobile_app_gone")
        self.assertFalse(got["sent"])
        self.assertIn("not found", got["error"])
        self.assertNotIn("accepted_at", got)

    def test_a_persistent_notification_is_somewhere_a_person_can_look(self):
        got = self.mcp.send_notification("Filter due", title="House")
        self.assertEqual(self.calls[0][:2], ("persistent_notification", "create"))
        self.assertTrue(got["sent"])
        self.assertIn("notifications", got["receipt"])


class TestTheLedgerIsReadable(unittest.TestCase):
    def setUp(self):
        import ha_mcp_server
        self.mcp = ha_mcp_server
        self._get = ha_mcp_server._panel_get
        self.asked = []

        def fake(path, timeout=60):
            self.asked.append(path)
            return {"readable": True, "rows": [
                {"id": "a1", "at": 1_790_000_000, "kind": "escalate",
                 "service": "notify.mobile_app_pixel", "title": "Freezer warm",
                 "ok": True, "outcome": "answered", "action": "todo",
                 "after_s": 60},
                {"id": "a2", "at": 1_789_990_000, "kind": "notify",
                 "service": "notify.mobile_app_pixel", "title": "Battery low",
                 "ok": False, "error": "Service not found",
                 "outcome": "failed"},
            ]}

        ha_mcp_server._panel_get = fake

    def tearDown(self):
        self.mcp._panel_get = self._get

    def test_it_reads_the_panel_and_gives_each_a_wall_clock_time(self):
        got = self.mcp.notification_history(hours=48)
        self.assertIn("/api/deliveries", self.asked[-1])
        self.assertIn("hours=48", self.asked[-1])
        first, second = got["messages"]
        self.assertEqual(first["sent_at"], self.mcp._local_text(1_790_000_000))
        self.assertEqual(first["to"], "notify.mobile_app_pixel")
        self.assertEqual(first["outcome"], "answered")
        self.assertEqual(second["outcome"], "failed")
        self.assertEqual(second["error"], "Service not found")
        # What the outcomes can and cannot say, so "pending" is not read
        # as "it never arrived".
        self.assertIn("opened", got["note"])

    def test_it_is_a_read_the_analyst_may_make_and_voice_may_not(self):
        import engine
        self.assertIn("mcp__home-assistant__notification_history",
                      engine.ANALYST_TOOLS)
        self.assertIn("notification_history", self.mcp.VOICE_REFUSED_TOOLS)
        names = {t["name"] for t in self.mcp.TOOLS}
        self.assertIn("notification_history", names)
        self.assertIn("notification_history", self.mcp.TOOL_IMPLEMENTATIONS)


class TestThePanelRoute(PanelCase):
    def setUp(self):
        super().setUp()
        self._file = deliveries.DELIVERIES_FILE
        deliveries.DELIVERIES_FILE = Path(self.tmp.name) / "deliveries.jsonl"

    def tearDown(self):
        deliveries.DELIVERIES_FILE = self._file
        super().tearDown()

    def test_the_ledger_comes_back_with_outcomes(self):
        deliveries.record("notify", delivery_id="x1",
                          service="notify.mobile_app_pixel",
                          title="Freezer warm", body="It is 6 degrees up.")
        deliveries.record("notify", delivery_id="x2",
                          service="notify.mobile_app_pixel",
                          title="Battery low", body="", ok=False,
                          error="Service not found")

        async def body(client):
            res = await client.get("/api/deliveries?hours=24&limit=5")
            self.assertEqual(res.status, 200)
            return await res.json()
        got = self.drive(body)
        self.assertTrue(got["readable"])
        by_id = {r["id"]: r for r in got["rows"]}
        self.assertEqual(by_id["x1"]["service"], "notify.mobile_app_pixel")
        self.assertEqual(by_id["x1"]["outcome"], "pending")
        self.assertEqual(by_id["x2"]["outcome"], "failed")
        self.assertEqual(by_id["x2"]["error"], "Service not found")


def _fake_curl(bindir: Path, code: str, body: str) -> None:
    """A curl that answers like Core: writes `body` where -o says and
    prints `code` for -w."""
    script = bindir / "curl"
    script.write_text(
        "#!/bin/bash\n"
        "out=''\n"
        "while [ $# -gt 0 ]; do\n"
        "  case \"$1\" in -o) shift; out=\"$1\";; esac\n"
        "  shift\n"
        "done\n"
        f"if [ -n \"$out\" ]; then printf '%s' '{body}' > \"$out\"; else printf '%s' '{body}'; fi\n"
        f"printf '%s' '{code}'\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)


@pytest.mark.slow
class TestHaNotify(unittest.TestCase):
    def run_notify(self, code: str, body: str, *args: str):
        with tempfile.TemporaryDirectory() as tmp:
            bindir = Path(tmp)
            _fake_curl(bindir, code, body)
            env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}",
                   "SUPERVISOR_TOKEN": "t"}
            return subprocess.run(["bash", str(NOTIFY_SH), *args], env=env,
                                  capture_output=True, text=True, timeout=30)

    def test_a_refused_send_fails_and_never_says_sent(self):
        res = self.run_notify("400", json.dumps({"message": "Service not found"}),
                              "hi", "--target", "gone")
        self.assertNotEqual(res.returncode, 0)
        self.assertNotIn("sent to", res.stdout.lower())
        self.assertIn("400", res.stdout + res.stderr)

    def test_an_accepted_send_says_where_and_when_and_what_is_unknown(self):
        res = self.run_notify("200", "[]", "hi", "--target", "pixel")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("notify.mobile_app_pixel", res.stdout)
        self.assertRegex(res.stdout, r"\d\d:\d\d")
        self.assertIn("does not report", res.stdout)


if __name__ == "__main__":
    unittest.main()
