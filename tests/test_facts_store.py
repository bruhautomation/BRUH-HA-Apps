#!/usr/bin/env python3
"""The facts store under memory.md, and the loop the Wrong button promised.

Three claims, each driven rather than described:

  * a fact is tagged with what it is about, deterministically, and comes
    back for the subject and for a few words of a question;
  * Wrong on a check's finding writes an exception for that entity under
    that check, and the CHECK reads it — the same snapshot files both
    sensors with the key absent and only the uncorrected one with it
    present, which is the acceptance test the design page names;
  * a run's memory block carries the facts about the entities it reads and
    a fraction of the document's bytes, with the corpus cards unchanged.
"""

import asyncio
import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL))

import categories  # noqa: E402
import facts_store  # noqa: E402
import findings_store  # noqa: E402
from checks import devices  # noqa: E402
from checks._util import House  # noqa: E402

NOW = 1_789_800_000.0


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self._old = (facts_store.FACTS_FILE, facts_store.INGEST_STATE_FILE)
        facts_store.FACTS_FILE = root / "facts.json"
        facts_store.INGEST_STATE_FILE = root / "facts-ingest.json"

    def tearDown(self):
        facts_store.FACTS_FILE, facts_store.INGEST_STATE_FILE = self._old
        self.tmp.cleanup()


class TestAddAndRecall(StoreCase):
    def test_a_fact_is_filed_once_and_a_re_add_refreshes_it(self):
        row, created = facts_store.add(
            "The garage fridge is meant to run 24/7",
            subject="sensor.garage_fridge_temp", source="correction",
            ts=NOW - 86400)
        self.assertTrue(created)
        again, created2 = facts_store.add(
            "The garage fridge is meant to run 24/7",
            subject="sensor.garage_fridge_temp", source="correction", ts=NOW)
        self.assertFalse(created2)
        self.assertEqual(again["id"], row["id"])
        self.assertEqual(again["first_seen"], int(NOW - 86400))
        self.assertEqual(again["ts"], int(NOW))
        self.assertEqual(len(facts_store.recall(subject="sensor.garage_fridge_temp")), 1)

    def test_recall_by_subject_then_by_words(self):
        facts_store.add("We call the utility room the boot room",
                        subject="area:utility", source="chat", ts=NOW)
        facts_store.add("The porch motion sensor reads on all the time",
                        subject="binary_sensor.porch_motion", source="correction",
                        ts=NOW)
        facts_store.add("Nobody is home on Tuesdays until six",
                        subject="house", source="voice", ts=NOW)
        by_subject = facts_store.recall(subject="binary_sensor.porch_motion")
        self.assertEqual([r["subject"] for r in by_subject],
                         ["binary_sensor.porch_motion"])
        by_words = facts_store.recall(query="boot room")
        self.assertEqual(by_words[0]["subject"], "area:utility")
        # A query with nothing in common is not padded with unrelated facts.
        self.assertEqual(facts_store.recall(query="helicopter"), [])

    def test_recall_is_deterministic(self):
        for i in range(12):
            facts_store.add(f"Fact number {i} about the house",
                            subject="house", source="study", ts=NOW - i)
        first = [r["id"] for r in facts_store.recall(query="fact house")]
        second = [r["id"] for r in facts_store.recall(query="fact house")]
        self.assertEqual(first, second)

    def test_an_expired_fact_is_not_recalled(self):
        facts_store.add("The guest room heater is on for the visit",
                        subject="climate.guest", source="chat", ts=NOW,
                        expires="2026-09-01")
        self.assertEqual(facts_store.recall(subject="climate.guest",
                                            now=NOW + 40 * 86400), [])

    def test_forget_drops_one(self):
        row, _ = facts_store.add("Wrong thing", subject="house", ts=NOW)
        self.assertTrue(facts_store.forget(row["id"]))
        self.assertFalse(facts_store.forget(row["id"]))
        self.assertEqual(facts_store.recall(subject="house"), [])


class TestTagging(StoreCase):
    def test_entities_areas_and_people_are_subjects(self):
        got = facts_store.tag_subjects(
            "The lounge lamp light.lounge_lamp stays on for the cat",
            known_entities=frozenset({"light.lounge_lamp"}),
            areas={"lounge": "Lounge"}, person="ben")
        self.assertEqual(got, ["light.lounge_lamp", "area:lounge", "person:ben"])

    def test_a_fact_about_nothing_in_particular_is_about_the_house(self):
        self.assertEqual(facts_store.tag_subjects("We go to bed late"), ["house"])

    def test_an_unknown_id_shaped_word_is_not_an_entity_when_a_list_is_given(self):
        got = facts_store.tag_subjects("version.2 of the firmware",
                                       known_entities=frozenset({"light.hall"}))
        self.assertEqual(got, ["house"])


