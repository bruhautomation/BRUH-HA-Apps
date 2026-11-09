#!/usr/bin/env python3
"""Symptoms of one open problem or one pending question are ONE row (#792).

The list showed "the basement humidity is high", "the basement dehumidifier
is off" and "Is the basement dehumidifier still in use?" as three cards,
when the first two wait on the third's answer; and three rows about the
water softener's salt as three. The store already folds one device's link
trouble and one shared cause (`_fold_devices`, `_fold_shared`); this is
the same fold keyed on a CAUSE a producer names (`cause`), and on the id
of a visible card a look or an investigation says a row is a symptom of
(`same_as`, stored as the cause ``f:<ts>``). The folded rows are listed
under the card they wait on (its evidence), never shown beside it. A
cause naming a card nobody can see is dropped, and a safety or security
row is never folded away.

Three groups, each shown once under its parent.
"""

import sys
import time
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "brain" / "panel"))
sys.path.insert(0, str(TESTS_DIR))

from test_resident_loop import LoopCase, case_reply, reply  # noqa: E402


# What kind of thing each sensor is: a fold by cause never takes a sensor
# of unknown kind, food or water (`corrections.strict_floor`).
CLASSES = {"sensor.basement_humidity": "humidity",
           "sensor.dehumidifier_power": "power",
           "sensor.softener_salt": "distance",
           "sensor.softener_brine": "distance",
           "sensor.softener_regen": "duration",
           "sensor.garage_motion_battery": "battery"}


class TestOneRowPerCause(LoopCase):
    def setUp(self):
        super().setUp()
        import decision_trail
        old = decision_trail.TRAIL_FILE
        decision_trail.TRAIL_FILE = str(Path(self.tmp.name) / "trail.jsonl")
        decision_trail._RECENT.clear()
        self.addCleanup(setattr, decision_trail, "TRAIL_FILE", old)
        self.trail = decision_trail
        names = self.server._NAMES
        saved = dict(names)
        self.addCleanup(lambda: (names.clear(), names.update(saved)))
        names.update({e: {"name": e.split(".")[1].replace("_", " "),
                          "class": c} for e, c in CLASSES.items()})

    def fs(self):
        return self.server.findings_store

    def live(self) -> dict[int, dict]:
        return {f["ts"]: f for f in self.fs().list_all()}

    def evidence(self, row) -> list[str]:
        return [e["entity"] for e in row.get("evidence") or []]

    def test_symptoms_of_a_pending_question_sit_under_it(self):
        fs = self.fs()
        question = fs.add_case({
            "kind": "question",
            "text": "Is the basement dehumidifier still in use?",
            "claim": "Is the basement dehumidifier still in use?", "detail": "It has been off for nine days.",
            "entity_id": "switch.basement_dehumidifier", "stakes": "low"})
        self.assertIsNotNone(question)
        cause = f"f:{question['ts']}"
        made = fs.add_many(self.server.triage.gate([
            {"text": "The basement humidity has read above 65% for a week",
             "entity_id": "sensor.basement_humidity", "severity": "warning",
             "source": "check:base.unusual", "cause": cause},
            {"text": "The basement dehumidifier has drawn no power for nine "
                     "days", "entity_id": "sensor.dehumidifier_power",
             "severity": "info", "source": "check:dev.frozen",
             "cause": cause}]))
        self.assertEqual(made, [])
        live = self.live()
        self.assertEqual(list(live), [question["ts"]])
        self.assertEqual(
            set(self.evidence(live[question["ts"]])) >= {
                "sensor.basement_humidity", "sensor.dehumidifier_power"},
            True)

    def test_rows_sharing_a_named_cause_are_one_row(self):
        fs = self.fs()
        made = fs.add_many(self.server.triage.gate([
            {"text": f"The water softener's {part} reads low",
             "entity_id": f"sensor.softener_{part}", "severity": "warning",
             "source": "check:dev.frozen", "cause": "softener_salt"}
            for part in ("salt", "brine", "regen")]))
        self.assertEqual(len(made), 1)
        [row] = self.live().values()
        self.assertEqual(set(self.evidence(row)) | {row["entity_id"]},
                         {"sensor.softener_salt", "sensor.softener_brine",
                          "sensor.softener_regen"})

    def test_an_investigation_names_the_card_a_row_is_a_symptom_of(self):
        fs = self.fs()
        host = self.file_check_row(
            text="The garage plug drops off Wi-Fi every night",
            entity_id="switch.garage_plug", source="check:dev.unavailable")
        fs.record_triage({host["ts"]: ("elevated", "Worth a look.")}, "l0")
        row = self.file_check_row(
            text="The garage motion sensor's battery stops reporting at night",
            entity_id="sensor.garage_motion_battery")
        self.investigations.append(case_reply(
            claim="The garage motion sensor's battery stops reporting at night",
            stakes="medium", same_as=f"f:{host['ts']}",
            detail="It drops out exactly when the plug does.",
            fix="Move the plug closer to the access point."))
        self.looks.append(reply([{"id": 1, "verdict": "investigate",
                                  "why": "Worth a look."}]))
        self.tick(time.time())
        live = self.live()
        self.assertNotIn(row["ts"], live)
        self.assertIn("sensor.garage_motion_battery", self.evidence(live[host["ts"]]))

    def test_a_cause_naming_nothing_visible_is_dropped(self):
        fs = self.fs()
        [made] = fs.add_many(self.server.triage.gate([
            {"text": "The pantry contact has not changed in nine days",
             "entity_id": "binary_sensor.pantry", "source": "check:dev.frozen",
             "cause": "f:12345"}]))
        self.assertNotIn("cause", fs.get(made["ts"]))

    def test_a_safety_row_is_never_folded_away(self):
        fs = self.fs()
        made = fs.add_many(self.server.triage.gate([
            {"text": "The basement humidity is high",
             "entity_id": "sensor.basement_humidity", "source": "check:dev.frozen",
             "cause": "basement_water"},
            {"text": "The basement leak sensor is wet",
             "entity_id": "binary_sensor.basement_leak",
             "source": "check:safety.tripped", "severity": "critical",
             "cause": "basement_water"}]))
        self.assertIn("binary_sensor.basement_leak",
                      [f["entity_id"] for f in self.live().values()])
        self.assertTrue(made)

    def test_a_fold_by_cause_writes_the_trail(self):
        fs = self.fs()
        fs.add_many(self.server.triage.gate([
            {"text": f"The water softener's {part} reads low",
             "entity_id": f"sensor.softener_{part}", "severity": "warning",
             "source": "check:dev.frozen", "cause": "softener_salt"}
            for part in ("salt", "brine")]))
        rows, readable = self.trail.read()
        self.assertTrue(readable)
        self.assertEqual([r["kind"] for r in rows], ["listed_under"])


