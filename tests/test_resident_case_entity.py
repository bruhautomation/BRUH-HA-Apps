#!/usr/bin/env python3
"""A Resident case is about the device it names, and clears when it is back.

Reported from a real house: an investigation filed "the front lock has been
offline since 10:20 yesterday" with `entity_id: ""`, so nothing tied the row
to the lock. The lock came back and read locked, the morning brief said so,
and the row stayed on the list (status planned) a day later. Two halves:

  * a case records the entity it is about — the signal it investigated,
    or the one device its evidence names — never an invented one;
  * a Resident row whose evidence shows that entity with no reading
    (unavailable, unknown, offline) is cleared, `clear_resolved`'s ending,
    once the entity reports a real state that changed after the row was
    filed. Never a fix in flight or done, never a row a person touched.
"""

import sys
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import findings_store  # noqa: E402
from test_cases import StoresCase  # noqa: E402
from test_resident_loop import LoopCase  # noqa: E402

LOCK = "lock.front_door"


def _iso(stamp: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(stamp))


def _lock_case(**fields) -> dict:
    row = {
        "claim": "The front lock has been offline since 10:20 yesterday",
        "detail": "It stopped answering and has not come back.",
        "kind": "problem", "stakes": "medium", "severity": "warning",
        "confidence": 0.8,
        "evidence": [{"entity": LOCK, "value": "unavailable",
                      "when": "2026-10-19 10:20"}],
        "actions": [],
        **fields,
    }
    row.setdefault("text", row["claim"])
    return findings_store.add_case(row, run_id="inv-1")


class TestACaseRecordsTheEntityItIsAbout(unittest.TestCase):
    """`case_subject`: the reply's own, the signal's, the evidence's one."""

    def subject(self, evidence, signal="", **row):
        return findings_store.case_subject({"evidence": evidence, **row},
                                           signal)

    def test_a_single_entity_in_the_evidence_is_the_cases_subject(self):
        self.assertEqual(self.subject(
            [{"entity": LOCK, "value": "unavailable", "when": ""}]), LOCK)

    def test_the_replys_own_entity_stands(self):
        self.assertEqual(self.subject(
            [{"entity": LOCK, "value": "unavailable", "when": ""}],
            "lock.side_door", entity_id="lock.back_door"), "lock.back_door")

    def test_the_signal_subject_comes_before_the_evidence(self):
        self.assertEqual(self.subject(
            [{"entity": "sensor.hub_signal", "value": "-90", "when": ""}],
            LOCK), LOCK)

    def test_two_devices_in_the_evidence_name_no_subject(self):
        self.assertEqual(self.subject([
            {"entity": LOCK, "value": "unavailable", "when": ""},
            {"entity": "sensor.hub_signal", "value": "-90", "when": ""}]), "")

    def test_two_readings_of_one_device_still_name_it(self):
        self.assertEqual(self.subject([
            {"entity": LOCK, "value": "unavailable", "when": "10:20"},
            {"entity": LOCK, "value": "unavailable", "when": "11:20"}]), LOCK)

    def test_a_string_that_is_not_an_entity_is_not_invented_into_one(self):
        self.assertEqual(self.subject(
            [{"entity": "the front lock", "value": "offline", "when": ""}]), "")
        self.assertEqual(self.subject([], "the front lock"), "")


class TestTheInvestigationFilesTheSubject(LoopCase):
    """The real `_resident_investigate`, a live signal, the CLI stubbed."""

    def test_a_filed_case_carries_the_signal_it_looked_at(self):
        import asyncio
        import json
        self.investigations.append({
            "ok": True, "error": "", "meta": {"session_id": "inv-9"},
            "text": json.dumps({
                "claim": "The front lock has been offline since 10:20",
                "detail": "It stopped answering and has not come back.",
                "kind": "problem", "confidence": 0.8, "stakes": "medium",
                "fix": "Check its batteries.",
                "evidence": [{"entity": LOCK, "value": "unavailable",
                              "when": "10:20"}],
                "actions": [], "escalate": False})})
        signal = {"kind": "state", "subject": LOCK, "salience": 0.6,
                  "text": "Front door lock went unavailable", "evidence": []}
        asyncio.run(self.server._resident_investigate(
            signal, time.time(), "normal"))
        rows = [r for r in self.server.findings_store._load()
                if r.get("source") == "resident"]
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(rows[0].get("entity_id"), LOCK)


