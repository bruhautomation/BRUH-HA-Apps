#!/usr/bin/env python3
"""A condition said without "only … when" is still a condition.

A house answered Wrong with reasons that carry a condition — "only unusual
if hot while the printer is idle", "only the ecobee sensor counts", "turns
on only when the Climate 3 ecobee reads >60%" — and some were stored as an
UNCONDITIONAL rule: `exception:<check>` on the sensor, or
`exception:resident` on every entity the case named. `corrections.conditional`
knew one shape ("only … when/if/while", "unless") and nothing else, while
`chores.report_while` already read "normal while it is running" as a
condition: so a reason the check could read as a state was, at the press,
a plain rule a model could then widen, and on a device with no status to
read it was a whole-entity mute.

Driven with examples the report never named: a dishwasher's "that's
normal while the dishwasher is running", and a Resident case about two
humidity sensors answered "only the bathroom sensor counts".
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
from checks._util import House  # noqa: E402
from test_running_machine_readings import STATE, WATER, dishwasher  # noqa: E402
from test_scoped_corrections import RouteCase  # noqa: E402

NORMAL_WHILE = "That's normal while the dishwasher is running."
ONLY_ONE_COUNTS = "Only the bathroom sensor counts."


class TestTheShapesAreConditions(unittest.TestCase):
    def test_said_without_only_when(self):
        for said in (NORMAL_WHILE, ONLY_ONE_COUNTS,
                     "fine during a wash",
                     "Expected when the kettle is boiling",
                     "only the ecobee sensor counts",
                     "only the upstairs one matters",
                     "it's a problem except when the heating is on"):
            self.assertTrue(corrections.conditional(said), said)

    def test_a_plain_reason_still_is_not(self):
        for said in ("it's mains powered", "not a problem here",
                     "it is the only one in the house", "that's normal",
                     "normal for this sensor"):
            self.assertFalse(corrections.conditional(said), said)


class TestACheckReasonSaidAsNormalWhile(RouteCase):
    ENTITY = WATER

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

    def test_no_status_to_read_writes_no_mute_and_asks(self):
        self.press(NORMAL_WHILE)
        self.assertEqual(self.rules(), [])
        kept = [r for r in facts_store.export_rows()
                if r.get("text") == NORMAL_WHILE]
        self.assertTrue(kept, facts_store.export_rows())
        self.assertFalse(kept[0].get("predicate"))
        self.assertEqual(len(self.questions()), 1)

    def test_a_status_to_read_writes_the_conditional_rule_and_no_wider(self):
        self.server._MACHINE_STATUS[self.ENTITY] = STATE
        self.replies["correct"] = {"scope": "entity", "lifetime": "permanent"}
        self.press(NORMAL_WHILE)
        rules = self.rules()
        self.assertEqual([(r["subject"], r["predicate"]) for r in rules],
                         [(self.ENTITY, "exception:base.unusual")])
        self.assertEqual(rules[0]["text"], NORMAL_WHILE)
        self.assertNotIn("correct", self.model_jobs())

    def test_the_rule_written_still_raises_the_reading_at_rest(self):
        self.server._MACHINE_STATUS[self.ENTITY] = STATE
        self.press(NORMAL_WHILE)
        text = self.rules()[0]["text"]
        for word, reported in (("finished", True), ("ready", True),
                               ("run", False)):
            snap = dishwasher(word)
            snap["corrections"]["entity"] = {
                WATER: {"base.unusual": {"text": text, "until": "",
                                         "id": "x"}}}
            self.assertEqual(
                House(snap).should_report(WATER, "base.unusual"), reported,
                word)


class TestAResidentCaseNamingWhichSensorCounts(RouteCase):
    ENTITY = "sensor.bathroom_humidity"
    OTHER = "sensor.landing_humidity"

    def test_no_rule_on_every_entity_and_a_fact_instead(self):
        row = findings_store.add_case({
            "text": "The bathroom fan did not run while it was humid",
            "claim": "The bathroom fan did not run while it was humid",
            "kind": "problem", "severity": "warning",
            "entity_id": self.ENTITY,
            "evidence": [{"entity": self.ENTITY, "value": "78",
                          "when": "08:00"},
                         {"entity": self.OTHER, "value": "71",
                          "when": "08:00"}]}, run_id="look-2")
        self.assertIsNotNone(row)

        async def body(client):
            res = await client.post(f"/api/finding/{row['ts']}/wrong",
                                    json={"note": ONLY_ONE_COUNTS})
            self.assertEqual(res.status, 200)

        self.drive(body)
        self.assertEqual(self.rules(), [])
        kept = [r for r in facts_store.export_rows()
                if r.get("text") == ONLY_ONE_COUNTS]
        self.assertTrue(kept, facts_store.export_rows())
        self.assertFalse(kept[0].get("predicate"))
        self.assertNotIn("correct", self.model_jobs())

    def test_the_sentence_says_it_was_kept_not_muted(self):
        said = corrections.conditional_confirmation(
            "Bathroom humidity", note=ONLY_ONE_COUNTS)
        self.assertIn("fact", said)
        self.assertNotIn("won't flag", said)
        self.assertNotIn("meant to run", said)


if __name__ == "__main__":
    unittest.main()
