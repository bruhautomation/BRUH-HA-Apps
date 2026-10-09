#!/usr/bin/env python3
"""The reports list in ⚙ › Developer can be put away and sent in one press.

Report #167: "This reports list is getting massive… I'd like to submit
multiple issues to fix at the same time." Held here:

  * Archive is the panel's own note (`devloop_archive`): the route takes
    fingerprints, the payload's rows say `archived` and why, and nothing in
    the loop's own files or on GitHub changes;
  * Unarchive is remembered, so the automatic rule does not put a row
    straight back;
  * a fault the loop says is no longer seen is archived automatically, but
    only while the loop's fault stream is on, never over a cloud verdict,
    and never once it is back;
  * Send on several rows marks each as its own Send would, runs ONE pass,
    and the day's cap holds the rest as `ready` with `capped` in the
    answer — the same words a single press reads.

GitHub is `test_devloop`'s loopback fake, so a send is a real send.
"""
from __future__ import annotations

import asyncio
import importlib
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import devloop  # noqa: E402
import devloop.github  # noqa: E402
import devloop.upstream  # noqa: E402
import devloop_archive  # noqa: E402

from test_devloop import NAMES, TOKEN, FakeGitHub, diagnostics  # noqa: E402

github = devloop.github
upstream = devloop.upstream


class ArchiveCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self._old = (devloop.DATA_DIR, devloop.TOKEN_FILE, github.API,
                     dict(upstream.STATE), devloop_archive.STORE)
        devloop.DATA_DIR = base / "devloop"
        devloop.TOKEN_FILE = base / "secrets" / "devloop_github_token"
        devloop_archive.STORE = str(base / "devloop-archive.json")
        self.gh = FakeGitHub()
        github.API = self.gh.url
        upstream.STATE.update(last_sweep=0.0, last_send=0.0, error="",
                              running=False)
        self._faults = upstream.reports.faults
        rows = [{"where": "Runs", "what": "card ended timeout 3 times",
                 "detail": "it timed out"},
                {"where": "Daemons", "what": "not running: automation_listener",
                 "detail": "it stopped"},
                {"where": "Checks", "what": "could not look",
                 "detail": "no snapshot"}]
        upstream.reports.faults = lambda diag: [dict(r) for r in rows]
        devloop.save_settings({"enabled": True, "repo": "me/reports",
                               "review": True, "max_issues_per_day": 2,
                               "streams": {"faults": True}})
        devloop.save_token(TOKEN)
        self.server = importlib.import_module("server")
        upstream.sweep(diagnostics(), NAMES)
        self.fps = [r["fp"] for r in upstream.listing() if r["state"] == "pending"]

    def tearDown(self):
        upstream.reports.faults = self._faults
        (devloop.DATA_DIR, devloop.TOKEN_FILE, github.API, state,
         devloop_archive.STORE) = self._old
        upstream.STATE.clear()
        upstream.STATE.update(state)
        self.gh.close()
        self.tmp.cleanup()

    def _post(self, path: str, body) -> tuple[int, dict]:
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
        app = web.Application()
        app.router.add_post("/api/devloop/archive", self.server.h_devloop_archive)
        app.router.add_post("/api/devloop/send", self.server.h_devloop_send_many)

        async def go():
            async with TestClient(TestServer(app)) as c:
                r = await c.post(path, json=body)
                return r.status, await r.json()
        return asyncio.run(go())

    def row(self, payload: dict, fp: str) -> dict:
        return [r for r in payload["queue"] if r["fp"] == fp][0]


class TestArchive(ArchiveCase):
    def test_archive_and_unarchive_are_a_note_in_the_panel(self):
        self.assertEqual(len(self.fps), 3)
        before = upstream._load()
        status, out = self._post("/api/devloop/archive",
                                 {"fps": self.fps[:2], "archived": True})
        self.assertEqual(status, 200)
        self.assertEqual(out["moved"], 2)
        self.assertTrue(self.row(out, self.fps[0])["archived"])
        self.assertEqual(self.row(out, self.fps[0])["archived_why"], "you")
        self.assertFalse(self.row(out, self.fps[2])["archived"])
        # The loop's own record and GitHub are untouched.
        self.assertEqual(upstream._load(), before)
        self.assertEqual(self.gh.issues, [])
        status, out = self._post("/api/devloop/archive",
                                 {"fps": [self.fps[0]], "archived": False})
        self.assertFalse(self.row(out, self.fps[0])["archived"])

    def test_nothing_named_is_refused(self):
        status, _out = self._post("/api/devloop/archive",
                                  {"fps": ["../../etc/passwd"]})
        self.assertEqual(status, 400)

    def test_a_fault_no_longer_seen_archives_itself_until_it_is_back(self):
        row = {"fp": "0123456789abcdef", "stream": "faults", "state": "sent",
               "cleared_noted": True, "verdict": "open"}
        on = {"enabled": True, "streams": {"faults": True}}
        [r] = devloop_archive.decorate([row], on)
        self.assertEqual((r["archived"], r["archived_why"]), (True, "no longer seen"))
        # Not while the stream is off: then nothing looked.
        [r] = devloop_archive.decorate([row], {"enabled": True, "streams": {}})
        self.assertFalse(r["archived"])
        # A verdict from the cloud stands instead.
        [r] = devloop_archive.decorate([{**row, "verdict": "fixed"}], on)
        self.assertFalse(r["archived"])
        # Back again: the loop clears the flag, and the row is back.
        [r] = devloop_archive.decorate([{**row, "cleared_noted": False}], on)
        self.assertFalse(r["archived"])
        # Unarchived by hand: stays out.
        devloop_archive.set_archived([row["fp"]], False)
        [r] = devloop_archive.decorate([row], on)
        self.assertFalse(r["archived"])

    def test_an_unreadable_archive_hides_nothing(self):
        Path(devloop_archive.STORE).write_text("{not json", encoding="utf-8")
        [r] = devloop_archive.decorate([{"fp": self.fps[0]}], {})
        self.assertFalse(r["archived"])


class TestSendSeveral(ArchiveCase):
    def test_one_press_sends_what_the_cap_allows_and_holds_the_rest(self):
        status, out = self._post("/api/devloop/send", {"fps": self.fps})
        self.assertEqual(status, 200)
        self.assertEqual(sorted(out["marked"]), sorted(self.fps))
        self.assertEqual(out.get("sent"), 2)
        self.assertEqual(out.get("capped"), 1)
        states = sorted(self.row(out, fp)["state"] for fp in self.fps)
        self.assertEqual(states, ["ready", "sent", "sent"])
        self.assertTrue(out["held"]["full"])

    def test_a_sent_report_is_refused_and_named(self):
        self._post("/api/devloop/send", {"fps": self.fps[:1]})
        status, out = self._post("/api/devloop/send", {"fps": self.fps[:1]})
        self.assertEqual(out["refused"], self.fps[:1])
        self.assertEqual(out["marked"], [])


class TestThePanelKnowsTheLoopIsOn(ArchiveCase):
    """`devloop` on /api/status is what lets a card or a reply that says
    brAIn cannot do something offer "Report to brAIn"."""

    def test_on_and_off(self):
        self.assertTrue(self.server._devloop_on())
        devloop.save_settings({"enabled": False})
        self.assertFalse(self.server._devloop_on())
        _auth, read = self.server._status_payload()
        self.assertIs(read["devloop"], False)


if __name__ == "__main__":
    unittest.main()
