"""A rule brAIn holds back by its record says so, however few answers it has.

`rule_record.qualifies` quiets a rule at two Wrongs, and the fault row that
says brAIn is holding it back used to wait for four answers, so a rule at
0 right / 3 wrong was held in silence."""
import json
import sys
import unittest
from pathlib import Path

PANEL = Path(__file__).resolve().parent.parent / "brain" / "panel"
sys.path.insert(0, str(PANEL))

import reports  # noqa: E402


def rows(source, wrong, total):
    diag = {"findings": {"scorecard": [{
        "source": source, "title": "A rule", "wrong": wrong,
        "confirmed": total - wrong, "total": total, "last": "wrong"}],
        "mute_offers_open": []}}
    return [r for r in reports.faults(diag)
            if str(r.get("where", "")).startswith("Producer")]


class TestTheNoticeFollowsTheHold(unittest.TestCase):
    def test_three_wrongs_and_no_confirmation_say_it_is_held(self):
        [row] = rows("check:forecast.decline", 3, 3)
        self.assertIn("holds", json.dumps(row).lower())

    def test_two_wrongs_of_two_say_it_too(self):
        [row] = rows("check:auto.condition_never_passes", 2, 2)
        self.assertIn("holds", json.dumps(row).lower())

    def test_one_wrong_is_not_a_record(self):
        self.assertEqual(rows("check:chore.waiting", 1, 1), [])


if __name__ == "__main__":
    unittest.main()
