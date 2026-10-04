#!/usr/bin/env python3
"""What the household's thumbs say, asked once and never applied unasked.

`notify_learn.py` is arithmetic over the delivery ledger; the server half
files its question through the Resident's door (`findings_store.add_case`)
and answers it through the case route every other card uses. Both are
driven here: the ledger is written by the real `deliveries.record` and the
real request drain's `note_answer`, the pass is the real
`_notify_learn_pass`, Yes and No go through `cases.end` with the server's
own `CASE_HOOKS`, and Undo through `_undo_finding` with the token the press
handed back — so the clause that lands in settings is the one a person
would see in ⚙.
"""

import asyncio
import sys
import tempfile
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import deliveries  # noqa: E402
import notify_learn  # noqa: E402
from test_dispatch import DispatchCase  # noqa: E402

NOW = 1_760_000_000.0
DAY = 86400


def sent(i, *, outcome="cleared", action="", after=20, entity="light.garden",
         source="check:dev.unavailable", severity="warning", kind="notify",
         n_rows=1, at=None) -> dict:
    """One folded delivery, in the shape `deliveries.fold` returns."""
    row = {"id": f"d{i}", "at": at if at is not None else NOW - i * 3600,
           "kind": kind, "ts": list(range(100 + i, 100 + i + n_rows)),
           "sources": [source], "entities": [entity] if entity else [],
           "severity": severity, "outcome": outcome, "ok": True}
    if outcome in ("answered", "cleared"):
        row["after_s"] = after
    if action:
        row["action"] = action
    return row


class TestTheArithmetic(unittest.TestCase):

    def test_nine_of_ten_swiped_qualifies(self):
        rows = [sent(i) for i in range(9)] + [sent(9, outcome="answered",
                                                   action="todo")]
        [cand] = notify_learn.tally(rows, NOW)
        self.assertEqual((cand["kind"], cand["subject"]),
                         ("entity", "light.garden"))
        self.assertEqual((cand["sends"], cand["negative"]), (10, 9))

    def test_seven_sends_is_an_anecdote(self):
        self.assertEqual(notify_learn.tally([sent(i) for i in range(7)], NOW), [])

    def test_seventy_percent_is_not_eighty(self):
        rows = [sent(i) for i in range(7)] + [
            sent(i, outcome="answered", action="fixed") for i in range(7, 10)]
        self.assertEqual(notify_learn.tally(rows, NOW), [])

    def test_ignored_is_not_a_dismissal(self):
        # An iPhone never reports a swipe; a message nobody touched may
        # have been read.
        rows = [sent(i, outcome="ignored") for i in range(10)]
        self.assertEqual(notify_learn.tally(rows, NOW), [])

    def test_a_dismiss_button_counts(self):
        rows = [sent(i, outcome="answered", action="snooze") for i in range(8)]
        [cand] = notify_learn.tally(rows, NOW)
        self.assertEqual(cand["dismissed"], 8)

    def test_critical_safety_resident_and_digests_are_never_counted(self):
        for over in ({"severity": "critical"}, {"source": "safety"},
                     {"source": "resident"}, {"n_rows": 3},
                     {"kind": "escalate"}, {"kind": "reminder"},
                     {"outcome": "pending"}, {"outcome": "failed"},
                     {"at": NOW - 40 * DAY}):
            with self.subTest(over=over):
                rows = [sent(i, **over) for i in range(12)]
                self.assertEqual(notify_learn.tally(rows, NOW), [])

    def test_a_producer_qualifies_only_on_what_its_devices_did_not_claim(self):
        garden = [sent(i) for i in range(10)]
        others = [sent(10 + i, entity=f"light.e{i}",
                       outcome="answered", action="fixed") for i in range(6)]
        found = notify_learn.tally(garden + others, NOW)
        self.assertEqual([(c["kind"], c["subject"]) for c in found],
                         [("entity", "light.garden")])

    def test_the_words(self):
        rows = [sent(i, outcome="answered", action="snooze", after=10)
                for i in range(9)] + [sent(9, outcome="answered",
                                           action="fixed")]
        [cand] = notify_learn.tally(rows, NOW)
        q = notify_learn.question(cand, "Garden lights")
        self.assertEqual(q, "You dismissed 9 of 10 Garden lights alerts within "
                            "a minute — move them to the morning list?")
        clause = notify_learn.clause(cand, "Garden lights")
        self.assertIn("light.garden", clause)
        self.assertIn("unless they are critical", clause)

    def test_asked_once_and_again_only_if_it_vanished_unanswered(self):
        key = "entity:light.garden"
        self.assertTrue(notify_learn.due({}, key, NOW, set()))
        for answer in ("accepted", "declined"):
            state = {key: {"answer": answer, "at": NOW - 400 * DAY, "ts": 5}}
            self.assertFalse(notify_learn.due(state, key, NOW, set()))
        waiting = {key: {"answer": "", "at": NOW - 40 * DAY, "ts": 5}}
        self.assertFalse(notify_learn.due(waiting, key, NOW, {5}))
        gone_recently = {key: {"answer": "", "at": NOW - 3 * DAY, "ts": 5}}
        self.assertFalse(notify_learn.due(gone_recently, key, NOW, set()))
        self.assertTrue(notify_learn.due(waiting, key, NOW, set()))

    def test_a_muted_producer_asks_nothing(self):
        rows = [sent(i) for i in range(10)]
        self.assertEqual(notify_learn.plan(rows, {}, NOW, set(), {}, muted=True),
                         [])
        self.assertTrue(notify_learn.plan(rows, {}, NOW, set(), {}))


