#!/usr/bin/env python3
""""It only turns on when…" is a condition, not "never say anything again".

Seen on a house: the homeowner answered a card about a dehumidifier with
"it only turns on when the thermostat's humidity reads above 60%", pressed
Wrong, and the answer was stored as a blanket `exception:resident` on the
unit and its sensor — so brAIn could never again say anything about the
unit, including on the day the condition held and it stayed off.

A reason that says WHEN the thing is meant to act is kept as a fact about
the condition, filed under the device, and writes no blanket rule for the
Resident; on a house check it is never widened past the press's own rule
(that check, that entity). The sentence said back says which happened.

Driven through the real routes with only the model stubbed.
"""

import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "brain"
                       / "panel"))

import corrections  # noqa: E402
import facts_store  # noqa: E402
import findings_store  # noqa: E402
from test_scoped_corrections import RouteCase  # noqa: E402

CONDITION = ("It only turns on when the landing thermostat's humidity reads "
             "above 60%.")


class TestTheWordsAreRead(unittest.TestCase):
    def test_a_condition_is_recognised(self):
        for said in (CONDITION,
                     "only runs if the cellar is above 60",
                     "it comes on only when the heating is off",
                     "It's meant to stay off unless the room is damp"):
            self.assertTrue(corrections.conditional(said), said)

    def test_a_plain_reason_is_not(self):
        for said in ("it's mains powered", "not a problem here",
                     "it is the only one in the house"):
            self.assertFalse(corrections.conditional(said), said)


class TestAResidentCaseKeepsTheCondition(RouteCase):
    def resident_row(self) -> dict:
        row = findings_store.add_case({
            "text": "The cupboard dehumidifier has not run all week",
            "claim": "The cupboard dehumidifier has not run all week",
            "kind": "problem", "severity": "warning",
            "entity_id": self.ENTITY,
            "evidence": [{"entity": self.ENTITY, "value": "off",
                          "when": "08:00"}]}, run_id="look-1")
        self.assertIsNotNone(row)
        return row

    def press_wrong(self, row: dict, note: str) -> int:
        out = {}

        async def body(client):
            res = await client.post(f"/api/finding/{row['ts']}/wrong",
                                    json={"note": note})
            out["status"] = res.status

        self.drive(body)
        return out["status"]

    def test_no_blanket_rule_and_a_fact_about_the_condition(self):
        row = self.resident_row()
        self.assertEqual(self.press_wrong(row, CONDITION), 200)
        self.assertEqual(self.rules(), [])
        facts = [r for r in facts_store.export_rows()
                 if "60%" in str(r.get("text") or "")]
        self.assertTrue(facts, facts_store.export_rows())
        self.assertIn(self.ENTITY, facts[0].get("subjects") or
                      [facts[0].get("subject")])
        self.assertFalse(facts[0].get("predicate"))
        self.assertNotIn("correct", self.model_jobs())

    def test_a_plain_reason_still_writes_the_rule(self):
        row = self.resident_row()
        self.assertEqual(self.press_wrong(row, "it's mains powered"), 200)
        self.assertTrue(self.rules())

    def test_the_sentence_said_back_names_the_condition(self):
        row = self.resident_row()
        said = asyncio.run(self.server._morph_wrong(
            f"f:{row['ts']}", findings_store.get(row["ts"]), CONDITION))
        self.assertIn("remember", said)
        self.assertIn("when", said)
        self.assertNotIn("won't flag", said)
        self.assertEqual(self.rules(), [])


class TestACheckRuleIsNeverWidenedByACondition(RouteCase):
    def test_a_conditional_reason_stays_on_the_press_rule(self):
        the_plan = corrections.plan(
            {"scope": "entity", "lifetime": "permanent"},
            {"source": "check:dev.frozen", "entity_id": self.ENTITY},
            note=CONDITION)
        self.assertEqual(the_plan["scope"], "entity_check")
        self.assertTrue(the_plan["conditional"])
        self.assertIn("remember", corrections.confirmation(
            the_plan, entity_name="Cupboard door"))


if __name__ == "__main__":
    unittest.main()
