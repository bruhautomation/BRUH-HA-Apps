#!/usr/bin/env python3
"""What a fact is filed as: things for subjects, real rooms, whole words,
one row per claim, and no bug report that outlives its release.

Five rules, each driven through the real store over a temporary file —
the inbox sweep a writer reaches it by, and the reconcile pass that puts
an already-stored row right:

  subjects    a decimal and a file name are not things; an entity must be
              in the registry when there is one; a row left with nothing is
              about the house
  rooms       an area subject is the REAL area id, found by name or alias,
              and a room no area is called is dropped
  text        a fact ends on a word, not inside one, and a 32-hex registry
              id is named (or shortened) unless a person wrote it
  folds       a paraphrase and a newer reading of the same state replace the
              older row, keeping its first sighting — never a correction, a
              rule or an occasion
  brAIn       a fact saying brAIn's own code is broken carries the version
              it was filed under and expires when a newer one runs, and the
              Clean up review offers it as stale
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import facts_store  # noqa: E402
import memory_cleanup  # noqa: E402

NOW = 1_789_800_000.0
DAY = 86400.0
HEX_DEVICE = "3fa4c1d2e5b6a7980123456789abcdef"
HEX_ENTRY = "0123456789abcdef0123456789abcdef"
HEX_UNKNOWN = "deadbeefdeadbeefdeadbeefdeadbeef"

REGISTRY = {
    "entities": frozenset({"sensor.freezer_temp", "light.lounge_lamp",
                           "sensor.brain_usage_session"}),
    "areas": {"laundry": "Laundry", "lounge": "Living Room",
              "garage": "Garage"},
    "area_aliases": {"lounge": ["den"]},
    "devices": {HEX_DEVICE: "Kitchen Plug"},
    "entries": {HEX_ENTRY: "Garage Zigbee"},
    "self_entities": frozenset({"sensor.brain_usage_session"}),
}


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
        self._version = os.environ.get("ADDON_VERSION")
        os.environ["ADDON_VERSION"] = "2.20.0"
        self._n = 0

    def tearDown(self):
        (facts_store.FACTS_FILE, facts_store.INGEST_STATE_FILE,
         facts_store.RECONCILE_STATE_FILE) = self._old
        if self._version is None:
            os.environ.pop("ADDON_VERSION", None)
        else:
            os.environ["ADDON_VERSION"] = self._version
        self.tmp.cleanup()

    def queue(self, *lines, registry=REGISTRY):
        self._n += 1
        path = self.inbox / f"{self._n:04d}.jsonl"
        path.write_text("".join(json.dumps(x) + "\n" for x in lines),
                        encoding="utf-8")
        return facts_store.ingest_inbox(self.inbox, self.processed,
                                        registry=registry)

    def rows(self):
        return facts_store.export_rows()

    def row(self, needle):
        for r in self.rows():
            if needle in r["text"]:
                return r
        self.fail(f"no row carrying {needle!r}: {[r['text'] for r in self.rows()]}")

    def store(self, rows):
        facts_store.FACTS_FILE.write_text(json.dumps({"facts": rows}),
                                          encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. A subject is a thing
# ---------------------------------------------------------------------------

class TestASubjectIsAThing(StoreCase):

    def test_a_number_and_a_file_name_are_not_subjects(self):
        self.queue({"fact": "The setpoint reads 69.98 in automations.yaml",
                    "source": "fix",
                    "subjects": ["69.98", "automations.yaml"]},
                   registry=None)
        got = self.row("setpoint")
        self.assertEqual(got["subjects"], ["house"], got)

    def test_the_scan_does_not_find_them_either_with_no_registry(self):
        self.queue({"fact": "The cost rose to 69.98 after scenes.yaml "
                            "changed, says light.porch", "source": "card"},
                   registry=None)
        got = self.row("cost rose")
        self.assertEqual(got["subjects"], ["light.porch"], got)

    def test_with_a_registry_an_entity_must_be_in_it(self):
        self.queue({"fact": "That plug runs the fridge", "source": "chat",
                    "subject": "switch.not_in_this_house",
                    "subjects": ["sensor.freezer_temp"]})
        got = self.row("runs the fridge")
        self.assertEqual(got["subjects"], ["sensor.freezer_temp"], got)

    def test_person_check_and_house_stay(self):
        self.queue({"fact": "Ben likes the hall bright", "source": "chat",
                    "subject": "person:ben", "subjects": ["check:dev.frozen"]})
        self.assertEqual(self.row("hall bright")["subjects"],
                         ["person:ben", "check:dev.frozen"])

    def test_a_stored_row_is_repaired_once_and_left_with_house(self):
        self.store([{"id": "a", "subject": "69.98",
                     "subjects": ["69.98", "something.yaml"],
                     "predicate": "", "text": "A reading of 69.98 was seen",
                     "source": "fix", "ts": int(NOW), "first_seen": int(NOW)},
                    {"id": "b", "subject": "sensor.gone_now",
                     "subjects": ["sensor.gone_now"], "predicate": "",
                     "text": "That sensor sits behind the fridge",
                     "source": "chat", "ts": int(NOW), "first_seen": int(NOW)}])
        out = facts_store.reconcile(None, self.inbox, now=NOW,
                                    registry=REGISTRY)
        self.assertGreaterEqual(out["repaired"], 1, out)
        self.assertEqual(self.row("69.98")["subjects"], ["house"])
        # A well-shaped entity the registry has lost keeps its subject: the
        # orphan rule ages it out, and a repair must not make it a house fact.
        self.assertEqual(self.row("behind the fridge")["subjects"],
                         ["sensor.gone_now"])


# ---------------------------------------------------------------------------
# 2. One room is one area id
# ---------------------------------------------------------------------------

class TestOneRoomOneAreaId(StoreCase):

    def test_a_guessed_id_and_a_name_resolve_to_the_real_area(self):
        self.queue({"fact": "The washer drains slowly", "source": "chat",
                    "subject": "area:laundry_room"},
                   {"fact": "The lounge gets the evening sun",
                    "source": "chat", "subject": "area:Living Room"},
                   {"fact": "The den is where the router lives",
                    "source": "chat", "subject": "area:den"})
        self.assertEqual(self.row("drains slowly")["subjects"],
                         ["area:laundry"])
        self.assertEqual(self.row("evening sun")["subjects"], ["area:lounge"])
        self.assertEqual(self.row("router lives")["subjects"], ["area:lounge"])

    def test_a_room_no_area_is_called_is_dropped(self):
        self.queue({"fact": "The attic is cold in winter", "source": "chat",
                    "subject": "area:attic"})
        self.assertEqual(self.row("attic")["subjects"], ["house"])

    def test_no_area_registry_keeps_the_subject_as_it_was(self):
        self.queue({"fact": "The attic is cold in winter", "source": "chat",
                    "subject": "area:attic"}, registry=None)
        self.assertEqual(self.row("attic")["subjects"], ["area:attic"])

    def test_stored_rows_are_moved_to_the_real_id(self):
        self.store([{"id": "a", "subject": "area:laundry_room",
                     "subjects": ["area:laundry_room"], "predicate": "",
                     "text": "The washer drains slowly", "source": "chat",
                     "ts": int(NOW), "first_seen": int(NOW)}])
        facts_store.reconcile(None, self.inbox, now=NOW, registry=REGISTRY)
        self.assertEqual(self.row("drains")["subjects"], ["area:laundry"])


# ---------------------------------------------------------------------------
# 3. Whole words and names, not ids
# ---------------------------------------------------------------------------

class TestWholeWordsAndNames(StoreCase):

    def test_a_long_line_ends_on_a_word_with_an_ellipsis(self):
        words = " ".join(f"word{i}" for i in range(200))
        self.queue({"fact": "brAIn fixed this: " + words, "source": "fix"})
        got = self.row("brAIn fixed this")["text"]
        self.assertLessEqual(len(got), facts_store.MAX_TEXT)
        self.assertTrue(got.endswith("…"), got[-20:])
        last = got[:-1].split()[-1]
        self.assertRegex(last, r"^word\d+$")
        self.assertIn(last, words.split())

    def test_a_line_a_writer_sliced_at_the_cap_is_cut_back_to_a_word(self):
        body = ("The pump " + "cycles often " * 60)[:facts_store.MAX_TEXT]
        self.assertTrue(body[-1].isalpha())
        self.queue({"fact": body, "source": "card"})
        got = self.row("The pump")["text"]
        self.assertTrue(got.endswith("…"), got[-20:])
        self.assertIn(got[:-1].split()[-1], ("cycles", "often"))

    def test_registry_ids_are_named_or_shortened(self):
        self.queue({"fact": f"Reloaded entry {HEX_ENTRY} and pinged device "
                            f"{HEX_DEVICE}; {HEX_UNKNOWN} did not answer",
                    "source": "fix"})
        got = self.row("Reloaded")["text"]
        self.assertIn("Garage Zigbee", got)
        self.assertIn("Kitchen Plug", got)
        self.assertNotIn(HEX_UNKNOWN, got)
        self.assertIn(HEX_UNKNOWN[:8] + "…", got)

    def test_an_entity_with_a_hex_object_id_is_left_alone(self):
        self.queue({"fact": f"sensor.{HEX_UNKNOWN} is the attic probe",
                    "source": "card"}, registry=None)
        self.assertIn(f"sensor.{HEX_UNKNOWN}", self.row("attic probe")["text"])

    def test_what_a_person_typed_keeps_its_ids(self):
        self.queue({"fact": f"Device {HEX_DEVICE} is the one by the door",
                    "source": "correction"})
        self.assertIn(HEX_DEVICE, self.row("by the door")["text"])

    def test_a_cleaned_line_is_still_its_queued_line(self):
        raw = f"Device {HEX_DEVICE} runs the dehumidifier overnight"
        self.queue({"fact": raw, "source": "fix"})
        out = facts_store.reconcile("## Devices\n- Something else\n",
                                    self.inbox, now=NOW, force=True,
                                    registry=REGISTRY)
        self.assertEqual(out["pending"], 1, out)
        self.assertEqual(facts_store.forget_text(raw, "fix"), 1)

    def test_stored_rows_are_repaired(self):
        cut = ("The boiler " + "fires twice " * 60)[:facts_store.MAX_TEXT]
        self.store([{"id": "a", "subject": "house", "subjects": ["house"],
                     "predicate": "", "text": cut, "source": "card",
                     "ts": int(NOW), "first_seen": int(NOW)},
                    {"id": "b", "subject": "house", "subjects": ["house"],
                     "predicate": "", "source": "fix", "ts": int(NOW),
                     "first_seen": int(NOW),
                     "text": f"Pinged {HEX_DEVICE} overnight"}])
        facts_store.reconcile(None, self.inbox, now=NOW, registry=REGISTRY)
        self.assertTrue(self.row("The boiler")["text"].endswith("…"))
        self.assertEqual(self.row("Pinged")["text"],
                         "Pinged Kitchen Plug overnight")


# ---------------------------------------------------------------------------
# 4. One row per claim
# ---------------------------------------------------------------------------

class TestOneRowPerClaim(StoreCase):

    def test_a_paraphrase_replaces_the_older_row_newest_wins(self):
        self.queue({"fact": "The freezer sensor sits in the garage corner",
                    "source": "card", "subject": "sensor.freezer_temp",
                    "ts": int(NOW)})
        self.queue({"fact": "The freezer sensor sits in the garage corner "
                            "shelf", "source": "study",
                    "subject": "sensor.freezer_temp", "ts": int(NOW + DAY)})
        rows = [r for r in self.rows() if "freezer" in r["text"]]
        self.assertEqual(len(rows), 1, rows)
        self.assertTrue(rows[0]["text"].endswith("shelf"))
        self.assertEqual(rows[0]["first_seen"], int(NOW))
        self.assertEqual([f["source"] for f in rows[0]["folded"]], ["card"])

    def test_a_recovery_supersedes_the_older_fault(self):
        self.queue({"fact": "The freezer sensor is frozen at -18",
                    "source": "card", "subject": "sensor.freezer_temp",
                    "ts": int(NOW)})
        self.queue({"fact": "The freezer sensor is live again",
                    "source": "card", "subject": "sensor.freezer_temp",
                    "ts": int(NOW + DAY)})
        texts = [r["text"] for r in self.rows()]
        self.assertEqual(texts, ["The freezer sensor is live again"], texts)

    def test_two_faults_are_both_kept(self):
        self.queue({"fact": "The freezer sensor battery is low",
                    "source": "card", "subject": "sensor.freezer_temp"})
        self.queue({"fact": "The freezer sensor has been unavailable",
                    "source": "card", "subject": "sensor.freezer_temp"})
        self.assertEqual(len(self.rows()), 2)

    def test_a_reading_about_more_things_is_not_folded_away(self):
        self.queue({"fact": "The freezer sensor and lamp are unavailable",
                    "source": "card",
                    "subjects": ["sensor.freezer_temp", "light.lounge_lamp"]})
        self.queue({"fact": "The freezer sensor is back online",
                    "source": "card", "subject": "sensor.freezer_temp"})
        self.assertEqual(len(self.rows()), 2)

    def test_what_a_person_said_is_never_folded_away(self):
        self.queue({"fact": "The freezer sensor is frozen on purpose here",
                    "source": "correction", "subject": "sensor.freezer_temp"})
        self.queue({"fact": "The freezer sensor is live again",
                    "source": "card", "subject": "sensor.freezer_temp"})
        sources = sorted(r["source"] for r in self.rows())
        self.assertEqual(sources, ["card", "correction"])

    def test_a_rule_and_an_occasion_are_never_folded_away(self):
        facts_store.add("The freezer sensor is stuck by design",
                        subject="sensor.freezer_temp", source="correction",
                        predicate="exception:dev.frozen", ts=NOW)
        facts_store.add("The freezer sensor is stuck during the party",
                        subject="sensor.freezer_temp", source="occasion",
                        predicate="occasion", ts=NOW)
        self.queue({"fact": "The freezer sensor is live again",
                    "source": "card", "subject": "sensor.freezer_temp"})
        self.assertEqual(len(self.rows()), 3)

    def test_stored_duplicates_are_folded_by_the_repair(self):
        base = {"subject": "sensor.freezer_temp", "predicate": "",
                "subjects": ["sensor.freezer_temp"], "source": "card"}
        self.store([dict(base, id="a", ts=int(NOW), first_seen=int(NOW),
                         text="The freezer sensor is frozen at -18"),
                    dict(base, id="b", ts=int(NOW + DAY),
                         first_seen=int(NOW + DAY),
                         text="The freezer sensor is live again")])
        out = facts_store.reconcile(None, self.inbox, now=NOW + DAY,
                                    registry=REGISTRY)
        self.assertEqual(out["folded"], 1, out)
        rows = self.rows()
        self.assertEqual([r["text"] for r in rows],
                         ["The freezer sensor is live again"])
        self.assertEqual(rows[0]["first_seen"], int(NOW))


# ---------------------------------------------------------------------------
# 5. A fact about brAIn being broken expires with its release
# ---------------------------------------------------------------------------

class TestBrainsOwnBugsExpire(StoreCase):

    def test_every_fact_carries_its_version(self):
        self.queue({"fact": "The lamp is on a timer", "source": "chat"})
        self.assertEqual(self.row("lamp")["version"], "2.20.0")

    def test_a_bug_report_expires_when_a_newer_version_runs(self):
        self.queue({"fact": "brAIn's get_history tool fails because it "
                            "drops end_time", "source": "correction"},
                   {"fact": "The usage sensor misreads the session window",
                    "source": "card",
                    "subject": "sensor.brain_usage_session"})
        self.assertEqual(facts_store.count(now=NOW), 2)
        self.assertIn("get_history", facts_store.retrieval_block(
            query="get_history tool fails", now=NOW))
        os.environ["ADDON_VERSION"] = "2.21.0"
        self.assertEqual(facts_store.count(now=NOW), 0)
        self.assertEqual(facts_store.retrieval_block(
            query="get_history tool fails", now=NOW), "")

    def test_what_is_not_about_brain_or_not_broken_stays(self):
        self.queue({"fact": "The ESPHome add-on fails to compile the "
                            "porch node", "source": "card"},
                   {"fact": "brAIn reads the hall sensor every hour",
                    "source": "card"},
                   {"fact": "The pump fails when the tank runs dry",
                    "source": "card"})
        os.environ["ADDON_VERSION"] = "3.0.0"
        self.assertEqual(facts_store.count(now=NOW), 3)

    def test_a_rule_never_expires_on_a_version(self):
        facts_store.add("brAIn's frozen check fails on this sensor",
                        subject="sensor.freezer_temp", source="correction",
                        predicate="exception:dev.frozen", ts=NOW)
        os.environ["ADDON_VERSION"] = "3.0.0"
        self.assertEqual(facts_store.exception_map(now=NOW),
                         {"sensor.freezer_temp": {"dev.frozen"}})

    def test_a_dev_build_expires_nothing(self):
        self.queue({"fact": "brAIn's chat tool is broken", "source": "chat"})
        os.environ["ADDON_VERSION"] = "dev"
        self.assertEqual(facts_store.count(now=NOW), 1)

    def test_an_old_row_is_stamped_and_expires_at_the_next_upgrade(self):
        self.store([{"id": "a", "subject": "house", "subjects": ["house"],
                     "predicate": "", "source": "correction",
                     "text": "The fix belongs in the add-on, not the house",
                     "ts": int(NOW), "first_seen": int(NOW)}])
        facts_store.reconcile(None, self.inbox, now=NOW, registry=REGISTRY)
        got = self.row("fix belongs")
        self.assertTrue(got["about_brain"])
        self.assertEqual(got["version"], "2.20.0")
        os.environ["ADDON_VERSION"] = "2.20.1"
        self.assertEqual(facts_store.count(now=NOW), 0)

    def test_the_clean_up_review_offers_it_as_stale(self):
        self.queue({"fact": "brAIn's get_history tool fails because it "
                            "drops end_time", "source": "correction"},
                   {"fact": "The lamp is on a timer", "source": "person"})
        os.environ["ADDON_VERSION"] = "2.21.0"
        dig = memory_cleanup.digest("", facts_store.export_rows())
        offered = [r for r in dig["facts"] if r.get("stale")]
        self.assertEqual(len(offered), 1, dig)
        self.assertIn("2.20.0", offered[0]["stale"])
        self.assertIn("2.21.0", offered[0]["stale"])
        # What a person typed that is about the house is still not offered.
        self.assertFalse([r for r in dig["facts"] if "lamp" in r["text"]])
        parsed = memory_cleanup.parse({"remove": []}, dig)
        self.assertEqual([(r["id"], r["reason"]) for r in parsed["rows"]],
                         [(offered[0]["id"], "stale")])


if __name__ == "__main__":
    unittest.main()
