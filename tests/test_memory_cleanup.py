#!/usr/bin/env python3
"""Memory clean-up — what brAIn remembers that is wrong, useless or an error.

What is driven:

  * `digest` keeps what a person said and the rules a press wrote out of
    what the review is handed, and numbers the document's fact lines;
  * `parse` refuses a removal naming a line nobody offered, a reason
    outside the closed set, a removal with no reason, and the same line
    twice;
  * the runner and the three routes, real, with only `engine.run_analyst`
    stubbed: facts leave the store at once, document lines become `FORGET:`
    requests in the memory inbox, a consolidation pass is started (stubbed)
    so the consolidator — the one writer of memory.md — carries them out,
    and an unticked line stays on the list.
"""

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))
sys.path.insert(0, str(BASE_DIR / "tests"))

import memory_cleanup  # noqa: E402
from fake_core_ws import drive_app  # noqa: E402

DOC = """# House
- The hall light is light.hall_ceiling.
- The lamp was on at 9pm on Tuesday.
- brAIn deep check marker 1712 — remove me.

## Routines
- The hall light is light.hall_ceiling.
"""


class TestTheDigest(unittest.TestCase):
    def test_headings_are_structure_and_lines_are_numbered(self):
        lines = memory_cleanup.doc_lines(DOC)
        self.assertEqual([l["id"] for l in lines], ["doc:2", "doc:3", "doc:4", "doc:7"])
        self.assertEqual(lines[0]["text"], "The hall light is light.hall_ceiling.")

    def test_what_a_person_said_and_the_rules_are_never_offered(self):
        facts = [
            {"id": "a1", "text": "The boiler is in the loft", "source": "study"},
            {"id": "a2", "text": "The cupboard contact never moves",
             "source": "correction"},
            {"id": "a3", "text": "Taught by hand", "source": "person"},
            {"id": "a4", "text": "normal here", "source": "panel",
             "predicate": "exception:dev.frozen"},
            {"id": "a5", "text": "quieter about the cat", "source": "resident",
             "predicate": "judgement:entity:quieter"},
        ]
        dig = memory_cleanup.digest(DOC, facts)
        self.assertEqual([f["id"] for f in dig["facts"]], ["fact:a1"])


class TestWhatMayComeBack(unittest.TestCase):
    def setUp(self):
        self.dig = memory_cleanup.digest(DOC, [
            {"id": "a1", "text": "The boiler is in the loft", "source": "study"}])

    def test_only_offered_lines_with_a_reason_become_rows(self):
        out = memory_cleanup.parse({"remove": [
            {"id": "doc:3", "reason": "useless", "why": "a one-off evening"},
            {"id": "doc:7", "reason": "duplicate", "why": "same as doc:2"},
            {"id": "fact:a1", "reason": "wrong", "why": "no boiler entity exists"},
            {"id": "doc:99", "reason": "error", "why": "invented"},
            {"id": "doc:4", "reason": "boring", "why": "not a reason"},
            {"id": "doc:4", "reason": "error", "why": ""},
            {"id": "doc:3", "reason": "useless", "why": "the same line twice"},
            "not a row",
        ]}, self.dig)
        self.assertEqual([r["id"] for r in out["rows"]], ["doc:3", "doc:7", "fact:a1"])
        self.assertEqual(out["dropped"], 5)
        self.assertEqual(out["rows"][2]["kind"], "fact")
        self.assertEqual(out["rows"][0]["text"], "The lamp was on at 9pm on Tuesday.")

    def test_an_empty_answer_is_an_answer(self):
        self.assertEqual(memory_cleanup.parse({"remove": []}, self.dig)["rows"], [])
        self.assertEqual(memory_cleanup.parse(None, self.dig)["rows"], [])


