#!/usr/bin/env python3
"""Behaviour tests for the PaperMC version/build resolvers in
scripts/download-server.sh.

PaperMC's v2 API is deprecated in favour of the v3 "fill" API. download-server.sh
now resolves Paper/Folia through v3 (with a v2 fallback). The jar download
itself needs the network, so we don't exercise it here — instead we source the
script (its dispatch is guarded behind a `BASH_SOURCE == $0` check) and feed the
pure jq-parsing functions captured-shape API JSON, asserting they pick the right
version and the newest STABLE build.
"""
from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPT = BASE_DIR / "bruh-minecraft-server" / "scripts" / "download-server.sh"


def _call(func: str, stdin: str) -> subprocess.CompletedProcess:
    """Source download-server.sh and pipe `stdin` into `func`."""
    return subprocess.run(
        ["bash", "-c", f'source "{SCRIPT}"; {func}'],
        input=stdin, capture_output=True, text=True, timeout=30,
        env={**os.environ, "MC_SERVER_DIR": "/tmp/nope", "SERVER_CACHE": "/tmp/nope"},
    )


class TestPaperPickVersion(unittest.TestCase):
    def test_v3_object_shape(self):
        payload = json.dumps({"versions": {
            "1.21": ["1.21.4", "1.21.3", "1.21"],
            "1.20": ["1.20.6", "1.20.4"],
        }})
        proc = _call("paper_pick_version", payload)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "1.21.4")

    def test_v2_flat_array_shape(self):
        payload = json.dumps({"versions": ["1.20.6", "1.21", "1.21.4"]})
        proc = _call("paper_pick_version", payload)
        self.assertEqual(proc.stdout.strip(), "1.21.4")

    def test_filters_non_mc_rebuild_markers(self):
        # Purpur/Paper have shipped out-of-order non-MC entries like 26.1.2;
        # they must not win LATEST resolution.
        payload = json.dumps({"versions": ["1.21.4", "26.1.2", "1.20.1"]})
        proc = _call("paper_pick_version", payload)
        self.assertEqual(proc.stdout.strip(), "1.21.4")


class TestPaperPickBuildV3(unittest.TestCase):
    def _builds(self, builds):
        return json.dumps({"builds": builds})

    def test_picks_newest_stable_ignoring_alpha(self):
        payload = self._builds([
            {"id": 10, "channel": "STABLE",
             "downloads": {"server:default": {"url": "https://x/p-10.jar",
                                              "checksums": {"sha256": "aaa"}}}},
            {"id": 12, "channel": "ALPHA",
             "downloads": {"server:default": {"url": "https://x/p-12.jar",
                                              "checksums": {"sha256": "bbb"}}}},
            {"id": 11, "channel": "STABLE",
             "downloads": {"server:default": {"url": "https://x/p-11.jar",
                                              "checksums": {"sha256": "ccc"}}}},
        ])
        proc = _call("paper_pick_build_v3", payload)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        build, url, sha = proc.stdout.strip().split("\t")
        self.assertEqual(build, "11")
        self.assertEqual(url, "https://x/p-11.jar")
        self.assertEqual(sha, "ccc")

    def test_falls_back_to_newest_when_no_stable(self):
        # Right after a fresh MC release there may be no STABLE build yet —
        # take the newest of any channel rather than emitting nothing.
        payload = self._builds([
            {"id": 5, "channel": "ALPHA",
             "downloads": {"server:default": {"url": "https://x/p-5.jar",
                                              "checksums": {"sha256": "z"}}}},
            {"id": 7, "channel": "BETA",
             "downloads": {"server:default": {"url": "https://x/p-7.jar",
                                              "checksums": {"sha256": "y"}}}},
        ])
        proc = _call("paper_pick_build_v3", payload)
        build, url, _sha = proc.stdout.strip().split("\t")
        self.assertEqual(build, "7")
        self.assertEqual(url, "https://x/p-7.jar")

    def test_bare_array_shape(self):
        # Some v3 responses return a bare array rather than {"builds": [...]}.
        payload = json.dumps([
            {"id": 3, "channel": "STABLE",
             "downloads": {"server:default": {"url": "https://x/p-3.jar",
                                              "checksums": {"sha256": "q"}}}},
        ])
        proc = _call("paper_pick_build_v3", payload)
        build, url, _ = proc.stdout.strip().split("\t")
        self.assertEqual(build, "3")
        self.assertEqual(url, "https://x/p-3.jar")


class TestScriptUsesV3(unittest.TestCase):
    def test_references_v3_endpoint_and_user_agent(self):
        text = SCRIPT.read_text()
        self.assertIn("fill.papermc.io/v3", text)
        self.assertIn("PAPER_UA", text)
        # The v3 API rejects requests without a descriptive User-Agent.
        self.assertIn('-A "${PAPER_UA}"', text)


if __name__ == "__main__":
    unittest.main()
