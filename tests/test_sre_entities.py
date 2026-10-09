#!/usr/bin/env python3
"""An overnight cause carries an entity, read off the records it cites.

`sre.parse_causes` keeps the model's `entity_id` only when it is one the
records name, and causes that cite device-level records (`zw:<node>`,
`zha:<ieee>`, `log:<hash>` for an integration) mostly came back with none:
`entity_id: ""` on the row, so it could not fold, could not be corrected
per entity and matched nothing on the To Do list — which is why the owner
saw the overnight check's causes filed again after moving them to To Do.

When the model names no valid entity the row takes a deterministic one off
the cited records (the first sorted entity of the cited device; for a log
line, of the integration it came from), never an invented one. Driven
through `sre.digest` / `sre.rows` and the real `_run_sre`.
"""

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))
sys.path.insert(0, str(BASE_DIR / "tests"))

import sre  # noqa: E402
from test_sre import NOW, PassCase, collected  # noqa: E402

ROUTER = "zha:aa:aa:aa:aa:aa:aa:aa:01"


def zwave_house() -> dict:
    """A Z-Wave node marked dead, its entities in the registry."""
    return collected(
        entities=[
            {"entity_id": "switch.landing_plug", "device_id": "dev-plug",
             "platform": "zha"},
            {"entity_id": "sensor.cellar_meter_node_status",
             "device_id": "dev-zw", "platform": "zwave_js",
             "unique_id": "123.45-node_status", "translation_key": "node_status",
             "entity_category": "diagnostic"},
            {"entity_id": "switch.cellar_pump", "device_id": "dev-zw",
             "platform": "zwave_js", "unique_id": "123.45-37-0-currentValue"},
            {"entity_id": "sensor.cellar_pump_power", "device_id": "dev-zw",
             "platform": "zwave_js", "unique_id": "123.45-50-0-value-66049"},
        ],
        devices=[{"id": "dev-zw", "name": "Cellar pump"}],
        states={"sensor.cellar_meter_node_status": {"state": "dead"}})


def cause(records, **over):
    row = {"title": "A cause", "records": records, "severity": "warning"}
    row.update(over)
    return row


class TestTheRowNamesAnEntity(unittest.TestCase):
    def rows_for(self, house, records, **over):
        dig = sre.digest(house, NOW)
        parsed = sre.parse_causes({"causes": [cause(records, **over)]}, dig)
        self.assertEqual(len(parsed["causes"]), 1)
        return sre.rows(parsed["causes"], dig, {"anchors": {}}, NOW)

    def test_a_zigbee_cause_takes_the_devices_entity(self):
        [row] = self.rows_for(collected(), [ROUTER])
        self.assertEqual(row["entity_id"], "switch.landing_plug")

    def test_a_zwave_cause_takes_a_device_entity_not_its_diagnostics(self):
        house = zwave_house()
        node = "zw:dev-zw"
        self.assertIn(node, [r["id"] for r in sre.digest(house, NOW)["records"]])
        [row] = self.rows_for(house, [node])
        self.assertEqual(row["entity_id"], "sensor.cellar_pump_power")

    def test_a_log_cause_takes_its_integrations_entity(self):
        dig = sre.digest(collected(), NOW)
        log_id = next(r["id"] for r in dig["records"] if r["kind"] == "log")
        [row] = self.rows_for(collected(), [log_id])
        self.assertEqual(row["entity_id"], "switch.landing_plug")

    def test_a_device_record_is_preferred_over_a_log_line(self):
        house = zwave_house()
        dig = sre.digest(house, NOW)
        log_id = next(r["id"] for r in dig["records"] if r["kind"] == "log")
        [row] = self.rows_for(house, [log_id, "zw:dev-zw"])
        self.assertEqual(row["entity_id"], "sensor.cellar_pump_power")

    def test_the_models_valid_entity_still_wins(self):
        house = zwave_house()
        [row] = self.rows_for(house, ["zw:dev-zw"],
                              entity_id="switch.cellar_pump")
        self.assertEqual(row["entity_id"], "switch.cellar_pump")

    def test_nothing_to_derive_from_is_still_no_entity(self):
        house = collected(entities=[], log=[{
            "name": "custom_components.nobody", "message": ["broke"],
            "level": "ERROR", "source": ["x.py", 1], "timestamp": NOW,
            "count": 3}])
        dig = sre.digest(house, NOW)
        log_id = next(r["id"] for r in dig["records"] if r["kind"] == "log")
        [row] = self.rows_for(house, [log_id])
        self.assertEqual(row["entity_id"], "")


class TestThroughThePass(PassCase):
    def setUp(self):
        super().setUp()
        import journal
        import todo_store
        root = Path(self.tmp.name)
        self._own = (journal.JOURNAL_FILE, todo_store.TODO_FILE,
                     todo_store.STATE_FILE)
        journal.JOURNAL_FILE = str(root / "journal.jsonl")
        todo_store.TODO_FILE = root / "todo.json"
        todo_store.STATE_FILE = root / "nowhere" / ".brain" / "todo.json"

    def tearDown(self):
        import journal
        import todo_store
        (journal.JOURNAL_FILE, todo_store.TODO_FILE,
         todo_store.STATE_FILE) = self._own
        super().tearDown()

    def test_the_filed_row_carries_the_entity(self):
        self.reply([{"title": "The landing router keeps dropping",
                     "records": [ROUTER]}])
        self.run_pass()
        [row] = self.rows()
        self.assertEqual(row["entity_id"], "switch.landing_plug")

    def test_a_new_anchor_about_the_same_entity_keeps_one_row(self):
        dig = sre.digest(self.collected, NOW)
        log_id = next(r["id"] for r in dig["records"] if r["kind"] == "log")
        self.reply([{"title": "The landing router keeps dropping",
                     "records": [ROUTER]}])
        self.run_pass()
        # Tomorrow the run cites the log line first: a new anchor, the same
        # plug. One row, and it is not cleared by the pass that refiled it.
        self.reply([{"title": "ZHA cannot reach the landing plug",
                     "records": [log_id, ROUTER]}])
        self.run_pass()
        rows = self.rows()
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(rows[0]["entity_id"], "switch.landing_plug")


if __name__ == "__main__":
    unittest.main()
