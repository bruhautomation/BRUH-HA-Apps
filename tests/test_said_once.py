#!/usr/bin/env python3
"""A subject a phone was told about is not pushed again on a later day.

One house heard about gaps in its history on three days of one week and
about devices dropping off Wi-Fi on two, each a new finding the store had
no reason to fold, and three times got "kept one thing for now" — the
release of a held message, titled as if it were a push about holding one
back (#639).

`notify_router.said_before` reads the delivery ledger: the same producer
about the same device, sent within a week at the same or a worse severity,
is not sent again (it is on the list, and the decision trail says when the
phone was told). Another device or a worse severity is news. And a held
message, released, is titled as what it is.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "brain" / "panel"))

import notify_router  # noqa: E402
from test_dispatch import NOTIFY_ROW, DispatchCase  # noqa: E402

NOW = 1_800_000_000.0
DAY = 86400


def msg(days_ago, *, sources=("check:net.drops",),
        entities=("sensor.hall_plug",), severity="warning", ok=True,
        kind="notify"):
    return {"at": NOW - days_ago * DAY, "kind": kind, "ok": ok,
            "sources": list(sources), "entities": list(entities),
            "severity": severity}


def row(**over):
    return {"source": "check:net.drops", "entity_id": "sensor.hall_plug",
            "severity": "warning", **over}


class TestSaidBefore(unittest.TestCase):
    def test_the_same_subject_this_week_was_said(self):
        self.assertIsNotNone(notify_router.said_before(row(), [msg(2)], NOW))

    def test_a_week_on_it_is_news_again(self):
        self.assertIsNone(notify_router.said_before(row(), [msg(8)], NOW))

    def test_another_device_is_news(self):
        self.assertIsNone(notify_router.said_before(
            row(entity_id="sensor.porch_plug"), [msg(2)], NOW))

    def test_worse_is_news_and_the_same_or_milder_is_not(self):
        self.assertIsNone(notify_router.said_before(
            row(severity="serious"), [msg(2)], NOW))
        self.assertIsNotNone(notify_router.said_before(
            row(severity="info"), [msg(2)], NOW))

    def test_the_last_day_is_the_dispatchers_to_judge(self):
        self.assertIsNone(notify_router.said_before(row(), [msg(0.5)], NOW))

    def test_a_failed_send_or_a_brief_said_nothing(self):
        self.assertIsNone(notify_router.said_before(row(), [msg(2, ok=False)], NOW))
        self.assertIsNone(notify_router.said_before(row(), [msg(2, kind="brief")], NOW))

    def test_a_producer_about_anything_is_never_matched_by_name_alone(self):
        self.assertIsNone(notify_router.said_before(
            {"source": "resident", "severity": "warning"},
            [msg(2, sources=("resident",), entities=())], NOW))
        # …while one check about no device is its own subject.
        self.assertIsNotNone(notify_router.said_before(
            {"source": "check:sys.history_gaps", "severity": "warning"},
            [msg(3, sources=("check:sys.history_gaps",), entities=())], NOW))


class TestTheReleaseTitle(unittest.TestCase):
    def test_a_released_hold_says_what_it_is(self):
        rows = [{"ts": 1, "until": NOW, "text": "x", "severity": "warning"},
                {"ts": 2, "until": NOW, "text": "y", "severity": "warning"}]
        self.assertEqual(notify_router.compose_released(rows[:1])[0],
                         "One thing from earlier")
        self.assertEqual(notify_router.compose_released(rows)[0],
                         "2 things from earlier")
        self.assertNotIn("kept", notify_router.compose_released(rows)[0])


class TestTheAnnouncerHoldsIt(DispatchCase):
    def setUp(self):
        super().setUp()
        self.point("decision_trail",
                   TRAIL_FILE=str(Path(self.tmp.name) / "decisions.jsonl"))

    def test_a_second_finding_on_a_later_day_is_not_pushed(self):
        [first] = self.file(NOTIFY_ROW)
        self.announce([first])       # the dispatcher is not set: sent as is
        self.assertEqual(len(self.sent), 1)
        # Two days on.
        ledger = self.copies("deliveries")[0].DELIVERIES_FILE
        lines = [json.loads(x) for x in ledger.read_text().splitlines()]
        for line in lines:
            line["at"] = int(line["at"]) - 2 * DAY
        ledger.write_text("".join(json.dumps(x) + "\n" for x in lines))
        again = dict(first, ts=first["ts"] + 1)
        self.announce([again])
        self.assertEqual(len(self.sent), 1, "the same subject went out twice")
        worse = dict(first, ts=first["ts"] + 2, severity="serious")
        self.announce([worse])
        self.assertEqual(len(self.sent), 2)


if __name__ == "__main__":
    unittest.main()
