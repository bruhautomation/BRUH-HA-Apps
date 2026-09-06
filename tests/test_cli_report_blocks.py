#!/usr/bin/env python3
"""`brain check` and `brain weekly`'s printing, lifted out and driven.

Both scripts embedded their report blocks as ``python3 -c '...'``. Shell
single quotes leave no way to put a ``"`` inside an f-string *expression*
except a backslash, and a backslash in one is a ``SyntaxError`` before
Python 3.12 — so every one of these parsed on the image's interpreter and
on nothing else. Nothing noticed for four releases, because nothing had
ever run them: they were written, reviewed and shipped.

``brain doctor --deep``'s blocks were fixed the same way one commit
earlier (``tests/test_doctor_deep.py::TestTheCliReportBlocks``), and the
same second trap applies here: **a heredoc IS stdin**, so a payload piped
into one arrives empty — which reads as "nothing to report" rather than as
an error, and is the quieter half of the same bug. The payload is an
argument and the script is the heredoc.

So these tests drive the real functions out of the real files. The two
greps at the end are greps on purpose, beside tests that drive, because
"this pattern is absent" is the one claim a grep can honestly make.
"""

import json
import re
import subprocess
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPTS = BASE_DIR / "brain" / "scripts"


class _Blocks(unittest.TestCase):
    """Lift named shell functions out of a shipped script and run them."""

    SCRIPT: Path

    def block(self, *names: str) -> str:
        src = self.SCRIPT.read_text(encoding="utf-8")
        out = []
        for name in names:
            match = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", src, re.M | re.S)
            self.assertIsNotNone(match, f"{name} is gone from {self.SCRIPT.name}")
            out.append(match.group(0))
        return "".join(out)

    def run_sh(self, names, body) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", "-c", "set -u\n" + self.block(*names) + "\n" + body],
            capture_output=True, text=True, timeout=30)

    def assert_no_dash_c(self):
        src = self.SCRIPT.read_text(encoding="utf-8")
        offenders = [line for line in src.splitlines()
                     if "python3 -c" in line
                     and not line.lstrip().startswith("#")]
        self.assertEqual(offenders, [], "\n".join(offenders))

    def assert_no_pipe_into_heredoc(self):
        src = self.SCRIPT.read_text(encoding="utf-8")
        offenders = [line for line in src.splitlines()
                     if "|" in line and "python3 - " in line]
        self.assertEqual(offenders, [], "\n".join(offenders))


class TestBrainCheckPrinting(_Blocks):
    SCRIPT = SCRIPTS / "brain-check.sh"

    CATALOG = json.dumps({
        "catalog": [
            {"id": "auto.dead_ref", "title": "Automation names a dead entity"},
            {"id": "dev.frozen", "title": "Sensor stuck on one reading"},
            {"id": "sys.disk", "title": "Disk filling up"},
            {"id": "dev.example", "title": "A shadow check", "shadow": True},
        ],
        "last": {"finished_at": 1, "created": 2, "cleared": 1,
                 "ran": ["auto.dead_ref", "sys.disk"],
                 "per_check": {"auto.dead_ref": 3},
                 "skipped": {"dev.frozen": "snapshot is missing stats"},
                 "errors": {"sys.disk": "KeyError: host"}},
    })

    def test_the_catalog_says_found_skipped_and_errored_apart(self):
        proc = self.run_sh(["print_catalog"], f"print_catalog '{self.CATALOG}'\n")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("3 found", proc.stdout)
        self.assertIn("skipped: snapshot is missing stats", proc.stdout)
        self.assertIn("ERROR KeyError: host", proc.stdout)
        self.assertIn("2 filed", proc.stdout)

    def test_a_shadow_check_is_labelled_in_the_catalog(self):
        """It files somewhere the tab does not render, and a catalog that
        did not say so would send somebody looking for rows that are not
        there."""
        proc = self.run_sh(["print_catalog"], f"print_catalog '{self.CATALOG}'\n")
        line = [ln for ln in proc.stdout.splitlines() if "dev.example" in ln]
        self.assertTrue(line, proc.stdout)
        self.assertIn("(shadow)", line[0])

    def test_a_house_with_no_pass_yet_says_so(self):
        payload = json.dumps({"catalog": [], "last": {}})
        proc = self.run_sh(["print_catalog"], f"print_catalog '{payload}'\n")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("No run yet", proc.stdout)

    def test_a_torn_payload_is_an_error_not_a_traceback(self):
        proc = self.run_sh(["print_catalog"], "print_catalog 'not json'\n")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("not JSON", proc.stdout)
        self.assertNotIn("Traceback", proc.stderr)

    def test_the_run_prints_what_was_filed_and_what_was_cleared(self):
        payload = json.dumps({
            "ran": ["auto.dead_ref"], "duration_s": 2.25, "refreshed": 4,
            "created": [{"severity": "serious", "text": "A dead reference"}],
            "cleared": [{"text": "A battery that came back"}],
            "skipped": {"dev.frozen": "no statistics"},
            "errors": {"sys.disk": "boom"},
            "snapshot_errors": {"supervisor": "timed out"},
            "shadow": {"created": 2},
        })
        proc = self.run_sh(["print_run"], f"print_run '{payload}'\n")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("1 checks ran in 2.2s", proc.stdout)
        self.assertIn("+ [serious] A dead reference", proc.stdout)
        self.assertIn("- A battery that came back", proc.stdout)
        self.assertIn("2 shadow row(s) filed", proc.stdout)
        self.assertIn("skipped dev.frozen: no statistics", proc.stdout)
        self.assertIn("ERROR sys.disk: boom", proc.stdout)
        self.assertIn("could not fetch supervisor: timed out", proc.stdout)

    def test_a_refused_pass_exits_non_zero(self):
        payload = json.dumps({"error": "a checks pass is already running"})
        proc = self.run_sh(["print_run"], f"print_run '{payload}'\n")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("already running", proc.stdout)

    def test_nothing_in_the_script_uses_python3_dash_c(self):
        self.assert_no_dash_c()

    def test_no_heredoc_python_is_also_piped_into(self):
        self.assert_no_pipe_into_heredoc()


