#!/usr/bin/env python3
"""Regression tests for install-plugin.sh and the install_plugins loop.

The 1.2.5 fix: a bad plugin URL (404, timeout, non-jar body, missing
URL field) MUST NOT crash the whole add-on. Pre-1.2.5, install-plugin.sh
exited 1 and bashio's implicit set -e in run.sh killed startup entirely
— users saw the add-on exit silently right after "Installing configured
plugins" with no Minecraft server launch.
"""
from __future__ import annotations

import http.server
import os
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ADDON_DIR = BASE_DIR / "bruh-minecraft-server"
SCRIPT = ADDON_DIR / "scripts" / "install-plugin.sh"
RUN_SH = ADDON_DIR / "run.sh"


def _run(args: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT)] + args,
        env={**os.environ, **(env or {})},
        capture_output=True, text=True, check=False, timeout=30,
    )


class TestInstallPluginEdgeCases(unittest.TestCase):
    def test_empty_url_exits_non_zero_with_clear_message(self):
        proc = _run([""])
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("url required", proc.stderr)

    def test_null_literal_url_rejected(self):
        """jq -r on a missing .url field returns 'null'. Must be caught."""
        proc = _run(["null"])
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("url required", proc.stderr)

    def test_non_http_url_rejected(self):
        proc = _run(["file:///etc/passwd"])
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("non-http(s) URL", proc.stderr)

    def test_html_body_is_rejected_as_invalid_jar(self):
        """GitHub rate-limit pages come back as 200 OK with HTML. We must
        treat those as failures, not save them as a jar."""
        # Serve a plain HTML response on a random port.
        class _HTMLHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<html><body>rate limited</body></html>")

            def log_message(self, *_args):  # silence test output
                return

        server = http.server.HTTPServer(("127.0.0.1", 0), _HTMLHandler)
        port = server.server_port
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                proc = _run(
                    [f"http://127.0.0.1:{port}/Plugin.jar", "Plugin.jar"],
                    env={"MC_SERVER_DIR": tmp},
                )
                self.assertNotEqual(proc.returncode, 0)
                self.assertIn("isn't a valid jar", proc.stderr)
                # And no corrupt jar was left behind
                self.assertFalse(
                    (Path(tmp) / "plugins" / "Plugin.jar").exists(),
                    "invalid download must not be saved as a jar",
                )
        finally:
            server.shutdown()

    def test_valid_jar_download_succeeds(self):
        """A real ZIP/PK payload lands in plugins/ with the right name."""
        class _JarHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(200)
                self.send_header("Content-Type", "application/java-archive")
                self.end_headers()
                # Minimum bytes: ZIP signature "PK\x03\x04" + filler
                self.wfile.write(b"PK\x03\x04" + b"\x00" * 16)

            def log_message(self, *_args):
                return

        server = http.server.HTTPServer(("127.0.0.1", 0), _JarHandler)
        port = server.server_port
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                proc = _run(
                    [f"http://127.0.0.1:{port}/test-plugin.jar"],
                    env={"MC_SERVER_DIR": tmp},
                )
                self.assertEqual(proc.returncode, 0, proc.stderr)
                jar = Path(tmp) / "plugins" / "test-plugin.jar"
                self.assertTrue(jar.exists())
                self.assertTrue(jar.read_bytes().startswith(b"PK"))
        finally:
            server.shutdown()


class TestInstallPluginsIsolation(unittest.TestCase):
    """install_plugins in run.sh must tolerate individual plugin failures
    without aborting the add-on. This is the 1.2.5 regression guard."""

    def test_run_sh_defensively_wraps_install_plugin(self):
        text = RUN_SH.read_text()
        # Locate the install_plugins function body
        start = text.index("install_plugins()")
        # Grab the next ~100 lines of context
        body = text[start:start + 3000]
        self.assertIn(
            "Plugin install failed", body,
            "install_plugins must log a warning on per-plugin failure instead of aborting",
        )
        self.assertIn(
            "set +o pipefail", body,
            "install_plugins must disable pipefail around the loop so one 404 "
            "doesn't crash the whole add-on (see 1.2.5 changelog)",
        )
        # And there must be a `|| bashio::log.warning` guard at the top level
        self.assertRegex(
            body, r"\)\s*\|\|\s*bashio::log\.warning",
            msg="install_plugins subshell must have a '|| bashio::log.warning' fallback",
        )


if __name__ == "__main__":
    unittest.main()