class TestTheQuestionAndItsAnswers(DispatchCase):

    def setUp(self):
        super().setUp()
        root = Path(self.tmp.name)
        for mod in self.copies("notify_learn"):
            self._restore.append((mod, "STORE", mod.STORE))
            mod.STORE = root / "notify-suggestions.json"
        self.server._NAMES["light.garden"] = {"name": "Garden lights", "area": ""}
        # Ten messages about the garden lights, nine swiped away within a
        # minute — written by the real writers, outcomes and all.
        now = time.time()
        for i in range(10):
            did = deliveries.new_id()
            at = now - 2 * DAY - i * 3600
            self.deliveries.record(
                "notify", delivery_id=did, service="mobile_app_phone",
                title="Garden lights", body="unavailable",
                rows=[{"ts": 900 + i, "source": "check:dev.unavailable",
                       "entity_id": "light.garden", "severity": "warning"}],
                when=at)
            if i < 9:
                self.deliveries.note_cleared(
                    {"tag": deliveries.tag_for(did)}, when=at + 15)
            else:
                self.deliveries.note_answer(900 + i, "fixed", when=at + 600)
        self.now = now

    def run_pass(self):
        return asyncio.run(self.server._notify_learn_pass(self.now))

    def end(self, case_id, verb):
        cases = self.server.cases
        ended = cases.end(case_id, verb, hooks=self.server.CASE_HOOKS)
        self.assertIsNotNone(ended)
        work = ended.pop("result", None)
        return asyncio.run(work()) if callable(work) else None

    def learned(self):
        import settings_store
        return settings_store.load()["notify_policy_learned"]

    def memory_lines(self):
        inbox = Path(self.server.MEMORY_INBOX_DIR)
        return sorted(p.read_text() for p in inbox.glob("*")) if inbox.is_dir() else []

    def test_the_pass_files_one_question_once(self):
        [row] = self.run_pass()
        self.assertEqual(row["source"], notify_learn.SOURCE)
        self.assertEqual(row["kind"], "question")
        self.assertIn("You swiped away 9 of 10 Garden lights alerts within a "
                      "minute", row["claim"])
        case = self.server.cases.get(f"f:{row['ts']}")
        self.assertEqual(case["kind"], "question")
        self.assertEqual(self.run_pass(), [], "asked again while it waits")
        self.assertEqual(self.learned(), [], "nothing applied by asking")

    def test_yes_adds_the_clause_and_no_memory_line_and_undo_takes_it_back(self):
        [row] = self.run_pass()
        before = self.memory_lines()
        payload = self.end(f"f:{row['ts']}", "do")
        [line] = self.learned()
        self.assertIn("Garden lights (light.garden)", line["clause"])
        self.assertIn("unless they are critical", line["clause"])
        self.assertEqual(self.memory_lines(), before)
        self.assertIn(line["clause"], self.server.settings_store
                      .notify_policy_text())
        # The toast's Undo: the card comes back and the clause goes.
        import undo_store
        entry = undo_store.take(payload["undo"])
        restored, _ = self.server._undo_finding(entry)
        self.assertTrue(restored)
        self.assertEqual(self.learned(), [])
        self.assertIsNotNone(self.server.findings_store.get(row["ts"]))

    def test_no_is_remembered_and_never_asked_again(self):
        [row] = self.run_pass()
        self.end(f"f:{row['ts']}", "wrong")
        self.assertEqual(self.learned(), [])
        self.assertEqual(notify_learn.load()["entity:light.garden"]["answer"],
                         "declined")
        self.assertEqual(self.run_pass(), [])

    def test_a_full_list_refuses_the_yes_before_anything_is_settled(self):
        import settings_store
        from aiohttp import web
        settings_store.save({"notify_policy_learned": [
            {"clause": f"line {i}"} for i in range(settings_store.NOTIFY_LEARNED_MAX)]})
        [row] = self.run_pass()
        with self.assertRaises(web.HTTPConflict):
            self.end(f"f:{row['ts']}", "do")
        self.assertIsNotNone(self.server.findings_store.get(row["ts"]))

    def test_stop_raising_these_is_a_mute_this_reads(self):
        import settings_store
        settings_store.save({"muted_sources": [notify_learn.SOURCE]})
        self.assertEqual(self.run_pass(), [])

    def test_an_unreadable_ledger_is_said_not_read_as_quiet(self):
        path = self.copies("deliveries")[0].DELIVERIES_FILE
        path.unlink()
        path.mkdir()
        self.assertEqual(self.run_pass(), [])
        self.assertIn("could not be read",
                      self.server.NOTIFY_LEARN_STATE["last_error"])


