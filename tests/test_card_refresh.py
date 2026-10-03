#!/usr/bin/env python3
"""A card refreshes when what it READS moved — by content, not by stamp.

The fingerprint `refresh_mode: changed` gates on hashed three build stamps:
memory.md's mtime (the consolidator rewrites it every pass, including with
the card's own learned facts), each store's `updated_at` (rebuilt nightly
whatever it found) and the findings block (which listed the card's OWN
rows the moment the Resident promoted them). So the gate was a 24-hour
timer with extra steps. And the searching path handed memory retrieval
nothing about the card, so a correction filed under a room never reached
the card about that room.

Driven over the real server helpers, the real facts and findings stores
and the real `collect_orientation` (with only Core's two reads replaced).
Mutations:

  build stamp            hash `updated_at` -> a nightly rebuild that found
                         the same answer moves every card
  mtime                  stamp memory.md by mtime -> a pass that rewrote
                         the headings moves every card
  own rows               drop `exclude_sources` -> a card's own finding,
                         promoted, is news to the card that filed it
  unnamed card           a shipped id missing from CATEGORY_STORES -> it
                         reads every store and moves on every rebuild
  blind orientation      drop `domains`/`query` in collect_orientation ->
                         the room's correction never reaches its card
"""
from __future__ import annotations

import asyncio
import importlib
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import categories  # noqa: E402
import facts_store  # noqa: E402
import findings_store  # noqa: E402
import ha_data  # noqa: E402

NOW = 1_789_800_000.0


