#!/usr/bin/env python3
""""It's on my list, stop reminding me" on a battery card.

The card stays away for the whole period (a month, the one every "don't
remind me" gets), and comes back early only when the thing is clearly worse:
the reading falls well under where it stood, or the device goes quiet. A
point or two of wobble is the same battery. The card that comes back says
the answer was heard.
"""

import asyncio
import sys
import time
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "brain" / "panel"))
sys.path.insert(0, str(TESTS_DIR))

import findings_store  # noqa: E402
from test_scoped_corrections import RouteCase  # noqa: E402


def states(**levels):
    return {eid: {"state": str(v)} for eid, v in levels.items()}


class TestBatteryDeferral(RouteCase):
    ENTITY = "sensor.hall_motion_battery"

    def defer(self, check="dev.battery_low", entity=None, text=None):
        entity = entity or self.ENTITY
        row, _ = findings_store.add(
            text or "Hall motion battery is low", severity="warning",
            detail="14% as of today.", fix="Replace the battery.",
            source=f"check:{check}", entity_id=entity)

        async def body(client):
            res = await client.post(f"/api/finding/{row['ts']}/wrong", json={
                "note": "It's on my to do list, stop reminding me"})
            self.assertEqual(res.status, 200)
            await asyncio.gather(*list(self.server._CORRECTION_TASKS))
        self.drive(body)
        return row

    def live(self, row):
        return row["ts"] in [f["ts"] for f in findings_store.list_all("live")]

    def test_stays_away_through_a_wobble_and_a_small_drop(self):
        row = self.defer()
        until = findings_store.get(row["ts"])["snoozed_until"]
        self.assertGreater(until, time.time() + 29 * 86400)
        for level in (14, 13, 12, 14, 11):
            findings_store.wake_worse(states(**{self.ENTITY: level}))
        self.assertFalse(self.live(row))

    def test_a_further_drop_brings_it_back_and_says_why(self):
        row = self.defer()
        findings_store.wake_worse(states(**{self.ENTITY: 14}))
        woke = findings_store.wake_worse(states(**{self.ENTITY: 8}))
        self.assertEqual([w["ts"] for w in woke], [row["ts"]])
        self.assertTrue(self.live(row))
        # the check re-reporting with its own detail keeps the sentence
        findings_store.refresh_details([{
            "text": row["text"], "detail": "8% as of today.",
            "severity": "warning", "source": "check:dev.battery_low",
            "entity_id": self.ENTITY}])
        detail = findings_store.get(row["ts"])["detail"]
        self.assertIn("8%", detail)
        self.assertIn("said you would handle this", detail)

    def test_going_unavailable_brings_it_back(self):
        row = self.defer(entity="binary_sensor.cellar_smoke_battery",
                         text="Cellar smoke alarm battery is low")
        eid = "binary_sensor.cellar_smoke_battery"
        findings_store.wake_worse({eid: {"state": "on"}})
        self.assertFalse(self.live(row))
        findings_store.wake_worse({eid: {"state": "unavailable"}})
        self.assertTrue(self.live(row))

    def test_a_card_that_was_already_unavailable_does_not_wake_at_once(self):
        row = self.defer()
        findings_store.wake_worse(states(**{self.ENTITY: "unavailable"}))
        self.assertFalse(self.live(row))

    def test_a_row_already_under_the_level_needs_a_real_drop(self):
        row = self.defer()
        findings_store.wake_worse(states(**{self.ENTITY: 9}))
        findings_store.wake_worse(states(**{self.ENTITY: 8}))
        self.assertFalse(self.live(row))
        findings_store.wake_worse(states(**{self.ENTITY: 5}))
        self.assertTrue(self.live(row))

    def test_other_checks_keep_the_plain_month(self):
        row = self.defer("dev.frozen", "sensor.attic_temperature")
        self.assertFalse(findings_store.get(row["ts"]).get("snooze_worse"))
        findings_store.wake_worse(
            {"sensor.attic_temperature": {"state": "unavailable"}})
        self.assertFalse(self.live(row))

    def test_undo_clears_it(self):
        row = self.defer()
        findings_store.snooze(row["ts"], 0)
        self.assertNotIn("snooze_worse", findings_store._load()[0])


if __name__ == "__main__":
    unittest.main()