class TestTheSettingsAreValidated(unittest.TestCase):

    def setUp(self):
        import settings_store
        self.settings_store = settings_store
        self.tmp = tempfile.TemporaryDirectory()
        self.old = settings_store.SETTINGS_FILE
        settings_store.SETTINGS_FILE = str(Path(self.tmp.name) / "s.json")

    def tearDown(self):
        self.settings_store.SETTINGS_FILE = self.old
        self.tmp.cleanup()

    def test_the_sentence_is_one_line_and_capped(self):
        s = self.settings_store
        out = s.save({"notify_policy": "wake me\nfor water\x00 " + "x" * 600})
        self.assertNotIn("\n", out["notify_policy"])
        self.assertLessEqual(len(out["notify_policy"]), s.NOTIFY_POLICY_MAX)
        with self.assertRaises(ValueError):
            s.save({"notify_policy": 5})

    def test_learned_lines_are_validated_deduped_and_capped(self):
        s = self.settings_store
        out = s.save({"notify_policy_learned": [{"clause": "a"}, {"clause": "A"}]})
        self.assertEqual(len(out["notify_policy_learned"]), 1)
        with self.assertRaises(ValueError):
            s.save({"notify_policy_learned": [{"clause": ""}]})
        with self.assertRaises(ValueError):
            s.save({"notify_policy_learned": [
                {"clause": f"c{i}"} for i in range(s.NOTIFY_LEARNED_MAX + 1)]})

    def test_an_unreadable_value_is_the_deterministic_path(self):
        s = self.settings_store
        Path(s.SETTINGS_FILE).write_text('{"notify_policy": 7, '
                                         '"notify_policy_learned": "x"}')
        got = s.load()
        self.assertEqual((got["notify_policy"], got["notify_policy_learned"]),
                         ("", []))
        self.assertEqual(s.notify_policy_text(got), "")


if __name__ == "__main__":
    unittest.main()
