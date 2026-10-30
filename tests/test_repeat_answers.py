#!/usr/bin/env python3
"""What the household already answered is read before a card is made.

A row marked Wrong twice, a device said to be unused or broken, and a Wrong
whose reason is "don't remind me" each came back as a fresh card. The
settled ledger now feeds `House.answered_off` (every check's one question,
`should_report`), and a deferral is the existing snooze.

The examples here are made up and differ from the reports: a cellar
humidity probe for the repeated Wrong, a garage remote for "not used", a
hall lock for the deferral.
"""

import asyncio
import sys
import tempfile
import time
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "brain" / "panel"))
sys.path.insert(0, str(TESTS_DIR))

import checks  # noqa: E402
import corrections  # noqa: E402
import findings_store  # noqa: E402
from test_house_checks import NOW, house  # noqa: E402
from test_scoped_corrections import RouteCase  # noqa: E402

devices = checks.devices
DAY = 86400


def with_answers(snap, entity, check, *, wrong=0, notes=()):
    snap.setdefault("answers", {}).setdefault(entity, {})[check] = {
        "wrong": wrong, "notes": list(notes)}
    return snap


def impossible_house():
    snap = house()
    snap["states"]["sensor.hall_temp"]["state"] = "99"
    return snap


class TestWrongTwiceStaysClosed(unittest.TestCase):
    def test_one_wrong_is_not_enough(self):
        snap = with_answers(impossible_house(), "sensor.hall_temp",
                            "dev.implausible", wrong=1)
        self.assertEqual(len(devices.implausible(snap, NOW)), 1)

    def test_two_wrongs_close_the_check_for_that_entity_only(self):
        snap = with_answers(impossible_house(), "sensor.hall_temp",
                            "dev.implausible", wrong=2)
        self.assertEqual(devices.implausible(snap, NOW), [])
        # a second entity that was never answered is still asked about
        snap["states"]["sensor.cellar_temp"] = dict(
            snap["states"]["sensor.hall_temp"])
        snap["entities"].append({"entity_id": "sensor.cellar_temp",
                                 "platform": "mqtt"})
        self.assertEqual([f["entity_id"]
                          for f in devices.implausible(snap, NOW)],
                         ["sensor.cellar_temp"])

    def test_a_different_kind_of_fault_is_not_closed(self):
        snap = house()
        snap["states"]["sensor.back_door_battery"]["state"] = "4"
        with_answers(snap, "sensor.back_door_battery", "dev.implausible",
                     wrong=3)
        self.assertEqual(len(devices.battery_low(snap, NOW)), 1)

    def test_a_broken_sensor_reason_closes_it_at_once(self):
        snap = with_answers(impossible_house(), "sensor.hall_temp",
                            "dev.implausible", wrong=1,
                            notes=["this sensor is broken, please ignore it"])
        self.assertEqual(devices.implausible(snap, NOW), [])

    def test_the_detail_reads_the_value_once(self):
        snap = impossible_house()
        found = devices.implausible(snap, NOW)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["detail"].count("99"), 1)


class TestAnUnusedDeviceYieldsNoBatteryCard(unittest.TestCase):
    def remote_house(self, level="3"):
        snap = house()
        snap["devices"].append({"id": "dev-remote", "name": "Garage remote"})
        snap["entities"].append({"entity_id": "sensor.garage_remote_battery",
                                 "platform": "mqtt", "device_id": "dev-remote"})
        snap["states"]["sensor.garage_remote_battery"] = {
            "state": level, "last_updated": "2026-01-01T00:00:00+00:00",
            "attributes": {"device_class": "battery",
                           "unit_of_measurement": "%",
                           "friendly_name": "Garage remote battery"}}
        return snap

    def ids(self, snap):
        return [f["entity_id"] for f in devices.battery_low(snap, NOW)]

    def test_it_files_without_an_answer(self):
        self.assertEqual(self.ids(self.remote_house()),
                         ["sensor.garage_remote_battery"])

    def test_a_fixed_answer_that_says_it_is_not_used_closes_it(self):
        for said in ("I don't use this remote any more", "retired",
                     "not used, it is a spare"):
            snap = with_answers(self.remote_house(),
                                "sensor.garage_remote_battery",
                                "dev.battery_low", notes=[said])
            self.assertEqual(self.ids(snap), [], said)

    def test_an_answer_about_the_same_device_closes_it(self):
        snap = self.remote_house()
        snap["entities"].append({"entity_id": "sensor.garage_remote_temp",
                                 "platform": "mqtt", "device_id": "dev-remote"})
        with_answers(snap, "sensor.garage_remote_temp", "dev.frozen",
                     notes=["we no longer use the remote"])
        self.assertEqual(self.ids(snap), [])

    def test_a_plain_replaced_it_does_not_close_it(self):
        snap = with_answers(self.remote_house(),
                            "sensor.garage_remote_battery",
                            "dev.battery_low",
                            notes=["Replaced the battery, the old one was dead"])
        self.assertEqual(len(self.ids(snap)), 1)


