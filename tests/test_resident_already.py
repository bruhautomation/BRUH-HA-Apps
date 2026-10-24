#!/usr/bin/env python3
"""A finding whose own look says it is already answered is not shown.

Seen on a house: "this automation has never fired" on the list under a look
saying the household had marked the report wrong before; a probe's row
under "the same faulty probe you already have a card for"; house-book
questions under "the house already answers this". In every case the look
had said the row was not news and the row was on screen anyway — because
the look answered `watch`/`investigate` with that reason (which shows a row
once its investigation does not run), or answered `ignore` about a row the
stale sweep had already shown (which a late verdict leaves open).

So the first look's contract says it in a word rather than a sentence
(`already`: `answered`, `marked_wrong`, `duplicate`), and a row a look says
that about is HELD — even one silence already showed, as long as nobody has
touched it. A row a person put back, a reply somebody typed under it, and a
safety floor all still win.
"""

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "brain"
                       / "panel"))

import resident  # noqa: E402
from test_resident_loop import LoopCase, reply  # noqa: E402


def open_ts(srv) -> set[int]:
    """What `get_findings(status='open')` lists: the open rows."""
    return {f["ts"] for f in srv.findings_store.list_all()
            if f["status"] == "open"}


class TestTheContractSaysItInAWord(unittest.TestCase):
    def test_the_schema_offers_the_word(self):
        item = resident.FIRST_LOOK_SCHEMA["properties"]["verdicts"]["items"]
        self.assertEqual(set(item["properties"]["already"]["enum"]),
                         {"", *resident.ALREADY})
        self.assertNotIn("already", item["required"])

    def test_already_turns_any_verdict_into_ignore(self):
        out = resident.parse_first_look({"verdicts": [
            {"id": 1, "verdict": "investigate", "already": "marked_wrong",
             "why": "The household marked this report wrong before."}]}, 1,
            [{"kind": "check", "subject": "automation.porch"}])
        self.assertEqual(out[1]["verdict"], "ignore")
        self.assertEqual(out[1]["already"], "marked_wrong")

    def test_a_safety_floor_outranks_already(self):
        out = resident.parse_first_look({"verdicts": [
            {"id": 1, "verdict": "ignore", "already": "duplicate",
             "why": "Same as the other leak card."}]}, 1,
            [{"kind": "state", "subject": "binary_sensor.leak",
              "safety": True}])
        self.assertNotEqual(out[1]["verdict"], "ignore")
        self.assertNotIn("already", out[1])

    def test_an_invented_word_is_dropped(self):
        out = resident.parse_first_look({"verdicts": [
            {"id": 1, "verdict": "watch", "already": "probably",
             "why": "One reading is not enough."}]}, 1,
            [{"kind": "check", "subject": "sensor.x"}])
        self.assertEqual(out[1]["verdict"], "watch")
        self.assertNotIn("already", out[1])


class TestARowTheLookCallsAnsweredIsHeld(LoopCase):
    def test_a_fresh_row_marked_wrong_before_is_held_not_investigated(self):
        srv = self.server
        row = self.file_check_row()
        self.looks.append(reply([{
            "id": 1, "verdict": "investigate", "already": "marked_wrong",
            "why": "The household marked this report wrong before."}]))
        out = self.tick(time.time())
        self.assertTrue(out["looked"], out)
        self.assertEqual(srv.findings_store.get(row["ts"])["status"], "held")
        self.assertNotIn(row["ts"], open_ts(srv))
        self.assertEqual(self.analyst_calls, [])

    def test_a_row_silence_showed_is_held_when_the_look_says_duplicate(self):
        import engine
        srv = self.server
        engine.get_auth = lambda: None
        now = time.time()
        row = self.file_check_row()
        self.tick(now)
        later = now + srv.triage.STALE_S + 60
        self.tick(later)
        self.assertIn(row["ts"], open_ts(srv))
        engine.get_auth = lambda: {"type": "oauth", "value": "x"}
        self.looks.append(reply([{
            "id": 1, "verdict": "ignore", "already": "duplicate",
            "why": "The same faulty probe already has a card."}]))
        self.tick(later + srv.RESIDENT_LOOK_S + 1)
        fresh = srv.findings_store.get(row["ts"])
        self.assertEqual(fresh["status"], "held")
        self.assertNotIn(row["ts"], open_ts(srv))

    def test_a_row_somebody_replied_under_stays_where_it_is(self):
        import engine
        srv = self.server
        engine.get_auth = lambda: None
        now = time.time()
        row = self.file_check_row()
        self.tick(now)
        later = now + srv.triage.STALE_S + 60
        self.tick(later)
        srv.findings_store.append_thread(row["ts"], "you", "look at this one")
        engine.get_auth = lambda: {"type": "oauth", "value": "x"}
        self.looks.append(reply([{
            "id": 1, "verdict": "ignore", "already": "answered",
            "why": "The house already answers this."}]))
        self.tick(later + srv.RESIDENT_LOOK_S + 1)
        self.assertEqual(srv.findings_store.get(row["ts"])["status"], "open")

    def test_a_row_a_person_put_back_is_never_taken_off(self):
        srv = self.server
        row = self.file_check_row()
        srv.findings_store.record_triage(
            {row["ts"]: ("held", "a cupboard")}, "look-0")
        srv.findings_store.elevate(row["ts"])
        srv.findings_store.record_triage(
            {row["ts"]: ("held", "already answered", True)}, "look-1")
        self.assertEqual(srv.findings_store.get(row["ts"])["status"], "open")

    def test_a_late_ignore_without_the_word_still_keeps_the_row(self):
        # The deliberate rule stands: a row already on screen never
        # vanishes into a run on an ordinary `ignore`.
        import engine
        srv = self.server
        engine.get_auth = lambda: None
        now = time.time()
        row = self.file_check_row()
        self.tick(now)
        later = now + srv.triage.STALE_S + 60
        self.tick(later)
        engine.get_auth = lambda: {"type": "oauth", "value": "x"}
        self.looks.append(reply([{"id": 1, "verdict": "ignore",
                                  "why": "it moved twice last month"}]))
        self.tick(later + srv.RESIDENT_LOOK_S + 1)
        self.assertEqual(srv.findings_store.get(row["ts"])["status"], "open")


if __name__ == "__main__":
    unittest.main()
