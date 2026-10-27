"""`brain findings` on a house with hundreds of open findings.

The list used to be handed to its Python printer through an environment
variable, and one environment string is capped by the kernel at 128 KB
(MAX_ARG_STRLEN): a few hundred findings with a sentence of detail each is
past it, and the script died with "Argument list too long" before it had
printed a line. The payload goes through a file now. This drives the real
script against a stand-in panel serving three hundred findings.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPT = BASE_DIR / "brain" / "scripts" / "brain-findings.sh"

COUNT = 300


def _payload() -> dict:
    findings = []
    for i in range(COUNT):
        findings.append({
            "ts": 1_700_000_000 + i,
            "text": f"Garden sensor {i} has stopped reporting",
            "detail": ("It last reported a reading three days ago and has "
                       "said nothing since; the hub it pairs through is "
                       "answering, so the sensor itself is the likely "
                       "cause. ") * 4,
            "fix": "Check its battery, then re-pair it with the hub.",
            "severity": "warning", "status": "open", "snoozed_until": 0,
        })
    return {"findings": findings, "hypotheses": []}


class _Panel(BaseHTTPRequestHandler):
    body = b""

    def do_GET(self):  # noqa: N802 — the stdlib's name
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *_args):
        pass


@pytest.mark.slow
class TestHundredsOfFindings(unittest.TestCase):
    def setUp(self):
        _Panel.body = json.dumps(_payload()).encode()
        self.assertGreater(len(_Panel.body), 131072,
                           "the fixture must be past one environment string")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Panel)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_the_list_prints_every_one(self):
        env = {k: v for k, v in os.environ.items()
               if k.lower() not in ("http_proxy", "https_proxy", "all_proxy")}
        env["NO_PROXY"] = env["no_proxy"] = "127.0.0.1,localhost"
        env["BRAIN_PANEL_URL"] = f"http://127.0.0.1:{self.server.server_port}"
        proc = subprocess.run(["bash", str(SCRIPT), "list"], env=env,
                              capture_output=True, text=True, timeout=60)
        self.assertNotIn("Argument list too long", proc.stderr)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Garden sensor 0 has stopped reporting", proc.stdout)
        self.assertIn(f"Garden sensor {COUNT - 1} has stopped reporting",
                      proc.stdout)


if __name__ == "__main__":
    unittest.main()
