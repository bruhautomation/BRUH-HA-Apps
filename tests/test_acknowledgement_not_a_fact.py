#!/usr/bin/env python3
"""A reason that only acknowledges, and a note about the software, are not
facts about the house (#306).

The reason box under Ignore is optional, and "That's fine" is what people
often type in it. Filed as it was, the Knowledge tab held a fact whose whole
text was "That's fine" (the exception rule) and a memory line ending
"because: That's fine". Notes about how Morph's panel behaves in the
companion app were filed under "The house" beside them.

Driven through the real `_end_finding`, the real inbox sweep and the real
reconcile pass over temporary stores.
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

import facts_store  # noqa: E402
import findings_store  # noqa: E402

NOW = 1_789_800_000.0


class EndingCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self._facts_old = (facts_store.FACTS_FILE, facts_store.INGEST_STATE_FILE,
                           facts_store.RECONCILE_STATE_FILE)
        facts_store.FACTS_FILE = root / "facts.json"
        facts_store.INGEST_STATE_FILE = root / "facts-ingest.json"
        facts_store.RECONCILE_STATE_FILE = root / "facts-reconcile.json"
        self._store_old = (findings_store.FINDINGS_FILE,
                           findings_store.SETTLED_FILE, findings_store.STATE_FILE)
        findings_store.FINDINGS_FILE = root / "findings.json"
        findings_store.SETTLED_FILE = root / "findings-settled.json"
        findings_store.STATE_FILE = root / "findings-state.json"
        self.server = importlib.import_module("server")
        self._facts_srv = self.server.facts_store
        self.server.facts_store = facts_store
        self._inbox_old = self.server.MEMORY_INBOX_DIR
        self.inbox = root / "inbox"
        self.server.MEMORY_INBOX_DIR = self.inbox
        # The scoping pass is a model run; nothing here should start one.
        self._start_old = self.server._start_correction
        self.started = []
        self.server._start_correction = lambda *a, **k: self.started.append(a)

    def tearDown(self):
        (facts_store.FACTS_FILE, facts_store.INGEST_STATE_FILE,
         facts_store.RECONCILE_STATE_FILE) = self._facts_old
        (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
         findings_store.STATE_FILE) = self._store_old
        self.server.facts_store = self._facts_srv
        self.server.MEMORY_INBOX_DIR = self._inbox_old
        self.server._start_correction = self._start_old
        self.tmp.cleanup()

    def queued(self) -> list[str]:
        lines = []
        for path in sorted(self.inbox.glob("*.jsonl")) if self.inbox.exists() else []:
            for line in path.read_text().splitlines():
                if line.strip():
                    lines.append(json.loads(line)["fact"])
        return lines

    def ingest(self):
        self.inbox.mkdir(parents=True, exist_ok=True)
        facts_store.ingest_inbox(self.inbox, self.inbox / "processed")

    def file_row(self):
        entry, _ = findings_store.add(
            "Hall has read exactly the same value for a week",
            detail="21°C on every one of the last 8 days", fix="Check it",
            severity="warning", source="check:dev.frozen",
            source_title="Sensors frozen on one value",
            entity_id="sensor.hall_temp")
        return findings_store.get(entry["ts"])

    def end(self, verb, note):
        return asyncio.run(self.server._end_finding(
            self.file_row(), self.server.FINDING_VERBS[verb], note))


class TestAnAcknowledgementIsNotAReason(EndingCase):
    def test_wrong_with_thats_fine_files_no_memory_line_and_keeps_the_rule(self):
        _payload, fact = self.end("wrong", "That's fine")
        self.assertEqual(fact, "")
        self.assertEqual(self.queued(), [])
        rules = facts_store.exceptions("sensor.hall_temp", "dev.frozen")
        self.assertEqual(len(rules), 1, "the rule is what stops the check")
        self.assertNotEqual(rules[0]["text"].strip().lower(), "that's fine")
        self.assertIn("Hall has read exactly", rules[0]["text"])
        self.assertEqual(self.started, [])
        self.ingest()
        plain = [r for r in facts_store._load() if not r.get("predicate")]
        self.assertEqual(plain, [])

    def test_each_acknowledgement_in_the_set(self):
        for note in ("ok", "Okay.", "all good", "Fine!", "yes", "no",
                     "that’s fine"):
            self.assertTrue(facts_store.bare_acknowledgement(note), note)

    def test_a_reason_is_still_a_reason(self):
        for note in ("that's fine in winter", "ok, it is a cupboard contact",
                     "it is a contact on a cupboard nobody opens"):
            self.assertFalse(facts_store.bare_acknowledgement(note), note)
        _payload, fact = self.end("wrong", "that's fine in winter")
        self.assertIn("that's fine in winter", fact)
        rules = facts_store.exceptions("sensor.hall_temp", "dev.frozen")
        self.assertEqual(rules[0]["text"], "that's fine in winter")

    def test_done_with_ok_files_the_plain_sentence(self):
        _payload, fact = self.end("done", "ok")
        self.assertNotIn("They said", fact)
        self.assertIn("Fixed by the homeowner", fact)


class TestTheSoftwareIsNotTheHouse(unittest.TestCase):
    def test_morph_panel_behaviour_is_software(self):
        for text in (
                "Morph's panel opens full screen in the companion app",
                "Pull-to-refresh is disabled on the Morph dashboard",
                "Morph respects the safe-area insets on the iPhone",
                "brAIn's panel scrolls under the header in the companion app"):
            self.assertTrue(facts_store.about_software(text), text)

    def test_house_facts_that_mention_brain_or_morph_stay(self):
        for text in ("brAIn reads the hall sensor every evening",
                     "The kitchen tablet shows the Morph dashboard",
                     "The lounge lamp stays on for the cat",
                     "The companion app on Ben's phone sends his location"):
            self.assertFalse(facts_store.about_software(text), text)


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
        (self.inbox / "processed").mkdir(parents=True)

    def tearDown(self):
        (facts_store.FACTS_FILE, facts_store.INGEST_STATE_FILE,
         facts_store.RECONCILE_STATE_FILE) = self._old
        self.tmp.cleanup()


class TestIngestAndRepair(StoreCase):
    def test_the_sweep_files_neither_shape(self):
        lines = [
            {"fact": "That's fine", "source": "correction",
             "subject": "sensor.hall_temp"},
            {"fact": 'brAIn reported: "Hall is frozen". The homeowner says '
                     "that is not a problem here, because: That's fine",
             "source": "correction", "subject": "sensor.hall_temp"},
            {"fact": "Morph's panel opens full screen in the companion app",
             "source": "chat"},
            {"fact": "The lounge lamp stays on for the cat", "source": "chat"},
        ]
        (self.inbox / "a.jsonl").write_text(
            "\n".join(json.dumps(x) for x in lines) + "\n")
        facts_store.ingest_inbox(self.inbox, self.inbox / "processed")
        texts = [r["text"] for r in facts_store._load()]
        self.assertEqual(texts, ["The lounge lamp stays on for the cat"])

    def test_the_repair_drops_stored_rows_of_those_shapes_once(self):
        def row(i, text, predicate="", about=""):
            r = {"id": f"r{i}", "subject": "sensor.hall_temp",
                 "subjects": ["sensor.hall_temp"], "predicate": predicate,
                 "text": text, "source": "correction", "ts": int(NOW),
                 "first_seen": int(NOW)}
            if about:
                r["about"] = about
            return r
        facts_store._write([
            row(1, "That's fine"),
            row(2, 'brAIn reported: "Hall is frozen". The homeowner says that '
                   "is not a problem here, because: ok"),
            row(3, "Morph's panel opens full screen in the companion app"),
            row(4, "The hall sensor sits above the radiator"),
            row(5, "That's fine", predicate="exception:dev.frozen",
                about="Hall is frozen"),
        ])
        out = facts_store.reconcile(None, self.inbox, now=NOW)
        self.assertEqual(out.get("not_facts"), 3, out)
        rows = facts_store._load()
        texts = sorted(r["text"] for r in rows)
        self.assertIn("The hall sensor sits above the radiator", texts)
        rule = [r for r in rows if r.get("predicate")]
        self.assertEqual(len(rule), 1, "the rule stays: it stops the check")
        self.assertEqual(rule[0]["text"],
                         '"Hall is frozen" was reported and marked wrong')
        self.assertEqual(len(rows), 2)
        self.assertGreaterEqual(facts_store.REPAIR_VERSION, 3)


if __name__ == "__main__":
    unittest.main()
