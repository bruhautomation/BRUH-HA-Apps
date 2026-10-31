#!/usr/bin/env python3
"""A failed backup must come out of the bridge as a failure with its reason.

#570: the bridge answered ok:false with only the script output, and the
integration's backup_now raised the generic "server refused the request" (or,
before that, reported done). The reason has to travel in `error`.
"""
from __future__ import annotations

import asyncio
import stat
import unittest
from pathlib import Path

from test_minecraft_bridge import BridgeTestCase


class TestBackupAnswer(BridgeTestCase):
    def _stub(self, body: str) -> None:
        d = Path(self.tmp.name) / "scripts"
        d.mkdir(exist_ok=True)
        s = d / "backup.sh"
        s.write_text("#!/bin/bash\n" + body)
        s.chmod(s.stat().st_mode | stat.S_IEXEC)
        self.bridge.SCRIPTS_DIR = d

    def test_failed_backup_carries_the_reason(self):
        self._stub("echo '[backup] ERROR: rsync is not installed'\nexit 1\n")
        answer = asyncio.run(self.bridge.handle({"kind": "backup", "payload": {}}))
        self.assertFalse(answer["ok"])
        self.assertIn("rsync is not installed", answer["error"])

    def test_good_backup_is_done(self):
        self._stub("echo fine\nexit 0\n")
        answer = asyncio.run(self.bridge.handle({"kind": "backup", "payload": {}}))
        self.assertTrue(answer["ok"])
        self.assertNotIn("error", answer)


if __name__ == "__main__":
    unittest.main()
