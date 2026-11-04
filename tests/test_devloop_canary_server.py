"""The canary and corpus streams through the real panel's `_devloop_stream`.

`devloop/canary.py` and `devloop/corpus.py` decide; this drives the server
half: the canary pass reads the settled ledger and files its rolling row,
the corpus pass reads the captures only while capture is on, and ⚙'s
settings route accepts the three new settings.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_dispatch import DispatchCase  # noqa: E402

TOKEN = "github_pat_" + "A1b2C3d4E5f6G7h8I9j0" * 2


class TestTheStreamsThroughThePanel(DispatchCase):
    def setUp(self):
        super().setUp()
        root = Path(self.tmp.name)
        self.point("devloop", DATA_DIR=root / "devloop",
                   TOKEN_FILE=root / "secrets" / "devloop_github_token")
        self.point("capture", CAPTURE_DIR=root / "capture")
        dl = self.server.devloop
        dl.save_settings({"enabled": True, "repo": "me/reports", "review": False,
                          "streams": {"corpus": True}})
        dl.save_token(TOKEN)

    def stream(self, name: str, version: str) -> dict:
        payload = {"versions": {"addon": version}, "health": {}}
        return asyncio.run(self.server._devloop_stream(name, payload))

    def test_the_canary_files_a_row_once_the_release_moves(self):
        dl = self.server.devloop
        self.assertEqual(self.stream("canary", "2.17.0")["rows"], 0, "a baseline")
        out = self.stream("canary", "2.17.1")
        self.assertEqual(out["rows"], 1)
        [entry] = [e for e in dl.upstream._load()["items"].values()
                   if e.get("stream") == "canary"]
        self.assertEqual(entry["what"], "brain 2.17.1")
        self.assertEqual(entry["state"], "ready")
        self.assertEqual(entry["canary"]["verdict"], "pending")

    def test_the_corpus_reads_captures_only_while_capture_is_on(self):
        cap = self.server.capture
        run_id = "0f3a9b2c-1111-4222-8333-944455556666"
        cap.CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
        (cap.CAPTURE_DIR / f"{run_id}.json").write_text(json.dumps({
            "schema": 1, "kind": "first_look", "id": run_id, "run_id": run_id,
            "captured_at": int(time.time()), "now": time.time(),
            "batch": [{"kind": "state", "subject": "light.x", "text": "x"}],
            "inputs": {}, "reply": {},
            "labels": [{"signal": 1, "outcome": "missed", "floor": "watch"}]}))
        self.server.settings_store.save({"capture": False})
        self.assertEqual(self.stream("corpus", "2.17.0")["rows"], 0)
        self.server.settings_store.save({"capture": True})
        self.assertEqual(self.stream("corpus", "2.17.0")["rows"], 1)

    def test_the_settings_route_takes_the_new_numbers(self):
        dl = self.server.devloop
        dl.save_settings({"stand_down_days": 45, "canary_window_hours": 12,
                          "house_login": "house-bot"})
        s = dl.load_settings()
        self.assertEqual((s["stand_down_days"], s["canary_window_hours"], s["house_login"]),
                         (45, 12, "house-bot"))
        self.assertIn("efficacy", self.server._devloop_payload()["status"])


if __name__ == "__main__":
    unittest.main()
