"""The phone's microphone, for Claude Code's own /voice.

Driven end to end: a real aiohttp server with the panel's own routes, a
WebSocket client standing in for the terminal page's Talk button, and the
real `scripts/brain-arecord.py` run as a subprocess with the exact argv
Claude Code 2.1.307 spawns (`-f S16_LE -r 16000 -c 1 -t raw -q -`). What
the page sends has to come out of the stand-in's stdout byte for byte,
because that stdout is what the CLI streams to its transcriber.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import voice_mic  # noqa: E402

ARECORD = BASE_DIR / "brain" / "scripts" / "brain-arecord.py"
CLI_ARGV = ["-f", "S16_LE", "-r", "16000", "-c", "1", "-t", "raw", "-q", "-"]
PROBE_ARGV = ["-f", "S16_LE", "-r", "16000", "-c", "1", "-t", "raw", "/dev/null"]


def _app() -> web.Application:
    app = web.Application()
    voice_mic.setup(app)
    return app


def _run_arecord(argv, url, timeout=10, wait=True):
    env = dict(os.environ, BRAIN_PANEL_URL=url)
    proc = subprocess.Popen([sys.executable, str(ARECORD), *argv],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=env)
    if wait:
        out, err = proc.communicate(timeout=timeout)
        return proc.returncode, out, err
    return proc


class TestTheStandInAnswersWhatTheCliAsks(unittest.TestCase):
    """The three calls the CLI makes, before any audio is involved."""

    def test_version_exits_zero(self):
        code, out, _ = _run_arecord(["--version"], "http://127.0.0.1:9")
        self.assertEqual(code, 0)
        self.assertIn(b"arecord", out)

    def test_the_probe_to_dev_null_succeeds_at_once(self):
        # Exit 0 is what the CLI's probe reads as "recording works"; a
        # failure there would send people to install SoX.
        code, _, _ = _run_arecord(PROBE_ARGV, "http://127.0.0.1:9", timeout=5)
        self.assertEqual(code, 0)

    def test_a_format_it_cannot_produce_is_refused(self):
        code, _, err = _run_arecord(["-f", "S16_LE", "-r", "44100", "-c", "1",
                                     "-t", "raw", "-"], "http://127.0.0.1:9")
        self.assertEqual(code, 1)
        self.assertIn(b"16000", err)

    def test_a_panel_that_is_not_there_is_said(self):
        code, out, err = _run_arecord(CLI_ARGV, "http://127.0.0.1:9")
        self.assertEqual(code, 1)
        self.assertEqual(out, b"")
        self.assertIn(b"not answering", err)


@pytest.mark.slow
class TestThePhoneReachesTheCli(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.server = TestServer(_app(), host="127.0.0.1")
        self.client = TestClient(self.server)
        await self.client.start_server()
        self.url = str(self.server.make_url("")).rstrip("/")

    async def asyncTearDown(self):
        await self.client.close()

    async def _next_json(self, ws, key, timeout=5):
        while True:
            msg = await asyncio.wait_for(ws.receive(), timeout)
            data = json.loads(msg.data)
            if key in data:
                return data

    async def test_what_the_page_sends_is_what_the_cli_reads(self):
        ws = await self.client.ws_connect("/api/voice/mic")
        ready = await self._next_json(ws, "ready")
        self.assertFalse(ready["listening"])

        before = bytes(range(256)) * 4          # in the pre-roll
        await ws.send_bytes(before)
        await asyncio.sleep(0.05)

        proc = await asyncio.to_thread(_run_arecord, CLI_ARGV, self.url,
                                       10, False)
        listening = await self._next_json(ws, "listening")
        self.assertTrue(listening["listening"])

        after = bytes(reversed(range(256))) * 8
        await ws.send_bytes(after)
        await asyncio.sleep(0.2)
        await ws.close()                         # the page stops talking

        out, err = await asyncio.to_thread(proc.communicate, timeout=10)
        self.assertEqual(proc.returncode, 0, err)
        self.assertEqual(out, before + after)

    async def test_sigterm_is_how_the_cli_stops_and_it_is_not_a_failure(self):
        ws = await self.client.ws_connect("/api/voice/mic")
        await self._next_json(ws, "ready")
        await ws.send_bytes(b"\x01\x00" * 800)
        proc = await asyncio.to_thread(_run_arecord, CLI_ARGV, self.url,
                                       10, False)
        await self._next_json(ws, "listening")
        proc.terminate()
        await asyncio.to_thread(proc.wait, 10)
        self.assertEqual(proc.returncode, 0)
        # And the page hears that nobody is reading any more.
        stopped = await self._next_json(ws, "listening")
        self.assertFalse(stopped["listening"])
        await ws.close()

    async def test_no_page_means_the_recording_ends_and_says_why(self):
        with unittest.mock.patch.object(voice_mic, "WAIT_FOR_SOURCE_S", 0.2):
            code, out, err = await asyncio.to_thread(
                _run_arecord, CLI_ARGV, self.url)
        self.assertEqual(code, 1)
        self.assertEqual(out, b"")
        self.assertIn(b"mic button", err)

    async def test_a_second_page_takes_over_and_the_first_is_told(self):
        first = await self.client.ws_connect("/api/voice/mic")
        await self._next_json(first, "ready")
        second = await self.client.ws_connect("/api/voice/mic")
        await self._next_json(second, "ready")
        told = await self._next_json(first, "replaced")
        self.assertTrue(told["replaced"])
        await second.close()

    async def test_half_a_sample_is_never_passed_on(self):
        hub = self.server.app[voice_mic.HUB_KEY]
        queue = hub.listen()
        hub.source = object()  # feed() does not look at the source
        hub.feed(b"\x01\x02\x03")
        self.assertEqual(queue.get_nowait(), b"\x01\x02")


@pytest.mark.slow
class TestOnlyTheContainerCanListen(unittest.IsolatedAsyncioTestCase):

    async def test_a_listener_that_is_not_loopback_is_refused(self):
        client = TestClient(TestServer(_app(), host="127.0.0.1"))
        await client.start_server()
        try:
            with unittest.mock.patch.object(voice_mic.ownership, "from_loopback",
                                   return_value=False):
                resp = await client.get("/api/voice/listen")
            self.assertEqual(resp.status, 403)
        finally:
            await client.close()

    async def test_no_terminal_no_microphone(self):
        client = TestClient(TestServer(_app(), host="127.0.0.1"))
        await client.start_server()
        try:
            with unittest.mock.patch.dict(os.environ, {"BRAIN_ENABLE_TERMINAL": "false"}):
                resp = await client.get("/api/voice/mic")
            self.assertEqual(resp.status, 404)
        finally:
            await client.close()


class TestTheCliSettingIsReadTheWayTheCliReadsIt(unittest.TestCase):

    def _read(self, content):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            if content is not None:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(content)
            return voice_mic.voice_setting(path)

    def test_no_file_is_voice_off(self):
        self.assertEqual(self._read(None),
                         {"known": True, "enabled": False, "mode": "hold"})

    def test_tap_mode_as_the_cli_writes_it(self):
        state = self._read(json.dumps(
            {"voiceEnabled": True, "voice": {"enabled": True, "mode": "tap"}}))
        self.assertEqual(state, {"known": True, "enabled": True, "mode": "tap"})

    def test_the_nested_key_wins(self):
        state = self._read(json.dumps(
            {"voiceEnabled": True, "voice": {"enabled": False}}))
        self.assertFalse(state["enabled"])

    def test_the_old_flag_alone_still_counts(self):
        self.assertTrue(self._read(json.dumps({"voiceEnabled": True}))["enabled"])

    def test_an_unreadable_file_is_not_voice_off(self):
        self.assertFalse(self._read("{not json")["known"])


class TestItShips(unittest.TestCase):

    def test_the_image_installs_the_stand_in_as_arecord(self):
        dockerfile = (BASE_DIR / "brain" / "Dockerfile").read_text()
        self.assertIn("/opt/scripts/brain-arecord.py /usr/local/bin/arecord",
                      dockerfile)

    def test_the_panel_registers_the_routes(self):
        server = (BASE_DIR / "brain" / "panel" / "server.py").read_text()
        self.assertIn("voice_mic.setup(app)", server)

    def test_the_terminal_frame_may_use_the_microphone(self):
        index = (BASE_DIR / "brain" / "panel" / "index.html").read_text()
        self.assertIn("microphone", index.split('id="termFrame"', 1)[1]
                      .split(">", 1)[0])


if __name__ == "__main__":
    unittest.main()
