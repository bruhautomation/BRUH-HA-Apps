#!/usr/bin/env python3
"""A reason that names a condition is not a blanket rule on a house check.

Report 435: two printer cards were answered "Normal while the printer is
printing. Only unusual if hot while the printer is idle", and each was
stored as a rule for the sensor with no condition, so the check could
never raise either again — in the idle state the person asked to hear
about included. A rule's text is the reason, so the reason is read against
the device's own job status (`chores.condition_holds`): the rule holds in
the state the person called normal and not in the other. A reason naming
a condition brAIn cannot watch writes no rule at all: it is kept as a fact
and the person is asked, on the existing correction-question route,
whether to stop flagging it altogether.
"""

import asyncio
import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "brain" / "panel"))
sys.path.insert(0, str(TESTS_DIR))

import corrections  # noqa: E402
import facts_store  # noqa: E402
import findings_store  # noqa: E402
from checks import baseline, chores  # noqa: E402
from checks._util import House  # noqa: E402
from test_house_checks import NOW, house, iso  # noqa: E402
from test_scoped_corrections import RouteCase  # noqa: E402

REASON = ("Normal while the printer is printing. Only unusual if hot while "
          "the printer is idle.")
SENSOR = "sensor.kiln_chamber_reading"
STATUS = "sensor.kiln_job_status"


class TestTheReasonIsRead(unittest.TestCase):
    def test_which_state_the_person_wants_to_hear_about(self):
        cases = {
            REASON: "idle",
            "Fine unless the washer is idle": "idle",
            "Normal while it is printing": "idle",
            "Only a problem when it is not printing": "idle",
            "Only matters while the dryer is running": "working",
            "It's mains powered": "",
            "It only turns on when the hallway reads above 60%": "",
        }
        for said, wanted in cases.items():
            self.assertEqual(chores.report_while(said), wanted, said)


def kiln(status: str, *, since: float = 7200, reason: str = REASON,
         check: str = "base.unusual") -> dict:
    snap = house()
    snap["devices"].append({"id": "dev_kiln", "name": "Studio kiln",
                            "manufacturer": "Generic", "model": ""})
    for eid, state, name in ((SENSOR, "61", "Kiln chamber reading"),
                             (STATUS, status, "Kiln job status")):
        snap["states"][eid] = {
            "state": state, "last_updated": iso(since),
            "last_changed": iso(since),
            "attributes": {"friendly_name": name}}
        if eid == STATUS:
            snap["states"][eid]["attributes"]["options"] = [
                "idle", "printing", "finish"]
        snap["entities"].append({"entity_id": eid, "platform": "mqtt",
                                 "device_id": "dev_kiln"})
    snap["corrections"] = {
        "entity": {SENSOR: {check: {"text": reason, "until": "", "id": "x"}}},
        "area": {}, "check": {},
        "never": {"checks": sorted(corrections.NEVER_CHECKS),
                  "domains": sorted(corrections.NEVER_DOMAINS),
                  "classes": sorted(corrections.NEVER_CLASSES),
                  "protected": []}}
    snap["_trail"] = []
    return snap


class TestTheRuleHoldsOnlyInTheStateCalledNormal(unittest.TestCase):
    def test_stands_down_while_the_machine_works(self):
        self.assertFalse(House(kiln("printing")).should_report(
            SENSOR, "base.unusual"))

    def test_raises_while_the_machine_is_idle(self):
        self.assertTrue(House(kiln("idle")).should_report(
            SENSOR, "base.unusual"))

    def test_raises_when_the_status_cannot_be_read(self):
        self.assertTrue(House(kiln("unavailable")).should_report(
            SENSOR, "base.unusual"))

    def test_a_whole_device_rule_with_a_condition_too(self):
        snap = kiln("idle", check="*")
        self.assertTrue(House(snap).should_report(SENSOR, "dev.frozen"))
        snap = kiln("printing", check="*")
        self.assertFalse(House(snap).should_report(SENSOR, "dev.frozen"))

    def test_a_plain_reason_stands_down_in_both_states(self):
        for status in ("printing", "idle"):
            self.assertFalse(House(kiln(status, reason="it's a dummy")
                                   ).should_report(SENSOR, "base.unusual"))

    def test_a_condition_on_a_device_with_no_status_is_the_old_rule(self):
        snap = kiln("idle")
        snap["states"].pop(STATUS)
        snap["entities"] = [e for e in snap["entities"]
                            if e["entity_id"] != STATUS]
        self.assertFalse(House(snap).should_report(SENSOR, "base.unusual"))


