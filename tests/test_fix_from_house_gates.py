"""The auditor and the reviewer gate (plan 0.5, 1.1, 1.2; section 0).

Both replace a person's judgement with a rule in code: every decline cites
evidence and a tenth are re-judged; every merge has the approvals its tier
asks for, from reviewers on a different model from the fixer.
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


A = _load("auditor.py", "ffh_test_auditor")
G = _load("merge_gate.py", "ffh_test_merge_gate")


def closures(n=30):
    out = []
    for i in range(1, n + 1):
        outcome = ("declined", "duplicate", "fixed")[i % 3]
        comment = {"declined": f"Declined: needs a new option (brain/config.yaml:{i}).",
                   "duplicate": f"Same as #{i + 100}",
                   "fixed": "Fixed in brAIn 4.3.0 (#601)"}[outcome]
        out.append({"number": i, "outcome": outcome, "comment": comment,
                    "closed_at": "2026-11-03T10:00:00Z"})
    return out


class TestTheSample(unittest.TestCase):
    def test_ten_percent_of_declines_and_duplicates_deterministic_by_week(self):
        cs = closures(30)
        audited = [c["number"] for c in cs if c["outcome"] != "fixed"]
        first = A.sample(cs, "2026-W45")
        self.assertEqual(len(first), 2)                     # ceil(0.1 × 20)
        self.assertTrue(set(first) <= set(audited))
        self.assertEqual(first, A.sample(list(reversed(cs)), "2026-W45"))
        weeks = {tuple(A.sample(cs, f"2026-W{w}")) for w in range(40, 52)}
        self.assertGreater(len(weeks), 1, "the seed must change with the week")

    def test_at_least_one_and_carried_unknowns(self):
        cs = closures(3)
        self.assertEqual(len(A.sample(cs, "2026-W45")), 1)
        self.assertIn(999, A.sample(cs, "2026-W45", carry=[999]))
        self.assertEqual(A.sample([], "2026-W45"), [])

    def test_week_of(self):
        self.assertEqual(A.week_of("2026-11-04"), "2026-W45")
        self.assertEqual(A.week_of("2027-01-01"), "2026-W53")


class TestEvidenceAndReopening(unittest.TestCase):
    def test_lint(self):
        self.assertFalse(A.lint("declined", "Declined: does not fit.")[0])
        self.assertFalse(A.lint("duplicate", "Duplicate.")[0])
        self.assertTrue(A.lint("declined", "Declined, see #12")[0])
        self.assertTrue(A.lint("declined", "Fixed in 4.2.3; tests/test_gate.py holds it")[0])
        self.assertTrue(A.lint("fixed", "anything")[0])

    def test_check_finds_closures_without_evidence(self):
        cs = closures(6) + [{"number": 50, "outcome": "declined", "comment": "Nope."}]
        self.assertEqual([c["number"] for c in A.check(cs)], [50])

    def test_the_reopen_rule(self):
        cs = closures(9) + [{"number": 50, "outcome": "declined", "comment": "Nope."}]
        verdicts = [{"number": 1, "verdict": "overturn", "reason": "the code at x.py:3 says otherwise"},
                    {"number": 2, "verdict": "uphold"},
                    {"number": 4, "verdict": "unknown"},
                    {"number": 50, "verdict": "uphold"},      # no evidence: reopened anyway
                    {"number": 404, "verdict": "overturn"}]   # not a closure: ignored
        out = A.apply(cs, verdicts)
        reopened = {a["number"]: a for a in out["reopen"]}
        self.assertEqual(sorted(reopened), [1, 50])
        self.assertEqual(reopened[1]["remove_labels"], ["devloop:duplicate"])
        self.assertEqual(reopened[1]["add_labels"], ["devloop:audit-reopened"])
        self.assertIn("overturned", reopened[1]["comment"])
        self.assertIn("without evidence", reopened[50]["comment"])
        self.assertEqual(out["upheld"], [2])
        self.assertEqual(out["carry"], [4])
        self.assertEqual(out["audit"], {"sampled": 4, "overturned": 1})

    @pytest.mark.slow
    def test_the_cli_lint_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.txt"
            path.write_text("Declined: does not fit.")
            r = subprocess.run([sys.executable, str(SCRIPTS / "auditor.py"), "lint",
                                "--outcome", "declined", "--comment-file", str(path)],
                               capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 1)


class TestTheTier(unittest.TestCase):
    def test_the_guards_own_output(self):
        guard_log = ("devloop-guard: ok\ntier=B\n")
        self.assertEqual(G.parse_tier(guard_log), "B")
        summary = ("## devloop-guard\n\n**Tier C**: a safety area, or logic across "
                   "add-ons: two independent reviewers and the house canary\n")
        self.assertEqual(G.parse_tier(summary), "C")
        self.assertEqual(G.parse_tier("::notice::tier=T"), "T")
        self.assertEqual(G.parse_tier("tier=M"), "M")

    def test_a_line_beats_prose_and_prose_is_read_strictly(self):
        self.assertEqual(G.parse_tier("Tier C means two reviewers.\ntier: A\n"), "A")
        self.assertEqual(G.parse_tier("tier B here, tier C there"), "C")
        self.assertIsNone(G.parse_tier("the tier is a test"))
        self.assertIsNone(G.parse_tier(""))


class TestTheGate(unittest.TestCase):
    def v(self, verdict, model="opus", reviewer=None):
        return {"verdict": verdict, "model": model,
                "reviewer": reviewer or f"{model}-{verdict}"}

    def test_tier_a_and_b_need_one_approve(self):
        for tier in ("A", "B", "T"):
            out = G.decide(tier, [self.v("approve")], "sonnet")
            self.assertTrue(out["merge"], tier)

    def test_tier_c_and_m_need_two_independent_approvals(self):
        for tier in ("C", "M"):
            one = G.decide(tier, [self.v("approve")], "sonnet")
            self.assertFalse(one["merge"])
            self.assertEqual(one["next"], "review")
            same = G.decide(tier, [self.v("approve", reviewer="r1"),
                                   self.v("approve", reviewer="r1")], "sonnet")
            self.assertFalse(same["merge"])
            two = G.decide(tier, [self.v("approve", "opus", "r1"),
                                  self.v("approve", "fable", "r2")], "sonnet")
            self.assertTrue(two["merge"])

    def test_no_tier_is_treated_as_c(self):
        out = G.decide(None, [self.v("approve")], "sonnet")
        self.assertEqual(out["tier"], "C")
        self.assertFalse(out["merge"])

    def test_a_reviewer_on_the_fixers_model_does_not_count(self):
        out = G.decide("A", [self.v("approve", "sonnet")], "sonnet")
        self.assertFalse(out["merge"])
        self.assertEqual(len(out["ignored"]), 1)
        self.assertFalse(G.decide("A", [self.v("approve", "")], "sonnet")["merge"])

    def test_request_changes_wins_and_unknown_is_not_approve(self):
        out = G.decide("A", [self.v("approve", "opus", "r1"),
                             self.v("request_changes", "fable", "r2")], "sonnet")
        self.assertEqual(out["next"], "fix")
        self.assertEqual(G.decide("A", [self.v("unknown")], "sonnet")["next"], "review")
        out = G.decide("A", [self.v("unknown", "opus", "r1"),
                             self.v("unknown", "fable", "r2")], "sonnet")
        self.assertEqual(out["next"], "escalate")
        self.assertEqual(out["escalate_model"], "opus")

    def test_a_raw_reply_is_parsed(self):
        reply = "The diff meets done_when; tests prove it.\nverdict: approve"
        self.assertEqual(G.parse_verdict(reply), "approve")
        self.assertEqual(G.parse_verdict("I think it's fine"), "unknown")
        out = G.decide("A", [{"reviewer": "r", "model": "opus", "text": reply}], "sonnet")
        self.assertTrue(out["merge"])

    @pytest.mark.slow
    def test_the_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            (t / "guard.txt").write_text("tier=B\n")
            (t / "v.json").write_text(json.dumps([self.v("approve")]))
            r = subprocess.run([sys.executable, str(SCRIPTS / "merge_gate.py"), "decide",
                                "--guard", str(t / "guard.txt"), "--fixer-model", "sonnet",
                                "--verdicts", str(t / "v.json")],
                               capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(json.loads(r.stdout)["merge"])


if __name__ == "__main__":
    unittest.main()
