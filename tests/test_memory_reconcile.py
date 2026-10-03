#!/usr/bin/env python3
"""One truth for forgetting: the facts store answers to the document.

The store is filed from the memory inbox within a minute, before the
consolidator has judged a line — and every way a person or a pass takes a
fact back (`FORGET:`, editing `memory.md`, `brain memory clear`, the
inbox's ✕, an undo) used to reach the document and leave the store
asserting the old thing to every run that reads it. Each test drives the
real module over a real temporary store, and names the mutation it fails
under.

  pending/kept/dropped   reconcile marks rows by whether the queue still
                         holds them and whether the document carries them
  left the document      a kept row the document stopped carrying goes
  clear                  an emptied document forgets everything not pending
  unreadable document    `None` decides nothing about any row
  orphan                 a fact about an entity the house no longer has
                         stops being retrieved at once, goes after 30 days
  FORGET:                an inbox `FORGET:` line takes the store's copy too,
                         exceptions included, and lands after the archive
  near-dedupe            a paraphrase is one row; a negation is not
  exception ids          two Wrongs on one sensor under two checks are two
                         rules, not one rule with a predicate overwritten
  retrieval              rooms and the question reach the block; an unnamed
                         subject is capped; the fingerprint moves with the set
  export/merge           the rules travel; an existing id wins
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import facts_store  # noqa: E402

NOW = 1_789_800_000.0
DAY = 86400.0


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._old = (facts_store.FACTS_FILE, facts_store.INGEST_STATE_FILE,
                     facts_store.RECONCILE_STATE_FILE)
        facts_store.FACTS_FILE = self.root / "facts.json"
        facts_store.INGEST_STATE_FILE = self.root / "facts-ingest.json"
        facts_store.RECONCILE_STATE_FILE = self.root / "facts-reconcile.json"
        self.inbox = self.root / "inbox"
        self.processed = self.inbox / "processed"
        self.processed.mkdir(parents=True)

    def tearDown(self):
        (facts_store.FACTS_FILE, facts_store.INGEST_STATE_FILE,
         facts_store.RECONCILE_STATE_FILE) = self._old
        self.tmp.cleanup()

    def queue(self, name: str, *lines: dict, folder: Path | None = None):
        path = (folder or self.inbox) / name
        path.write_text("".join(json.dumps(line) + "\n" for line in lines),
                        encoding="utf-8")
        return path

    def texts(self) -> list[str]:
        return sorted(r["text"] for r in facts_store.export_rows())

    def row(self, text: str) -> dict:
        for r in facts_store.export_rows():
            if r["text"] == text:
                return r
        raise AssertionError(f"no row {text!r}")


class TestTheDocumentIsTheCuratedTruth(StoreCase):

    def setUp(self):
        super().setUp()
        for text in ("The porch light runs on a dusk timer",
                     "The boiler is serviced every October",
                     "Somebody turned the kettle on at 07:02"):
            facts_store.add(text, subject="house", source="voice", ts=NOW)

    def test_pending_kept_and_dropped(self):
        self.queue("a.jsonl", {"fact": "The porch light runs on a dusk timer",
                               "source": "voice"})
        doc = ("# Home Memory\n\n## Devices\n"
               "- The boiler gets serviced every October (observed 2026-09)\n")
        out = facts_store.reconcile(doc, self.inbox, now=NOW, force=True)
        self.assertEqual(out["pending"], 1, out)
        self.assertEqual(out["kept"], 1, out)
        self.assertEqual(out["dropped"], 1, out)
        self.assertEqual(self.row("The porch light runs on a dusk timer")
                         ["curation"], "pending")
        self.assertEqual(self.row("The boiler is serviced every October")
                         ["curation"], "kept")
        dropped = self.row("Somebody turned the kettle on at 07:02")
        self.assertEqual(dropped["curation"], "dropped")
        # A dropped row keeps its subjects but is no longer a standing fact
        # read to every run.
        block = facts_store.retrieval_block(entities=["light.x"], now=NOW)
        self.assertIn("serviced every October", block)
        self.assertNotIn("kettle", block)

    def test_a_line_that_left_the_document_leaves_the_store(self):
        doc = "## Devices\n- The boiler is serviced every October\n"
        facts_store.reconcile(doc, self.inbox, now=NOW, force=True)
        self.assertEqual(self.row("The boiler is serviced every October")
                         ["curation"], "kept")
        # A person deletes the line from memory.md.
        out = facts_store.reconcile("## Devices\n- Something else entirely\n",
                                    self.inbox, now=NOW + 60, force=True)
        self.assertGreaterEqual(out["forgotten"], 1, out)
        self.assertNotIn("The boiler is serviced every October", self.texts())

    def test_clearing_the_document_forgets_everything_not_waiting(self):
        self.queue("a.jsonl", {"fact": "The porch light runs on a dusk timer",
                               "source": "voice"})
        facts_store.reconcile("## Devices\n- The boiler is serviced every "
                              "October\n", self.inbox, now=NOW, force=True)
        facts_store.reconcile("", self.inbox, now=NOW + 60, force=True)
        self.assertEqual(self.texts(), ["The porch light runs on a dusk timer"])

    def test_an_unreadable_document_decides_nothing(self):
        before = facts_store.export_rows()
        out = facts_store.reconcile(None, self.inbox, now=NOW, force=True)
        self.assertEqual(out["forgotten"], 0)
        self.assertEqual(facts_store.export_rows(), before)

    def test_an_unreadable_queue_decides_nothing(self):
        before = facts_store.export_rows()
        out = facts_store.reconcile("## x\n- y\n", self.root / "no-such-dir",
                                    now=NOW, force=True)
        # A missing directory is an empty queue; what may not happen is a
        # forget of a row the document never carried.
        self.assertEqual(out["forgotten"], 0, out)
        self.assertEqual(len(facts_store.export_rows()), len(before))

    def test_exceptions_are_never_curated_away(self):
        facts_store.add("It is a contact on a cupboard nobody opens",
                        subject="binary_sensor.cupboard",
                        source="correction",
                        predicate="exception:dev.frozen", ts=NOW)
        facts_store.reconcile("", self.inbox, now=NOW, force=True)
        facts_store.reconcile("", self.inbox, now=NOW + 60, force=True)
        self.assertIn("It is a contact on a cupboard nobody opens",
                      self.texts())

    def test_an_unchanged_pass_is_skipped(self):
        doc = "## Devices\n- The boiler is serviced every October\n"
        first = facts_store.reconcile(doc, self.inbox, now=NOW)
        second = facts_store.reconcile(doc, self.inbox, now=NOW)
        self.assertFalse(first["skipped"])
        self.assertTrue(second["skipped"])


class TestAFactAboutNothingStopsBeingTold(StoreCase):

    def test_orphan_hidden_then_forgotten(self):
        facts_store.add("The hall sensor sits behind the coats",
                        subject="sensor.hall_motion", source="chat", ts=NOW)
        known = {"light.porch"}
        out = facts_store.reconcile(None, self.inbox, known_entities=known,
                                    registry_fresh=True, now=NOW, force=True)
        self.assertEqual(out["orphaned"], 1, out)
        self.assertTrue(self.row("The hall sensor sits behind the coats")
                        ["gone_since"])
        self.assertEqual(facts_store.retrieval_block(
            entities=["sensor.hall_motion"], now=NOW), "")
        later = NOW + (facts_store.ORPHAN_DAYS + 1) * DAY
        facts_store.reconcile(None, self.inbox, known_entities=known,
                              registry_fresh=True, now=later, force=True)
        self.assertEqual(self.texts(), [])

    def test_a_registry_that_is_not_fresh_orphans_nothing(self):
        facts_store.add("The hall sensor sits behind the coats",
                        subject="sensor.hall_motion", source="chat", ts=NOW)
        facts_store.reconcile(None, self.inbox, known_entities={"light.x"},
                              registry_fresh=False, now=NOW, force=True)
        self.assertNotIn("gone_since",
                         self.row("The hall sensor sits behind the coats"))

    def test_an_entity_that_comes_back_is_told_again(self):
        facts_store.add("The hall sensor sits behind the coats",
                        subject="sensor.hall_motion", source="chat", ts=NOW)
        facts_store.reconcile(None, self.inbox, known_entities={"light.x"},
                              registry_fresh=True, now=NOW, force=True)
        facts_store.reconcile(None, self.inbox,
                              known_entities={"sensor.hall_motion"},
                              registry_fresh=True, now=NOW + 60, force=True)
        self.assertNotIn("gone_since",
                         self.row("The hall sensor sits behind the coats"))


class TestTheInboxSweep(StoreCase):

    def test_forget_in_the_queue_takes_the_archived_fact(self):
        self.queue("old.jsonl", {"fact": "The garage door sticks in winter",
                                 "source": "chat"}, folder=self.processed)
        self.queue("new.jsonl",
                   {"fact": "FORGET: the garage door sticks in winter",
                    "source": "person"})
        facts_store.ingest_inbox(self.inbox, self.processed)
        self.assertEqual(self.texts(), [])

    def test_forget_reaches_an_exception(self):
        facts_store.add("The cupboard contact never moves, by design",
                        subject="binary_sensor.cupboard",
                        source="correction",
                        predicate="exception:dev.frozen", ts=NOW)
        self.assertEqual(facts_store.forget_matching(
            "the cupboard contact never moves by design"), 1)

    def test_a_one_word_request_takes_only_an_exact_match(self):
        facts_store.add("The fridge door is left ajar for the cat",
                        subject="house", source="chat", ts=NOW)
        self.assertEqual(facts_store.forget_matching("fridge"), 0)

    def test_the_writer_subject_and_run_survive(self):
        self.queue("a.jsonl", {"fact": "That plug is the dehumidifier",
                               "source": "correction",
                               "subject": "switch.plug_3",
                               "subjects": ["sensor.plug_3_power"],
                               "run_id": "run-abc"})
        facts_store.ingest_inbox(self.inbox, self.processed)
        row = self.row("That plug is the dehumidifier")
        self.assertEqual(row["subject"], "switch.plug_3")
        self.assertIn("sensor.plug_3_power", row["subjects"])
        self.assertNotIn("house", row["subjects"])
        self.assertEqual(row["run_id"], "run-abc")

    def test_a_device_health_snapshot_expires(self):
        self.queue("a.jsonl",
                   {"fact": "The hall sensor battery is low", "ts": NOW,
                    "source": "voice"},
                   {"fact": "The hall sensor battery is replaced every "
                            "spring", "ts": NOW, "source": "voice"})
        facts_store.ingest_inbox(self.inbox, self.processed)
        snap = self.row("The hall sensor battery is low")
        self.assertTrue(snap["expires"])
        self.assertEqual(self.row(
            "The hall sensor battery is replaced every spring")["expires"], "")
        later = NOW + (facts_store.TRANSIENT_DAYS + 2) * DAY
        self.assertNotIn("battery is low",
                         facts_store.retrieval_block(
                             entities=["sensor.anything"], now=later))

    def test_a_paraphrase_is_one_row_and_a_negation_is_not(self):
        self.queue("a.jsonl",
                   {"fact": "The porch light runs on a dusk timer",
                    "source": "chat"},
                   {"fact": "The porch light runs on a dusk timer schedule",
                    "source": "chat"},
                   {"fact": "The porch light does not run on a dusk timer",
                    "source": "chat"})
        facts_store.ingest_inbox(self.inbox, self.processed)
        texts = self.texts()
        self.assertEqual(len(texts), 2, texts)
        self.assertIn("The porch light does not run on a dusk timer", texts)

    def test_short_sentences_are_never_merged(self):
        facts_store.add("Lounge is warm", subject="house", ts=NOW,
                        near_dedupe=True)
        facts_store.add("Lounge is cold", subject="house", ts=NOW,
                        near_dedupe=True)
        self.assertEqual(len(self.texts()), 2)


class TestTwoRulesOnOneSensor(StoreCase):

    def test_the_predicate_is_part_of_the_id(self):
        for check in ("dev.frozen", "base.unusual"):
            facts_store.add("That is normal for this sensor.",
                            subject="sensor.hall", source="correction",
                            predicate=f"exception:{check}", ts=NOW,
                            finding_key=f"key {check}")
        self.assertEqual(facts_store.exception_map(now=NOW),
                         {"sensor.hall": {"dev.frozen", "base.unusual"}})
        # Raising one again takes that rule and leaves the other.
        self.assertEqual(facts_store.forget_exceptions("key dev.frozen"), 1)
        self.assertEqual(facts_store.exception_map(now=NOW),
                         {"sensor.hall": {"base.unusual"}})

    def test_an_ordinary_fact_keeps_the_id_it_always_had(self):
        self.assertEqual(facts_store.fact_id("house", "x"),
                         facts_store.fact_id("house", "x", ""))
        self.assertNotEqual(
            facts_store.fact_id("house", "x", "exception:dev.frozen"),
            facts_store.fact_id("house", "x"))

    def test_forget_text_leaves_exceptions(self):
        facts_store.add("That is normal here", subject="sensor.hall",
                        source="correction", predicate="exception:dev.frozen",
                        ts=NOW)
        facts_store.add("That is normal here", subject="sensor.hall",
                        source="correction", ts=NOW)
        self.assertEqual(facts_store.forget_text("That is normal here",
                                                 "correction"), 1)
        self.assertEqual(facts_store.exception_map(now=NOW),
                         {"sensor.hall": {"dev.frozen"}})


class TestRetrievalByRoomAndQuestion(StoreCase):

    def test_a_room_fact_reaches_a_run_about_the_room(self):
        facts_store.add("The lounge gets the evening sun",
                        subject="area:lounge", source="chat", ts=NOW)
        self.assertIn("evening sun", facts_store.retrieval_block(
            areas=["lounge"], now=NOW))
        self.assertEqual(facts_store.retrieval_block(
            entities=["light.kitchen"], now=NOW), "")

    def test_the_question_reaches_a_fact_tagged_elsewhere(self):
        facts_store.add("The greenhouse heater only runs below five degrees",
                        subject="switch.greenhouse_heater", source="chat",
                        ts=NOW)
        block = facts_store.retrieval_block(
            query="why is the greenhouse heater off", now=NOW)
        self.assertIn("greenhouse heater", block)

    def test_an_unnamed_subject_is_capped(self):
        for i in range(8):
            facts_store.add(f"Boiler note {i} about pressure and flow",
                            subject="climate.boiler", source="study",
                            ts=NOW - i)
        block = facts_store.retrieval_block(
            query="boiler pressure flow", now=NOW)
        self.assertEqual(block.count("Boiler note"),
                         facts_store.PER_SUBJECT_CAP)
        # Named, the cap does not apply.
        named = facts_store.retrieval_block(entities=["climate.boiler"],
                                            now=NOW)
        self.assertEqual(named.count("Boiler note"), 8)

    def test_the_fingerprint_moves_with_the_set_and_not_the_date(self):
        facts_store.add("The lounge gets the evening sun",
                        subject="area:lounge", source="chat", ts=NOW)
        first = facts_store.retrieval_fingerprint(areas=["lounge"], now=NOW)
        facts_store.add("The lounge gets the evening sun",
                        subject="area:lounge", source="chat", ts=NOW + DAY)
        self.assertEqual(first, facts_store.retrieval_fingerprint(
            areas=["lounge"], now=NOW + DAY))
        facts_store.add("The lounge radiator is oversized",
                        subject="area:lounge", source="chat", ts=NOW + DAY)
        self.assertNotEqual(first, facts_store.retrieval_fingerprint(
            areas=["lounge"], now=NOW + DAY))
        self.assertEqual(facts_store.retrieval_fingerprint(
            areas=["garage"], now=NOW), "")


class TestTheRulesTravel(StoreCase):

    def test_export_and_merge_carry_the_exception(self):
        facts_store.add("It is a contact on a cupboard nobody opens",
                        subject="binary_sensor.cupboard", source="correction",
                        predicate="exception:dev.frozen", ts=NOW,
                        finding_key="cupboard frozen")
        exported = facts_store.export_rows()
        # A second install, empty.
        facts_store.FACTS_FILE = self.root / "other.json"
        self.assertEqual(facts_store.merge_rows(exported), 1)
        self.assertEqual(facts_store.exception_map(now=NOW),
                         {"binary_sensor.cupboard": {"dev.frozen"}})
        self.assertEqual(facts_store.export_rows()[0]["finding_key"],
                         "cupboard frozen")

    def test_an_existing_id_wins(self):
        facts_store.add("The porch light runs on a dusk timer",
                        subject="house", source="chat", confidence="high",
                        ts=NOW)
        incoming = [{"text": "The porch light runs on a dusk timer",
                     "subject": "house", "confidence": 0.1,
                     "source": "import"}]
        self.assertEqual(facts_store.merge_rows(incoming), 0)
        self.assertEqual(self.row("The porch light runs on a dusk timer")
                         ["source"], "chat")

    def test_garbage_rows_are_dropped(self):
        self.assertEqual(facts_store.merge_rows(
            [None, 3, {"text": ""}, {"subject": "house"}]), 0)
        self.assertEqual(facts_store.merge_rows("not a list"), 0)


if __name__ == "__main__":
    unittest.main()