class TestThePress(unittest.TestCase):
    """The runner and the routes, real, with the CLI stubbed."""

    def setUp(self):
        import facts_store
        import server
        self.server, self.facts = server, facts_store
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "inbox").mkdir()
        doc = root / "memory.md"
        doc.write_text(DOC, encoding="utf-8")
        self._old = (memory_cleanup.STORE, facts_store.FACTS_FILE,
                     server.SHARED_MEMORY_FILE, server.MEMORY_INBOX_DIR,
                     server.engine.run_analyst, server.engine.get_auth,
                     server._consolidate_now)
        memory_cleanup.STORE = str(root / "cleanup.json")
        facts_store.FACTS_FILE = root / "facts.json"
        server.SHARED_MEMORY_FILE = doc
        server.MEMORY_INBOX_DIR = root / "inbox"
        self.inbox = root / "inbox"
        facts_store.add("The boiler is in the loft", subject="house", source="study")
        self.fact_id = facts_store.export_rows()[0]["id"]
        self.prompts = []
        self.consolidations = []

        def fake_run(prompt, system, *a, **kw):
            self.prompts.append({"prompt": prompt, "system": system, **kw})
            return {"ok": True, "error": "", "meta": {"session_id": "m-1"},
                    "text": json.dumps({"remove": [
                        {"id": "doc:3", "reason": "useless", "why": "a one-off evening"},
                        {"id": "doc:7", "reason": "duplicate", "why": "same as the first"},
                        {"id": f"fact:{self.fact_id}", "reason": "wrong",
                         "why": "there is no boiler in the registry"},
                        {"id": "doc:42", "reason": "error", "why": "invented"}]})}

        def fake_consolidate():
            self.consolidations.append(1)
            return True, ""

        server.engine.run_analyst = fake_run
        server.engine.get_auth = lambda: {"type": "oauth", "value": "x"}
        server._consolidate_now = fake_consolidate
        server.MAINT_STATE["memory_cleanup"].update(running=False, last_error="")
        server.MEMORY_STATE.update(merging=False)

    def tearDown(self):
        (memory_cleanup.STORE, self.facts.FACTS_FILE,
         self.server.SHARED_MEMORY_FILE, self.server.MEMORY_INBOX_DIR,
         self.server.engine.run_analyst, self.server.engine.get_auth,
         self.server._consolidate_now) = self._old
        self.tmp.cleanup()

    def test_the_runner_saves_only_what_passed_and_reads_the_house(self):
        asyncio.run(self.server._run_memory_cleanup())
        proposal = memory_cleanup.load()["proposal"]
        self.assertEqual([r["id"] for r in proposal["rows"]],
                         ["doc:3", "doc:7", f"fact:{self.fact_id}"])
        self.assertEqual(proposal["dropped"], 1)
        [call] = self.prompts
        self.assertEqual(call["job"], memory_cleanup.JOB)
        self.assertIs(call["schema"], memory_cleanup.SCHEMA)
        self.assertIn("doc:2: The hall light is light.hall_ceiling.", call["prompt"])

    def test_apply_removes_what_was_ticked_and_nothing_else(self):
        asyncio.run(self.server._run_memory_cleanup())

        async def go(client):
            res = await client.post("/api/memory/cleanup/apply", json={
                "ids": ["doc:3", f"fact:{self.fact_id}"]})
            body = await res.json()
            for _ in range(20):
                if self.consolidations:
                    break
                await asyncio.sleep(0.02)
            return res.status, body

        status, body = drive_app(self.server.make_app, go)
        self.assertEqual(status, 200, body)
        self.assertEqual(body["result"], {"facts": 1, "lines": 1, "consolidating": True})
        # The fact left the store at once.
        self.assertEqual(self.facts.export_rows(), [])
        # The document line became a FORGET request for the consolidator,
        # which was started; memory.md itself was not written here.
        lines = [json.loads(line) for p in self.inbox.glob("*.jsonl")
                 for line in p.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([l["fact"] for l in lines],
                         ["FORGET: The lamp was on at 9pm on Tuesday."])
        self.assertEqual(lines[0]["source"], "cleanup")
        self.assertEqual(self.consolidations, [1])
        self.assertIn("The lamp was on at 9pm", self.server.SHARED_MEMORY_FILE.read_text())
        # The unticked row is still on the list.
        left = memory_cleanup.load()["proposal"]["rows"]
        self.assertEqual([r["id"] for r in left], ["doc:7"])

    def test_nothing_ticked_is_a_409_and_discard_clears(self):
        asyncio.run(self.server._run_memory_cleanup())

        async def go(client):
            nothing = await client.post("/api/memory/cleanup/apply", json={"ids": []})
            gone = await client.post("/api/memory/cleanup/discard")
            return nothing.status, (await gone.json())["proposal"]

        self.assertEqual(drive_app(self.server.make_app, go), (409, None))

    def test_a_press_without_a_credential_spends_nothing(self):
        self.server.engine.get_auth = lambda: None

        async def go(client):
            return (await client.post("/api/memory/cleanup/run")).status

        self.assertEqual(drive_app(self.server.make_app, go), 400)
        self.assertEqual(self.prompts, [])


if __name__ == "__main__":
    unittest.main()
