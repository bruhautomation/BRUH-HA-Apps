#!/usr/bin/env python3
"""What brAIn brings to each kind of run — `GET /api/memory/context`.

The owner could not tell what a new conversation is handed from what sits
in Knowledge. The route answers it from the builders that make each run's
context (`server._context_sources` → `context_map.report`), so these tests
drive the real route over a temporary memory document, a temporary
/config/CLAUDE.md and a personality, and assert:

  * every kind of run is listed, each with what it is given and what it
    may look up, and every size is a whole number;
  * a conversation is given the memory document (inside CLAUDE.md, measured
    off the real file) and the personality, sized as the builders size them;
  * the facts store's part in each run is said as the code does it: per
    message on the chat face only, by `recall` where there are tools, and
    not at all in the first look or the overnight check;
  * nothing secret leaves: no document text, no CLAUDE.md text, no token;
  * the numbers context_map names for other processes match their source.
"""

import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))
sys.path.insert(0, str(BASE_DIR / "tests"))

import context_map  # noqa: E402
from fake_core_ws import drive_app  # noqa: E402

DOC = ("# Home Memory\n\n## People\n- Two adults and a cat called Biscuit.\n\n"
       "## Devices\n- The garage fridge runs 24/7 on purpose.\n")
# A marker shaped like a sign-in key; the route must never echo it.
PLANTED = "sk-" + "ant-oat01-" + "NOT-REAL-shaped-like-one"
CLAUDE_MD = (
    "# CLAUDE.md - Auto-generated Home Assistant Context\n\n"
    "## User Notes\n\n<!-- bruh:user-notes:start -->\nThe porch is south.\n"
    "<!-- bruh:user-notes:end -->\n\n"
    "## Dashboards\n\n- default\n\n"
    "## Learned Home Knowledge\n\n> Maintained automatically.\n\n"
    + DOC + f"\n<!-- {PLANTED} -->\n"
    "\n## Available Directories\n\n- /config/\n")
KINDS = ["conversation", "card", "voice", "first_look", "investigation",
         "overnight"]


class TestTheRoute(unittest.TestCase):
    def setUp(self):
        import facts_store
        import ha_data
        import personality
        import server
        self.server = server
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        doc = root / "memory.md"
        doc.write_text(DOC, encoding="utf-8")
        claude_md = root / "CLAUDE.md"
        claude_md.write_text(CLAUDE_MD, encoding="utf-8")
        self._old = (server.SHARED_MEMORY_FILE, ha_data.CONTEXT_FILE,
                     facts_store.FACTS_FILE, server._personality_lines,
                     os.environ.get("BRAIN_SHARED_DIR"))
        server.SHARED_MEMORY_FILE = doc
        ha_data.CONTEXT_FILE = str(claude_md)
        facts_store.FACTS_FILE = root / "facts.json"
        os.environ["BRAIN_SHARED_DIR"] = str(root)
        self.persona = ("The household gave brAIn a personality; speak as it.\n"
                        "Name: Vesper. Dry, brief, kind.")
        server._personality_lines = lambda: self.persona
        self.facts, self.ha_data, self.personality = facts_store, ha_data, personality

    def tearDown(self):
        (self.server.SHARED_MEMORY_FILE, self.ha_data.CONTEXT_FILE,
         self.facts.FACTS_FILE, self.server._personality_lines, shared) = self._old
        if shared is None:
            os.environ.pop("BRAIN_SHARED_DIR", None)
        else:
            os.environ["BRAIN_SHARED_DIR"] = shared
        self.tmp.cleanup()

    def fetch(self):
        async def go(client):
            res = await client.get("/api/memory/context")
            return res.status, await res.text()
        status, text = drive_app(self.server.make_app, go)
        self.assertEqual(status, 200, text)
        return json.loads(text), text

    def test_every_kind_of_run_is_listed_with_numbers(self):
        body, _ = self.fetch()
        self.assertEqual([r["key"] for r in body["runs"]], KINDS)
        for run in body["runs"]:
            self.assertTrue(run["title"] and run["when"], run["key"])
            self.assertTrue(run["given"], f"{run['key']} is given nothing")
            self.assertTrue(run["looks_up"]["summary"], run["key"])
            for p in run["given"] + run["each_time"]:
                self.assertIsInstance(p["bytes"], int, (run["key"], p["key"]))
                self.assertIsInstance(p["tokens"], int, (run["key"], p["key"]))
                self.assertGreaterEqual(p["bytes"], 0)
                self.assertIsInstance(p["upto"], bool)
            for g in run["looks_up"]["groups"]:
                self.assertEqual(g["count"], len(g["tools"]))
        mem = body["memory"]
        self.assertEqual(mem["document_bytes"], len(DOC.encode()))
        self.assertIsInstance(mem["waiting"], int)

    def test_a_conversation_carries_the_document_and_the_personality(self):
        body, _ = self.fetch()
        conv = {p["key"]: p for p in body["runs"][0]["given"]}
        # Measured off the builders: the personality the chat appends, the
        # file Claude Code reads, and the excerpt inside it.
        self.assertEqual(conv["personality"]["bytes"], len(self.persona.encode()))
        self.assertEqual(conv["claude_md"]["bytes"], len(CLAUDE_MD.encode()))
        self.assertGreater(conv["memory_excerpt"]["bytes"], len(DOC.encode()))
        self.assertLess(conv["memory_excerpt"]["bytes"], conv["claude_md"]["bytes"])
        self.assertEqual(conv["notes"]["bytes"], len(b"The porch is south."))
        identity = self.server.CHAT_IDENTITY
        self.assertGreater(conv["identity"]["bytes"], len(identity.encode()) - 1)
        self.assertEqual(conv["identity"]["sec"], "instructions")
        # The per-message facts are a cap, and only the chat face has them.
        [each] = body["runs"][0]["each_time"]
        self.assertEqual(each["bytes"], self.server.CHAT_CONTEXT_CHARS)
        self.assertTrue(each["upto"])
        self.assertEqual(each["only"], "chat")

    def test_what_each_run_may_look_up_is_the_code_s_own_list(self):
        body, _ = self.fetch()
        runs = {r["key"]: r for r in body["runs"]}
        card_tools = {t for g in runs["card"]["looks_up"]["groups"] for t in g["tools"]}
        self.assertEqual(card_tools, {context_map.bare(t)
                                      for t in self.server.engine.ANALYST_TOOLS})
        self.assertIn("recall", card_tools)
        self.assertNotIn("call_service", card_tools)
        conv_tools = {t for g in runs["conversation"]["looks_up"]["groups"]
                      for t in g["tools"]}
        self.assertIn("recall", conv_tools)
        self.assertIn("call_service", conv_tools)
        # No tools at all: said, and nothing listed.
        for key in ("first_look", "overnight"):
            self.assertEqual(runs[key]["looks_up"]["groups"], [], key)
            self.assertEqual(runs[key]["looks_up"]["count"], 0, key)
        # The overnight check is not handed memory in any form.
        labels = " ".join(p["label"] for p in runs["overnight"]["given"]).lower()
        self.assertNotIn("memory", labels)
        self.assertNotIn("fact", labels)
        # Voice never reads CLAUDE.md, and says so.
        self.assertNotIn("claude_md", [p["key"] for p in runs["voice"]["given"]])
        self.assertIn("does not read the house summary file", runs["voice"]["when"])

    def test_nothing_secret_or_private_is_sent(self):
        _, text = self.fetch()
        self.assertNotIn(PLANTED, text)
        self.assertNotIn("sk-ant", text)
        for line in ("Biscuit", "garage fridge", "The porch is south",
                     "Dry, brief, kind", "Vesper"):
            self.assertNotIn(line, text, f"{line!r} — contents left the route")
        self.assertNotIn(self.server.CHAT_IDENTITY[:60], text)


