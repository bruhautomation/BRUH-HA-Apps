#!/usr/bin/env python3
"""A Wrong about an automation's standing fact is an answer, whatever it says (#768).

`auto.never_fired` kept filing an automation the owner leaves idle on
purpose, after they marked it Wrong; only a later hold kept it off the
list. #579 made one Wrong close the check for that automation
(`ANSWERED_ONCE`, read off the settled ledger), and that held — for a
Wrong that reached the ledger. A reason that reads as "not now" ("don't
remind me", "not needed for now") turned the press into a snooze or a
hold instead (`server._for_now`), which writes no ledger entry and no
rule, so the next pass filed the row again and something downstream had
to hold it. For a report of a standing fact about an automation — it has
never fired, it has been off for months — the next pass is the same fact,
and there is nothing for a snooze to wait for: the Wrong is the answer.

Driven through the real ending (`server._end_finding`) into the real
check over a snapshot built the way the collector builds it. The second
example is one the report never named: `auto.forgotten_off`, answered
"not needed for now". A house check about a device is still snoozed by
"for now" (`tests/test_fixing_it_is_a_snooze.py`), and other automations
still report.
"""
import asyncio
import importlib
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import corrections  # noqa: E402
import decision_trail  # noqa: E402
import facts_store  # noqa: E402
import findings_store  # noqa: E402
from checks import automations as auto  # noqa: E402
from test_house_checks import NOW, house  # noqa: E402
from test_never_fired_safety import installed  # noqa: E402


class Replay(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self._facts_old = (facts_store.FACTS_FILE, facts_store.INGEST_STATE_FILE)
        facts_store.FACTS_FILE = root / "facts.json"
        facts_store.INGEST_STATE_FILE = root / "facts-ingest.json"
        self._store_old = (findings_store.FINDINGS_FILE,
                           findings_store.SETTLED_FILE, findings_store.STATE_FILE)
        findings_store.FINDINGS_FILE = root / "findings.json"
        findings_store.SETTLED_FILE = root / "findings-settled.json"
        findings_store.STATE_FILE = root / "findings-state.json"
        self.server = importlib.import_module("server")
        self._facts_srv = self.server.facts_store
        self.server.facts_store = facts_store
        self._inbox_old = self.server.MEMORY_INBOX_DIR
        self.server.MEMORY_INBOX_DIR = root / "inbox"
        self._trail = decision_trail.TRAIL_FILE
        decision_trail.TRAIL_FILE = str(root / "decisions.jsonl")

    def tearDown(self):
        decision_trail.TRAIL_FILE = self._trail
        facts_store.FACTS_FILE, facts_store.INGEST_STATE_FILE = self._facts_old
        (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
         findings_store.STATE_FILE) = self._store_old
        self.server.facts_store = self._facts_srv
        self.server.MEMORY_INBOX_DIR = self._inbox_old
        self.tmp.cleanup()

    def snap(self, *entity_ids, off=False):
        snap = house()
        snap["states"].pop("automation.morning", None)
        snap["automations"] = []
        snap["entities"] = [e for e in snap["entities"]
                            if not str(e.get("entity_id", "")).startswith(
                                "automation.")]
        for eid in entity_ids:
            slug = eid.split(".", 1)[1]
            installed(snap, {"id": slug, "alias": slug.replace("_", " "),
                             "triggers": [{"trigger": "state",
                                           "entity_id": "binary_sensor.x"}],
                             "actions": []}, eid)
            if off:
                snap["states"][eid]["state"] = "off"
        # What the collector loads beside the house (`checks.snapshot`).
        snap["answers"] = findings_store.answered_checks()
        snap["facts"] = facts_store.exception_map(NOW)
        snap["corrections"] = corrections.scope_map(NOW, protected=[])
        return snap

    def press_wrong(self, row, check, note):
        [filed] = findings_store.add_many([{**row, "source": f"check:{check}"}])
        asyncio.run(self.server._end_finding(
            findings_store.get(filed["ts"]), self.server.FINDING_VERBS["wrong"],
            note, refine=False))


class TestNeverFiredAnsweredNotNow(Replay):
    def test_dont_remind_me_closes_it_for_that_automation(self):
        [row] = auto.never_fired(self.snap("automation.storm_shutters"), NOW)
        self.press_wrong(row, "auto.never_fired",
                         "Don't remind me, it is meant to sit idle")
        again = auto.never_fired(
            self.snap("automation.storm_shutters", "automation.attic_fan"), NOW)
        self.assertEqual([f["entity_id"] for f in again],
                         ["automation.attic_fan"])


class TestForgottenOffAnsweredForNow(Replay):
    def test_not_needed_for_now_closes_it_for_that_automation(self):
        [row] = auto.forgotten_off(
            self.snap("automation.pool_heater", off=True), NOW)
        self.press_wrong(row, "auto.forgotten_off", "Not needed for now")
        again = auto.forgotten_off(
            self.snap("automation.pool_heater", "automation.xmas_lights",
                      off=True), NOW)
        self.assertEqual([f["entity_id"] for f in again],
                         ["automation.xmas_lights"])


if __name__ == "__main__":
    unittest.main()