class TestTheLedgerFeedsIt(unittest.TestCase):
    def test_counts_and_notes_come_off_the_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = findings_store.SETTLED_FILE
            findings_store.SETTLED_FILE = Path(tmp) / "settled.json"
            try:
                shaped = {"text": "Cellar probe is reporting an impossible value",
                          "source": "check:dev.implausible",
                          "entity_id": "sensor.cellar_probe"}
                for _ in range(3):
                    findings_store._remember_settled(
                        shaped, "ignored", note="the probe is broken")
                got = findings_store.answered_checks()
            finally:
                findings_store.SETTLED_FILE = old
        row = got["sensor.cellar_probe"]["dev.implausible"]
        self.assertEqual(row["wrong"], 3)
        self.assertEqual(row["notes"], ["the probe is broken"])


class TestDontRemindMe(RouteCase):
    ENTITY = "lock.hall_door"

    def press(self, row, note):
        async def body(client):
            res = await client.post(f"/api/finding/{row['ts']}/wrong",
                                    json={"note": note})
            self.assertEqual(res.status, 200)
            await asyncio.gather(*list(self.server._CORRECTION_TASKS))
            return await res.json()
        return self.drive(body)

    def test_the_words_are_read(self):
        for said in ("Don't remind me",
                     "It's on my to do list, stop reminding me",
                     "I am aware don't bring this up again",
                     "I know about it"):
            self.assertTrue(corrections.deferral(said), said)
        for said in ("this sensor is broken", "I need to fix this light",
                     "normal for this sensor", ""):
            self.assertFalse(corrections.deferral(said), said)

    def deferred(self, said):
        row = self.check_row("dev.battery_low")
        before = time.time()
        self.press(row, said)
        self.assertEqual(self.rules(), [], said)
        kept = findings_store.get(row["ts"])
        self.assertIsNotNone(kept)
        until = int(kept.get("snoozed_until") or 0)
        self.assertGreaterEqual(
            until, before + corrections.DEFERRAL_DAYS * DAY - 5)
        self.assertFalse(kept.get("snooze_wake"))
        self.assertNotIn(row["ts"], [
            f["ts"] for f in findings_store.list_all("live")])
        # and the check raising the same card again does not open it
        again, created = findings_store.add(
            row["text"], severity="warning", detail="19% now", fix="x",
            source="check:dev.battery_low", entity_id=self.ENTITY)
        self.assertFalse(created)
        self.assertNotIn(row["ts"], [
            f["ts"] for f in findings_store.list_all("live")])

    def test_stop_reminding_me_is_a_timed_snooze_not_a_rule(self):
        self.deferred("It's on my to do list, stop reminding me")

    def test_dont_remind_me_is_a_timed_snooze_not_a_rule(self):
        self.deferred("Don't remind me")

    def test_a_period_in_the_words_is_used(self):
        row = self.check_row("dev.frozen")
        self.press(row, "I am aware, remind me in 3 weeks, not before")
        until = int(findings_store.get(row["ts"]).get("snoozed_until") or 0)
        self.assertAlmostEqual(until, time.time() + 21 * DAY, delta=60)

    def test_a_reason_for_good_is_still_a_rule(self):
        row = self.check_row("dev.frozen")
        self.press(row, "this sensor is broken, stop reminding me")
        self.assertEqual([r["subject"] for r in self.rules()], [self.ENTITY])


if __name__ == "__main__":
    unittest.main()