class TestTheReviewersThreeStayVisible(LoopCase):
    """An investigation names a pending question as the card a leak sensor,
    a smoke alarm and a lock wait on (the review's reproduction, #790):
    none of them is folded under it. No class is known for the two
    binary sensors, as in the review."""

    def run_one(self, host, eid, text, source, clock):
        row = self.file_check_row(text=text, entity_id=eid, source=source)
        self.investigations.append(case_reply(
            claim=text, stakes="medium", same_as=f"f:{host['ts']}",
            detail="Related to the dehumidifier.", fix="Check it.",
            evidence=[{"entity": eid, "value": "low", "when": "today"}]))
        self.looks.append(reply([{"id": 1, "verdict": "investigate",
                                  "why": "Worth a look."}]))
        self.tick(clock)
        return row

    def test_leak_smoke_and_lock_rows_are_never_folded(self):
        clock = time.time()
        host = self.server.findings_store.add_case({
            "kind": "question", "text": "Is the dehumidifier still in use?",
            "claim": "Is the dehumidifier still in use?",
            "detail": "It has been off for nine days.",
            "entity_id": "switch.dehum", "stakes": "low"})
        for eid, text, source in (
                ("binary_sensor.basement_leak",
                 "Basement leak sensor unavailable", "check:dev.unavailable"),
                ("binary_sensor.hall_smoke",
                 "Hall smoke detector battery is at 3%", "check:dev.battery"),
                ("lock.front_door", "Front door lock battery low",
                 "check:dev.battery")):
            self.run_one(host, eid, text, source, clock)
            clock += self.server.RESIDENT_LOOK_S + 1
            live = {f["entity_id"]: f for f in
                    self.server.findings_store.list_all()}
            self.assertIn(eid, live, text)
            self.assertIn(live[eid]["status"], ("open", "needs_you"), text)
            self.assertNotIn("cause", live[eid])


if __name__ == "__main__":
    unittest.main()
