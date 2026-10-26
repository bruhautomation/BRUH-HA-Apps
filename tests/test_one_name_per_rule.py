#!/usr/bin/env python3
"""One rule, one name, on every screen (#439).

The mute question asked "Stop raising 'Device check'?" about the
impossible-readings rule, while the fault list called it "Impossible sensor
readings" — and the battery rule, which the household finds useful, also
files under "Device check", so the question named a group of rules and the
person could not tell which one stopping it would stop. A rule is named by
its own catalog title everywhere a person reads it: the card, the
scorecard, the fault list, the mute question and History. The question
says which kinds of report the rule files, with one example, and names
where it can be turned back on by the words the panel shows.
"""

import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import checks  # noqa: E402
import findings_store  # noqa: E402
import mute_offer  # noqa: E402

RULE = "check:dev.implausible"
TITLE = checks.get_check("dev.implausible")["title"]
GROUP = checks.GROUP_TITLES["dev"]


class Store(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self._old = (findings_store.FINDINGS_FILE, findings_store.INBOX_DIR,
                     findings_store.SETTLED_FILE, findings_store.STATE_FILE)
        findings_store.FINDINGS_FILE = root / "findings.json"
        findings_store.INBOX_DIR = root / "inbox"
        findings_store.SETTLED_FILE = root / "settled.json"
        findings_store.STATE_FILE = root / "none" / ".brain" / "state.json"

    def tearDown(self):
        (findings_store.FINDINGS_FILE, findings_store.INBOX_DIR,
         findings_store.SETTLED_FILE, findings_store.STATE_FILE) = self._old
        self.tmp.cleanup()

    def wrongs(self, source=RULE, n=5):
        for i in range(n):
            row, _ = findings_store.add(
                f"The attic thermometer {i} reads an impossible value",
                source=source, source_title=GROUP)
            findings_store.settle_and_clear(row["ts"], "ignored")


class TestTheRuleHasOneName(Store):

    def test_the_two_names_differ_in_the_first_place(self):
        self.assertNotEqual(TITLE, GROUP)

    def test_the_scorecard_names_the_rule_not_its_group(self):
        self.wrongs()
        [row] = findings_store.scorecard()
        self.assertEqual(row["title"], TITLE)

    def test_a_shaped_row_names_the_rule(self):
        row, _ = findings_store.add("The attic thermometer reads -150",
                                    source=RULE, source_title=GROUP)
        self.assertEqual(findings_store.get(row["ts"])["source_title"], TITLE)

    def test_the_mute_question_names_the_rule(self):
        self.wrongs()
        [item] = mute_offer.plan(findings_store.scorecard(), {}, 0.0, set(),
                                 set())
        row = item["row"]
        self.assertIn(TITLE, row["text"])
        self.assertNotIn(GROUP, row["text"] + row["claim"] + row["detail"])

    def test_the_battery_rule_is_not_the_same_name(self):
        self.assertNotEqual(TITLE, checks.get_check("dev.battery_low")["title"])


class TestTheMuteQuestionSaysWhatItStops(Store):

    def test_it_names_an_example_and_where_to_turn_it_back_on(self):
        self.wrongs()
        [item] = mute_offer.plan(findings_store.scorecard(), {}, 0.0, set(),
                                 set())
        detail = item["row"]["detail"]
        self.assertIn("The attic thermometer", detail)
        self.assertNotIn("scorecard", detail.lower())
        self.assertIn("History", detail)
        self.assertIn("Ignored", detail)
        self.assertIn("Restore", detail)



class TestEveryRuleHasItsOwnName(unittest.TestCase):

    def test_no_two_checks_share_a_title(self):
        seen = {}
        for spec in checks.CHECKS:
            self.assertTrue(spec.get("title"), spec["id"])
            self.assertNotIn(spec["title"], seen,
                             f"{spec['id']} and {seen.get(spec['title'])}")
            seen[spec["title"]] = spec["id"]


if __name__ == "__main__":
    unittest.main()
