"""The canary: how the house runs on a release it just installed (plan section 0).

With nobody in the loop, the house is what tells the cloud a release broke
something, and the cloud reverts on it. These hold:

* an install is a version that MOVED; a first reading is a baseline;
* new faults, came-back fixes, a rule's right-share falling 20 points
  against the previous release and a start that keeps failing are each a
  regression, said at once; none by the window's end is healthy;
* one rolling issue per release, titled ``[canary] brain <version>``, with
  a whole ``brain-canary`` block, rewritten hourly, never held for review,
  its final verdict posted once as a comment and then left alone;
* the other BRUH add-ons get the same from what the siblings stream reads;
* a regressed canary is never closed as superseded.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "tests"))
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

from test_devloop import NAMES, DevloopCase, diagnostics, upstream  # noqa: E402

import devloop  # noqa: E402
import devloop.blocks as blocks  # noqa: E402
import devloop.canary as canary  # noqa: E402

HOUR = 3600
KEYS = {"v", "product", "release", "installed_at", "checked_at", "window_hours",
        "new_faults", "came_back", "scorecard_drops", "start_crash", "verdict", "digest"}


def digest_of(obj: dict) -> str:
    body = {k: v for k, v in obj.items() if k != "digest"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode()).hexdigest()


class TestTheJudgement(unittest.TestCase):
    def rel(self, at=1000.0, previous="2.0.0"):
        return {"installed_at": at, "previous": previous}

    def judge(self, items=None, settled=None, starts=None, now=1000.0 + HOUR, rel=None):
        return canary.judge(rel or self.rel(), product="brAIn", version="2.1.0",
                            items=items or {}, settled=settled or [],
                            starts=starts or [], window_s=24 * HOUR, now=now)

    def test_an_install_is_a_version_that_moved(self):
        data = {"products": {}, "starts": []}
        self.assertEqual(canary.observe(data, {"brAIn": "2.0.0"}, 10.0), [],
                         "a first reading is a baseline")
        self.assertEqual(canary.observe(data, {"brAIn": "2.0.0"}, 20.0), [])
        self.assertEqual(canary.observe(data, {"brAIn": "2.1.0"}, 30.0), [("brAIn", "2.1.0")])
        rel = data["products"]["brAIn"]["releases"]["2.1.0"]
        self.assertEqual((rel["installed_at"], rel["previous"]), (30.0, "2.0.0"))
        canary.observe(data, {"brAIn": "2.1.1"}, 40.0)
        self.assertEqual(rel["superseded_at"], 40.0)

    def test_quiet_is_pending_then_healthy(self):
        self.assertEqual(self.judge()["verdict"], "pending")
        obj = self.judge(now=1000.0 + 25 * HOUR)
        self.assertEqual(obj["verdict"], "healthy")
        self.assertEqual((obj["product"], obj["release"], obj["window_hours"]),
                         ("brain", "2.1.0", 24))
        self.assertEqual(set(obj) | {"digest"}, KEYS)

    def test_a_fault_first_seen_on_the_release_is_a_regression(self):
        items = {"a": {"fp": "a", "stream": "faults", "what": "card ended timeout",
                       "first_seen": 1500.0, "seen": 2},
                 "b": {"fp": "b", "stream": "faults", "what": "older",
                       "first_seen": 500.0, "seen": 9},
                 "c": {"fp": "c", "stream": "faults", "what": "one blip",
                       "first_seen": 1500.0, "seen": 1},
                 "d": {"fp": "d", "stream": "siblings", "product": "GardenRX",
                       "what": "not ours", "first_seen": 1500.0, "seen": 3}}
        obj = self.judge(items)
        self.assertEqual(obj["new_faults"], [{"fp": "a", "what": "card ended timeout"}])
        self.assertEqual(obj["verdict"], "regressed")

    def test_a_fix_that_came_back_is_a_regression(self):
        items = {"a": {"fp": "a", "stream": "faults", "came_back_at": 1200.0}}
        self.assertEqual(self.judge(items)["came_back"], ["a"])

    def test_a_rule_twenty_points_less_right_is_a_regression(self):
        def rows(release, right, wrong, src="check:auto.dead_ref"):
            return ([{"source": src, "kind": "fixed", "release": release}] * right
                    + [{"source": src, "kind": "ignored", "release": release}] * wrong)
        settled = rows("2.0.0", 9, 1) + rows("2.1.0", 6, 4) + rows("2.1.0", 1, 1, "few")
        obj = self.judge(settled=settled)
        self.assertEqual(obj["scorecard_drops"], [
            {"producer": "check:auto.dead_ref", "before": 90.0, "after": 60.0}])
        # A ledger with no release on its rows compares nothing.
        bare = [{k: v for k, v in r.items() if k != "release"} for r in settled]
        self.assertEqual(self.judge(settled=bare)["scorecard_drops"], [])

    def test_a_start_that_keeps_failing_is_a_regression(self):
        ok = [{"at": 1100.0, "version": "2.1.0", "ready": True}]
        self.assertFalse(self.judge(starts=ok)["start_crash"])
        many = [{"at": 1100.0 + i, "version": "2.1.0", "ready": True} for i in range(4)]
        self.assertTrue(self.judge(starts=many)["start_crash"])
        unready = [{"at": 1100.0 + i, "version": "2.1.0", "ready": False} for i in range(3)]
        self.assertTrue(self.judge(starts=unready)["start_crash"])
        other = [{"at": 1100.0 + i, "version": "2.0.0", "ready": False} for i in range(5)]
        self.assertFalse(self.judge(starts=other)["start_crash"])

    def test_a_release_replaced_early_is_judged_on_its_window(self):
        rel = {**self.rel(), "superseded_at": 1000.0 + 2 * HOUR}
        items = {"a": {"fp": "a", "stream": "faults", "first_seen": 1000.0 + 3 * HOUR, "seen": 5}}
        obj = self.judge(items, rel=rel, now=1000.0 + 4 * HOUR)
        self.assertEqual(obj["verdict"], "healthy", "a fault after it was replaced is not its")


class _Case(DevloopCase):
    def setUp(self):
        super().setUp()
        self.switch_on(review=True)
        self.settled: list[dict] = []

    def pass_(self, now: float, version: str = "2.17.0", products=None):
        diag = diagnostics(version=version)
        upstream.sweep(diag, NAMES, now=now)
        if products:
            data = upstream._load()
            data["products"] = products
            upstream._save(data)
        rows = canary.pass_rows(version, self.settled, now=now)
        upstream.ingest("canary", rows, diag, NAMES, now=now)
        upstream.send_due(now=now)

    def canaries(self):
        return [i for i in self.gh.issues if i["title"].startswith("[canary]")]


class TestTheCanaryIssue(_Case):
    def test_an_install_opens_one_issue_rewritten_hourly_then_judged_once(self):
        t = time.time() - 3 * 86400
        self.pass_(t)
        self.assertEqual(self.canaries(), [], "a first reading is a baseline")
        t2 = t + HOUR
        self.pass_(t2, "2.17.1")
        [issue] = self.canaries()
        self.assertEqual(issue["title"], "[canary] brain 2.17.1")
        obj = blocks.parse_block("canary", issue["body"])
        self.assertEqual(set(obj), KEYS)
        self.assertEqual(obj["digest"], digest_of(obj))
        self.assertEqual(obj["verdict"], "pending")
        self.assertIsNone(blocks.parse_block("devloop", issue["body"]),
                          "a canary is not a report to fix")
        self.assertNotIn(1, [n for n, _ in self.gh.comments])
        # Hourly through the window: the body is rewritten.
        self.pass_(t2 + HOUR, "2.17.1")
        later = blocks.parse_block("canary", self.canaries()[0]["body"])
        self.assertNotEqual(later["checked_at"], obj["checked_at"])
        # At the window's end the verdict is said, once.
        self.pass_(t2 + 25 * HOUR, "2.17.1")
        final = [b for n, b in self.gh.comments if n == issue["number"]]
        self.assertEqual(len(final), 1)
        self.assertIn("**healthy**", final[0])
        self.assertEqual(blocks.parse_block("canary", final[0])["verdict"], "healthy")
        self.pass_(t2 + 27 * HOUR, "2.17.1")
        self.assertEqual(len([n for n, _ in self.gh.comments if n == issue["number"]]), 1)
        self.assertEqual(len(self.canaries()), 1)
        self.assertEqual(upstream.efficacy()["canaries"][0]["verdict"], "healthy")

    def test_a_regression_is_said_at_once(self):
        t = time.time() - 3 * 86400
        self.pass_(t)
        self.pass_(t + HOUR, "2.17.1")
        self.rows.append({"where": "Runs", "what": "brief ended error 2 times", "detail": ""})
        for h in (2, 3):
            self.pass_(t + h * HOUR, "2.17.1")
        [issue] = self.canaries()
        said = [b for n, b in self.gh.comments if n == issue["number"]]
        self.assertEqual(len(said), 1, "posted the pass it was found, not at the window's end")
        obj = blocks.parse_block("canary", said[0])
        self.assertEqual(obj["verdict"], "regressed")
        self.assertEqual([f["what"] for f in obj["new_faults"]], ["brief ended error 2 times"])

    def test_it_waits_for_no_review_but_honours_the_switches(self):
        devloop.save_settings({"streams": {"canary": False}})
        self.assertFalse(devloop.stream_on("canary"))
        devloop.save_settings({"streams": {"canary": True}, "enabled": False})
        t = time.time() - 3 * 86400
        self.pass_(t)
        self.pass_(t + HOUR, "2.17.1")
        self.assertEqual(self.gh.issues, [], "the loop is off")

    def test_a_regressed_canary_is_not_closed_as_superseded(self):
        t = time.time() - 9 * 86400
        self.pass_(t)
        self.pass_(t + HOUR, "2.17.1")
        canary_data = canary.load()
        canary_data["starts"] = [{"at": t + HOUR + i, "version": "2.17.1", "ready": True}
                                 for i in range(4)]
        canary.save(canary_data)
        self.pass_(t + 2 * HOUR, "2.17.1")
        self.pass_(t + 3 * HOUR, "2.17.2")
        self.pass_(t + 30 * HOUR, "2.17.2")
        self.pass_(t + 31 * HOUR, "2.17.3")
        by_title = {i["title"]: i for i in self.canaries()}
        self.assertEqual(by_title["[canary] brain 2.17.1"]["state"], "open")
        self.assertEqual(by_title["[canary] brain 2.17.2"]["state"], "closed",
                         "a healthy one gives way to the next")


class TestSiblingCanaries(_Case):
    def test_a_sibling_release_gets_its_own_canary(self):
        t = time.time() - 3 * 86400
        self.pass_(t, products={"GardenRX": "0.3.0"})
        self.pass_(t + HOUR, products={"GardenRX": "0.3.1"})
        [issue] = self.canaries()
        self.assertEqual(issue["title"], "[canary] gardenrx 0.3.1")
        obj = blocks.parse_block("canary", issue["body"])
        self.assertEqual((obj["product"], obj["scorecard_drops"]), ("gardenrx", []))
        self.assertIn("devloop:gardenrx", [x["name"] for x in issue["labels"]])


class TestTheHeartbeat(DevloopCase):
    def test_a_start_is_noted_only_while_the_loop_is_on_and_ready_by_the_pass(self):
        canary.note_start("2.17.0", now=10.0)
        self.assertEqual(canary.load()["starts"], [])
        self.switch_on()
        canary.note_start("2.17.0", now=10.0)
        self.assertEqual(canary.load()["starts"][-1]["ready"], False)
        canary.pass_rows("2.17.0", [], now=20.0)
        self.assertTrue(canary.load()["starts"][-1]["ready"])


if __name__ == "__main__":
    unittest.main()
