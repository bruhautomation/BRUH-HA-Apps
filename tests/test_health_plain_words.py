#!/usr/bin/env python3
"""⚙ › Diagnostics speaks the owner's language, and one count reads one way.

The fault list printed brAIn's machinery straight through — "Producer
Sensors frozen on one value (check:dev.frozen): ignored 3 of 4 times",
"Run (memory): ended crash (6 times) — claude exited 1", "Looks: 9
findings waiting" — and the queue's mute question said the same rule was
"marked wrong 4 of 4", a second wording of one pair of numbers. The
scorecard listed rules as "user-1789499215" over a bare "2/0".

What is held here:

* every fault row carries a `title` and a `sentence` free of ids, job
  words and exit codes, with the ids folded into `technical`;
* the machine fields the development loop fingerprints (`where`, `what`,
  `detail`) are exactly what they were;
* the count is worded by one function and the Health row and the queue's
  question use it; a rule with a mute question open points at it;
* the scorecard names every row and words its count and verdict;
* the release notes are read from the Supervisor and cut into versions.
"""
from __future__ import annotations

import asyncio
import importlib
import re
import sys
import unittest
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestServer, make_mocked_request

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))

import addon_options  # noqa: E402
import mute_offer  # noqa: E402
import plain_words  # noqa: E402
import reports  # noqa: E402

NOW = 1_790_000_000

# A house with the four faults the owner screenshotted, in the payload's
# real shapes.
DIAG = {
    "generated_at": NOW,
    "journal": {
        "runs": 40, "claude_runs": 30,
        "failures": [
            {"source": "memory", "outcome": "crash", "ok": False,
             "error": "claude exited 1", "ts": NOW - 60 * i}
            for i in range(6)
        ],
    },
    "findings": {
        "scorecard": [
            {"source": "check:dev.frozen", "title": "Sensors frozen on one value",
             "confirmed": 1, "wrong": 3, "total": 4, "last": "wrong"},
            {"source": "user-1789499215", "title": "user-1789499215",
             "confirmed": 0, "wrong": 5, "total": 5, "last": "wrong"},
        ],
        "waiting_for_look": 9,
        "waiting_for_look_oldest_s": 5 * 3600,
    },
    "checks": {"skipped": {"climate.window": "no outdoor reference"},
               "errors": {"auto.conflict": "KeyError: 'x'"}},
    "check_titles": {"climate.window": "A window left open"},
    "daemons": {"automation_listener": {"running": False}},
    "options": {"enable_automation_integration": True},
}

# What no visible line may carry: an id, a job word, an exit code.
FORBIDDEN = re.compile(
    r"check:\S|\bProducer\b|\bRun \(|\bLooks\b|exited \d|\buser-\d|"
    r"\b[a-z]+\.[a-z_]+\b(?<!e\.g)|_listener|\bcrash\b")


def _visible(row: dict) -> str:
    return f"{row.get('title', '')} {row.get('sentence', '')}"


class TestEveryFaultSaysItInWords(unittest.TestCase):
    def setUp(self):
        self.rows = reports.faults(DIAG)

    def test_every_row_has_a_title_a_sentence_and_no_machinery(self):
        self.assertGreaterEqual(len(self.rows), 6)
        for row in self.rows:
            with self.subTest(row=row["where"]):
                self.assertTrue(row.get("title"))
                self.assertTrue(row.get("sentence"))
                self.assertIsNone(FORBIDDEN.search(_visible(row)),
                                  _visible(row))

    def test_the_ids_are_kept_under_the_row(self):
        technical = " ".join(r.get("technical", "") for r in self.rows)
        for word in ("check:dev.frozen", "claude exited 1", "auto.conflict",
                     "automation_listener"):
            self.assertIn(word, technical)

    def test_a_job_is_named_for_what_it_does(self):
        [run] = [r for r in self.rows if r["where"].startswith("Run (")]
        self.assertEqual(run["title"], "Filing facts into memory")
        self.assertIn("6 times", run["sentence"])

    def test_the_machine_fields_did_not_move(self):
        """`where|what` is the development loop's fingerprint."""
        by_where = {r["where"]: r for r in self.rows}
        self.assertEqual(by_where["Run (memory)"]["what"],
                         "ended crash (6 times)")
        self.assertEqual(
            by_where["Producer Sensors frozen on one value (check:dev.frozen)"]
            ["what"], "ignored 3 of 4 times")
        self.assertEqual(by_where["Looks"]["what"],
                         "9 findings are still waiting for a look")
        self.assertEqual(by_where["Check climate.window"]["what"],
                         "could not run")
        self.assertEqual(by_where["Daemons"]["what"],
                         "not running: automation_listener")

    def test_a_check_is_named_by_its_catalog_title(self):
        [row] = [r for r in self.rows if r["where"] == "Check climate.window"]
        self.assertIn("A window left open", row["title"])


class TestOneCountOneWording(unittest.TestCase):
    def test_the_health_row_and_the_queue_question_word_the_count_alike(self):
        rows = reports.faults(DIAG)
        [health] = [r for r in rows if "check:dev.frozen" in r["where"]]
        words = plain_words.record_words(3, 4)
        self.assertEqual(words, "3 marked wrong of 4 answers")
        self.assertIn(words, health["sentence"])
        [asked] = mute_offer.plan(DIAG["findings"]["scorecard"][:1], {}, NOW,
                                  set(), set())
        self.assertIn(words, asked["row"]["claim"])
        self.assertNotIn("check:", asked["row"]["claim"])

    def test_a_rule_with_a_mute_question_open_points_at_it(self):
        diag = {**DIAG, "findings": {**DIAG["findings"],
                                     "mute_offers_open": ["check:dev.frozen"]}}
        [row] = [r for r in reports.faults(diag)
                 if "check:dev.frozen" in r["where"]]
        self.assertIn("Needs you", row["sentence"])
        self.assertNotIn("Ignore all like this", row["sentence"])


