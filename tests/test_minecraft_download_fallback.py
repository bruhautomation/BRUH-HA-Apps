#!/usr/bin/env python3
"""A failed jar check or download must not stop an add-on that has a jar (#575).

With `minecraft_version: LATEST` the version is looked up at every start. A
transient failure of that lookup used to stop the whole add-on although a
working server.jar was already installed. These tests run the real script with
a `curl` that always fails.
"""
from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bruh-minecraft-server" / "scripts" / "download-server.sh"
RUN_SH = Path(__file__).resolve().parent.parent / "bruh-minecraft-server" / "run.sh"


def _run(root: Path, jar: bytes | None, server_type: str = "paper"):
    server = root / "server"
    server.mkdir()
    if jar is not None:
        (server / "server.jar").write_bytes(jar)
        (server / ".server-meta.json").write_text(
            '{"server_type":"paper","version":"1.21.4","build":"100"}')
    bin_dir = root / "bin"
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    curl.write_text("#!/bin/bash\necho 'curl: (6) Could not resolve host' >&2\nexit 6\n")
    curl.chmod(curl.stat().st_mode | stat.S_IEXEC)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}",
           "MC_SERVER_DIR": str(server), "SERVER_CACHE": str(root / "cache"),
           "SERVER_TYPE": server_type, "MINECRAFT_VERSION": "LATEST"}
    proc = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True,
                          text=True, timeout=60)
    return proc, server


class TestDownloadFallback(unittest.TestCase):
    def test_failed_check_with_an_installed_jar_boots_the_old_jar(self):
        for kind in ("paper", "purpur", "vanilla", "fabric"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                proc, server = _run(Path(tmp), b"OLDJAR", kind)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertIn("Starting the installed jar", proc.stderr)
                self.assertIn("next start", proc.stderr)
                self.assertEqual((server / "server.jar").read_bytes(), b"OLDJAR")

    def test_no_jar_at_all_is_fatal_and_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc, _ = _run(Path(tmp), None)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("no server jar is installed", proc.stderr)

    def test_unsupported_type_is_still_a_config_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc, _ = _run(Path(tmp), b"OLDJAR", "bogus")
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("Unsupported server_type", proc.stderr)


class TestRunShTolerates(unittest.TestCase):
    def test_run_sh_boots_the_existing_jar_when_the_download_step_fails(self):
        text = RUN_SH.read_text()
        start = text.index("download_server_jar() {")
        body = text[start:text.index("\n}\n", start)]
        self.assertIn('server.jar', body)
        self.assertRegex(body, r"-s .*server\.jar")


if __name__ == "__main__":
    unittest.main()
