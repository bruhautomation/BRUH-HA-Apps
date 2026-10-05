#!/usr/bin/env python3
"""A chore marked done is done when the check that filed it says so.

"Kid's Bathroom ZSE44 battery 0%" was ticked off twelve days before the
walkthrough and read 0% that day; "An integration did not finish setting
up (EPSON…)" was ticked off while the integration sat in setup_retry. A
tick is somebody's word, and the check that filed the chore is the one
reading that can confirm it — so a check that RAN and still reports the
problem, past `todo_store.CHORE_SETTLE_S`, puts the chore back on the list
saying so, and the settled answer goes back to `accepted`.

Driven over the real stores and, for the delayed verification, the real
check (`sys.backup_stale`) over a fixture house with only the snapshot
fetch replaced — `test_settled_lapse`'s harness.
"""
import asyncio
import importlib
import sys
import tempfile
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import findings_store  # noqa: E402
import todo_store  # noqa: E402
from test_settled_lapse import SOURCE, backup_text, never_backed_up  # noqa: E402


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self._old = (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
                     findings_store.STATE_FILE, todo_store.TODO_FILE,
                     todo_store.STATE_FILE)
        findings_store.FINDINGS_FILE = root / "findings.json"
        findings_store.SETTLED_FILE = root / "settled.json"
        findings_store.STATE_FILE = root / "nowhere" / ".brain" / "s.json"
        todo_store.TODO_FILE = root / "todo.json"
        todo_store.STATE_FILE = root / "nowhere" / ".brain" / "t.json"

    def tearDown(self):
        (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
         findings_store.STATE_FILE, todo_store.TODO_FILE,
         todo_store.STATE_FILE) = self._old
        self.tmp.cleanup()

    def done_chore(self, text: str, done_ago: float,
                   source: str = SOURCE) -> dict:
        """A finding moved to the list and ticked off ``done_ago`` seconds
        ago — the store states the real flow leaves behind."""
        key = findings_store.normalize(text)
        item = todo_store.add(text, origin="finding", source=source,
                              source_title="Backups", finding_key=key)
        findings_store.remember_answer(key, text, "accepted", source=source)
        todo_store.complete(item["id"], now=time.time() - done_ago)
        findings_store.remember_answer(key, text, "fixed", source=source)
        return item

    def ledger_kind(self, text: str) -> str:
        key = findings_store.normalize(text)
        return next(e["kind"] for e in findings_store._load_settled()
                    if e["key"] == key)


class TestThePassReopensIt(StoreCase):

    def test_a_check_still_reporting_it_puts_it_back_saying_so(self):
        text = backup_text()
        item = self.done_chore(text, todo_store.CHORE_SETTLE_S + 60)
        findings_store.clear_resolved({SOURCE},
                                      {findings_store.normalize(text)})
        back = todo_store.get(item["id"])
        self.assertEqual(back["status"], "open")
        self.assertEqual(back["note"], todo_store.CAME_BACK_NOTE)
        self.assertTrue(back["came_back"])
        # The work is waiting again, so the answer is `accepted` again —
        # which still suppresses a re-report of the same row.
        self.assertEqual(self.ledger_kind(text), "accepted")
        self.assertIn(findings_store.normalize(text),
                      findings_store.suppressing_keys())

    def test_inside_the_settling_time_it_is_left_done(self):
        text = backup_text()
        item = self.done_chore(text, 60)
        findings_store.clear_resolved({SOURCE},
                                      {findings_store.normalize(text)})
        self.assertEqual(todo_store.get(item["id"])["status"], "done")
        self.assertEqual(self.ledger_kind(text), "fixed")

    def test_a_check_that_no_longer_reports_it_leaves_it_done(self):
        text = backup_text()
        item = self.done_chore(text, todo_store.CHORE_SETTLE_S + 60)
        findings_store.clear_resolved({SOURCE}, set())
        self.assertEqual(todo_store.get(item["id"])["status"], "done")

    def test_a_check_that_did_not_run_reopens_nothing(self):
        text = backup_text()
        item = self.done_chore(text, todo_store.CHORE_SETTLE_S + 60)
        findings_store.clear_resolved({"check:dev.frozen"},
                                      {findings_store.normalize(text)})
        self.assertEqual(todo_store.get(item["id"])["status"], "done")

    def test_a_chore_from_a_models_report_has_no_rule_to_ask(self):
        text = "The bathroom fan never turns off"
        item = self.done_chore(text, todo_store.CHORE_SETTLE_S + 60,
                               source="climate")
        findings_store.clear_resolved({"climate"},
                                      {findings_store.normalize(text)})
        self.assertEqual(todo_store.get(item["id"])["status"], "done")


class TestTheDelayedVerification(StoreCase):
    """`server._verify_chore`, with the real check over a fixture house."""

    def setUp(self):
        super().setUp()
        self.server = importlib.import_module("server")
        self.snap = never_backed_up()

        async def collect(now):
            return dict(self.snap, now=now)

        self._collect = self.server.checks.snapshot.collect
        self.server.checks.snapshot.collect = collect
        self.addCleanup(setattr, self.server.checks.snapshot, "collect",
                        self._collect)

    def test_the_check_still_seeing_it_reopens_the_chore(self):
        item = self.done_chore(backup_text(), todo_store.CHORE_SETTLE_S + 60)
        out = asyncio.run(self.server._verify_chore(item["id"]))
        self.assertEqual(out, {"checked": True, "came_back": True})
        self.assertEqual(todo_store.get(item["id"])["status"], "open")

    def test_the_check_not_seeing_it_leaves_it_done(self):
        item = self.done_chore(backup_text(), todo_store.CHORE_SETTLE_S + 60)
        self.snap["supervisor"]["backups"] = [
            {"slug": "new", "name": "Tonight",
             "date": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())}]
        out = asyncio.run(self.server._verify_chore(item["id"]))
        self.assertEqual(out, {"checked": True, "came_back": False})
        self.assertEqual(todo_store.get(item["id"])["status"], "done")

    def test_completing_a_chore_from_a_check_schedules_the_look(self):
        """`_complete_todo` hands the finished item to the verifier."""
        seen = []
        orig = self.server._spawn_chore_verification
        self.server._spawn_chore_verification = seen.append
        self.addCleanup(setattr, self.server, "_spawn_chore_verification",
                        orig)

        async def nothing(*a, **k):
            return None
        orig_submit = self.server._submit_memory
        self.server._submit_memory = nothing
        self.addCleanup(setattr, self.server, "_submit_memory", orig_submit)

        text = backup_text()
        key = findings_store.normalize(text)
        item = todo_store.add(text, origin="finding", source=SOURCE,
                              finding_key=key)
        done, _fact = asyncio.run(self.server._complete_todo(item, ""))
        self.assertEqual(done["status"], "done")
        self.assertEqual([i["id"] for i in seen], [item["id"]])


if __name__ == "__main__":
    unittest.main()