class TestTheScorecardIsNamed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = importlib.import_module("server")

    def setUp(self):
        self._old = (self.server.findings_store.scorecard,
                     self.server.settings_store.muted,
                     self.server.resolve_category)
        self.server.findings_store.scorecard = lambda: [
            {"source": "user-1789499215", "title": "user-1789499215",
             "confirmed": 2, "wrong": 0, "total": 2},
            {"source": "custom-1790198889", "title": "Custom",
             "confirmed": 1, "wrong": 3, "total": 4},
            {"source": "check:forecast.decline", "title": "",
             "confirmed": 0, "wrong": 3, "total": 3},
            {"source": "mute_offer", "title": "", "confirmed": 1,
             "wrong": 0, "total": 1},
            {"source": "sre", "title": "", "confirmed": 4, "wrong": 1,
             "total": 5},
        ]
        self.server.settings_store.muted = lambda: {"check:forecast.decline"}
        self.server.resolve_category = (
            lambda cid: {"title": "Laundry watch"}
            if cid == "user-1789499215" else None)

    def tearDown(self):
        (self.server.findings_store.scorecard,
         self.server.settings_store.muted,
         self.server.resolve_category) = self._old

    def test_every_row_has_a_name_a_count_in_words_and_a_verdict(self):
        rows = {r["source"]: r for r in self.server._scorecard()}
        self.assertEqual(rows["user-1789499215"]["name"], "Laundry watch")
        self.assertEqual(rows["custom-1790198889"]["name"],
                         "A question you asked")
        self.assertNotIn("forecast.decline",
                         rows["check:forecast.decline"]["name"])
        self.assertEqual(rows["mute_offer"]["name"], "Rule suggestions")
        self.assertEqual(rows["sre"]["name"], "Overnight health check")
        self.assertEqual(rows["custom-1790198889"]["count_words"],
                         "right 1 of 4, wrong 3")
        self.assertEqual(rows["custom-1790198889"]["verdict"], "doubtful")
        self.assertEqual(rows["sre"]["verdict"], "trusted")
        self.assertEqual(rows["check:forecast.decline"]["verdict"], "muted")
        self.assertTrue(rows["check:forecast.decline"]["muted"])


class FakeSupervisor:
    def __init__(self, text: str | None, status: int = 200):
        self.text, self.status = text, status

    def app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/addons/self/changelog", self._log)
        return app

    async def _log(self, request: web.Request) -> web.Response:
        assert request.headers.get("Authorization") == "Bearer test-token"
        if self.status != 200:
            return web.json_response({"result": "error"}, status=self.status)
        return web.Response(text=self.text, content_type="text/plain")


NOTES = """# Changelog

All notable changes, newest first.

## 2.18.10

### Added

- **Screens**, a new stream.

## 2.18.9

### Changed

- Fix opens a box.
"""


class TestWhatsNewIsReadFromTheSupervisor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = importlib.import_module("server")

    def setUp(self):
        self._old = (addon_options.SUPERVISOR_URL, addon_options.TOKEN)

    def tearDown(self):
        (addon_options.SUPERVISOR_URL, addon_options.TOKEN) = self._old

    def _ask(self, supervisor: FakeSupervisor) -> dict:
        async def run():
            sv = TestServer(supervisor.app())
            await sv.start_server()
            try:
                addon_options.SUPERVISOR_URL = str(sv.make_url("")).rstrip("/")
                addon_options.TOKEN = "test-token"
                req = make_mocked_request("GET", "/api/changelog")
                resp = await self.server.h_changelog(req)
                import json
                return json.loads(resp.body)
            finally:
                await sv.close()
        return asyncio.run(run())

    def test_the_notes_come_back_cut_into_versions_newest_first(self):
        body = self._ask(FakeSupervisor(NOTES))
        self.assertEqual(body["error"], "")
        self.assertEqual([s["version"] for s in body["sections"]],
                         ["2.18.10", "2.18.9"])
        self.assertIn("Screens", body["sections"][0]["text"])
        self.assertNotIn("## 2.18.9", body["sections"][0]["text"])

    def test_a_refusal_is_a_sentence_not_an_empty_list(self):
        body = self._ask(FakeSupervisor(None, status=404))
        self.assertEqual(body["sections"], [])
        self.assertIn("404", body["error"])

    def test_no_supervisor_is_said(self):
        addon_options.TOKEN = ""
        req = make_mocked_request("GET", "/api/changelog")
        import json
        body = json.loads(asyncio.run(self.server.h_changelog(req)).body)
        self.assertTrue(body["error"])
        self.assertEqual(body["sections"], [])

    def test_sections_sort_by_version_not_by_file_order(self):
        cut = self.server.changelog_sections(
            "## 2.9.0\n\nold\n\n## 2.10.0\n\nnew\n")
        self.assertEqual([c["version"] for c in cut], ["2.10.0", "2.9.0"])


if __name__ == "__main__":
    unittest.main()