class TestTheInboxIsIngestedOnceAndNeverDrained(StoreCase):
    def setUp(self):
        super().setUp()
        self.inbox = Path(self.tmp.name) / "inbox"
        self.processed = self.inbox / "processed"
        self.inbox.mkdir()
        self.processed.mkdir()

    def write(self, folder, name, *records):
        with open(folder / name, "w", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")

    def test_lines_become_facts_and_the_files_stay(self):
        self.write(self.inbox, "1-panel.jsonl",
                   {"ts": int(NOW), "source": "correction",
                    "fact": "binary_sensor.porch_motion reads on all the time; "
                            "that is how it is wired", "confidence": "high"},
                   {"ts": int(NOW), "source": "assist", "fact": "We like it warm",
                    "confidence": "medium", "person": "ben"})
        self.write(self.processed, "0-study.jsonl",
                   {"ts": int(NOW - 99), "source": "study",
                    "fact": "The boiler is a 2019 Worcester", "confidence": "high"},
                   {"ts": int(NOW - 98), "source": "panel", "fact": "FORGET: x"})
        n = facts_store.ingest_inbox(self.inbox, self.processed,
                                     known_entities=frozenset({"binary_sensor.porch_motion"}))
        self.assertEqual(n, 3)
        self.assertTrue((self.inbox / "1-panel.jsonl").exists())
        porch = facts_store.recall(subject="binary_sensor.porch_motion")
        self.assertEqual(len(porch), 1)
        self.assertEqual(porch[0]["source"], "correction")
        ben = facts_store.recall(subject="person:ben")
        self.assertEqual(len(ben), 1)
        # A second sweep over the same files ingests nothing new.
        self.assertEqual(facts_store.ingest_inbox(self.inbox, self.processed), 0)
        # A file the consolidator moved is still one file.
        (self.inbox / "1-panel.jsonl").rename(self.processed / "1-panel.jsonl")
        self.assertEqual(facts_store.ingest_inbox(self.inbox, self.processed), 0)

    def test_a_torn_line_does_not_stop_the_rest(self):
        with open(self.inbox / "2-x.jsonl", "w", encoding="utf-8") as fh:
            fh.write('{"ts": 1, "source": "chat", "fact": "First"}\n')
            fh.write('{"ts": 2, "source": "chat", "fa')
        self.assertEqual(facts_store.ingest_inbox(self.inbox, self.processed), 1)


class TestExceptionsReachTheRule(StoreCase):
    """The acceptance test: a Wrong on a frozen-sensor finding suppresses
    that rule for that entity on the next pass, and nothing else."""

    def snapshot(self):
        days = [{"start": NOW - (7 - i) * 86400, "mean": 21.0, "min": 21.0,
                 "max": 21.0} for i in range(8)]
        state = {"state": "21.0", "last_updated": "2026-09-19T10:00:00+00:00",
                 "attributes": {"device_class": "temperature",
                                "unit_of_measurement": "°C",
                                "friendly_name": "Hall"}}
        return {
            "now": NOW,
            "states": {"sensor.hall_temp": dict(state),
                       "sensor.loft_temp": {**state, "attributes": {
                           **state["attributes"], "friendly_name": "Loft"}}},
            "entities": [{"entity_id": "sensor.hall_temp"},
                         {"entity_id": "sensor.loft_temp"}],
            "stats": {"sensor.hall_temp": list(days),
                      "sensor.loft_temp": list(days)},
            "available": {}, "errors": {},
        }

    def test_without_the_key_both_file_and_with_it_only_the_uncorrected_one(self):
        snap = self.snapshot()
        before = {r["entity_id"] for r in devices.frozen(snap, NOW)}
        self.assertEqual(before, {"sensor.hall_temp", "sensor.loft_temp"})

        facts_store.add("it is a contact on a cupboard nobody opens",
                        subject="sensor.hall_temp", source="correction",
                        predicate="exception:dev.frozen", ts=NOW)
        snap["facts"] = facts_store.exception_map(NOW)
        after = {r["entity_id"] for r in devices.frozen(snap, NOW)}
        self.assertEqual(after, {"sensor.loft_temp"})
        # The exception is for THIS rule: another check still sees the
        # entity.
        self.assertFalse(House(snap).excepted("sensor.hall_temp", "dev.implausible"))
        self.assertTrue(House(snap).excepted("sensor.hall_temp", "dev.frozen"))

    def test_a_whole_entity_exception_stands_every_rule_down(self):
        facts_store.add("stop telling me about this sensor",
                        subject="sensor.hall_temp", source="correction",
                        predicate="exception:*", ts=NOW)
        snap = {"facts": facts_store.exception_map(NOW)}
        self.assertTrue(House(snap).excepted("sensor.hall_temp", "dev.frozen"))
        self.assertTrue(House(snap).excepted("sensor.hall_temp", "base.unusual"))

    def test_an_unreadable_store_excepts_nothing(self):
        self.assertFalse(House({"facts": None}).excepted("sensor.x", "dev.frozen"))
        self.assertFalse(House({}).excepted("sensor.x", "dev.frozen"))


class TestWrongWritesTheException(unittest.TestCase):
    """Through the real `_end_finding`, on the real stores."""

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

    def tearDown(self):
        facts_store.FACTS_FILE, facts_store.INGEST_STATE_FILE = self._facts_old
        (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
         findings_store.STATE_FILE) = self._store_old
        self.server.facts_store = self._facts_srv
        self.server.MEMORY_INBOX_DIR = self._inbox_old
        self.tmp.cleanup()

    def test_wrong_on_a_check_row_records_the_rule_and_the_entity(self):
        entry, _ = findings_store.add(
            "Hall has read exactly the same value for a week",
            detail="21°C on every one of the last 8 days", fix="Check it",
            severity="warning", source="check:dev.frozen",
            source_title="Sensors frozen on one value",
            entity_id="sensor.hall_temp")
        spec = self.server.FINDING_VERBS["wrong"]
        asyncio.run(self.server._end_finding(
            findings_store.get(entry["ts"]), spec,
            "it is a contact on a cupboard nobody opens"))
        rows = facts_store.exceptions("sensor.hall_temp", "dev.frozen")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "correction")
        self.assertIn("cupboard", rows[0]["text"])
        self.assertEqual(facts_store.exception_map(), {"sensor.hall_temp": {"dev.frozen"}})

    def test_done_records_no_exception(self):
        entry, _ = findings_store.add(
            "Loft has read exactly the same value for a week",
            severity="warning", source="check:dev.frozen",
            source_title="Sensors frozen on one value",
            entity_id="sensor.loft_temp")
        asyncio.run(self.server._end_finding(
            findings_store.get(entry["ts"]), self.server.FINDING_VERBS["done"],
            "replaced the battery"))
        self.assertEqual(facts_store.exception_map(), {})

    def test_wrong_on_an_analyst_row_records_no_exception(self):
        entry, _ = findings_store.add(
            "The hall is cold", severity="warning", source="analyst",
            source_title="Comfort", entity_id="sensor.hall_temp")
        asyncio.run(self.server._end_finding(
            findings_store.get(entry["ts"]), self.server.FINDING_VERBS["wrong"],
            "no it is not"))
        self.assertEqual(facts_store.exception_map(), {})


