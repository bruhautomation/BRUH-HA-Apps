"""The corpus stream: real first looks the household disagreed with (plan 1.7).

With capture on, a first look whose labels say it raised what was marked
Wrong, or passed over what was then confirmed, is filed as one issue
carrying a ``brain-corpus`` block. The block is a corpus entry the
repository's own validator (`tests/test_corpus.validate`) accepts, scrubbed
and aliased like everything the loop sends. Off by default, nothing while
capture is off, and the loop's review and caps apply.
"""
from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "tests"))
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

from test_corpus import validate  # noqa: E402
from test_devloop import NAMES, TOKEN, DevloopCase, diagnostics, upstream  # noqa: E402

import devloop  # noqa: E402
from devloop import blocks, corpus  # noqa: E402


def capture(labels, run_id="0f3a9b2c-1111-4222-8333-944455556666"):
    return {
        "schema": 1, "kind": "first_look", "id": run_id, "run_id": run_id,
        "captured_at": 1_800_000_000, "now": 1_800_000_000.0, "source": "resident",
        "model": "haiku",
        "batch": [
            {"kind": "state", "subject": "binary_sensor.kitchen_leak",
             "text": "Kitchen leak off → on", "safety": True},
            {"kind": "check", "subject": "light.bedroom_lamp",
             "text": f"Bedroom Lamp unavailable in Master Bedroom; Bearer {TOKEN}"},
        ],
        "inputs": {"memory": "Alex works nights in the Kitchen"},
        "reply": {}, "labels": labels,
    }


class TestTheEntry(unittest.TestCase):
    def test_only_a_wrong_or_missed_look_is_a_case(self):
        self.assertIsNone(corpus.entry_for(capture([])))
        self.assertIsNone(corpus.entry_for(capture(
            [{"signal": 1, "outcome": "confirmed", "floor": "watch"}])))
        entry = corpus.entry_for(capture([
            {"signal": 1, "outcome": "missed", "floor": "watch"},
            {"signal": 2, "outcome": "wrong", "ceiling": "ignore"},
            {"signal": 2, "outcome": "confirmed", "floor": "watch"}]))
        self.assertEqual(validate(entry), [])
        self.assertEqual([lb["outcome"] for lb in entry["labels"]], ["missed", "wrong"])
        self.assertEqual(entry["kind"], "first_look")

    def test_nothing_while_capture_is_off(self):
        caps = [capture([{"signal": 1, "outcome": "missed", "floor": "watch"}])]
        self.assertEqual(corpus.rows(caps, capture_on=False), [])
        self.assertEqual(len(corpus.rows(caps, capture_on=True)), 1)

    def test_it_is_off_by_default(self):
        self.assertFalse(devloop.STREAMS["corpus"]["default_on"])
        self.assertTrue(devloop.STREAMS["canary"]["default_on"])


class TestTheIssue(DevloopCase):
    def test_the_block_is_a_valid_entry_and_carries_nothing_from_the_house(self):
        self.switch_on()
        devloop.save_settings({"streams": {"corpus": True}})
        rows = corpus.rows([capture([
            {"signal": 1, "outcome": "missed", "floor": "watch"},
            {"signal": 2, "outcome": "wrong", "ceiling": "ignore"}])], capture_on=True)
        upstream.ingest("corpus", rows, diagnostics(), NAMES, now=time.time())
        upstream.send_due()
        [issue] = self.gh.issues
        obj = blocks.parse_block("corpus", issue["body"])
        self.assertIsNotNone(obj)
        entry = {k: v for k, v in obj.items() if k not in ("v", "digest")}
        self.assertEqual(validate(entry), [])
        self.assertEqual(validate(obj), [], "the block itself is an entry too")
        text = json.dumps(obj)
        for real in ("Kitchen", "Bedroom Lamp", "Master Bedroom", "light.bedroom_lamp",
                     "Alex", TOKEN):
            self.assertNotIn(real, text, real)
        self.assertEqual(blocks.parse_block("devloop", issue["body"])["stream"], "corpus")

    def test_review_holds_it_like_any_report(self):
        self.switch_on(review=True)
        rows = corpus.rows([capture([{"signal": 1, "outcome": "missed",
                                      "floor": "watch"}])], capture_on=True)
        upstream.ingest("corpus", rows, diagnostics(), NAMES)
        upstream.send_due()
        self.assertEqual(self.gh.issues, [])
        self.assertEqual([r["state"] for r in upstream.listing()], ["pending"])


if __name__ == "__main__":
    unittest.main()
