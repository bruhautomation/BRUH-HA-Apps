#!/usr/bin/env python3
"""An answer about a thing that is down holds until the thing changes.

"Expected, those are unplugged" and "I don't think this is true any more"
were kept as free text while the same cards came back: an integration that
did not set up (one answer for an entry, kept against that entry), and a
plug that is out with scenes still aimed at it (kept against the plug while
it stays out, and the claim that scenes still use it read again from the
house as it is before the card is filed).

The second examples are ones the reports never named: a different
integration entry that stays asked about, an entry that fails again after
the answer, and a script (not a scene) aimed at a plug that came back.
"""

import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import findings_store  # noqa: E402
import sre  # noqa: E402
from checks import system  # noqa: E402
from test_house_checks import NOW, house  # noqa: E402
from test_sre import NOW as SRE_NOW  # noqa: E402
from test_sre_sources import MISSING, log_row, missing_house  # noqa: E402

DAY = 86400


def entry(eid, title, since):
    return {"entry_id": eid, "domain": title.lower().replace(" ", "_"),
            "title": title, "state": "setup_retry", "source": "user",
            "reason": "Cannot connect to host", "failing_since": since}


class TestSetupFailureAnswerIsKeptOnTheEntry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = findings_store.SETTLED_FILE
        findings_store.SETTLED_FILE = Path(self.tmp.name) / "settled.json"

    def tearDown(self):
        findings_store.SETTLED_FILE = self.old
        self.tmp.cleanup()

    def snap(self, *entries):
        snap = house(config_entries=list(entries))
        snap["answers"] = findings_store.answered_checks()
        return snap

    def rows(self, *entries):
        return system.entry_failed(self.snap(*entries), NOW)

    def answer(self, row, when):
        shaped = {**row, "source": "check:sys.entry_failed"}
        findings_store._remember_settled(
            shaped, "ignored", when=when,
            note="expected, those are unplugged and not in use")

    def test_the_row_names_its_entries(self):
        [row] = self.rows(entry("e1", "Garage cam", NOW - 3 * DAY))
        self.assertEqual(row["items"], ["entry:e1"])

    def test_the_answered_entry_stays_quiet_the_other_is_still_asked(self):
        mine = entry("e1", "Garage cam", NOW - 3 * DAY)
        [row] = self.rows(mine)
        self.answer(row, NOW - DAY)
        self.assertEqual(self.rows(mine), [])
        other = entry("e2", "Attic hub", NOW - 2 * DAY)
        [again] = self.rows(mine, other)
        self.assertEqual(again["items"], ["entry:e2"])
        self.assertIn("Attic hub", again["detail"])
        self.assertNotIn("Garage cam", again["detail"])

    def test_an_entry_that_loads_and_fails_again_is_news(self):
        first = entry("e1", "Garage cam", NOW - 5 * DAY)
        [row] = self.rows(first)
        self.answer(row, NOW - 3 * DAY)
        self.assertEqual(self.rows(first), [])
        # it loaded, then failed again after the answer was given
        again = entry("e1", "Garage cam", NOW - 2 * DAY)
        self.assertEqual(len(self.rows(again)), 1)

    def test_answering_a_second_entry_keeps_the_first_answered(self):
        a = entry("e1", "Garage cam", NOW - 3 * DAY)
        [row] = self.rows(a)
        self.answer(row, NOW - DAY)
        b = entry("e2", "Attic hub", NOW - 3 * DAY)
        [row2] = self.rows(a, b)
        self.answer(row2, NOW - 3600)
        self.assertEqual(self.rows(a, b), [])


class TestUnpluggedPlugAnswer(unittest.TestCase):
    def test_a_snoozed_or_answered_plug_is_held_while_it_stays_down(self):
        states = {"switch.porch_heater": {"state": "unavailable"},
                  "switch.shed_lamp": {"state": "on"}}
        rows = [{"source": sre.SOURCE, "entity_id": "switch.porch_heater",
                 "snoozed_until": SRE_NOW + DAY}]
        self.assertEqual(sre.answered_down(rows, [], states, SRE_NOW),
                         {"switch.porch_heater"})
        ignored = [{"source": sre.SOURCE, "entity_id": "switch.porch_heater",
                    "items": ["switch.shed_lamp"]}]
        # the lamp is up: that answer is spent, the plug's still holds
        self.assertEqual(sre.answered_down([], ignored, states, SRE_NOW),
                         {"switch.porch_heater"})
        # it came back: nothing is held
        states["switch.porch_heater"]["state"] = "on"
        self.assertEqual(sre.answered_down([], ignored, states, SRE_NOW), set())
        # nothing read, nothing guessed; another producer's rows do not count
        self.assertEqual(sre.answered_down(rows, [], {}, SRE_NOW), set())
        other = [{"source": "check:dev.unavailable",
                  "entity_id": "switch.porch_heater"}]
        states["switch.porch_heater"]["state"] = "unavailable"
        self.assertEqual(sre.answered_down([], other, states, SRE_NOW), set())

    def test_an_answered_plug_leaves_the_digest(self):
        dig = sre.digest(
            missing_house([log_row(MISSING, "homeassistant.helpers.service")]),
            SRE_NOW, set_aside={"switch.porch_heater"})
        self.assertFalse(any(r["kind"] == "log" for r in dig["records"]))


class TestTheScenesClaimIsReadAgain(unittest.TestCase):
    def judged(self, state):
        h = missing_house([log_row(MISSING, "homeassistant.helpers.service")])
        h["states"]["switch.porch_heater"]["state"] = state
        dig = sre.digest(h, SRE_NOW)
        recs = [r["id"] for r in dig["records"] if r["kind"] == "log"]
        parsed = sre.parse_causes({"causes": [{
            "title": "Porch heater is offline", "records": recs[:1],
            "detail": "x", "fix": "Bring it back."}]}, dig)
        return sre.hold_transient(parsed["causes"], dig, SRE_NOW)

    def test_still_down_is_kept(self):
        kept, held = self.judged("unavailable")
        self.assertEqual((len(kept), len(held)), (1, 0))

    def test_back_is_dropped_before_it_is_shown(self):
        kept, held = self.judged("off")
        self.assertEqual((len(kept), len(held)), (0, 1))
        self.assertIn("answers now", held[0]["reason"])


if __name__ == "__main__":
    unittest.main()
