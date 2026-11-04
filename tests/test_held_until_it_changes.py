#!/usr/bin/env python3
""""Don't remind me" on a check's card holds it until the fact changes.

Reports #602, #694 and #698: a free-text "stop bringing up …", "I am aware,
don't bring this up again" or "it's on my to do list, stop reminding me" on
a network, integrations or battery card was kept as words, or slept for a
month, and the same card came back about a thing that had not changed. Now
the answer holds the card for that thing — no clock — and it returns only
when the check's own report about it changes: it got worse, it names
something new, or it went away for long enough to have been over. The card
and the decision trail say which answer muted it, and replaying the answer
or the check's report sends nothing.

The examples are made up: a loft plug as the Zigbee router, a Matter setup
with nothing on it, and a shed sensor's battery.
"""

import asyncio
import json
import sys
import time
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "brain" / "panel"))
sys.path.insert(0, str(TESTS_DIR))

import corrections  # noqa: E402
import decision_trail  # noqa: E402
import findings_store  # noqa: E402
import triage  # noqa: E402
from test_scoped_corrections import RouteCase  # noqa: E402

DAY = 86400

ROUTER = {"text": "Loft plug is a Zigbee router with a weak link",
          "detail": "Loft plug's link quality is 31 out of 255 (under 40 is "
                    "weak).",
          "fix": "Move it or the coordinator closer.", "severity": "warning",
          "source": "check:net.zigbee_weak", "entity_id": "switch.loft_plug",
          "fixable": False}
MATTER = {"text": "Matter is set up with no devices on it",
          "detail": "The Matter integration is installed and has no devices.",
          "fix": "Remove the Matter integration if nothing will use it.",
          "severity": "info", "source": "check:net.matter_empty",
          "fixable": False}
BATTERY = {"text": "Shed sensor battery is low",
           "detail": "Shed sensor battery is at 14%.",
           "fix": "Replace the battery.", "severity": "warning",
           "source": "check:dev.battery_low",
           "entity_id": "sensor.shed_sensor_battery", "fixable": False}


class HoldCase(RouteCase):
    def setUp(self):
        super().setUp()
        decision_trail.clear_memory()

    def file(self, row):
        created = findings_store.add_many(triage.gate([dict(row)]))
        self.assertEqual(len(created), 1)
        return created[0]

    def answer(self, row, said):
        async def body(client):
            res = await client.post(f"/api/finding/{row['ts']}/wrong",
                                    json={"note": said})
            self.assertEqual(res.status, 200)
            await asyncio.gather(*list(self.server._CORRECTION_TASKS))
            return await res.json()
        return self.drive(body)

    def live(self, row):
        """On screen: the row is there and not asleep."""
        shown = findings_store.get(row["ts"])
        return shown is not None and not int(shown.get("snoozed_until") or 0)

    def a_pass(self, rows, reported=True):
        """One checks pass: file, refresh, clear — what `run_checks` does."""
        rows = [dict(r) for r in rows] if reported else []
        created = findings_store.add_many(triage.gate(rows))
        findings_store.refresh_details(rows)
        sources = {r["source"] for r in (ROUTER, MATTER, BATTERY)}
        findings_store.clear_resolved(
            sources, {findings_store.normalize(r["text"]) for r in rows})
        return created


class TestTheWordsAreRead(unittest.TestCase):
    def test_every_way_the_house_said_it(self):
        for said in ("Don't remind me",
                     "stop bringing up wifi dropping out issues",
                     "I am aware, don't bring this up again",
                     "It's on my to do list, stop reminding me",
                     "please stop mentioning the matter setup",
                     "quit flagging the camera retention",
                     "stop telling me about the shed battery",
                     "don't bring up the router again"):
            self.assertTrue(corrections.deferral(said), said)

    def test_everyday_sentences_are_not_a_deferral(self):
        for said in ("this sensor is broken", "I need to fix this light",
                     "the automation should stop raising the blinds at 6",
                     "it should stop when the door opens",
                     "I don't need a reminder", "normal for this sensor",
                     "they don't notify me when the door opens",
                     "don't tell me it's offline, it's reporting wrong",
                     "I'm aware, fix it now", "Don't tell me what to do",
                     ""):
            self.assertFalse(corrections.deferral(said), said)


