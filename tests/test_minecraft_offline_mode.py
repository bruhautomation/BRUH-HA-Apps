"""Behaviour tests for offline mode (1.3.0).

When the host has no internet access, run.sh sets BMS_OFFLINE=true and
the download / install scripts MUST short-circuit their curl calls and
reuse cached artefacts rather than hanging on unreachable upstreams.

These tests exercise the actual shell scripts end-to-end (no mocks) by
running them with BMS_OFFLINE=true and a controlled filesystem layout.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
DOWNLOAD_SCRIPT = BASE_DIR / "bruh-minecraft-server" / "scripts" / "download-server.sh"
BEDROCK_SCRIPT = BASE_DIR / "bruh-minecraft-server" / "scripts" / "install-bedrock-support.sh"
RUN_SH = BASE_DIR / "bruh-minecraft-server" / "run.sh"


class TestRunShDetectNetworkMode(unittest.TestCase):
    """run.sh must define detect_network_mode() and call it before any
    network-dependent step (download_server_jar, install_plugins,
    install_bedrock_support)."""

    @classmethod
    def setUpClass(cls):
        cls.run_sh = RUN_SH.read_text()

    def test_detect_network_mode_function_exists(self):
        self.assertIn("detect_network_mode()", self.run_sh)

    def test_detect_network_mode_exports_BMS_OFFLINE(self):
        self.assertIn('export BMS_OFFLINE="false"', self.run_sh)
        self.assertIn('export BMS_OFFLINE="true"', self.run_sh)

    def test_detect_network_mode_called_in_main(self):
        # Find the main() function and check detect_network_mode is called
        match = re.search(r"^main\(\)\s*\{(.+?)^\}", self.run_sh, re.DOTALL | re.MULTILINE)
        self.assertIsNotNone(match, "main() not found in run.sh")
        body = match.group(1)
        self.assertIn("detect_network_mode", body)

    def test_download_server_jar_short_circuits_when_offline(self):
        """download_server_jar() in run.sh must reuse existing server.jar
        when BMS_OFFLINE=true rather than calling the download script."""
        match = re.search(
            r"download_server_jar\(\)\s*\{(.+?)^\}",
            self.run_sh, re.DOTALL | re.MULTILINE,
        )
        self.assertIsNotNone(match)
        body = match.group(1)
        self.assertIn('BMS_OFFLINE', body)

    def test_install_plugins_short_circuits_when_offline(self):
        match = re.search(
            r"install_plugins\(\)\s*\{(.+?)^\}",
            self.run_sh, re.DOTALL | re.MULTILINE,
        )
        self.assertIsNotNone(match)
        body = match.group(1)
        self.assertIn('BMS_OFFLINE', body)


class TestDownloadServerOfflineFallback(unittest.TestCase):
    """download-server.sh must reuse the existing server.jar when
    BMS_OFFLINE=true, and fail with a clear error when there's no
    cached jar to fall back to."""

    def _run(self, server_dir: Path, *, has_existing_jar: bool, server_type: str = "paper"):
        if has_existing_jar:
            (server_dir / "server.jar").write_bytes(b"PK\x03\x04fake-jar-content")
        env = {
            **os.environ,
            "BMS_OFFLINE": "true",
            "MC_SERVER_DIR": str(server_dir),
            "SERVER_CACHE": str(server_dir / "_cache"),
            "SERVER_TYPE": server_type,
            "MINECRAFT_VERSION": "LATEST",
        }
        proc = subprocess.run(
            ["bash", str(DOWNLOAD_SCRIPT)],
            env=env, capture_output=True, text=True, check=False,
        )
        return proc

    def test_offline_with_cached_jar_succeeds_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            server_dir = Path(tmp)
            proc = self._run(server_dir, has_existing_jar=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("Offline mode", proc.stderr)
            self.assertIn("reusing existing server.jar", proc.stderr)
            # The jar should be untouched
            self.assertTrue((server_dir / "server.jar").exists())

    def test_offline_with_no_cached_jar_fails_clearly(self):
        with tempfile.TemporaryDirectory() as tmp:
            server_dir = Path(tmp)
            proc = self._run(server_dir, has_existing_jar=False)
            self.assertEqual(proc.returncode, 1)
            self.assertIn("offline mode and no cached server.jar", proc.stderr.lower())
            # Must include actionable guidance
            self.assertIn("internet", proc.stderr.lower())


class TestBedrockOfflineFallback(unittest.TestCase):
    """install-bedrock-support.sh must skip install_jar() calls when
    BMS_OFFLINE=true and reuse cached Geyser/Floodgate jars."""

    @classmethod
    def setUpClass(cls):
        cls.script_text = BEDROCK_SCRIPT.read_text()

    def test_install_jar_calls_are_gated_by_BMS_OFFLINE(self):
        """The script source must check BMS_OFFLINE before calling install_jar
        to avoid network calls when offline."""
        self.assertIn("BMS_OFFLINE", self.script_text)
        # And the install_jar callsites must be inside an else branch (i.e.,
        # only run when NOT offline).
        # Verify the gate is defensive: BMS_OFFLINE check appears BEFORE the
        # install_jar geyser line.
        offline_idx = self.script_text.find('BMS_OFFLINE:-false')
        first_install_idx = self.script_text.rfind("install_jar geyser")
        self.assertGreater(first_install_idx, offline_idx,
                           "install_jar callsites must be after the BMS_OFFLINE check")

    def _run_offline(self, server_dir: Path, *, seed_jars: bool):
        plugins_dir = server_dir / "plugins"
        plugins_dir.mkdir()
        if seed_jars:
            (plugins_dir / "Geyser-Spigot.jar").write_bytes(b"PKfake")
            (plugins_dir / "floodgate-spigot.jar").write_bytes(b"PKfake")
        env = {
            **os.environ,
            "BMS_OFFLINE": "true",
            "MC_SERVER_DIR": str(server_dir),
            "SERVER_TYPE": "paper",
            "MOTD": "test",
            "ONLINE_MODE": "true",
            "GEYSER_AUTH_TYPE": "floodgate",
        }
        # Replace install_jar with a tripwire — if it's ever called we fail
        # the test loudly. This is the strongest assertion that the offline
        # gate is doing its job.
        source = BEDROCK_SCRIPT.read_text()
        tripwire_install_jar = (
            "install_jar() {\n"
            "    echo 'TRIPWIRE: install_jar called in offline mode' >&2\n"
            "    exit 99\n"
            "}\n"
        )
        # Stub configure_geyser too so we don't need a real Geyser config tree
        stub_configure_geyser = (
            "configure_geyser() { return 0; }\n"
        )
        patched = re.sub(
            r"^install_jar\(\)\s*\{.*?^\}\s*$",
            tripwire_install_jar,
            source, count=1, flags=re.DOTALL | re.MULTILINE,
        )
        patched = re.sub(
            r"^configure_geyser\(\)\s*\{.*?^\}\s*$",
            stub_configure_geyser,
            patched, count=1, flags=re.DOTALL | re.MULTILINE,
        )
        proc = subprocess.run(
            ["bash", "-c", patched],
            env=env, capture_output=True, text=True, check=False,
        )
        return proc

    def test_offline_with_cached_jars_skips_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            server_dir = Path(tmp)
            proc = self._run_offline(server_dir, seed_jars=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertNotIn("TRIPWIRE", proc.stderr,
                             "install_jar must NOT be called when offline")
            self.assertIn("Offline", proc.stderr)
            self.assertIn("Geyser", proc.stderr)

    def test_offline_with_no_cached_jars_warns_but_does_not_fail(self):
        """When offline AND there's no cached Geyser jar, the add-on shouldn't
        crash — it should log a clear warning and continue (the Java server
        will still work, Bedrock just won't)."""
        with tempfile.TemporaryDirectory() as tmp:
            server_dir = Path(tmp)
            proc = self._run_offline(server_dir, seed_jars=False)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("no cached Geyser jar", proc.stderr)


if __name__ == "__main__":
    unittest.main()
