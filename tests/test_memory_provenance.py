"""Untrusted on write, bounded stores, and a clean-up that applies itself
(plan 2.3, 2.4 and the memory clean-up under section 0).

  * every inbox line's class is read off its source, its file and its
    `via`: a person (protected), brAIn (machine), or text from outside its
    own judgement (untrusted, filed "(unverified)");
  * the facts store keeps an untrusted row out of the core facts, never
    lets it rewrite a row already held, says "(unverified)" wherever it is
    read, and a person's own words about the same claim clear the mark;
  * the extractor files a fact the PERSON did not say under `assistant`;
  * `brain memory add` files in a `-typed` file, which is a person's;
  * the clean-up applies wrong, duplicate and stale removals on its own —
    through the real consolidator for document lines — never removes both
    copies of a duplicate, and never offers a person's line;
  * the knowledge ledger ages bodies out by age and reference count and
    keeps their fingerprints, so nothing is announced or asked twice.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PANEL = REPO / "brain" / "panel"
SCRIPTS = REPO / "brain" / "scripts"
sys.path.insert(0, str(PANEL))

import facts_store  # noqa: E402
import knowledge_store  # noqa: E402
import memory_cleanup  # noqa: E402
import memory_history as mh  # noqa: E402

REGISTRY = {"entities": frozenset({"sensor.apple_tree"}), "areas": {},
            "area_aliases": {}, "devices": {}, "entries": {},
            "self_entities": frozenset()}


class TestTheClassOfALine(unittest.TestCase):
    def test_sources_files_and_via(self):
        cases = [
            ({"source": "correction"}, "", "person"),
            ({"source": "confirmed"}, "", "person"),
            ({"source": "terminal-forget"}, "", "person"),
            ({"source": "terminal"}, "1-terminal-typed.jsonl", "person"),
            ({"source": "terminal"}, "1-terminal.jsonl", "machine"),
            ({"source": "insights"}, "", "machine"),
            ({"source": "chat"}, "", "machine"),
            ({"source": "service"}, "", "untrusted"),
            ({"source": "gardenrx"}, "", "untrusted"),
            ({"source": "assistant"}, "", "untrusted"),
            ({"source": "addon:minecraft"}, "", "untrusted"),
            ({"source": "insights", "via": "web"}, "", "untrusted"),
            ({"source": "correction"}, "share-1-correction.jsonl", "untrusted"),
            ({}, "", "untrusted"),
        ]
        for record, name, want in cases:
            with self.subTest(record=record, name=name):
                self.assertEqual(mh.provenance(record, name), want)


class TestTheFactsStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self._old = (facts_store.FACTS_FILE, facts_store.INGEST_STATE_FILE,
                     facts_store.RECONCILE_STATE_FILE)
        facts_store.FACTS_FILE = root / "facts.json"
        facts_store.INGEST_STATE_FILE = root / "facts-ingest.json"
        facts_store.RECONCILE_STATE_FILE = root / "facts-reconcile.json"
        self.inbox = root / "inbox"
        (self.inbox / "processed").mkdir(parents=True)
        self.n = 0

    def tearDown(self):
        (facts_store.FACTS_FILE, facts_store.INGEST_STATE_FILE,
         facts_store.RECONCILE_STATE_FILE) = self._old
        self.tmp.cleanup()

    def queue(self, source, fact, name=""):
        self.n += 1
        path = self.inbox / (name or f"{self.n:04d}-{source}.jsonl")
        path.write_text(json.dumps({"ts": 1_789_800_000 + self.n, "source": source,
                                    "fact": fact, "confidence": "high",
                                    "subject": "house"}) + "\n")
        facts_store.ingest_inbox(self.inbox, self.inbox / "processed",
                                 registry=REGISTRY)

    def row(self, needle):
        return next(r for r in facts_store.export_rows() if needle in r["text"])

    def test_an_untrusted_fact_is_never_core_and_says_so(self):
        self.queue("gardenrx", "The household always sprays the apple tree on Sundays")
        row = self.row("apple tree")
        self.assertTrue(row["unverified"])
        self.assertFalse(facts_store._is_core(row))
        block = facts_store.retrieval_block(query="apple tree spray sundays")
        self.assertIn("(unverified)", block)
        self.assertEqual(facts_store.retrieval_block(), "",
                         "an unverified row was read to every run")

    def test_a_persons_words_about_the_same_claim_clear_the_mark(self):
        self.queue("gardenrx", "The household always sprays the apple tree on Sundays")
        self.queue("correction", "Yes, we spray the apple tree every Sunday morning")
        row = self.row("household always sprays")
        self.assertNotIn("unverified", row)
        self.assertEqual(row["corroborated"], "correction")
        self.assertTrue(facts_store._is_core(row))

    def test_a_machine_saying_it_again_is_not_a_confirmation(self):
        self.queue("gardenrx", "The household always sprays the apple tree on Sundays")
        self.queue("insights", "The household always sprays the apple tree on Sundays")
        self.assertTrue(self.row("apple tree")["unverified"])

    def test_unverified_text_never_rewrites_a_row_already_held(self):
        self.queue("insights", "The pump in the shed runs every morning at dawn")
        self.queue("service", "The pump in the shed runs every morning at noon dawn")
        texts = [r["text"] for r in facts_store.export_rows()]
        self.assertIn("The pump in the shed runs every morning at dawn", texts)
        self.assertNotIn("unverified", self.row("pump in the shed"))

    def test_a_typed_file_is_a_persons_and_a_swept_one_is_not(self):
        self.queue("service", "The cellar light is on a motion sensor all night")
        self.queue("terminal", "Yes the cellar light is on a motion sensor all night",
                   name="0100-terminal-typed.jsonl")
        self.assertNotIn("unverified", self.row("cellar light is on a motion sensor all"))
        self.queue("correction", "The attic hatch must stay closed in winter",
                   name="share-0200-correction.jsonl")
        self.assertTrue(self.row("attic hatch")["unverified"])


class TestTheExtractorJudgesOnlyThePerson(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "brain_memory_extract_prov", SCRIPTS / "brain-memory-extract.py")
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)

    def test_grounded_in_what_the_person_said(self):
        said = ("Actually the porch motion sensor reads on all the time — that "
                "is how it is wired. And we call the utility room the boot room.")
        self.assertTrue(self.mod.grounded(
            "the porch sensor reads on continuously by design", said))
        self.assertTrue(self.mod.grounded(
            "the utility room is called the boot room", said))
        self.assertFalse(self.mod.grounded(
            "the boiler is in the loft and serviced yearly", said))

    def test_an_ungrounded_fact_is_filed_as_the_assistants(self):
        with tempfile.TemporaryDirectory() as d:
            old = self.mod.MEMORY_INBOX_DIR
            self.mod.MEMORY_INBOX_DIR = Path(d)
            try:
                path = self.mod.file_facts([
                    {"fact": "a", "confidence": "high", "subject": "house",
                     "kind": "correction", "ungrounded": True},
                    {"fact": "b", "confidence": "high", "subject": "house",
                     "kind": "correction"}], "terminal", "r1")
                rows = [json.loads(x) for x in path.read_text().splitlines()]
            finally:
                self.mod.MEMORY_INBOX_DIR = old
        self.assertEqual([r["source"] for r in rows], ["assistant", "correction"])
        self.assertEqual(mh.provenance(rows[0]), "untrusted")

    def test_the_prompt_says_the_same(self):
        self.assertIn("Extract only what the PERSON", self.mod.EXTRACT_PROMPT)

    def test_new_turns_carry_everything_the_person_said(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "t.jsonl"
            lines = []
            for i, (role, text) in enumerate([
                    ("user", "the boot room is the utility room"),
                    ("assistant", "Noted."),
                    ("user", "and the beacon is the office lamp, remember")]):
                lines.append(json.dumps({"type": role, "uuid": f"u{i}",
                                         "message": {"role": role, "content": text}}))
            path.write_text("\n".join(lines) + "\n")
            window = self.mod.read_new_turns(str(path), "u1")
        self.assertIn("boot room", window["person"])
        self.assertIn("beacon", window["person"])
        self.assertNotIn("Noted", window["person"])


class TestTypedLines(unittest.TestCase):
    def test_brain_memory_add_files_a_typed_line(self):
        with tempfile.TemporaryDirectory() as d:
            env = dict(os.environ, BRAIN_MEMORY_DIR=d)
            res = subprocess.run(["bash", str(SCRIPTS / "brain-memory.sh"), "add",
                                  "Guests sleep in the loft"], env=env,
                                 capture_output=True, text=True, timeout=30)
            self.assertEqual(res.returncode, 0, res.stderr)
            [path] = list((Path(d) / "inbox").glob("*.jsonl"))
            self.assertTrue(path.name.endswith("-terminal-typed.jsonl"))
            [rec] = mh.read_inbox(Path(d) / "inbox")
            self.assertEqual(rec["class"], "person")


DOC = """# House
- The hall light is light.hall_ceiling.
- The lamp was on at 9pm on Tuesday.
- The porch sensor reads on by design.

