#!/usr/bin/env python3
"""A rule the scorecard says is wrong here is OFFERED for muting, never muted.

Reported: auto.conflict 1 confirmed against 4 Wrong, forecast.decline 0/3,
condition_never_passes 0/2 — each kept filing, and nothing offered to stop
it. `mute_offer.py` is the arithmetic; the server half files the question
through `add_case` and answers it through the case route, Yes performing the
existing mute (`_mute_source`). Driven over the real store and routes.
"""
import asyncio
import sys
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import mute_offer  # noqa: E402
from test_dispatch import DispatchCase  # noqa: E402

SRC = "check:auto.conflict"


def row(wrong=4, confirmed=0, last="wrong", source=SRC):
    return {"source": source, "title": "Automations fighting",
            "wrong": wrong, "confirmed": confirmed,
            "total": wrong + confirmed, "last": last}


class TestTheArithmetic(unittest.TestCase):
    def plan(self, rows, state=None, muted=frozenset(), excluded=frozenset()):
        return mute_offer.plan(rows, state or {}, 1e9, set(), set(muted), excluded)

    def test_four_endings_mostly_wrong_with_a_wrong_last_qualifies(self):
        self.assertEqual(len(self.plan([row(3, 1), ])), 1)   # 75%, last wrong

    def test_below_the_floor_or_share_or_last_agreed_does_not(self):
        self.assertEqual(self.plan([row(3, 0)]), [])          # 3 endings
        self.assertEqual(self.plan([row(2, 2)]), [])          # 50%
        self.assertEqual(self.plan([row(4, 0, last="confirmed")]), [])

    def test_unmutable_muted_and_question_producers_are_never_offered(self):
        for src in ("resident", "safety", mute_offer.SOURCE, "notify_policy"):
            self.assertEqual(self.plan([row(source=src)],
                                       excluded={"resident", "safety"}), [])
        self.assertEqual(self.plan([row()], muted={SRC}), [])

    def test_a_no_stays_a_no_until_the_record_doubles(self):
        state = {SRC: {"ts": 1, "at": 1, "wrong": 4, "answer": "declined"}}
        self.assertEqual(self.plan([row(7)], state), [])
        self.assertEqual(len(self.plan([row(8)], state)), 1)


class TestTheServerHalf(DispatchCase):

    def setUp(self):
        super().setUp()
        for mod in self.copies("mute_offer"):
            self._restore.append((mod, "STORE", mod.STORE))
            mod.STORE = Path(self.tmp.name) / "mute-offers.json"
        fs = self.server.findings_store
        for i in range(4):
            [r] = fs.add_many([{"text": f"A and B fight {i}", "source": SRC,
                                "source_title": "Automations fighting",
                                "entity_id": f"automation.a{i}"}])
            fs.settle_and_clear(r["ts"], "ignored")
        [live] = fs.add_many([{"text": "Another fight", "source": SRC,
                               "source_title": "Automations fighting",
                               "entity_id": "automation.zz"}])
        self.live = live

    def run_pass(self):
        return asyncio.run(self.server._mute_offer_pass(time.time()))

    def end(self, case_id, verb):
        cases = self.server.cases
        ended = cases.end(case_id, verb, hooks=self.server.CASE_HOOKS)
        self.assertIsNotNone(ended)
        work = ended.pop("result", None)
        return asyncio.run(work()) if callable(work) else None

    def muted(self):
        return set(self.server.settings_store.muted())

    def test_the_pass_asks_once_and_mutes_nothing(self):
        [q] = self.run_pass()
        self.assertEqual((q["source"], q["kind"]), (mute_offer.SOURCE, "question"))
        self.assertIn("4 of 4", q["claim"])
        self.assertEqual(self.muted(), set())
        self.assertEqual(self.run_pass(), [], "asked again while it waits")

    def test_yes_mutes_the_rule_and_clears_what_it_filed_and_undo_unmutes(self):
        [q] = self.run_pass()
        payload = self.end(f"f:{q['ts']}", "do")
        self.assertEqual(self.muted(), {SRC})
        self.assertIsNone(self.server.findings_store.get(self.live["ts"]))
        import undo_store
        restored, _ = self.server._undo_finding(undo_store.take(payload["undo"]))
        self.assertTrue(restored)
        self.assertEqual(self.muted(), set())

    def test_no_keeps_the_rule_and_is_not_asked_again(self):
        [q] = self.run_pass()
        self.end(f"f:{q['ts']}", "wrong")
        self.assertEqual(self.muted(), set())
        self.assertIsNotNone(self.server.findings_store.get(self.live["ts"]))
        self.assertEqual(mute_offer.load()[SRC]["answer"], "declined")
        self.assertEqual(self.run_pass(), [])


if __name__ == "__main__":
    unittest.main()