class TestBrainWeeklyPrinting(_Blocks):
    SCRIPT = SCRIPTS / "brain-weekly.sh"

    WEEK = json.dumps({
        "enabled": True, "day": "Sunday",
        "notify_service": "notify.mobile_app_phone",
        "last_sent": 0, "last_error": "",
        "energy": {"available": True,
                   "energy": {"this": 84.2, "last": 91.0, "unit": " kWh",
                              "comparable": True, "change_pct": -7.5,
                              "days": 7},
                   "cost": {"this": 21.4, "unit": " GBP", "days": 5,
                            "comparable": False}},
        "findings": {"settled": 3, "confirmed": 2, "wrong": 1,
                     "still_open": 4, "open_now": 9,
                     "by_source": [["Battery check", 2]]},
        "learned": {"available": True, "total": 2, "removed": 1,
                    "added": ["The kitchen light is on a dimmer"]},
        "one_thing": {"severity": "serious", "text": "The freezer is warming"},
        "worth_reporting": True,
        "last_text": "Last week you...",
    })

    def test_the_week_prints_every_section(self):
        proc = self.run_sh(["print_week"], f"print_week '{self.WEEK}'\n")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Weekly report: on, Sundays -> notify.mobile_app_phone",
                      proc.stdout)
        self.assertIn("Never sent", proc.stdout)
        self.assertIn("Electricity: 84.2 kWh over 7 days vs 91.0 kWh before "
                      "(-7.5%)", proc.stdout)
        self.assertIn("no comparison", proc.stdout)
        self.assertIn("Findings: 3 answered this week (2 real, 1 misread)",
                      proc.stdout)
        self.assertIn("2 from Battery check", proc.stdout)
        self.assertIn("Learned: 2 new, 1 corrected", proc.stdout)
        self.assertIn("One thing to do: [serious] The freezer is warming",
                      proc.stdout)
        self.assertIn("Last report sent:", proc.stdout)

    def test_an_unreadable_memory_log_is_not_nothing_learned(self):
        """"I could not look" and "there was nothing" are different
        claims, and the report has to keep them apart."""
        payload = json.dumps({"findings": {}, "learned": {"available": False},
                              "energy": {"available": False,
                                         "reason": "no energy configuration"}})
        proc = self.run_sh(["print_week"], f"print_week '{payload}'\n")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("the memory log could not be read", proc.stdout)
        self.assertIn("Energy: no energy configuration", proc.stdout)
        self.assertIn("nothing open", proc.stdout)

    def test_a_torn_payload_is_an_error_not_a_traceback(self):
        proc = self.run_sh(["print_week"], "print_week '{{{'\n")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("not JSON", proc.stdout)
        self.assertNotIn("Traceback", proc.stderr)

    def test_sending_prints_the_report_and_a_refusal_exits_non_zero(self):
        sent = json.dumps({"sent": True, "text": "This week the boiler..."})
        proc = self.run_sh(["print_sent"], f"print_sent '{sent}'\n")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("This week the boiler", proc.stdout)

        refused = json.dumps({"error": "no notify service is configured"})
        proc = self.run_sh(["print_sent"], f"print_sent '{refused}'\n")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("Not sent: no notify service is configured", proc.stdout)

    def test_a_week_not_worth_reporting_exits_zero(self):
        payload = json.dumps({"sent": False})
        proc = self.run_sh(["print_sent"], f"print_sent '{payload}'\n")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("nothing was sent", proc.stdout)

    def test_nothing_in_the_script_uses_python3_dash_c(self):
        self.assert_no_dash_c()

    def test_no_heredoc_python_is_also_piped_into(self):
        self.assert_no_pipe_into_heredoc()


if __name__ == "__main__":
    unittest.main()
