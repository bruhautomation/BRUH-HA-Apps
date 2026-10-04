#!/usr/bin/env python3
"""A rule a Wrong wrote is an effect of that press, and goes back with it.

Wrong on a check's row writes an `exception:<check>` fact under the entity,
and the check reads it before filing. Two presses take a Wrong back — the
toast's Undo and "Let brAIn raise it again" — and both put back the row or
the wording while leaving the rule standing, so the check stayed muted for
that entity with nothing on screen saying so.

Driven through the real routes on a live client (`test_todo_list`'s
harness), over the real findings, facts and settled stores. Mutations:

  undo leaves the rule      drop `exception` from the token -> the rule
                            survives an Undo of the press that wrote it
  raise-again leaves it     drop `forget_exceptions` in the unsettle
                            route -> the check stays muted
  undo takes the other      forget every exception on the entity -> an
                            Undo of one Wrong takes a second check's rule
  resident writes nothing   drop the Resident branch of `_exception_rule`
                            -> a later look is not told it was dismissed
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import facts_store  # noqa: E402
import findings_store  # noqa: E402
from test_todo_list import PanelCase  # noqa: E402


class FactsCase(PanelCase):
    def setUp(self):
        super().setUp()
        root = Path(self.tmp.name)
        self._facts = (facts_store.FACTS_FILE, facts_store.INGEST_STATE_FILE,
                       facts_store.RECONCILE_STATE_FILE)
        facts_store.FACTS_FILE = root / "facts.json"
        facts_store.INGEST_STATE_FILE = root / "facts-ingest.json"
        facts_store.RECONCILE_STATE_FILE = root / "facts-reconcile.json"
        self._srv_facts = self.server.facts_store
        self.server.facts_store = facts_store

    def tearDown(self):
        (facts_store.FACTS_FILE, facts_store.INGEST_STATE_FILE,
         facts_store.RECONCILE_STATE_FILE) = self._facts
        self.server.facts_store = self._srv_facts
        super().tearDown()

    def check_row(self, check: str = "dev.frozen",
                  entity: str = "binary_sensor.cupboard") -> dict:
        entry, created = findings_store.add(
            f"{entity} has read exactly the same value for a week ({check})",
            severity="warning", detail="off on every one of the last 8 days",
            fix="Check it", source=f"check:{check}",
            source_title="Sensors frozen on one value", entity_id=entity)
        self.assertTrue(created)
        return entry

    def press(self, client, ts, verb="wrong", note=""):
        async def go():
            res = await client.post(f"/api/finding/{ts}/{verb}",
                                    json={"note": note})
            self.assertEqual(res.status, 200, await res.text())
            return await res.json()
        return go()


class TestUndoTakesTheRuleBack(FactsCase):

    def test_undo_of_a_wrong_removes_its_rule_and_only_its_rule(self):
        first = self.check_row("dev.frozen")
        second = self.check_row("base.unusual")

        async def run(client):
            await self.press(client, second["ts"], note="normal for it")
            out = await self.press(client, first["ts"],
                                   note="a cupboard nobody opens")
            self.assertEqual(facts_store.exception_map(),
                             {"binary_sensor.cupboard":
                              {"dev.frozen", "base.unusual"}})
            res = await client.post(f"/api/undo/{out['undo']}")
            self.assertEqual(res.status, 200, await res.text())

        self.drive(run)
        self.assertEqual(facts_store.exception_map(),
                         {"binary_sensor.cupboard": {"base.unusual"}})
        self.assertIsNotNone(findings_store.get(first["ts"]))

    def test_a_token_from_before_the_ids_finds_the_rule_by_its_report(self):
        row = self.check_row()

        async def run(client):
            out = await self.press(client, row["ts"])
            # The shape a token had before it carried the rule's ids.
            entry = self.server.undo_store._ENTRIES[out["undo"]]
            self.assertTrue(entry.pop("exception"))
            res = await client.post(f"/api/undo/{out['undo']}")
            self.assertEqual(res.status, 200, await res.text())

        self.drive(run)
        self.assertEqual(facts_store.exception_map(), {})


class TestRaisingItAgainReleasesTheRule(FactsCase):

    def test_the_unsettle_press_forgets_the_exception(self):
        row = self.check_row()
        key = findings_store.normalize(row["text"])

        async def run(client):
            await self.press(client, row["ts"])
            self.assertTrue(facts_store.exception_map())
            res = await client.post("/api/findings/unsettle",
                                    json={"key": key})
            self.assertEqual(res.status, 200, await res.text())

        self.drive(run)
        self.assertEqual(facts_store.exception_map(), {})
        self.assertNotIn(key, findings_store.suppressing_keys())

    def test_a_rule_whose_ledger_entry_aged_out_is_still_released(self):
        row = self.check_row()
        key = findings_store.normalize(row["text"])

        async def run(client):
            await self.press(client, row["ts"])
            findings_store.unsettle(key)           # the entry is gone
            res = await client.post("/api/findings/unsettle",
                                    json={"key": key})
            self.assertEqual(res.status, 200, await res.text())

        self.drive(run)
        self.assertEqual(facts_store.exception_map(), {})


class TestTheResidentsWrongIsARule(FactsCase):

    def test_wrong_on_a_case_writes_exception_resident_on_what_it_read(self):
        entry, created = findings_store.add(
            "The porch light has been left on all night",
            severity="warning", source=findings_store.RESIDENT_SOURCE,
            source_title="brAIn",
            evidence=[{"entity": "light.porch", "value": "on",
                       "when": "all night"},
                      {"entity": "binary_sensor.porch_motion",
                       "value": "off"}])
        self.assertTrue(created)

        async def run(client):
            await self.press(client, entry["ts"],
                             note="it is a security light, on by design")

        self.drive(run)
        rules = facts_store.exceptions("light.porch", "resident")
        self.assertEqual(len(rules), 1)
        self.assertIn("security light", rules[0]["text"])
        self.assertIn("binary_sensor.porch_motion", rules[0]["subjects"])
        self.assertEqual(rules[0]["about"],
                         "The porch light has been left on all night")
        # And a later look at that light is told it was dismissed.
        block = facts_store.retrieval_block(entities=["light.porch"])
        self.assertIn("not to be reported again: resident", block)

    def test_an_analyst_row_writes_no_rule(self):
        entry, _ = findings_store.add(
            "The hall is cold", severity="warning", source="analyst",
            source_title="Comfort", entity_id="sensor.hall_temp")

        async def run(client):
            await self.press(client, entry["ts"], note="no it is not")

        self.drive(run)
        self.assertEqual(facts_store.exception_map(), {})


if __name__ == "__main__":
    unittest.main()