class TestThePieces(unittest.TestCase):
    def test_every_read_only_tool_has_a_name_a_person_can_read(self):
        import engine
        others = [t for t in engine.ANALYST_TOOLS
                  if context_map.tool_group(t) == context_map.OTHER]
        self.assertEqual(others, [])

    def test_the_mcp_server_s_tools_are_read_off_its_source(self):
        names = context_map.mcp_tool_names()
        self.assertIn("recall", names)
        self.assertIn("get_history", names)
        self.assertGreater(len(names), 50)

    def test_numbers_named_for_other_processes_match_their_source(self):
        pool = (BASE_DIR / "brain" / "integrations" / "assist-worker-pool.py"
                ).read_text(encoding="utf-8")
        self.assertIn(f"MEMORY_MAX_BYTES = {context_map.VOICE_MEMORY_BYTES}\n", pool)
        self.assertIn(f"AREA_MAP_MAX_BYTES = {context_map.VOICE_MAP_BYTES}\n", pool)
        gen = (BASE_DIR / "brain" / "scripts" / "ha-context-gen.sh"
               ).read_text(encoding="utf-8")
        default = context_map.claude_md_memory_budget()
        self.assertIn(f"${{BRAIN_CONTEXT_MEMORY_BYTES:-{default}}}", gen)
        self.assertIn(context_map.MEMORY_HEADING, gen)
        self.assertIn(context_map.AFTER_MEMORY.strip(), gen)

    def test_claude_md_split_measures_its_two_blocks(self):
        split = context_map.claude_md_split(CLAUDE_MD)
        self.assertEqual(split["notes"], len(b"The porch is south."))
        self.assertTrue(re.search(r"\d", str(split["memory"])))
        self.assertEqual(context_map.claude_md_split("")["memory"], 0)
        placeholder = ("<!-- bruh:user-notes:start -->\n<!-- Anything inside -->\n"
                       "<!-- bruh:user-notes:end -->")
        self.assertEqual(context_map.claude_md_split(placeholder)["notes"], 0)


if __name__ == "__main__":
    unittest.main()