class TestRetrievalCostsAFractionOfTheDocument(StoreCase):
    """A 20 KB document and two hundred facts; a run about ten entities gets
    every fact about those ten and well under a quarter of the bytes."""

    def test_the_block_is_small_and_complete(self):
        document = "# Home Memory\n\n## Preferences\n" + "\n".join(
            f"- Standing fact number {i} about how this house is run, in a "
            f"sentence long enough to cost something" for i in range(220))
        self.assertGreater(len(document), 20_000)
        wanted = [f"sensor.room_{i}_temp" for i in range(10)]
        for i in range(200):
            subject = wanted[i % 10] if i < 60 else f"light.other_{i}"
            facts_store.add(f"Fact {i} about {subject} and its habits",
                            subject=subject, source="study", ts=NOW - i)
        for i in range(6):
            facts_store.add(f"House preference {i}", subject="house",
                            source="chat", ts=NOW - i)

        block = facts_store.retrieval_block(entities=wanted, limit_chars=6_000)
        self.assertTrue(block.startswith(categories.MEMORY_HEAD))
        for eid in wanted:
            self.assertIn(eid, block)
        self.assertNotIn("light.other_", block)
        self.assertLess(len(block), 0.25 * len(document))

    def test_an_empty_store_falls_back_to_the_document(self):
        self.assertEqual(facts_store.retrieval_block(entities=["light.x"]), "")


if __name__ == "__main__":
    unittest.main()
