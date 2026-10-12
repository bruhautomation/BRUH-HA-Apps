"""A security or safety finding is read with the problems, first after the
urgent ones — never under Tidy-ups.

`sec.addon_unprotected` and `sec.login_bans` file at `info` severity, and
`answers.chip` read every `info` row as a tidy-up, so a house's security
findings sat in the collapsed Tidy-ups group beside an unused helper and a
lamp with no room. The source decides here, not the severity: a report about
who can reach the house is never housekeeping.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "brain" / "panel"))

import answers  # noqa: E402


def row(source, severity="info", **over):
    case = {"kind": "problem", "source": source, "severity": severity,
            "situation": "generic", "status": "open"}
    case.update(over)
    return case


class TestSecurityIsNeverATidyUp(unittest.TestCase):
    def test_an_info_security_check_is_a_problem(self):
        for src in ("check:sec.addon_unprotected", "check:sec.login_bans",
                    "safety", "security"):
            with self.subTest(src=src):
                self.assertEqual(answers.chip(row(src)), "problem")
                self.assertEqual(answers.group(row(src)), "problems")

    def test_registry_housekeeping_is_still_a_tidy_up(self):
        for src in ("check:reg.unused_helper", "check:reg.no_area"):
            with self.subTest(src=src):
                self.assertEqual(answers.chip(row(src)), "tidy")
                self.assertEqual(answers.group(row(src)), "tidy")

    def test_security_reads_first_after_urgent(self):
        cases = [
            row("check:base.trend", "serious"),
            row("check:sec.login_bans", "info"),
            row("safety", "critical", urgent=True),
        ]
        ordered = sorted(cases, key=answers.feed_key)
        self.assertEqual([c["source"] for c in ordered],
                         ["safety", "check:sec.login_bans", "check:base.trend"])


if __name__ == "__main__":
    unittest.main()
