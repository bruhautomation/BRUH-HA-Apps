#!/usr/bin/env python3
"""The development loop: this house's faults, as issues in a private repo.

The claims the feature makes, each driven rather than described:

  * it is off, and an off loop sends nothing and sweeps nothing;
  * what leaves is aliased — no entity id, name or room from the house,
    no credential — while file names and service verbs survive, because a
    report nobody can read is no use to the one person it is for;
  * one fault is one issue: digits fold, a second pass files nothing new,
    and a queue wiped by a reinstall finds its issue again by the marker;
  * review holds a new report until a press, and Delete is for good;
  * a public repository is refused;
  * after the first send the loop says only WHEN: it stopped, it is back,
    it is still happening on a newer version.

GitHub is a real HTTP server on loopback speaking the five calls the
client makes, so a request shape the code gets wrong fails here.
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import devloop  # noqa: E402
import devloop.aliases  # noqa: E402
import devloop.github  # noqa: E402
import devloop.upstream  # noqa: E402

aliases_mod = devloop.aliases
github = devloop.github
upstream = devloop.upstream

TOKEN = "github_pat_" + "A1b2C3d4E5f6G7h8I9j0" * 2


class FakeGitHub:
    """Issues and comments for one repository, over HTTP."""

    def __init__(self, private: bool = True):
        self.private = private
        self.issues: list[dict] = []
        self.comments: list[tuple[int, str]] = []
        self.requests: list[tuple[str, str]] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, status, body):
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _body(self):
                n = int(self.headers.get("Content-Length") or 0)
                return json.loads(self.rfile.read(n) or b"{}")

            def _authed(self):
                if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                    self._send(401, {"message": "Bad credentials"})
                    return False
                return True

            def do_GET(self):
                fake.requests.append(("GET", self.path))
                if not self._authed():
                    return
                path = self.path.split("?")[0]
                if path == "/repos/me/reports":
                    self._send(200, {"private": fake.private})
                    return
                if path == "/repos/me/reports/issues":
                    page = int(re.search(r"[?&]page=(\d+)", self.path).group(1))
                    rows = list(reversed(fake.issues))[(page - 1) * 100:page * 100]
                    self._send(200, rows)
                    return
                m = re.match(r"^/repos/me/reports/issues/(\d+)$", path)
                if m:
                    self._send(200, fake.issues[int(m.group(1)) - 1])
                    return
                self._send(404, {"message": "Not Found"})

            def do_POST(self):
                fake.requests.append(("POST", self.path))
                if not self._authed():
                    return
                body = self._body()
                if self.path == "/repos/me/reports/issues":
                    n = len(fake.issues) + 1
                    issue = {"number": n, "state": "open", "title": body["title"],
                             "body": body["body"], "labels": body.get("labels"),
                             "html_url": f"https://github.test/me/reports/issues/{n}"}
                    fake.issues.append(issue)
                    self._send(201, issue)
                    return
                m = re.match(r"^/repos/me/reports/issues/(\d+)/comments$", self.path)
                if m:
                    fake.comments.append((int(m.group(1)), body["body"]))
                    self._send(201, {"id": len(fake.comments)})
                    return
                self._send(404, {"message": "Not Found"})

            def do_PATCH(self):
                fake.requests.append(("PATCH", self.path))
                if not self._authed():
                    return
                m = re.match(r"^/repos/me/reports/issues/(\d+)$", self.path)
                if m:
                    issue = fake.issues[int(m.group(1)) - 1]
                    issue.update(self._body())
                    self._send(200, issue)
                    return
                self._send(404, {"message": "Not Found"})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


NAMES = {
    "light.kitchen": {"name": "Kitchen", "area": "Kitchen"},
    "light.bedroom_lamp": {"name": "Bedroom Lamp", "area": "Master Bedroom"},
    "person.alex": {"name": "Alex", "area": None},
    "sensor.lounge_temp": {"name": "Lounge Temperature", "area": "Lounge"},
}


def diagnostics(failures: int = 3, version: str = "2.17.0") -> dict:
    """A payload `reports.faults` reads two rows out of: a dead daemon and a
    producer the homeowner marks Wrong — both naming the house."""
    return {
        "versions": {"addon": version},
        "health": {"state": "degraded",
                   "reason": "light.bedroom_lamp is not reporting"},
        "daemons": {"automation_listener": {"running": False}},
        "expected_daemons": ["automation_listener"],
        "journal": {"runs": 10, "failures": [
            {"source": "card", "outcome": "timeout",
             "error": f"Kitchen card timed out {failures} times; "
                      "Bearer abcdefghijklmnopqrstuvwxyz0123 "
                      f"{TOKEN} in Master Bedroom"}] * 1},
    }


class DevloopCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self._old = (devloop.DATA_DIR, devloop.TOKEN_FILE, github.API,
                     dict(upstream.STATE))
        devloop.DATA_DIR = base / "devloop"
        devloop.TOKEN_FILE = base / "secrets" / "devloop_github_token"
        self.gh = FakeGitHub()
        github.API = self.gh.url
        upstream.STATE.update(last_sweep=0.0, last_send=0.0, error="",
                              running=False)
        # The fault rows are the real sweep's; what they are built from is
        # not this file's business, so the rows themselves are given.
        self._faults = upstream.reports.faults
        self.rows = [
            {"where": "Runs", "what": "card ended timeout 3 times",
             "detail": "Kitchen card timed out; Bearer abcdefghijklmnopqrstuvwxyz0123 "
                       f"{TOKEN}, see server.py and light.turn_on on "
                       "light.bedroom_lamp in Master Bedroom"},
            {"where": "Daemons", "what": "not running: automation_listener",
             "detail": "notify.mobile_app_alex_phone could not be told"},
        ]
        upstream.reports.faults = lambda diag: [dict(r) for r in self.rows]

    def tearDown(self):
        upstream.reports.faults = self._faults
        (devloop.DATA_DIR, devloop.TOKEN_FILE, github.API, state) = self._old
        upstream.STATE.clear()
        upstream.STATE.update(state)
        self.gh.close()
        self.tmp.cleanup()

    def switch_on(self, review: bool = False):
        devloop.save_settings({"enabled": True, "repo": "me/reports",
                               "review": review})
        devloop.save_token(TOKEN)


class TestOffMeansOff(DevloopCase):
    def test_it_is_off_by_default(self):
        self.assertFalse(devloop.enabled())
        self.assertEqual(devloop.load_settings()["review"], True)

    def test_an_off_loop_sends_nothing(self):
        devloop.save_token(TOKEN)
        devloop.save_settings({"repo": "me/reports"})
        upstream.sweep(diagnostics(), NAMES)
        for fp in [r["fp"] for r in upstream.listing()]:
            upstream.mark(fp, "ready")
        out = upstream.send_due()
        self.assertIn("skipped", out)
        self.assertEqual(self.gh.requests, [])


class TestWhatLeaves(DevloopCase):
    def test_nothing_from_the_house_and_no_credential(self):
        self.switch_on()
        upstream.sweep(diagnostics(), NAMES)
        upstream.send_due()
        self.assertEqual(len(self.gh.issues), 2)
        sent = json.dumps(self.gh.issues)
        for real in ("Kitchen", "Bedroom Lamp", "Master Bedroom", "light.kitchen",
                     "light.bedroom_lamp", "alex", "Alex", TOKEN,
                     "abcdefghijklmnopqrstuvwxyz0123"):
            self.assertNotIn(real, sent, real)
        # …while what a developer needs survives.
        self.assertIn("server.py", sent)
        self.assertIn("light.turn_on", sent)
        self.assertIn("automation_listener", sent)
        self.assertRegex(sent, r"light\.light_\d\d")

    def test_the_preview_is_what_is_sent(self):
        self.switch_on(review=True)
        upstream.sweep(diagnostics(), NAMES)
        fp = upstream.listing()[0]["fp"]
        preview = upstream.preview(fp)
        upstream.mark(fp, "ready")
        upstream.send_due()
        self.assertEqual(self.gh.issues[0]["title"], preview["title"])
        self.assertEqual(self.gh.issues[0]["body"], preview["body"])
        self.assertIn(github.MARKER.format(fp=fp), preview["body"])

    def test_the_token_is_never_in_the_payload_the_panel_serves(self):
        self.switch_on()
        listing = json.dumps({"s": devloop.load_settings(),
                              "q": upstream.listing(), "st": upstream.status()})
        self.assertNotIn(TOKEN, listing)


class TestAliases(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = devloop.DATA_DIR
        devloop.DATA_DIR = Path(self.tmp.name)

    def tearDown(self):
        devloop.DATA_DIR = self._old
        self.tmp.cleanup()

    def test_a_room_named_like_an_id_does_not_corrupt_the_id(self):
        a = aliases_mod.Aliases()
        a.learn({"light.kitchen": {"name": "Light", "area": "Kitchen"}})
        out = a.apply("light.kitchen is in the Kitchen; Light is on")
        self.assertRegex(out, r"^light\.light_01 is in the Room 1; Light 1 is on$")

    def test_a_shorter_name_does_not_rewrite_an_alias(self):
        a = aliases_mod.Aliases()
        a.learn({"light.a": {"name": "Room", "area": "Big Room"}})
        self.assertEqual(a.apply("Big Room"), "Room 1")

    def test_files_and_services_are_left_alone(self):
        a = aliases_mod.Aliases()
        self.assertEqual(a.apply("see server.py, memory.md, e.g. light.turn_on"),
                         "see server.py, memory.md, e.g. light.turn_on")

    def test_an_alias_is_stable_across_a_reload(self):
        a = aliases_mod.Aliases()
        first = a.apply("sensor.garage_freezer")
        a.save()
        b = aliases_mod.Aliases.load()
        self.assertEqual(b.apply("sensor.garage_freezer"), first)
        self.assertNotEqual(b.apply("sensor.other"), first)


class TestOneFaultOneIssue(DevloopCase):
    def test_digits_fold_into_one_fingerprint(self):
        self.assertEqual(upstream.fingerprint("Runs", "3 of 12 failed"),
                         upstream.fingerprint("Runs", "4 of 13 failed"))
        self.assertNotEqual(upstream.fingerprint("Runs", "a"),
                            upstream.fingerprint("Daemons", "a"))

    def test_a_second_pass_files_nothing_new(self):
        self.switch_on()
        upstream.sweep(diagnostics(), NAMES)
        upstream.send_due()
        self.rows[0]["what"] = "card ended timeout 5 times"
        upstream.sweep(diagnostics(), NAMES)
        upstream.send_due()
        self.assertEqual(len(self.gh.issues), 2)

    def test_a_lost_queue_finds_its_issue_by_the_marker(self):
        self.switch_on()
        upstream.sweep(diagnostics(), NAMES)
        upstream.send_due()
        (devloop.DATA_DIR / "queue.json").unlink()
        upstream.sweep(diagnostics(), NAMES)
        upstream.send_due()
        self.assertEqual(len(self.gh.issues), 2)
        self.assertTrue(all(r["issue"] for r in upstream.listing()))


class TestReview(DevloopCase):
    def test_a_new_report_waits_for_a_press(self):
        self.switch_on(review=True)
        upstream.sweep(diagnostics(), NAMES)
        upstream.send_due()
        self.assertEqual(self.gh.issues, [])
        self.assertEqual({r["state"] for r in upstream.listing()}, {"pending"})

    def test_delete_is_for_good(self):
        self.switch_on(review=True)
        upstream.sweep(diagnostics(), NAMES)
        fps = [r["fp"] for r in upstream.listing()]
        for fp in fps:
            self.assertTrue(upstream.mark(fp, "discarded"))
        devloop.save_settings({"review": False})
        upstream.sweep(diagnostics(), NAMES)
        upstream.send_due()
        self.assertEqual(self.gh.issues, [])

    def test_an_id_off_the_wire_is_checked(self):
        self.assertIsNone(upstream.preview("../../etc/passwd"))
        self.assertFalse(upstream.mark("zz", "ready"))
        self.assertFalse(upstream.mark("0" * 16, "sent"))


class TestRefusals(DevloopCase):
    def test_a_public_repository_is_refused(self):
        self.gh.private = False
        self.switch_on()
        upstream.sweep(diagnostics(), NAMES)
        out = upstream.send_due()
        self.assertIn("public", out["error"])
        self.assertEqual(self.gh.issues, [])

    def test_a_bad_token_or_repo_never_gets_stored(self):
        with self.assertRaises(ValueError):
            devloop.save_token("token: abc")
        with self.assertRaises(ValueError):
            devloop.save_settings({"repo": "me/../x y"})
        with self.assertRaises(ValueError):
            devloop.save_settings({"surprise": True})

    def test_the_token_file_is_private(self):
        devloop.save_token(TOKEN)
        self.assertEqual(devloop.TOKEN_FILE.stat().st_mode & 0o777, 0o600)


class TestFollowUps(DevloopCase):
    def _sent(self):
        self.switch_on()
        t = time.time()
        upstream.sweep(diagnostics(), NAMES, now=t)
        upstream.send_due(now=t)
        return t

    def test_a_fault_that_stops_is_said_once(self):
        t = self._sent()
        self.rows = []
        later = t + upstream.CLEAR_AFTER_S + 60
        upstream.sweep(diagnostics(), NAMES, now=later)
        upstream.send_due(now=later)
        upstream.send_due(now=later + 3600)
        notes = [c for c in self.gh.comments if c[1].startswith("Not seen since")]
        self.assertEqual(len(notes), 2)  # one per issue, not one per pass

    def test_a_closed_issue_whose_fault_comes_back_is_reopened(self):
        t = self._sent()
        keep = list(self.rows)
        self.rows = []
        later = t + upstream.CLEAR_AFTER_S + 60
        upstream.sweep(diagnostics(), NAMES, now=later)
        upstream.send_due(now=later)
        self.gh.issues[0]["state"] = "closed"
        self.rows = keep
        upstream.sweep(diagnostics(), NAMES, now=later + 600)
        upstream.send_due(now=later + 600)
        self.assertEqual(self.gh.issues[0]["state"], "open")
        self.assertTrue(any(c[0] == 1 and c[1].startswith("Back again")
                            for c in self.gh.comments))

    def test_a_new_version_that_did_not_fix_it_says_so_once(self):
        t = self._sent()
        upstream.sweep(diagnostics(version="2.17.1"), NAMES, now=t + 3600)
        upstream.send_due(now=t + 3600)
        upstream.sweep(diagnostics(version="2.17.1"), NAMES, now=t + 7200)
        upstream.send_due(now=t + 7200)
        still = [c for c in self.gh.comments if "Still happening on brAIn 2.17.1" in c[1]]
        self.assertEqual(len(still), 2)

    def test_a_follow_up_carries_nothing_from_the_house(self):
        t = self._sent()
        self.rows = []
        upstream.sweep(diagnostics(), NAMES, now=t + upstream.CLEAR_AFTER_S + 60)
        upstream.send_due(now=t + upstream.CLEAR_AFTER_S + 60)
        for _, text in self.gh.comments:
            self.assertRegex(text, r"^(Not seen since|Back again|Still happening)")
            self.assertNotIn("Kitchen", text)


class TestTheRepoIsSafeToShip(unittest.TestCase):
    def test_backups_leave_the_token_out(self):
        text = (BASE_DIR / "brain" / "config.yaml").read_text()
        self.assertIn("secrets/**", text)
        self.assertTrue(str(devloop.TOKEN_FILE).startswith("/data/secrets/")
                        or "secrets" in str(devloop.TOKEN_FILE))

    def test_devloop_md_exists_and_says_it_is_optional(self):
        text = (BASE_DIR / "brain" / "DEVLOOP.md").read_text()
        self.assertIn("off by default", text.lower())
        self.assertIn("private", text.lower())


if __name__ == "__main__":
    unittest.main()


class TestTheRoutes(DevloopCase):
    """The panel's half, through the real handlers: the token goes in and
    never comes back out, and a bad field is a 400 naming it."""

    def _client(self):
        import importlib

        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
        server = importlib.import_module("server")
        app = web.Application()
        app.router.add_get("/api/devloop", server.h_devloop_get)
        app.router.add_put("/api/devloop", server.h_devloop_put)
        app.router.add_put("/api/devloop/token", server.h_devloop_token)
        app.router.add_post("/api/devloop/run", server.h_devloop_run)
        app.router.add_get("/api/devloop/item/{fp}", server.h_devloop_item)
        return TestClient(TestServer(app))

    def test_the_token_never_comes_back_and_bad_fields_are_refused(self):
        import asyncio

        async def go():
            async with self._client() as c:
                r = await c.put("/api/devloop/token", json={"token": TOKEN})
                self.assertEqual(r.status, 200)
                self.assertNotIn(TOKEN, await r.text())
                r = await c.get("/api/devloop")
                body = await r.json()
                self.assertTrue(body["token_set"])
                self.assertNotIn(TOKEN, json.dumps(body))
                r = await c.put("/api/devloop", json={"repo": "not a repo"})
                self.assertEqual(r.status, 400)
                r = await c.put("/api/devloop/token", json={"token": "hunter2"})
                self.assertEqual(r.status, 400)
                r = await c.post("/api/devloop/run")
                self.assertEqual(r.status, 409)  # off
                r = await c.get("/api/devloop/item/..%2Fsecrets")
                self.assertEqual(r.status, 404)

        asyncio.run(go())


class TestStreams(DevloopCase):
    def test_the_fault_stream_is_its_own_switch(self):
        self.switch_on()
        devloop.save_settings({"streams": {"faults": False}})
        upstream.sweep(diagnostics(), NAMES)
        upstream.send_due()
        self.assertEqual(self.gh.issues, [])
        with self.assertRaises(ValueError):
            devloop.save_settings({"streams": {"telepathy": True}})

    def test_a_stream_switched_off_never_claims_the_fault_stopped(self):
        self.switch_on()
        t = time.time()
        upstream.sweep(diagnostics(), NAMES, now=t)
        upstream.send_due(now=t)
        devloop.save_settings({"streams": {"faults": False}})
        later = t + upstream.CLEAR_AFTER_S + 60
        upstream.sweep(diagnostics(), NAMES, now=later)
        upstream.send_due(now=later)
        self.assertEqual(self.gh.comments, [])
