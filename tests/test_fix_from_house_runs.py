"""The run record and the loop's efficacy numbers (plan 1.3, 1.4, 4.1).

``runs.jsonl`` holds one validated row per run in the reports repository,
and held^7d, the came-back, revert and overturned-decline rates, batch
sizes and tiers are computed from it by code, never written by the model.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
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


C = _load("ffh_common.py", "ffh_test_common_r")
R = _load("runs_record.py", "ffh_test_runs_record")

NOW = datetime(2026, 11, 20, tzinfo=timezone.utc)
HOUSE = "house-bot"


def row(run_id="2026-11-04T10:00Z", started="2026-11-04T10:00:00Z",
        ended="2026-11-04T12:30:00Z", **over) -> dict:
    out = {"run_id": run_id, "started": started, "ended": ended,
           "models": ["opus", "sonnet"],
           "issues": {"fixed": 4, "declined": 1, "duplicate": 1},
           "prs": [{"number": 601, "tier": "A", "reviewer_verdicts": ["approve"],
                    "merged": True, "reverted": False, "issues": [11, 12, 13]},
                   {"number": 602, "tier": "C",
                    "reviewer_verdicts": ["approve", "approve"],
                    "merged": True, "reverted": False, "issues": [14]}],
           "guard_failures": 1, "monitor_hits": [], "tokens": None}
    out.update(over)
    return out


def held(fp, held_ok, days=7, release="4.3.0", issue=11):
    return {"v": 1, "fp": fp, "release": release,
            "installed_at": "2026-11-05T00:00:00Z", "held_days": days,
            "held": held_ok, "_issue": issue}


class TestValidation(unittest.TestCase):
    def test_a_good_row_passes(self):
        good = row(audit={"sampled": 2, "overturned": 1}, reverted_prs=[590],
                   ablation={"component": "batch_size_8", "disabled": True}, tokens=10)
        self.assertIs(R.validate(good), good)

    def test_bad_rows_are_refused(self):
        cases = {
            "missing": {k: v for k, v in row().items() if k != "prs"},
            "time order": row(ended="2026-11-04T09:00:00Z"),
            "bad time": row(started="yesterday"),
            "no models": row(models=[]),
            "bad outcome": row(issues={"closed": 3}),
            "negative": row(issues={"fixed": -1}),
            "bool count": row(issues={"fixed": True}),
            "bad tier": row(prs=[{"number": 1, "tier": "D", "reviewer_verdicts": [],
                                  "merged": False, "reverted": False}]),
            "bad verdict": row(prs=[{"number": 1, "tier": "A",
                                     "reviewer_verdicts": ["lgtm"],
                                     "merged": False, "reverted": False}]),
            "merged unreviewed": row(prs=[{"number": 1, "tier": "A",
                                           "reviewer_verdicts": ["unknown"],
                                           "merged": True, "reverted": False}]),
            "C on one approve": row(prs=[{"number": 1, "tier": "C",
                                          "reviewer_verdicts": ["approve"],
                                          "merged": True, "reverted": False}]),
            "M on one approve": row(prs=[{"number": 1, "tier": "M",
                                          "reviewer_verdicts": ["approve", "unknown"],
                                          "merged": True, "reverted": False}]),
            "hits": row(monitor_hits=[{"what": "x"}]),
            "tokens": row(tokens=-5),
            "audit": row(audit={"sampled": 1, "overturned": 2}),
            "kind": row(kind="party"),
        }
        for why, bad in cases.items():
            with self.subTest(why=why):
                with self.assertRaises(R.RowError):
                    R.validate(bad)

    def test_append_refuses_a_duplicate_run_and_keeps_one_line_per_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runs.jsonl"
            path.write_text(json.dumps(row(run_id="a")))       # no trailing newline
            R.append(path, row(run_id="b"))
            with self.assertRaises(R.RowError):
                R.append(path, row(run_id="b"))
            with self.assertRaises(R.RowError):
                R.append(path, row(run_id="c", models=[]))
            lines = path.read_text().splitlines()
        self.assertEqual([json.loads(ln)["run_id"] for ln in lines], ["a", "b"])

    def test_a_corrupt_file_names_its_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runs.jsonl"
            path.write_text(json.dumps(row()) + "\n{oops\n")
            with self.assertRaisesRegex(R.RowError, "line 2"):
                R.read_rows(path)


class TestMetrics(unittest.TestCase):
    def rows(self):
        return [
            row(),
            row(run_id="2", started="2026-11-10T10:00:00Z", ended="2026-11-10T11:00:00Z",
                issues={"fixed": 6, "came_back": 2, "declined": 2},
                prs=[{"number": 610, "tier": "B", "reviewer_verdicts":
                      ["request_changes", "approve"], "merged": True, "reverted": False,
                      "issues": [20, 21]},
                     {"number": 611, "tier": "A", "reviewer_verdicts": ["unknown"],
                      "merged": False, "reverted": False}],
                reverted_prs=[601], audit={"sampled": 4, "overturned": 1},
                monitor_hits=[{"pattern": "skip_flag_retry", "pr": 610}], tokens=1000),
            row(run_id="old", started="2026-09-01T10:00:00Z", ended="2026-09-01T11:00:00Z",
                issues={"fixed": 50}),
        ]

    def test_the_numbers(self):
        hb = [held("a", True), held("b", True), held("c", False),
              held("d", True, days=3),                      # not 7 days yet
              held("a", True, days=8)]                      # newer of the same fix
        m = R.metrics(self.rows(), hb, NOW, days=28)
        self.assertEqual(m["runs"], 2)                       # the September run is out
        self.assertEqual(m["issues"]["fixed"], 10)
        self.assertEqual(m["held_7d_n"], 3)
        self.assertAlmostEqual(m["held_7d"], 0.667, places=3)
        self.assertEqual(m["came_back_rate"], 0.2)
        self.assertEqual(m["revert_rate"], round(1 / 3, 3))
        self.assertEqual(m["reverted"], [601])
        self.assertEqual(m["overturned_declines_rate"], 0.25)
        self.assertEqual(m["batch_size"], {"mean": 2, "median": 2, "max": 3})
        self.assertEqual(m["tiers"]["A"], 2)
        self.assertEqual(m["tiers"]["C"], 1)
        self.assertEqual(m["reviewer_verdicts"]["request_changes"], 1)
        self.assertEqual(m["guard_failures"], 2)
        self.assertEqual(m["monitor_hits"], 1)
        self.assertEqual(m["tokens"], 1000)

    def test_nothing_measured_is_said_not_zero(self):
        m = R.metrics([], [], NOW)
        self.assertIsNone(m["held_7d"])
        self.assertIsNone(m["revert_rate"])
        text = R.render([], [], NOW)
        self.assertIn("## Loop health", text)
        self.assertIn("not yet measured", text)

    def test_render_names_the_score_and_the_last_runs(self):
        text = R.render(self.rows(), [held("a", True)], NOW)
        self.assertIn("**held^7d**: 100% of 1", text)
        self.assertIn("(#601)", text)
        self.assertIn("- 2: 1.0 h;", text)
        self.assertIn("#611 (open)", text)

    def test_held_blocks_are_verified_when_given_as_issues(self):
        good = C.sign({k: v for k, v in held("a", True).items() if k != "_issue"})
        forged = dict(good, held=True, fp="b", held_days=9)
        issues = [{"number": 11, "comments": [
            {"user": {"login": HOUSE}, "body": C.fence(good, "brain-held")},
            {"user": {"login": HOUSE}, "body": C.fence(forged, "brain-held")},
            {"user": {"login": "x"}, "body": C.fence(good, "brain-held")}]}]
        found = R.held_from(issues, HOUSE)
        self.assertEqual([h["fp"] for h in found], ["a"])


class TestAblation(unittest.TestCase):
    def series(self, came_back_after):
        rows = []
        for i in range(3):
            rows.append(row(run_id=f"p{i}", started=f"2026-11-0{i + 1}T10:00:00Z",
                            ended=f"2026-11-0{i + 1}T11:00:00Z",
                            issues={"fixed": 10, "came_back": 1},
                            prs=[{"number": 700 + i, "tier": "A",
                                  "reviewer_verdicts": ["approve"], "merged": True,
                                  "reverted": False, "issues": [100 + i]}]))
        for i in range(3):
            rows.append(row(run_id=f"a{i}", started=f"2026-11-1{i}T10:00:00Z",
                            ended=f"2026-11-1{i}T11:00:00Z",
                            issues={"fixed": 10, "came_back": came_back_after},
                            prs=[{"number": 710 + i, "tier": "A",
                                  "reviewer_verdicts": ["approve"], "merged": True,
                                  "reverted": False, "issues": [110 + i]}],
                            ablation={"component": "hostile_reread", "disabled": True}))
        return rows

    def test_a_component_that_mattered_is_restored(self):
        out = R.ablation_compare(self.series(came_back_after=4), "hostile_reread")
        self.assertEqual(out["verdict"], "restore")
        self.assertIn("came_back_rate", out["worse"])

    def test_a_component_that_did_not_matter_stays_removed(self):
        hb = [held("x", True, issue=100), held("y", True, issue=111)]
        out = R.ablation_compare(self.series(came_back_after=1), "hostile_reread", hb)
        self.assertEqual(out["verdict"], "keep_removed")
        self.assertEqual(out["without_component"]["held_7d"], 1.0)

    def test_too_few_runs_is_not_enough_data(self):
        rows = self.series(1)[2:]
        self.assertEqual(R.ablation_compare(rows, "hostile_reread")["verdict"],
                         "not_enough_data")
        self.assertEqual(R.ablation_compare(rows, "nothing")["verdict"], "not_enough_data")


class TestTheCli(unittest.TestCase):
    @pytest.mark.slow
    def test_append_then_render(self):
        script = str(SCRIPTS / "runs_record.py")
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            (t / "row.json").write_text(json.dumps(row()))
            (t / "bad.json").write_text(json.dumps(row(models=[])))
            ok = subprocess.run([sys.executable, script, "append", str(t / "runs.jsonl"),
                                 str(t / "row.json")], capture_output=True, text=True,
                                timeout=60)
            bad = subprocess.run([sys.executable, script, "validate", str(t / "bad.json")],
                                 capture_output=True, text=True, timeout=60)
            out = subprocess.run([sys.executable, script, "render", str(t / "runs.jsonl"),
                                  "--now", "2026-11-05T00:00:00Z"],
                                 capture_output=True, text=True, timeout=60)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertEqual(bad.returncode, 1)
        self.assertIn("models", bad.stderr)
        self.assertIn("## Loop health", out.stdout)


if __name__ == "__main__":
    unittest.main()