class TestHeaterIdleIsNeverSilencedByIt(unittest.TestCase):
    def test_a_hot_nozzle_on_an_idle_printer_still_files(self):
        snap = house()
        dev = {"id": "dev_pr", "name": "Loft", "manufacturer": "Bambu Lab",
               "model": "A1"}
        snap["devices"].append(dev)
        nozzle, status = "sensor.loft_nozzle_temperature", "sensor.loft_status"
        snap["states"][nozzle] = {
            "state": "180", "last_updated": iso(60), "last_changed": iso(60),
            "attributes": {"device_class": "temperature",
                           "unit_of_measurement": "°C",
                           "state_class": "measurement",
                           "friendly_name": "Loft Nozzle temperature"}}
        snap["states"][status] = {
            "state": "idle", "last_updated": iso(7200),
            "last_changed": iso(7200),
            "attributes": {"friendly_name": "Loft Status"}}
        for eid in (nozzle, status):
            snap["entities"].append({"entity_id": eid,
                                     "platform": "bruh_bambu",
                                     "device_id": "dev_pr"})
        snap["corrections"] = {
            "entity": {nozzle: {
                "base.unusual": {"text": REASON, "until": "", "id": "a"},
                "*": {"text": "it is a printer", "until": "", "id": "b"}}},
            "area": {}, "check": {},
            "never": {"checks": sorted(corrections.NEVER_CHECKS),
                      "domains": [], "classes": [], "protected": []}}
        rows = baseline.heater_idle(snap, NOW)
        self.assertEqual([r["entity_id"] for r in rows], [nozzle])


class TestThePress(RouteCase):
    ENTITY = "sensor.kiln_chamber_reading"

    def setUp(self):
        super().setUp()
        self._status_old = dict(self.server._MACHINE_STATUS)
        self.server._MACHINE_STATUS.clear()

    def tearDown(self):
        self.server._MACHINE_STATUS.clear()
        self.server._MACHINE_STATUS.update(self._status_old)
        super().tearDown()

    def press(self, note):
        row = self.check_row("base.unusual")

        async def body(client):
            res = await client.post(f"/api/finding/{row['ts']}/wrong",
                                    json={"note": note})
            self.assertEqual(res.status, 200)
            await asyncio.gather(*list(self.server._CORRECTION_TASKS))

        self.drive(body)

    def questions(self):
        return [f for f in findings_store.list_all()
                if f["source"] == corrections.SOURCE]

    def test_a_watchable_condition_is_written_and_asks_nothing(self):
        self.server._MACHINE_STATUS[self.ENTITY] = STATUS
        self.press(REASON)
        rules = self.rules()
        self.assertEqual([r["subject"] for r in rules], [self.ENTITY])
        self.assertEqual(rules[0]["text"], REASON)
        self.assertEqual(self.questions(), [])
        self.assertNotIn("correct", self.model_jobs())

    def test_a_condition_brain_cannot_watch_writes_no_rule_and_asks(self):
        self.press(REASON)
        self.assertEqual(self.rules(), [])
        kept = [r for r in facts_store.export_rows()
                if r.get("text") == REASON]
        self.assertTrue(kept)
        self.assertFalse(kept[0].get("predicate"))
        asked = self.questions()
        self.assertEqual(len(asked), 1)
        self.assertEqual(asked[0]["kind"], "question")

        async def yes(_client):
            return await self.server._end_finding(
                asked[0], self.server.FINDING_VERBS["confirm"], "")

        payload, _fact = self.drive(yes)
        self.assertTrue(payload.get("_exception_ids"))
        rules = self.rules()
        self.assertEqual([r["subject"] for r in rules], [self.ENTITY])
        self.assertEqual(rules[0]["predicate"], "exception:base.unusual")

    def test_a_condition_in_words_naming_no_state_asks_too(self):
        self.server._MACHINE_STATUS[self.ENTITY] = STATUS
        self.press("It only matters when guests are staying")
        self.assertEqual(self.rules(), [])
        self.assertEqual(len(self.questions()), 1)

    def test_a_plain_reason_is_the_rule_it_always_was(self):
        self.press("it's a dummy sensor")
        self.assertEqual(len(self.rules()), 1)
        self.assertEqual(self.questions(), [])


if __name__ == "__main__":
    unittest.main()
