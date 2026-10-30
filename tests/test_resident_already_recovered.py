#!/usr/bin/env python3
"""A finding whose own look says it is over, or ordinary, is set aside (#537).

Seen on a house: "can't reach the TV's cast service" on the list under a look
saying the TV had been switched off since the evening; "these plugs dropped
off" under a look saying they were all connected again. The look had said
there was nothing to do and the card was on screen anyway, with the look's
own sentence contradicting it — because the look's `already` word only had
room for "answered", "marked wrong" and "duplicate", and "it has already come
back" or "that is just the device being off" are neither.

So the word has two more values: `recovered` (the problem has already ended)
and `explained` (what the row reports is the ordinary state of a thing, like
a device that is switched off). Either sets the row aside exactly as the
other words do — a safety floor and a person's own touch still win.

The rows are invented: a cast speaker in a den and a pair of garden plugs.
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


class TestTheWordCanSayItIsOver(unittest.TestCase):
    def test_recovered_and_explained_are_words_the_look_may_give(self):
        for word in ("recovered", "explained"):
            out = resident.parse_first_look({"verdicts": [
                {"id": 1, "verdict": "watch", "already": word,
                 "why": "The garden plugs are both connected again."}]}, 1,
                [{"kind": "check", "subject": "switch.garden_plug"}])
            self.assertEqual(out[1]["verdict"], "ignore", word)
            self.assertEqual(out[1]["already"], word)

    def test_the_prompt_tells_the_look_when_to_use_them(self):
        text = resident.FIRST_LOOK_SYSTEM
        self.assertIn('"recovered"', text)
        self.assertIn('"explained"', text)

    def test_a_safety_floor_still_outranks_recovered(self):
        out = resident.parse_first_look({"verdicts": [
            {"id": 1, "verdict": "ignore", "already": "recovered",
             "why": "The sensor is dry again."}]}, 1,
            [{"kind": "state", "subject": "binary_sensor.sink_leak",
              "safety": True}])
        self.assertNotEqual(out[1]["verdict"], "ignore")


class TestARowTheLookCallsOverIsHeld(LoopCase):
    def setUp(self):
        super().setUp()
        import decision_trail
        old = decision_trail.TRAIL_FILE
        decision_trail.TRAIL_FILE = str(Path(self.tmp.name) / "trail.jsonl")
        self.addCleanup(setattr, decision_trail, "TRAIL_FILE", old)

    def _shown_then_looked(self, answer: dict) -> dict:
        """A row silence showed, then a look's answer about it."""
        import engine
        srv = self.server
        engine.get_auth = lambda: None
        now = time.time()
        row = self.file_check_row(
            text="The den speaker's cast service cannot be reached",
            entity_id="media_player.den_speaker",
            source="check:net.unreachable", source_title="Unreachable")
        self.tick(now)
        later = now + srv.triage.STALE_S + 60
        self.tick(later)
        self.assertEqual(srv.findings_store.get(row["ts"])["status"], "open")
        engine.get_auth = lambda: {"type": "oauth", "value": "x"}
        self.looks.append(reply([{"id": 1, **answer}]))
        self.tick(later + srv.RESIDENT_LOOK_S + 1)
        return srv.findings_store.get(row["ts"])

    def test_explained_holds_a_row_already_on_screen(self):
        row = self._shown_then_looked({
            "verdict": "watch", "already": "explained",
            "why": "The den speaker has been switched off since the evening."})
        self.assertEqual(row["status"], "held")

    def test_recovered_holds_a_row_already_on_screen(self):
        row = self._shown_then_looked({
            "verdict": "ignore", "already": "recovered",
            "why": "The den speaker answered again an hour later."})
        self.assertEqual(row["status"], "held")

    def test_a_fresh_recovered_row_is_held_not_investigated(self):
        srv = self.server
        row = self.file_check_row()
        self.looks.append(reply([{
            "id": 1, "verdict": "investigate", "already": "recovered",
            "why": "The pantry contact changed again this morning."}]))
        self.tick(time.time())
        self.assertEqual(srv.findings_store.get(row["ts"])["status"], "held")
        self.assertEqual(self.analyst_calls, [])


if __name__ == "__main__":
    unittest.main()