class TestHeldForThatSubject(HoldCase):
    def test_no_clock_ends_it(self):
        for template in (ROUTER, MATTER, BATTERY):
            row = self.file(template)
            self.answer(row, "I am aware, don't bring this up again")
            kept = findings_store.get(row["ts"])
            self.assertIsNotNone(kept)
            self.assertEqual(self.rules(), [])
            self.assertFalse(self.live(row))
            # Not a month: the hold is not a period.
            self.assertGreater(int(kept["snoozed_until"]),
                               time.time() + 365 * DAY)
            self.assertEqual(kept["hold"]["said"],
                             "I am aware, don't bring this up again")

    def test_a_replay_files_nothing_and_rings_nothing(self):
        row = self.file(ROUTER)
        self.answer(row, "stop bringing up wifi dropping out issues")
        for _ in range(4):
            self.assertEqual(self.a_pass([ROUTER]), [])
        # the same words again on the same card
        self.answer(row, "stop bringing up wifi dropping out issues")
        self.assertEqual(self.a_pass([ROUTER]), [])
        self.assertFalse(self.live(row))
        self.assertEqual(len([f for f in findings_store._load()
                              if f["text"] == ROUTER["text"]]), 1)

    def test_a_pass_that_misses_it_once_does_not_end_it(self):
        row = self.file(ROUTER)
        self.answer(row, "Don't remind me")
        self.a_pass([ROUTER], reported=False)
        self.assertIsNotNone(findings_store.get(row["ts"]))
        self.assertEqual(self.a_pass([ROUTER]), [])
        self.assertFalse(self.live(row))

    def test_gone_long_enough_is_over_and_a_return_is_news(self):
        row = self.file(MATTER)
        self.answer(row, "Don't remind me")
        self.a_pass([MATTER], reported=False)
        items = findings_store._load()
        for entry in items:
            if entry["ts"] == row["ts"]:
                entry["snooze_hold"]["absent_since"] = int(
                    time.time() - findings_store.HOLD_ABSENT_S - 60)
        findings_store._write(items)
        self.a_pass([MATTER], reported=False)
        self.assertIsNone(findings_store.get(row["ts"]))
        self.assertEqual(len(self.a_pass([MATTER])), 1)

    def test_a_worse_report_brings_it_back_and_says_which_answer(self):
        row = self.file(ROUTER)
        self.answer(row, "Don't remind me")
        worse = {**ROUTER, "severity": "serious"}
        self.a_pass([worse])
        self.assertTrue(self.live(row))
        shown = findings_store.get(row["ts"])
        self.assertIn("Don't remind me", shown["detail"])
        self.assertNotIn("hold", shown)

    def test_a_report_naming_something_new_brings_it_back(self):
        row = self.file(MATTER)
        self.answer(row, "Don't remind me")
        moved = {**MATTER, "detail": "The Matter integration is installed "
                                     "and the Thread border router Kitchen "
                                     "hub has left it."}
        self.a_pass([moved])
        self.assertTrue(self.live(row))

    def test_the_same_report_reworded_by_a_number_stays_held(self):
        row = self.file(ROUTER)
        self.answer(row, "Don't remind me")
        self.a_pass([{**ROUTER, "detail": ROUTER["detail"].replace(
            "31", "29")}])
        self.assertFalse(self.live(row))

    def test_the_card_and_the_trail_say_which_answer(self):
        row = self.file(BATTERY)
        self.answer(row, "It's on my to do list, stop reminding me")
        shaped = findings_store.get(row["ts"])
        self.assertEqual(shaped["hold"]["said"],
                         "It's on my to do list, stop reminding me")
        lines = [json.loads(x) for x in Path(
            decision_trail.TRAIL_FILE).read_text().splitlines()]
        held = [x for x in lines if x.get("kind") == "hold"]
        self.assertTrue(held)
        self.assertIn("stop reminding me", held[-1]["reason"])
        self.assertEqual(held[-1]["subject"], BATTERY["entity_id"])

    def test_the_battery_still_wakes_when_clearly_worse(self):
        row = self.file(BATTERY)
        self.answer(row, "It's on my to do list, stop reminding me")
        eid = BATTERY["entity_id"]
        findings_store.wake_worse({eid: {"state": "14"}})
        findings_store.wake_worse({eid: {"state": "6"}})
        self.assertTrue(self.live(row))
        self.assertNotIn("hold", findings_store.get(row["ts"]))

    def test_undo_wakes_it(self):
        row = self.file(ROUTER)
        self.answer(row, "Don't remind me")
        findings_store.snooze(row["ts"], 0)
        self.assertTrue(self.live(row))
        self.assertNotIn("hold", findings_store.get(row["ts"]))

    def test_a_rule_brain_may_not_quiet_keeps_the_month(self):
        # A safety check, a security check and a critical row: a hold
        # nothing could end is the plain 30-day snooze instead.
        for template in (
                {**ROUTER, "text": "Cellar leak sensor is wet",
                 "source": "check:safety.tripped",
                 "entity_id": "binary_sensor.cellar_leak"},
                {**ROUTER, "text": "The back door lock answers voice "
                                   "assistants from the cloud",
                 "source": "check:sec.lock_cloud_voice",
                 "entity_id": "lock.back_door"},
                {**BATTERY, "text": "Loft smoke alarm battery is flat",
                 "severity": "critical",
                 "entity_id": "sensor.loft_smoke_battery"}):
            row = self.file(template)
            self.answer(row, "Don't remind me")
            kept = findings_store.get(row["ts"])
            self.assertNotIn("hold", kept, template["source"])
            self.assertLess(int(kept["snoozed_until"]),
                            time.time() + (corrections.DEFERRAL_DAYS + 1)
                            * DAY, template["source"])

    def test_a_named_period_is_still_that_period(self):
        row = self.file(ROUTER)
        self.answer(row, "I am aware, remind me in 3 weeks")
        kept = findings_store.get(row["ts"])
        self.assertAlmostEqual(int(kept["snoozed_until"]),
                               time.time() + 21 * DAY, delta=60)
        self.assertNotIn("hold", kept)


if __name__ == "__main__":
    unittest.main()
