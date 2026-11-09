#!/usr/bin/env python3
"""No daily cap on new issues unless the owner sets one (#797).

The owner's words: "make sure we get rid of the 50 daily limitation, and 5
per hour thing. That's silly. If there is an issue to send, just send it."
The loop held new issues to 10 a day by default (20 on autopilot), refused
any cap above 50, and filed at most 5 in one pass. Now 0 — the default — is
no limit: one `send_due` pass files every ready report. A cap the owner
sets is still kept. A stored 10 or 20 from before this was the old
default (or autopilot's reading of it, saved back by the panel), which the
owner never chose, so it reads as no limit until they save a number again.

GitHub is the loopback fake `test_devloop` uses, so a send is a real send.
"""
from __future__ import annotations

import importlib
import json
import sys
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import devloop  # noqa: E402
import devloop.upstream  # noqa: E402

from test_devloop import DevloopCase, diagnostics  # noqa: E402

upstream = devloop.upstream


def _name(i: int) -> str:
    # Letters, not digits: a fingerprint folds digits, so "part 1" and
    # "part 2" would be one report.
    return "".join(chr(97 + int(d)) for d in f"{i:03d}")


def _rows(n: int) -> list[dict]:
    return [{"where": f"Idea: part {_name(i)}", "what": f"something to add {_name(i)}",
             "detail": ""} for i in range(n)]


class NoCapCase(DevloopCase):
    def _queue(self, n: int, t: float) -> None:
        for i, row in enumerate(_rows(n)):
            upstream.ingest("ideas", [row], diagnostics(), now=t + i)
        ready = [r for r in upstream.listing() if r["state"] == "ready"]
        self.assertEqual(len(ready), n)

    def _store_raw(self, **values) -> None:
        """Write settings.json as an install from before this change left it."""
        path = devloop.settings_file()
        stored = json.loads(path.read_text(encoding="utf-8"))
        stored.update(values)
        stored.pop("issue_cap_chosen", None)
        path.write_text(json.dumps(stored), encoding="utf-8")


class TestEveryReadyReportGoesInOnePass(NoCapCase):
    def test_sixty_ready_reports_are_all_filed_by_one_pass(self):
        self.switch_on()
        self.assertEqual(devloop.load_settings()["max_issues_per_day"], 0)
        t = time.time()
        self._queue(60, t)
        out = upstream.send_due(now=t + 100)
        self.assertEqual(out.get("sent"), 60, out)
        self.assertEqual(out.get("capped"), 0, out)
        self.assertEqual(len(self.gh.issues), 60)

    def test_the_per_pass_ceiling_is_gone(self):
        self.assertFalse(hasattr(upstream, "MAX_SENDS_PER_PASS"))

    def test_autopilot_puts_no_cap_on_issues(self):
        self.switch_on()
        on = devloop.save_settings({"autopilot": True})
        self.assertEqual(on["max_issues_per_day"], 0)
        t = time.time()
        self._queue(30, t)
        self.assertEqual(upstream.send_due(now=t + 100).get("sent"), 30)


class TestACapTheOwnerSetsIsKept(NoCapCase):
    def test_an_explicit_cap_of_three_files_three(self):
        self.switch_on()
        devloop.save_settings({"max_issues_per_day": 3})
        t = time.time()
        self._queue(10, t)
        out = upstream.send_due(now=t + 100)
        self.assertEqual((out.get("sent"), out.get("capped")), (3, 7), out)
        self.assertEqual(len(self.gh.issues), 3)

    def test_a_cap_above_fifty_is_accepted_and_negative_is_refused(self):
        self.assertEqual(devloop.save_settings(
            {"max_issues_per_day": 500})["max_issues_per_day"], 500)
        with self.assertRaises(ValueError):
            devloop.save_settings({"max_issues_per_day": -1})

    def test_an_explicit_ten_saved_now_is_kept(self):
        self.switch_on()
        devloop.save_settings({"max_issues_per_day": 10})
        self.assertEqual(devloop.load_settings()["max_issues_per_day"], 10)
        t = time.time()
        self._queue(12, t)
        self.assertEqual(upstream.send_due(now=t + 100).get("sent"), 10)

    def test_autopilot_keeps_an_explicit_cap(self):
        devloop.save_settings({"max_issues_per_day": 3, "autopilot": True})
        self.assertEqual(devloop.load_settings()["max_issues_per_day"], 3)


class TestAnOldDefaultReadsAsNoLimit(NoCapCase):
    def test_a_stored_old_default_of_ten_is_no_limit(self):
        self.switch_on()
        self._store_raw(max_issues_per_day=10)
        self.assertEqual(devloop.load_settings()["max_issues_per_day"], 0)
        t = time.time()
        self._queue(15, t)
        self.assertEqual(upstream.send_due(now=t + 100).get("sent"), 15)

    def test_autopilots_twenty_saved_back_is_no_limit(self):
        self.switch_on()
        self._store_raw(max_issues_per_day=20)
        self.assertEqual(devloop.load_settings()["max_issues_per_day"], 0)

    def test_any_other_stored_number_is_kept(self):
        self.switch_on()
        self._store_raw(max_issues_per_day=7)
        self.assertEqual(devloop.load_settings()["max_issues_per_day"], 7)

    def test_saving_something_else_does_not_bring_the_old_ten_back(self):
        self.switch_on()
        self._store_raw(max_issues_per_day=10)
        devloop.save_settings({"max_runs_per_day": 5})
        self.assertEqual(devloop.load_settings()["max_issues_per_day"], 0)


class TestTheHeldLineWithNoCap(NoCapCase):
    def test_no_limit_is_never_full(self):
        self.switch_on()
        t = time.time()
        self._queue(3, t)
        upstream.send_due(now=t + 100)
        server = importlib.import_module("server")
        held = server._devloop_held(now=t + 200)
        self.assertEqual((held["limit"], held["today"], held["full"]), (0, 3, False))


class TestThePanel(unittest.TestCase):
    def test_the_input_has_no_ceiling_and_says_no_limit(self):
        html = (PANEL_DIR / "index.html").read_text(encoding="utf-8")
        tag = html[html.index('id="devCapIssues"'):]
        tag = tag[:tag.index(">")]
        self.assertNotIn("max=", tag)
        self.assertIn('placeholder="No limit"', tag)
        app = (PANEL_DIR / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("max_issues_per_day ?? 10", app)


if __name__ == "__main__":
    unittest.main()
