#!/usr/bin/env python3
"""A rule never once right here is offered for muting after two Wrongs.

Reported from a house (devloop #252): `mute_offer` waited for four endings,
and four checks sat at 0 confirmed against 2 Wrong and were never offered.
A rule with no confirmation at all and two Wrongs, the latest a Wrong, is
offered now — still a question, never a mute — and never for a producer
that cannot be muted or a safety check.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import mute_offer  # noqa: E402

NOW = 1_800_000_000.0
UNMUTABLE = frozenset({"resident", "safety", "security",
                       "check:safety.tripped"})


def row(source, confirmed, wrong, last="wrong"):
    return {"source": source, "title": source, "confirmed": confirmed,
            "wrong": wrong, "total": confirmed + wrong, "last": last}


def offered(*rows):
    return [p["source"] for p in mute_offer.plan(
        list(rows), {}, NOW, set(), set(), UNMUTABLE)]


class TestNeverRightTwiceWrong(unittest.TestCase):
    def test_zero_confirmed_two_wrong_is_offered(self):
        self.assertEqual(offered(row("check:forecast.decline", 0, 2)),
                         ["check:forecast.decline"])

    def test_one_confirmed_two_wrong_is_not(self):
        self.assertEqual(offered(row("check:forecast.decline", 1, 2)), [])

    def test_the_latest_ending_has_to_be_a_wrong(self):
        self.assertEqual(offered(row("check:x.y", 0, 2, last="")), [])

    def test_one_wrong_is_not_enough(self):
        self.assertEqual(offered(row("check:x.y", 0, 1)), [])

    def test_a_safety_check_is_never_offered(self):
        self.assertEqual(offered(row("check:climate.freeze", 0, 2),
                                 row("check:climate.freeze", 0, 6)), [])

    def test_an_unmutable_producer_is_never_offered(self):
        self.assertEqual(offered(row("resident", 0, 3),
                                 row("check:safety.tripped", 0, 2)), [])

    def test_it_is_a_question_not_a_mute(self):
        [p] = mute_offer.plan([row("check:x.y", 0, 2)], {}, NOW, set(),
                              set(), UNMUTABLE)
        self.assertEqual(p["row"]["kind"], "question")


if __name__ == "__main__":
    unittest.main()
