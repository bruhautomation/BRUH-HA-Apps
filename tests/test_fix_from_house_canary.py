"""The canary's revert plan (self-learning plan, section 0).

With no person in the loop, the house's canary judges a release and the
cloud reverts what it blames. ``canary.py`` makes that decision in code:
which PRs, whole, and what each retry runs on.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / ".claude" / "skills" / "fix-from-house" / "scripts"


def _load(filename: str, name: str):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


C = _load("ffh_common.py", "ffh_test_common_c")
K = _load("canary.py", "ffh_test_canary")

HOUSE = "house-bot"


def canary(verdict="regressed", product="brain", release="4.3.0", **over) -> dict:
    obj = {"v": 1, "product": product, "release": release,
           "installed_at": "2026-11-04T08:00:00Z", "checked_at": "2026-11-04T12:00:00Z",
           "window_hours": 24, "new_faults": [], "came_back": [],
           "scorecard_drops": [], "start_crash": False, "verdict": verdict}
    obj.update(over)
    return C.sign(obj)


def canary_issue(obj: dict, title=None, author=HOUSE) -> dict:
    title = title or f"[canary] {obj['product']} {obj['release']}"
    return {"number": 900, "title": title, "user": {"login": author},
            "body": "Health of the release.\n\n" + C.fence(obj, "brain-canary")}


PRS = [
    {"number": 601, "title": "Checks: router", "head_ref": "devloop/2026-11-03-1-checks",
     "product": "brain", "release": "4.3.0", "files": ["brain/panel/checks/net.py",
                                                       "tests/test_net.py"],
     "issues": [11, 12], "fps": ["fp-net"], "model": "sonnet"},
    {"number": 602, "title": "Today: chips", "head_ref": "devloop/2026-11-03-2-today",
     "product": "brain", "release": "4.3.0", "files": ["brain/panel/app.js",
                                                       "brain/panel/answers.py"],
     "issues": [13], "fps": ["fp-chip"], "model": "opus"},
    {"number": 590, "title": "Older", "head_ref": "devloop/2026-11-01-1-x",
     "product": "brain", "release": "4.2.9", "files": ["brain/panel/x.py"],
     "issues": [9], "model": "sonnet"},
    {"number": 603, "title": "Print", "head_ref": "devloop/2026-11-03-3-print",
     "product": "BRUH Print", "release": "4.3.0", "files": ["bruh-print/panel/a.py"],
     "issues": [14], "model": "sonnet"},
]


def plan(obj, prs=PRS, since=None, **kw):
    got, why = K.read_canary(canary_issue(obj, **kw), HOUSE)
    return K.plan(got, why, prs, since)


class TestReadingTheCanary(unittest.TestCase):
    def test_an_unsigned_or_forged_canary_reverts_nothing(self):
        forged = dict(canary(), verdict="regressed", start_crash=True)
        self.assertEqual(plan(forged)["action"], "none")
        self.assertEqual(plan(canary(start_crash=True), author="stranger")["action"], "none")

    def test_the_title_must_match_the_block(self):
        out = plan(canary(), title="[canary] brain 4.2.0")
        self.assertEqual(out["action"], "none")
        self.assertIn("disagree", out["reason"])
        self.assertEqual(plan(canary(), title="canary for brain")["action"], "none")

    def test_pending_waits_and_healthy_does_nothing(self):
        self.assertEqual(plan(canary("pending"))["action"], "wait")
        self.assertEqual(plan(canary("healthy"))["action"], "none")
        self.assertEqual(plan(canary("bogus"))["action"], "none")

    def test_a_product_with_spaces(self):
        out = plan(canary(product="BRUH Print", start_crash=True))
        self.assertEqual([r["pr"] for r in out["reverts"]], [603])


class TestAttribution(unittest.TestCase):
    def test_a_fault_whose_where_names_a_file_reverts_only_that_pr(self):
        out = plan(canary(new_faults=[{"fp": "n1", "what": "net check crashed",
                                       "where": "brain/panel/checks/net.py:44"}]))
        self.assertEqual(out["action"], "revert")
        self.assertEqual(out["mode"], "attributed")
        self.assertEqual([r["pr"] for r in out["reverts"]], [601])
        r = out["reverts"][0]
        self.assertEqual(r["branch"], "devloop/revert-601")
        self.assertEqual(r["tier"], "B")
        self.assertEqual(r["reopen"], [11, 12])
        self.assertEqual(r["label"], "devloop:came-back")
        self.assertEqual(r["retry_model"], "opus")
        self.assertIn("net check crashed", r["what_broke"])

    def test_module_and_directory_forms_of_where(self):
        for where in ("checks.net", "panel/checks", "net.py", "brain/panel/checks/"):
            with self.subTest(where=where):
                out = plan(canary(new_faults=[{"fp": "n", "what": "w", "where": where}]))
                self.assertEqual([r["pr"] for r in out["reverts"]], [601], where)

    def test_a_came_back_fingerprint_blames_the_pr_that_closed_it(self):
        out = plan(canary(came_back=["fp-chip"]))
        self.assertEqual([r["pr"] for r in out["reverts"]], [602])
        self.assertEqual(out["reverts"][0]["retry_model"], "fable")

    def test_a_scorecard_drop_on_a_producer_a_pr_touched(self):
        out = plan(canary(scorecard_drops=[{"producer": "answers", "before": 0.8,
                                            "after": 0.4}]))
        self.assertEqual([r["pr"] for r in out["reverts"]], [602])

    def test_anything_unattributed_reverts_every_pr_of_the_release(self):
        for obj in (canary(start_crash=True),
                    canary(new_faults=[{"fp": "z", "what": "who knows"}]),
                    canary(new_faults=[{"fp": "n", "what": "w",
                                        "where": "brain/panel/checks/net.py"},
                                       {"fp": "z", "what": "elsewhere",
                                        "where": "brain/panel/nowhere.py"}]),
                    canary()):        # regressed with no signal at all
            with self.subTest(obj=obj):
                out = plan(obj)
                self.assertEqual(out["mode"], "all")
                self.assertEqual([r["pr"] for r in out["reverts"]], [601, 602])

    def test_only_this_releases_unreverted_fix_prs_are_candidates(self):
        prs = PRS + [
            {"number": 604, "title": "revert", "head_ref": "devloop/revert-599",
             "product": "brain", "release": "4.3.0", "files": ["brain/panel/x.py"]},
            {"number": 605, "title": "gone", "head_ref": "devloop/a", "reverted": True,
             "product": "brain", "release": "4.3.0", "files": ["brain/panel/x.py"]},
        ]
        out = plan(canary(start_crash=True), prs=prs)
        self.assertEqual([r["pr"] for r in out["reverts"]], [601, 602])

    def test_since_release_covers_a_house_that_skipped_versions(self):
        out = plan(canary(start_crash=True), since="4.2.8")
        self.assertEqual([r["pr"] for r in out["reverts"]], [590, 601, 602])
        out = plan(canary(start_crash=True), since="4.2.9")
        self.assertEqual([r["pr"] for r in out["reverts"]], [601, 602])

    def test_nothing_to_revert_is_said(self):
        out = plan(canary(start_crash=True, release="4.4.0"))
        self.assertEqual(out["action"], "none")

    def test_after_fable_the_issue_is_declined(self):
        prs = [dict(PRS[0], model="fable")]
        out = plan(canary(start_crash=True), prs=prs)
        self.assertIsNone(out["reverts"][0]["retry_model"])
        self.assertTrue(out["reverts"][0]["decline"])


class TestTheCli(unittest.TestCase):
    @pytest.mark.slow
    def test_plan_prints_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            (t / "cfg.json").write_text(json.dumps({"house_login": HOUSE}))
            (t / "issue.json").write_text(json.dumps(canary_issue(canary(start_crash=True))))
            (t / "prs.json").write_text(json.dumps(PRS))
            r = subprocess.run([sys.executable, str(SCRIPTS / "canary.py"), "plan",
                                "--config", str(t / "cfg.json"), "--issue",
                                str(t / "issue.json"), "--prs", str(t / "prs.json")],
                               capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["action"], "revert")


if __name__ == "__main__":
    unittest.main()