class Isolated(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.server = importlib.import_module("server")
        self._old = (facts_store.FACTS_FILE, facts_store.INGEST_STATE_FILE,
                     facts_store.RECONCILE_STATE_FILE,
                     findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
                     findings_store.STATE_FILE,
                     self.server.SHARED_MEMORY_FILE, self.server.facts_store)
        facts_store.FACTS_FILE = root / "facts.json"
        facts_store.INGEST_STATE_FILE = root / "facts-ingest.json"
        facts_store.RECONCILE_STATE_FILE = root / "facts-reconcile.json"
        findings_store.FINDINGS_FILE = root / "findings.json"
        findings_store.SETTLED_FILE = root / "settled.json"
        findings_store.STATE_FILE = root / "nowhere" / ".brain" / "s.json"
        self.memory = root / "memory.md"
        self.server.SHARED_MEMORY_FILE = self.memory
        self.server.facts_store = facts_store

    def tearDown(self):
        (facts_store.FACTS_FILE, facts_store.INGEST_STATE_FILE,
         facts_store.RECONCILE_STATE_FILE,
         findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
         findings_store.STATE_FILE,
         self.server.SHARED_MEMORY_FILE, self.server.facts_store) = self._old
        self.tmp.cleanup()


class TestEveryShippedCardNamesItsStores(unittest.TestCase):

    def test_the_table_is_exactly_the_shipped_cards(self):
        self.assertEqual(set(categories.CATEGORY_STORES),
                         set(categories.CATEGORY_IDS))

    def test_a_card_nobody_shipped_reads_everything(self):
        self.assertIsNone(categories.stores_for("custom-123"))
        self.assertEqual(categories.stores_for("health"), ())


class TestTheStoresPartIsWhatTheyFound(Isolated):

    def snap(self, **over) -> dict:
        stores = {
            "rhythm": {"state": "ready", "updated_at": 1,
                       "summary": "Up at 07:10 on weekdays"},
            "energy": {"state": "ready", "updated_at": 1,
                       "summary": "12 kWh a day"},
            "baselines": {"state": "collecting", "updated_at": 1,
                          "summary": "9 of 14 days"},
        }
        for name, patch in over.items():
            stores[name] = dict(stores[name], **patch)
        return {"stores": stores}

    def test_a_rebuild_that_found_the_same_answer_moves_nothing(self):
        first = self.server._store_stamp("overview", self.snap())
        again = self.server._store_stamp("overview", self.snap(
            rhythm={"updated_at": 99}, baselines={"updated_at": 99,
                                                  "summary": "10 of 14 days"}))
        self.assertEqual(first, again)

    def test_a_ready_stores_new_answer_moves_the_cards_that_read_it(self):
        moved = self.snap(rhythm={"summary": "Up at 06:40 on weekdays"})
        self.assertNotEqual(self.server._store_stamp("overview", self.snap()),
                            self.server._store_stamp("overview", moved))
        # Health reads no store, so nothing a store says moves it.
        self.assertEqual(self.server._store_stamp("health", self.snap()),
                         self.server._store_stamp("health", moved))

    def test_a_store_the_card_does_not_read_is_ignored(self):
        moved = self.snap(energy={"summary": "30 kWh a day"})
        self.assertEqual(self.server._store_stamp("lighting", self.snap()),
                         self.server._store_stamp("lighting", moved))


class TestTheMemoryPartIsWhatTheCardIsTold(Isolated):

    def test_a_rewrite_that_changed_no_fact_line_moves_nothing(self):
        self.memory.write_text("# Home Memory\n\n## Devices\n"
                               "- The boiler is serviced every October\n")
        first = self.server._memory_stamp(("climate",))
        self.memory.write_text("# Home Memory\n<!-- rewritten -->\n\n"
                               "## Devices\n\n"
                               "- The boiler is serviced every October\n")
        self.assertEqual(first, self.server._memory_stamp(("climate",)))
        self.memory.write_text("## Devices\n- The boiler is serviced every "
                               "April\n")
        self.assertNotEqual(first, self.server._memory_stamp(("climate",)))

    def test_with_facts_it_is_the_set_this_card_would_be_told(self):
        facts_store.add("The guest room is deliberately left unheated",
                        subject="climate.guest_room", source="correction",
                        ts=NOW)
        climate = self.server._memory_stamp(("climate",))
        lighting = self.server._memory_stamp(("light",))
        self.assertTrue(climate.startswith("facts:"))
        facts_store.add("The porch light is on a dusk timer",
                        subject="light.porch", source="chat", ts=NOW)
        self.assertEqual(climate, self.server._memory_stamp(("climate",)))
        self.assertNotEqual(lighting, self.server._memory_stamp(("light",)))


class TestACardsOwnRowsAreNotNewsToIt(Isolated):

    def test_the_cards_promoted_finding_does_not_move_its_findings_part(self):
        before = findings_store.prompt_block(("climate",))
        entry, _ = findings_store.add(
            "The guest room never reaches its setpoint", severity="warning",
            source="climate", source_title="Climate")
        findings_store.set_status(entry["ts"], "open")
        self.assertEqual(before, findings_store.prompt_block(("climate",)))
        self.assertNotEqual(before, findings_store.prompt_block(("energy",)))


class TestTheRecallStep(unittest.TestCase):

    def test_the_analyst_is_told_to_ask_memory_first(self):
        self.assertIn("`recall`", categories.ANALYST_SYSTEM)
        gather = categories.ANALYST_SYSTEM.split("HOW TO GATHER", 1)[1]
        self.assertLess(gather.index("recall"),
                        gather.index("Search, don't enumerate"))

    def test_and_may_call_it(self):
        import engine
        self.assertTrue(any(t.endswith("recall") for t in engine.ANALYST_TOOLS))


class TestTheOrientationCarriesWhatTheCardIsAbout(Isolated):

    def setUp(self):
        super().setUp()
        self.memory.write_text("# Home Memory\n")

        async def rest_get(session, path, **_kw):
            if path == "/config":
                return {"location_name": "Home", "time_zone": "UTC"}
            return [{"entity_id": "climate.guest_room", "state": "off",
                     "attributes": {}},
                    {"entity_id": "light.porch", "state": "on",
                     "attributes": {}}]

        async def registries(session):
            return {"entity_area": {"climate.guest_room": "Guest room"},
                    "entity_area_id": {"climate.guest_room": "guest_room"},
                    "entity_device": {}, "device_names": {},
                    "hidden": set()}

        self._fetch = (ha_data._rest_get, ha_data.get_registries)
        ha_data._rest_get = rest_get
        ha_data.get_registries = registries

    def tearDown(self):
        ha_data._rest_get, ha_data.get_registries = self._fetch
        super().tearDown()

    def test_the_cards_domains_reach_retrieval(self):
        facts_store.add("The guest room is deliberately left unheated",
                        subject="climate.guest_room", source="correction",
                        ts=NOW)
        blind = asyncio.run(ha_data.collect_orientation(question=None))
        told = asyncio.run(ha_data.collect_orientation(
            question=None, domains=("climate",)))
        self.assertNotIn("deliberately left unheated",
                         blind.get("context") or "")
        self.assertIn("deliberately left unheated", told.get("context") or "")

    def test_a_room_fact_reaches_a_question_about_it(self):
        facts_store.add("The guest room is only used at Christmas",
                        subject="area:guest_room", source="chat", ts=NOW)
        told = asyncio.run(ha_data.collect_orientation(
            question="why is the guest room cold?"))
        self.assertIn("only used at Christmas", told.get("context") or "")

    def test_the_rooms_of_the_entities_read(self):
        regs = {"entity_area_id": {"climate.guest_room": "guest_room",
                                   "light.porch": "outside",
                                   "light.hall": "guest_room"}}
        self.assertEqual(ha_data.areas_for(
            regs, ["climate.guest_room", "light.hall", "light.porch",
                   "sensor.unknown"]), ["guest_room", "outside"])
        self.assertEqual(ha_data.areas_for({}, ["light.porch"]), [])


if __name__ == "__main__":
    unittest.main()
