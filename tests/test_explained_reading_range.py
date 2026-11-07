#!/usr/bin/env python3
"""A reason typed on a reading's row holds while the reading stays explained.

"That's normal for this sensor" on a `base.unusual` or `dev.implausible` row
was a rule for ever: the check never spoke about that sensor again, at any
value. A reason that names a machine state already holds only in that state
(`chores.report_while`); one that names none now holds only while the
reading stays in the range the person was shown and explained — between the
usual and the reading on the card, with a margin (`explained` on the row,
kept on the rule by the press and read by `House._applies_now`). A reading
that leaves it is news again.

Driven with a dishwasher's water probe (the band check) and a hall
thermometer at an impossible 99 °C (the range check), and through the real
Wrong press, so the range written on the row is the one the rule reads.
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
from checks import baseline as band  # noqa: E402
from checks import devices  # noqa: E402
from checks._util import House  # noqa: E402
from test_house_checks import NOW as HOUSE_NOW  # noqa: E402
from test_house_checks import house  # noqa: E402
from test_running_machine_readings import NOW, WATER, dishwasher  # noqa: E402
from test_scoped_corrections import RouteCase  # noqa: E402

NORMAL = "That's normal for this sensor."
HALL = "sensor.hall_temp"


def rule(snap, eid, check, explained):
    snap["corrections"] = snap.get("corrections") or {
        "entity": {}, "area": {}, "check": {},
        "never": {"checks": sorted(corrections.NEVER_CHECKS)}}
    snap["corrections"]["entity"] = {eid: {check: {
        "text": NORMAL, "until": "", "id": "x", "explained": explained}}}
    return snap


class TestTheRowSaysWhatItExplains(unittest.TestCase):
    def test_the_band_row_carries_its_range(self):
        rows = band.unusual(dishwasher("finished", water=45.0), NOW)
        low, high = rows[0]["explained"]
        self.assertLessEqual(low, 21.0)
        self.assertGreaterEqual(high, 45.0)
        self.assertLess(high, 55.0)

    def test_the_impossible_row_carries_its_range(self):
        snap = house()
        snap["states"][HALL]["state"] = "99"
        rows = [r for r in devices.implausible(snap, HOUSE_NOW)
                if r["entity_id"] == HALL]
        low, high = rows[0]["explained"]
        self.assertLessEqual(low, 60.0)
        self.assertGreaterEqual(high, 99.0)
        self.assertLess(high, 130.0)


class TestTheRuleHoldsInsideTheRange(unittest.TestCase):
    def test_band_quiet_inside_and_news_outside(self):
        explained = band.unusual(dishwasher("finished", water=45.0),
                                 NOW)[0]["explained"]
        snap = rule(dishwasher("finished", water=46.0), WATER,
                    "base.unusual", explained)
        self.assertEqual(band.unusual(snap, NOW), [])
        snap = rule(dishwasher("finished", water=58.0), WATER,
                    "base.unusual", explained)
        self.assertEqual([r["entity_id"] for r in band.unusual(snap, NOW)],
                         [WATER])

    def test_impossible_quiet_inside_and_news_outside(self):
        snap = house()
        snap["states"][HALL]["state"] = "99"
        explained = [r for r in devices.implausible(snap, HOUSE_NOW)
                     if r["entity_id"] == HALL][0]["explained"]
        for value, filed in (("101", False), ("150", True)):
            snap = rule(house(), HALL, "dev.implausible", explained)
            snap["states"][HALL]["state"] = value
            ids = [r["entity_id"] for r in devices.implausible(snap,
                                                               HOUSE_NOW)]
            self.assertEqual(HALL in ids, filed, value)

    def test_a_rule_with_no_range_holds_as_it_always_did(self):
        snap = dishwasher("finished", water=58.0)
        snap["corrections"]["entity"] = {WATER: {"base.unusual": {
            "text": NORMAL, "until": "", "id": "x"}}}
        self.assertFalse(House(snap).should_report(WATER, "base.unusual"))


class TestThePressKeepsTheRange(RouteCase):
    ENTITY = WATER

    def test_the_rule_written_carries_the_rows_range(self):
        entry, created = findings_store.add(
            "Kitchen dishwasher Water temperature is reading far outside its "
            "usual range", severity="info", detail="55 °C now.",
            fix="Look at it", source="check:base.unusual",
            source_title="Unusual readings", entity_id=WATER,
            explained=[20.0, 58.4])
        self.assertTrue(created)
        stored = [f for f in findings_store.list_all()
                  if f.get("entity_id") == WATER]
        self.assertEqual(stored[0].get("explained"), [20.0, 58.4])

        async def body(client):
            res = await client.post(f"/api/finding/{entry['ts']}/wrong",
                                    json={"note": NORMAL})
            self.assertEqual(res.status, 200)
            await asyncio.gather(*list(self.server._CORRECTION_TASKS))

        self.drive(body)
        rules = [r for r in self.rules()
                 if r["predicate"] == "exception:base.unusual"]
        self.assertEqual([r.get("explained") for r in rules], [[20.0, 58.4]])
        table = corrections.scope_map()
        self.assertEqual(
            table["entity"][WATER]["base.unusual"].get("explained"),
            [20.0, 58.4])
        self.assertTrue(facts_store.export_rows())


if __name__ == "__main__":
    unittest.main()
