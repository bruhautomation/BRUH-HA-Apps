#!/usr/bin/env python3
"""A right answer suppresses while it is still the answer.

The settled ledger was permanent for every ending, and "the analyst would
re-report next week what you answered today" is true of exactly one of
them. Wrong says the report was wrong about this house and stays so. Fixed
and accepted say it was RIGHT, and a real problem comes back — a battery
runs low again, the backup goes stale again — and several check texts are
one sentence for the whole house, so one press blinded a whole check.

Driven over the real store and, for the verification, the real check
(`sys.backup_stale`) over a fixture house, with only the snapshot fetch
replaced. Mutations each test catches:

  permanent fixed        drop `lapse_settled` -> a check that stopped
                         reporting a fixed problem never files it again
  wrong lapses           lapse `ignored` too -> a Wrong comes back
  could-not-look lapses  lapse on a check that did not run -> an answer
                         ends on a pass that never looked
  no recurrence          drop the carry in `_remember_settled` -> nothing
                         says the problem came back, or after how long
  green for ever         drop `_came_back` -> a fixed row its check still
                         reports stays fixed
  premature reopen       ignore `FIX_SETTLE_S` -> a pass in the moment a
                         restart takes reopens what was just fixed
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

import checks  # noqa: E402
import findings_store  # noqa: E402
from test_house_checks import house  # noqa: E402

DAY = 86400.0
CHECK = "sys.backup_stale"
SOURCE = "check:" + CHECK


def never_backed_up() -> dict:
    snap = house()
    snap["supervisor"]["backups"] = []
    return snap


def backup_text() -> str:
    found = checks.system.backup_stale(never_backed_up(), time.time())
    assert found, "the fixture house must report no backups"
    return found[0]["text"]


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self._old = (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
                     findings_store.STATE_FILE)
        findings_store.FINDINGS_FILE = root / "findings.json"
        findings_store.SETTLED_FILE = root / "settled.json"
        findings_store.STATE_FILE = root / "nowhere" / ".brain" / "s.json"

    def tearDown(self):
        (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
         findings_store.STATE_FILE) = self._old
        self.tmp.cleanup()

    def file(self, text: str, source: str = SOURCE) -> dict:
        entry, created = findings_store.add(
            text, severity="warning", source=source, source_title="Backups")
        self.assertTrue(created)
        return entry

    def settle(self, text: str, kind: str, source: str = SOURCE) -> None:
        entry = self.file(text, source)
        findings_store.settle_and_clear(entry["ts"], kind)

    def ledger(self, text: str) -> dict:
        key = findings_store.normalize(text)
        for entry in findings_store._load_settled():
            if entry.get("key") == key:
                return entry
        raise AssertionError(f"no ledger entry for {text!r}")


class TestWhichAnswersLapse(StoreCase):

    def test_fixed_on_a_check_lapses_when_the_check_stops_reporting(self):
        text = "The newest backup is more than a week old"
        self.settle(text, "fixed")
        # Still reported: still suppressed.
        findings_store.clear_resolved({SOURCE},
                                      {findings_store.normalize(text)})
        self.assertIn(findings_store.normalize(text),
                      findings_store.suppressing_keys())
        self.assertIsNone(findings_store.add(text, source=SOURCE)[0])
        # The pass ran and it is gone: the answer ends.
        findings_store.clear_resolved({SOURCE}, set())
        self.assertTrue(self.ledger(text)["lapsed_at"])
        again, created = findings_store.add(text, severity="warning",
                                            source=SOURCE)
        self.assertTrue(created)
        self.assertEqual(again["status"], "open")

    def test_a_check_that_did_not_run_lapses_nothing(self):
        text = "The newest backup is more than a week old"
        self.settle(text, "fixed")
        findings_store.clear_resolved({"check:something.else"}, set())
        self.assertNotIn("lapsed_at", self.ledger(text))
        self.assertIsNone(findings_store.add(text, source=SOURCE)[0])

    def test_wrong_never_lapses(self):
        text = "The hall sensor has not moved for a week"
        self.settle(text, "ignored", source="check:dev.frozen")
        findings_store.clear_resolved({"check:dev.frozen"}, set())
        self.assertNotIn("lapsed_at", self.ledger(text))
        self.assertIsNone(findings_store.add(
            text, source="check:dev.frozen")[0])

    def test_accepted_on_a_check_lapses_like_fixed(self):
        text = "The porch sensor battery is low"
        self.settle(text, "accepted", source="check:dev.battery_low")
        findings_store.clear_resolved({"check:dev.battery_low"}, set())
        self.assertTrue(self.ledger(text)["lapsed_at"])

    def test_a_fixed_report_from_a_model_lapses_on_the_calendar(self):
        text = "The bathroom fan never turns off at night"
        self.settle(text, "fixed", source="analyst")
        key = findings_store.normalize(text)
        now = time.time()
        self.assertIn(key, findings_store.suppressing_keys(now))
        later = now + (findings_store.FIXED_LAPSE_DAYS + 1) * DAY
        self.assertNotIn(key, findings_store.suppressing_keys(later))

    def test_an_accepted_chore_from_a_model_waits_for_the_chore(self):
        text = "Descale the kettle"
        self.settle(text, "accepted", source="analyst")
        later = time.time() + 400 * DAY
        self.assertIn(findings_store.normalize(text),
                      findings_store.suppressing_keys(later))

    def test_coming_back_is_counted_and_dated(self):
        text = "The newest backup is more than a week old"
        self.settle(text, "fixed")
        first = self.ledger(text)["ts"]
        findings_store.clear_resolved({SOURCE}, set())
        self.settle(text, "fixed")
        entry = self.ledger(text)
        self.assertEqual(entry["recurred"], 1)
        self.assertEqual(entry["previous_at"], first)
        self.assertNotIn("lapsed_at", entry)


class TestAFixThatDidNotHold(StoreCase):

    def fixed_row(self, text: str, ended_ago: float, source: str = SOURCE):
        entry = self.file(text, source)
        findings_store.set_status(entry["ts"], "fixed", result="Done")
        findings_store.set_fix_window(entry["ts"], started=time.time() - 600,
                                      ended=time.time() - ended_ago)
        return entry["ts"]

    def test_still_reported_after_the_settle_reopens_the_row(self):
        text = "The newest backup is more than a week old"
        ts = self.fixed_row(text, ended_ago=findings_store.FIX_SETTLE_S + 30)
        findings_store.clear_resolved({SOURCE},
                                      {findings_store.normalize(text)})
        row = findings_store.get(ts)
        self.assertEqual(row["status"], "open")
        self.assertTrue(row["came_back"])
        self.assertEqual(row["result"], findings_store.CAME_BACK_RESULT)

    def test_inside_the_settle_it_is_left_alone(self):
        text = "The newest backup is more than a week old"
        ts = self.fixed_row(text, ended_ago=5)
        findings_store.clear_resolved({SOURCE},
                                      {findings_store.normalize(text)})
        self.assertEqual(findings_store.get(ts)["status"], "fixed")

    def test_not_reported_any_more_stays_fixed(self):
        text = "The newest backup is more than a week old"
        ts = self.fixed_row(text, ended_ago=findings_store.FIX_SETTLE_S + 30)
        findings_store.clear_resolved({SOURCE}, set())
        self.assertEqual(findings_store.get(ts)["status"], "fixed")

    def test_a_models_fixed_row_is_never_reopened_by_a_check(self):
        text = "The newest backup is more than a week old"
        ts = self.fixed_row(text, ended_ago=findings_store.FIX_SETTLE_S + 30,
                            source="analyst")
        findings_store.clear_resolved({"analyst"},
                                      {findings_store.normalize(text)})
        self.assertEqual(findings_store.get(ts)["status"], "fixed")


class TestTheFixIsVerifiedByItsOwnCheck(StoreCase):
    """`server._verify_fix`, with the real check over a fixture house."""

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

    def fixed(self, text: str) -> int:
        entry = self.file(text)
        findings_store.set_status(entry["ts"], "fixed", result="Done")
        findings_store.set_fix_window(
            entry["ts"], started=time.time() - 900,
            ended=time.time() - findings_store.FIX_SETTLE_S - 60)
        return entry["ts"]

    def test_the_check_still_seeing_it_reopens_the_row(self):
        ts = self.fixed(backup_text())
        out = asyncio.run(self.server._verify_fix(ts))
        self.assertEqual(out, {"checked": True, "came_back": True})
        self.assertEqual(findings_store.get(ts)["status"], "open")

    def test_the_check_not_seeing_it_leaves_it_fixed(self):
        ts = self.fixed(backup_text())
        self.snap["supervisor"]["backups"] = [
            {"slug": "new", "name": "Tonight",
             "date": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())}]
        out = asyncio.run(self.server._verify_fix(ts))
        self.assertEqual(out, {"checked": True, "came_back": False})
        self.assertEqual(findings_store.get(ts)["status"], "fixed")

    def test_a_check_that_could_not_look_answers_nothing(self):
        ts = self.fixed(backup_text())
        self.snap["available"] = dict(self.snap["available"],
                                      supervisor=False)
        self.snap["supervisor"] = None
        out = asyncio.run(self.server._verify_fix(ts))
        self.assertFalse(out["checked"])
        self.assertEqual(findings_store.get(ts)["status"], "fixed")

    def test_a_models_row_is_not_verified(self):
        entry = self.file("The bathroom fan never turns off", source="analyst")
        findings_store.set_status(entry["ts"], "fixed", result="Done")
        out = asyncio.run(self.server._verify_fix(entry["ts"]))
        self.assertEqual(out["checked"], False)


if __name__ == "__main__":
    unittest.main()