class TestARowAboutADeviceThatCameBackClears(StoresCase):

    def back(self, entity: str, state: str, after: float) -> dict:
        return {entity: {"state": state, "last_changed": _iso(after)}}

    def test_the_lock_reading_locked_again_clears_the_row(self):
        filed = _lock_case()
        gone = findings_store.clear_returned(
            self.back(LOCK, "locked", filed["ts"] + 3600), filed["ts"] + 7200)
        self.assertEqual([g["ts"] for g in gone], [filed["ts"]])
        self.assertIsNone(findings_store.get(filed["ts"]))
        # `clear_resolved`'s ending: nothing settled, nothing to memory.
        self.assertFalse(findings_store.is_known(filed["text"]))

    def test_a_sensor_that_read_unknown_clears_the_same_way(self):
        filed = findings_store.add_case({
            "text": "The tank level sensor stopped reporting",
            "claim": "The tank level sensor stopped reporting",
            "detail": "It has read unknown since this morning.",
            "kind": "problem", "stakes": "low", "severity": "info",
            "evidence": [{"entity": "sensor.tank_level", "value": "unknown",
                          "when": "08:00"}]}, run_id="inv-2")
        gone = findings_store.clear_returned(
            self.back("sensor.tank_level", "62", filed["ts"] + 60),
            filed["ts"] + 120)
        self.assertEqual(len(gone), 1)

    def test_a_planned_row_is_cleared_too(self):
        filed = _lock_case()
        findings_store.set_status(filed["ts"], "planned")
        gone = findings_store.clear_returned(
            self.back(LOCK, "locked", filed["ts"] + 60), filed["ts"] + 120)
        self.assertEqual(len(gone), 1)

    def test_still_unavailable_stays(self):
        filed = _lock_case()
        for state in ("unavailable", "unknown"):
            gone = findings_store.clear_returned(
                self.back(LOCK, state, filed["ts"] + 60), filed["ts"] + 120)
            self.assertEqual(gone, [])
        self.assertIsNotNone(findings_store.get(filed["ts"]))

    def test_a_state_that_has_not_changed_since_the_filing_stays(self):
        filed = _lock_case()
        gone = findings_store.clear_returned(
            self.back(LOCK, "locked", filed["ts"] - 600), filed["ts"] + 120)
        self.assertEqual(gone, [])

    def test_an_entity_the_states_do_not_hold_stays(self):
        filed = _lock_case()
        self.assertEqual(findings_store.clear_returned({}, filed["ts"] + 60),
                         [])
        self.assertIsNotNone(findings_store.get(filed["ts"]))

    def test_a_row_that_never_reported_it_offline_stays(self):
        filed = _lock_case(evidence=[
            {"entity": LOCK, "value": "unlocked", "when": "02:10"}],
            claim="The front lock was unlocked at 2am",
            text="The front lock was unlocked at 2am")
        gone = findings_store.clear_returned(
            self.back(LOCK, "locked", filed["ts"] + 60), filed["ts"] + 120)
        self.assertEqual(gone, [])

    def test_a_fix_in_flight_or_done_stays(self):
        for status in ("fixing", "fixed"):
            filed = _lock_case(text=f"The front lock is offline ({status})",
                               claim=f"The front lock is offline ({status})")
            findings_store.set_status(filed["ts"], status)
            gone = findings_store.clear_returned(
                self.back(LOCK, "locked", filed["ts"] + 60), filed["ts"] + 120)
            self.assertEqual(gone, [], status)
            # One case per status: the next is filed after this one goes.
            findings_store.remove(filed["ts"])

    def test_a_snoozed_row_or_one_a_person_put_back_stays(self):
        filed = _lock_case()
        findings_store.snooze(filed["ts"], int(filed["ts"] + 86400))
        gone = findings_store.clear_returned(
            self.back(LOCK, "locked", filed["ts"] + 60), filed["ts"] + 120)
        self.assertEqual(gone, [])

    def test_another_producers_row_is_not_this_sweeps(self):
        [row] = findings_store.add_many([{
            "text": "Front lock unavailable", "severity": "warning",
            "source": "check:dev.unavailable", "entity_id": LOCK,
            "evidence": [{"entity": LOCK, "value": "unavailable",
                          "when": ""}]}])
        gone = findings_store.clear_returned(
            self.back(LOCK, "locked", row["ts"] + 60), row["ts"] + 120)
        self.assertEqual(gone, [])


class TestTheChecksPassRunsTheSweep(unittest.TestCase):
    """Wired where the states are already fetched, not on a loop of its own."""

    def test_run_checks_hands_the_snapshot_states_to_the_sweep(self):
        src = (BASE_DIR / "brain" / "panel" / "server.py").read_text(
            encoding="utf-8")
        body = src[src.index("async def run_checks("):]
        body = body[:body.index("\nasync def ", 10)]
        self.assertIn("findings_store.clear_returned(", body)


if __name__ == "__main__":
    unittest.main()
