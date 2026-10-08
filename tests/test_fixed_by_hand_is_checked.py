#!/usr/bin/env python3
"""A person's "I've fixed it" on a check's row is checked by that check.

The settled ledger kept a `fixed` answer from a house check suppressing
the re-report for as long as the check went on reporting it — the only
thing that ended it (`lapse_settled`) was the check STOPPING. So a fix
that did not hold was swallowed on every pass ("you said you had fixed
it", ten times a day in the decision trail) and the card never came
back. A finished chore already comes back this way after
`todo_store.CHORE_SETTLE_S`; a finding marked fixed by hand now does too,
by its answer lapsing so the next pass files it again as a recurrence.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import findings_store as fs  # noqa: E402
import todo_store  # noqa: E402

ROW = {"text": "The garage sensor has not reported for a day",
       "severity": "warning", "entity_id": "sensor.garage",
       "source": "check:dev.unavailable"}
SOURCES = {"check:dev.unavailable"}


class TestAFixThatDidNotHoldComesBack(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for mod, name, value in (
                (fs, "FINDINGS_FILE", root / "findings.json"),
                (fs, "INBOX_DIR", root / "inbox"),
                (fs, "SETTLED_FILE", root / "settled.json"),
                (fs, "STATE_FILE", root / "no" / "where" / "f.json"),
                (todo_store, "TODO_FILE", root / "todo.json"),
                (todo_store, "STATE_FILE", root / "no" / "where" / "t.json")):
            p = mock.patch.object(mod, name, value)
            p.start()
            self.addCleanup(p.stop)
        [row] = fs.add_many([dict(ROW)])
        fs.settle_and_clear(row["ts"], "fixed")
        self.key = fs.normalize(ROW["text"])

    def age_the_answer(self, seconds):
        data = json.loads(fs.SETTLED_FILE.read_text(encoding="utf-8"))
        for entry in data["settled"]:
            entry["ts"] = int(entry["ts"]) - seconds
        fs.SETTLED_FILE.write_text(json.dumps(data), encoding="utf-8")

    def test_still_reported_past_the_settling_time_files_again(self):
        self.age_the_answer(todo_store.CHORE_SETTLE_S + 60)
        fs.clear_resolved(SOURCES, {self.key})
        again = fs.add_many([dict(ROW)])
        self.assertEqual(len(again), 1)
        self.assertEqual(again[0]["text"], ROW["text"])

    def test_inside_the_settling_time_it_is_still_the_answer(self):
        fs.clear_resolved(SOURCES, {self.key})
        self.assertEqual(fs.add_many([dict(ROW)]), [])

    def test_a_check_that_did_not_run_calls_nothing_back(self):
        self.age_the_answer(todo_store.CHORE_SETTLE_S + 60)
        fs.clear_resolved(set(), {self.key})
        self.assertEqual(fs.add_many([dict(ROW)]), [])

    def test_wrong_is_never_called_back(self):
        fs.unsettle(self.key)
        [row] = fs.add_many([dict(ROW)])
        fs.settle_and_clear(row["ts"], "ignored")
        self.age_the_answer(todo_store.CHORE_SETTLE_S + 60)
        fs.clear_resolved(SOURCES, {self.key})
        self.assertEqual(fs.add_many([dict(ROW)]), [])


if __name__ == "__main__":
    unittest.main()