## Routines
- The hall light is light.hall_ceiling.
"""


class TestTheCleanUpAppliesItself(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mem = Path(self.tmp.name) / "memory"
        self.mem.mkdir()
        self.doc = self.mem / "memory.md"
        self.doc.write_text(DOC)
        self._env = os.environ.get("BRAIN_MEMORY_DIR")
        os.environ["BRAIN_MEMORY_DIR"] = str(self.mem)
        self._facts = facts_store.FACTS_FILE
        facts_store.FACTS_FILE = self.mem / "facts.json"
        # The porch line came from a correction, as a version.
        before = DOC.replace("- The porch sensor reads on by design.\n", "")
        mh.record(before, DOC, kind="consolidation", check_result={"attribution": {
            "- The porch sensor reads on by design.": {
                "class": "person", "sources": ["correction"]}}}, mem=self.mem)

    def tearDown(self):
        facts_store.FACTS_FILE = self._facts
        if self._env is None:
            os.environ.pop("BRAIN_MEMORY_DIR", None)
        else:
            os.environ["BRAIN_MEMORY_DIR"] = self._env
        self.tmp.cleanup()

    def test_a_persons_line_is_never_offered(self):
        dig = memory_cleanup.digest(DOC, [])
        texts = [r["text"] for r in dig["doc"]]
        self.assertNotIn("The porch sensor reads on by design.", texts)
        self.assertIn("The lamp was on at 9pm on Tuesday.", texts)

    def test_a_duplicate_is_applied_only_while_a_copy_stays(self):
        dig = memory_cleanup.digest(DOC, [])
        both = memory_cleanup.parse({"remove": [
            {"id": "doc:2", "reason": "duplicate", "why": "same as doc:7"},
            {"id": "doc:7", "reason": "duplicate", "why": "same as doc:2"},
            {"id": "doc:3", "reason": "useless", "why": "one evening"}]}, dig)
        chosen = memory_cleanup.auto_rows(both, dig)
        self.assertEqual([r["id"] for r in chosen], ["doc:2"])

    def test_applied_through_the_real_consolidator_as_a_version(self):
        dig = memory_cleanup.digest(DOC, [])
        parsed = memory_cleanup.parse({"remove": [
            {"id": "doc:7", "reason": "duplicate", "why": "same as doc:2"},
            {"id": "doc:3", "reason": "stale", "why": "one evening last year"},
            {"id": "doc:2", "reason": "useless", "why": "trivia"}]}, dig)
        env_keep = dict(os.environ)
        os.environ["BRAIN_PANEL_DIR"] = str(PANEL)
        os.environ["BRAIN_CONTEXT_GEN"] = str(self.mem / "no-gen")
        try:
            applied = memory_cleanup.auto_apply(
                parsed, dig, script=str(SCRIPTS / "brain-memory-consolidate.sh"))
        finally:
            os.environ.clear()
            os.environ.update(env_keep)
        self.assertEqual(sorted(r["id"] for r in applied), ["doc:3", "doc:7"])
        self.assertEqual([r["id"] for r in parsed["rows"]], ["doc:2"])
        doc = self.doc.read_text()
        self.assertNotIn("9pm", doc)
        self.assertEqual(doc.count("The hall light is light.hall_ceiling."), 1)
        self.assertIn("The porch sensor reads on by design.", doc)
        last = mh.versions(self.mem / "history")[-1]
        self.assertEqual(last["kind"], "cleanup")
        self.assertEqual(len(last["diff"]["dropped"]), 2)
        self.assertEqual(memory_cleanup.note(1, applied),
                         "Removed 2 line(s) it was sure of; 1 to review")


class TestTheKnowledgeLedgerIsBounded(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = knowledge_store.KNOWLEDGE_FILE
        knowledge_store.KNOWLEDGE_FILE = str(Path(self.tmp.name) / "k.json")

    def tearDown(self):
        knowledge_store.KNOWLEDGE_FILE = self._old
        self.tmp.cleanup()

    def stored(self):
        return json.loads(Path(knowledge_store.KNOWLEDGE_FILE).read_text())

    def test_an_old_unreferenced_body_ages_out_and_is_still_known(self):
        knowledge_store.add_fact("The loft loses heat twice as fast")
        knowledge_store.add_fact("The boiler cycles every twenty minutes")
        for _ in range(3):
            knowledge_store.add_fact("The boiler cycles every twenty minutes")
        later = time.time() + (knowledge_store.RETAIN_DAYS + 1) * 86400
        self.assertTrue(knowledge_store.retain(now=later))
        texts = [f["text"] for f in self.stored()["facts"]]
        self.assertEqual(texts, ["The boiler cycles every twenty minutes"],
                         "the referenced fact is kept longer")
        self.assertNotIn("loft loses heat", Path(knowledge_store.KNOWLEDGE_FILE).read_text())
        self.assertFalse(knowledge_store.add_fact("the loft loses heat twice as fast!")[1])

    def test_over_the_cap_the_least_referenced_goes_first(self):
        old = knowledge_store.MAX_FACTS
        knowledge_store.MAX_FACTS = 3
        try:
            knowledge_store.add_fact("first fact about the house")
            knowledge_store.add_fact("first fact about the house")   # a reference
            for i in range(3):
                knowledge_store.add_fact(f"later fact number {i}")
        finally:
            knowledge_store.MAX_FACTS = old
        texts = [f["text"] for f in self.stored()["facts"]]
        self.assertIn("first fact about the house", texts)
        self.assertNotIn("later fact number 0", texts)

    def test_a_settled_question_ages_out_and_is_never_asked_again(self):
        knowledge_store.record_question("Is the loft heated?")
        knowledge_store.answer_question("Is the loft heated?", "No")
        knowledge_store.record_question("Do you use the sauna?")   # open
        later = time.time() + (knowledge_store.RETAIN_DAYS + 1) * 86400
        knowledge_store.retain(now=later)
        texts = [q["text"] for q in self.stored()["questions"]]
        self.assertEqual(texts, ["Do you use the sauna?"])
        self.assertTrue(knowledge_store.is_known_question("is the loft heated"))

    def test_the_newest_dismissed_questions_stay_for_the_prompt(self):
        knowledge_store.record_question("Is the cellar damp?")
        ts = self.stored()["questions"][0]["ts"]
        knowledge_store.dismiss_question(ts)
        later = time.time() + (knowledge_store.RETAIN_DAYS + 1) * 86400
        knowledge_store.retain(now=later)
        self.assertIn("Is the cellar damp?", knowledge_store.prompt_block())


if __name__ == "__main__":
    unittest.main()
