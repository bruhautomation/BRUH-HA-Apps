#!/usr/bin/env python3
"""The garden's season reaches brAIn's memory with nobody telling it.

Driven through the real `garden_facts.sync` into the real facts store, then
read back through `recall` the way the MCP tool asks: one fact per crop,
replaced (not piled up) as the totals move, aged out by its own expiry, and
"I could not look" (no GardenRX sensor) never read as "nothing was picked".
"""
from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "brain" / "panel"))

import facts_store  # noqa: E402
import garden_facts  # noqa: E402

SENSOR = "sensor.gardenrx_harvest_season"


def states(by_crop, state="12.5", year=2026):
    return {
        SENSOR: {"state": state, "attributes": {
            "gardenrx": "harvest", "year": year, "by_crop": by_crop}},
        "light.kitchen": {"state": "on", "attributes": {}},
    }


def crop(name, lb, picks, value=0, last="2026-09-30T10:00:00Z", count=0):
    return {"crop": name, "lb": lb, "picks": picks, "value": value,
            "last_at": last, "count": count}


class GardenFactsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self._old = (facts_store.FACTS_FILE, facts_store.INGEST_STATE_FILE)
        facts_store.FACTS_FILE = root / "facts.json"
        facts_store.INGEST_STATE_FILE = root / "ingest.json"

    def tearDown(self):
        facts_store.FACTS_FILE, facts_store.INGEST_STATE_FILE = self._old
        self.tmp.cleanup()

    def garden_rows(self):
        return [r for r in facts_store._load() if r.get("source") == "gardenrx"]


class TestOneFactPerCrop(GardenFactsCase):
    def test_each_crop_is_one_fact_recall_finds(self):
        now = time.time()
        crops = [crop(f"Crop{i}", 3 + i, 2) for i in range(6)]
        crops[0] = crop("Tomatoes", 12.5, 9, value=31.4)
        self.assertEqual(garden_facts.sync(states(crops), now), 6)
        rows = self.garden_rows()
        self.assertEqual(len(rows), 6)
        tomato = next(r for r in rows if "Tomatoes" in r["text"])
        self.assertIn("12.5 lb over 9 picks", tomato["text"])
        self.assertIn("2026", tomato["text"])
        self.assertIn("last picked 2026-09-30", tomato["text"])
        self.assertEqual(tomato["subject"], SENSOR)
        self.assertGreater(tomato["expires"], facts_store._day(now))
        # `recall garden` returns every crop: the per-subject cap is per key
        # for a keyed fact, or six crops under one sensor would read as three.
        got = facts_store.recall(query="garden", limit=20)
        self.assertEqual(len([r for r in got if r["source"] == "gardenrx"]), 6)

    def test_new_totals_replace_the_old_rather_than_piling_up(self):
        now = time.time()
        garden_facts.sync(states([crop("Tomatoes", 12.5, 9), crop("Beans", 2, 1)]), now)
        garden_facts.sync(states([crop("Tomatoes", 14, 10)]), now + 3600)
        rows = self.garden_rows()
        self.assertEqual(len(rows), 1, [r["text"] for r in rows])
        self.assertIn("14 lb over 10 picks", rows[0]["text"])

    def test_an_unchanged_season_keeps_its_first_seen(self):
        now = time.time()
        season = states([crop("Kale", 4, 3)])
        garden_facts.sync(season, now)
        first = self.garden_rows()[0]["first_seen"]
        garden_facts.sync(season, now + 7200)
        rows = self.garden_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["first_seen"], first)

    def test_a_counted_crop_says_so(self):
        garden_facts.sync(states([crop("Squash", 0, 2, count=5)]), time.time())
        self.assertIn("5 counted over 2 picks", self.garden_rows()[0]["text"])

    def test_an_expired_season_is_not_recalled(self):
        then = time.time() - 30 * 86400
        garden_facts.sync(states([crop("Peas", 1, 1)]), then)
        self.assertEqual(self.garden_rows()[0]["expires"] < facts_store._day(time.time()), True)
        self.assertEqual(facts_store.recall(query="garden"), [])

    def test_other_sources_are_never_touched(self):
        facts_store.add("The garden hose is in the shed.", source="person")
        garden_facts.sync(states([crop("Peas", 1, 1)]), time.time())
        garden_facts.sync(states([]), time.time())
        rows = facts_store._load()
        self.assertEqual([r["source"] for r in rows], ["person"])


class TestCouldNotLookIsNotNothing(GardenFactsCase):
    def test_no_sensor_or_no_reading_leaves_the_facts_alone(self):
        garden_facts.sync(states([crop("Peas", 1, 1)]), time.time())
        for snap in ({"light.kitchen": {"state": "on", "attributes": {}}},
                     states([crop("Peas", 9, 9)], state="unavailable"),
                     {SENSOR: {"state": "3", "attributes": {"gardenrx": "harvest"}}}):
            self.assertIsNone(garden_facts.sync(snap, time.time()))
        self.assertEqual(len(self.garden_rows()), 1)
        self.assertIn("1 lb over 1 pick,", self.garden_rows()[0]["text"])

    def test_an_empty_season_clears_them(self):
        garden_facts.sync(states([crop("Peas", 1, 1)]), time.time())
        self.assertEqual(garden_facts.sync(states([]), time.time()), 0)
        self.assertEqual(self.garden_rows(), [])


class TestTheChecksPassFilesIt(GardenFactsCase):
    def test_run_checks_calls_it_with_the_states_it_already_has(self):
        server = (Path(__file__).resolve().parent.parent / "brain" / "panel"
                  / "server.py").read_text(encoding="utf-8")
        start = server.index("async def run_checks(")
        body = server[start:server.index("result = checks.run_all(snapshot, started)", start)]
        self.assertIn("_record_garden, snapshot, started", body)

    def test_the_pass_files_and_a_failure_does_not_stop_it(self):
        import server  # noqa: PLC0415
        snap = {"states": states([crop("Plums", 6, 4)])}
        self.assertEqual(server._record_garden(snap, time.time()), 1)
        self.assertIn("Plums", self.garden_rows()[0]["text"])
        self.assertIsNone(server._record_garden({"states": "not a map"}, time.time()))


if __name__ == "__main__":
    unittest.main()
