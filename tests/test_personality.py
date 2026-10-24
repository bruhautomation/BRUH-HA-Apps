"""Who brAIn is in this house lives in brAIn, not in Morph.

The owner: *"the personality settings are in Morph, not brAIn … not every
person who uses these apps are going to use Morph, but they have to use
brAIn. So we need to put that stuff in brAIn, period."* So the persona, its
name and its growth log are one JSON file in brAIn's config
(`personality.py`), served at `/api/personality`, carried in the chat's and
the terminal's prompt, the generated `/config/CLAUDE.md` and the voice
prompt, read ONCE out of Morph's old copy at startup, and recorded from a
conversation through one MCP tool that no unattended run and no voice turn
may call.
"""
from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PANEL = ROOT / "brain" / "panel"
SCRIPTS = ROOT / "brain" / "scripts"
MCP_DIR = ROOT / "brain" / "ha-mcp-server"
sys.path.insert(0, str(PANEL))

import personality  # noqa: E402

# A Morph frontend copy in the shape such a file is written in: an exported
# object literal with unquoted keys, a template literal, comments and a
# trailing comma, and a growth array of dated entries.
MORPH_JS = r"""// Who the dashboard's assistant is, for this household.
export const PERSONA = {
  name: 'Juniper',
  // what it is like
  persona: `Warm and dry-humoured. Says what it did in one line,
and never fusses about it.`,
};

/* How it has grown */
export const GROWTH = [
  { date: '2026-08-02', text: "Learned that \"the den\" means the office." },
  { at: 1757000000000, note: 'Stopped announcing the heating twice.' },
  'Calls the side door the garden door.',
];
"""


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / ".brain"
        self.dir.mkdir()
        self.file = str(self.dir / "personality.json")

    def tearDown(self):
        self.tmp.cleanup()


class TestTheStore(StoreCase):
    def test_an_absent_file_is_no_personality(self):
        data = personality.load(self.file)
        self.assertEqual(data["name"], "")
        self.assertEqual(data["persona"], "")
        self.assertEqual(data["growth"], [])
        self.assertFalse(personality.is_set(data))
        self.assertEqual(personality.prompt_block(data), "")

    def test_a_broken_file_never_raises(self):
        Path(self.file).write_text("{not json", encoding="utf-8")
        self.assertFalse(personality.is_set(personality.load(self.file)))
        Path(self.file).write_text("[1, 2]", encoding="utf-8")
        self.assertFalse(personality.is_set(personality.load(self.file)))

    def test_save_and_growth_round_trip(self):
        personality.save("Juniper", "Warm and brief.", path=self.file)
        personality.add_growth("Learned the den is the office.",
                               when=1_760_000_000, path=self.file)
        data = personality.load(self.file)
        self.assertEqual(data["name"], "Juniper")
        self.assertEqual(data["persona"], "Warm and brief.")
        self.assertEqual(len(data["growth"]), 1)
        self.assertRegex(data["growth"][0]["date"], r"^\d{4}-\d{2}-\d{2}$")
        # A save keeps the growth log.
        personality.save("Juniper", "Warmer.", path=self.file)
        self.assertEqual(len(personality.load(self.file)["growth"]), 1)

    def test_caps(self):
        with self.assertRaises(ValueError):
            personality.save("x" * (personality.NAME_MAX + 1), "", path=self.file)
        with self.assertRaises(ValueError):
            personality.save("x", "y" * (personality.PERSONA_MAX + 1), path=self.file)
        with self.assertRaises(ValueError):
            personality.add_growth("   ", path=self.file)
        for i in range(personality.GROWTH_MAX + 5):
            personality.add_growth(f"entry {i}", when=1_760_000_000 + i, path=self.file)
        growth = personality.load(self.file)["growth"]
        self.assertEqual(len(growth), personality.GROWTH_MAX)
        self.assertEqual(growth[-1]["text"], f"entry {personality.GROWTH_MAX + 4}")

    def test_it_never_creates_its_own_directory(self):
        missing = str(Path(self.tmp.name) / "nowhere" / "personality.json")
        with self.assertRaises(ValueError):
            personality.save("Juniper", "Warm.", path=missing)
        self.assertFalse(Path(missing).parent.exists())

    def test_the_payload_lists_growth_newest_first(self):
        personality.add_growth("first", when=1_700_000_000, path=self.file)
        personality.add_growth("second", when=1_760_000_000, path=self.file)
        out = personality.payload(self.file)
        self.assertEqual([g["text"] for g in out["growth"]], ["second", "first"])


class TestThePromptBlock(StoreCase):
    def test_it_names_and_describes_and_is_bounded(self):
        personality.save("Juniper", "Warm and brief.", path=self.file)
        block = personality.prompt_block(personality.load(self.file))
        self.assertIn("Your name is Juniper.", block)
        self.assertIn("Your personality: Warm and brief.", block)
        long = {"name": "Juniper", "persona": "word " * 900, "growth": [
            {"date": "2026-01-0%d" % i, "text": "grew " * 100} for i in range(1, 9)]}
        block = personality.prompt_block(long)
        self.assertLess(len(block), personality.PROMPT_PERSONA_CHARS
                        + personality.PROMPT_GROWTH_ENTRIES
                        * (personality.PROMPT_GROWTH_CHARS + 20) + 200)
        self.assertEqual(block.count("\n- "), personality.PROMPT_GROWTH_ENTRIES)

    def test_the_claude_md_section_is_empty_when_none_is_set(self):
        self.assertEqual(personality.section(self.file), "")
        personality.save("Juniper", "Warm.", path=self.file)
        self.assertIn("## Personality", personality.section(self.file))


class TestTheMorphMigration(StoreCase):
    def write_morph(self, text):
        src = Path(self.tmp.name) / "personality.js"
        src.write_text(text, encoding="utf-8")
        return str(src)

    def test_the_object_literal_is_read_once(self):
        src = self.write_morph(MORPH_JS)
        before = Path(src).read_bytes()
        said = personality.migrate_from_morph(src, self.file)
        self.assertIn("moved", said)
        data = personality.load(self.file)
        self.assertEqual(data["name"], "Juniper")
        self.assertIn("never fusses", data["persona"])
        self.assertEqual(len(data["growth"]), 3)
        self.assertTrue(any('"the den"' in g["text"] for g in data["growth"]))
        self.assertEqual(Path(src).read_bytes(), before, "Morph's file was written")
        # Once: an existing brAIn file is never replaced.
        personality.save("Rowan", "Different.", path=self.file)
        self.assertEqual(personality.migrate_from_morph(src, self.file), "")
        self.assertEqual(personality.load(self.file)["name"], "Rowan")

    def test_a_plain_string_persona(self):
        src = self.write_morph('const PERSONA = "Cheerful and quick.";\n'
                               'const GROWTH = [];\n')
        personality.migrate_from_morph(src, self.file)
        self.assertEqual(personality.load(self.file)["persona"], "Cheerful and quick.")

    def test_an_unreadable_file_moves_nothing_and_says_so(self):
        for bad in ("export const PERSONA = `hi ${name}`;",
                    "export const PERSONA = makePersona();",
                    "export const OTHER = 1;"):
            src = self.write_morph(bad)
            said = personality.migrate_from_morph(src, self.file)
            self.assertIn("nothing was moved", said, bad)
            self.assertFalse(os.path.exists(self.file), bad)

    def test_no_morph_file_is_silent(self):
        self.assertEqual(personality.migrate_from_morph(
            str(Path(self.tmp.name) / "absent.js"), self.file), "")


class TestTheRoutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import server
        cls.server = server

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        (Path(self.tmp.name) / ".brain").mkdir()
        self.file = str(Path(self.tmp.name) / ".brain" / "personality.json")
        self.old = personality.STORE
        personality.STORE = self.file
        self.old_prompt = self.server.TERMINAL_PROMPT_FILE
        self.server.TERMINAL_PROMPT_FILE = Path(self.tmp.name) / "term.md"

    def tearDown(self):
        personality.STORE = self.old
        self.server.TERMINAL_PROMPT_FILE = self.old_prompt
        self.tmp.cleanup()

    def drive(self, body):
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer

        async def run():
            app = web.Application()
            app.router.add_get("/api/personality", self.server.h_personality_get)
            app.router.add_put("/api/personality", self.server.h_personality_put)
            app.router.add_post("/api/personality/growth",
                                self.server.h_personality_growth)
            async with TestClient(TestServer(app)) as client:
                await body(client)
        asyncio.run(run())

    def test_get_put_and_growth(self):
        seen = {}

        async def body(client):
            res = await client.get("/api/personality")
            seen["empty"] = await res.json()
            res = await client.put("/api/personality",
                                   json={"name": "Juniper", "persona": "Warm."})
            seen["put"] = res.status
            res = await client.post("/api/personality/growth",
                                    json={"text": "Learned the den is the office."})
            seen["grow"] = res.status
            seen["after"] = await (await client.get("/api/personality")).json()
            res = await client.put("/api/personality", json={"persona": 3})
            seen["bad"] = res.status
            res = await client.post("/api/personality/growth", json={"text": ""})
            seen["bad_grow"] = res.status

        self.drive(body)
        self.assertFalse(seen["empty"]["set"])
        self.assertEqual(seen["put"], 200)
        self.assertEqual(seen["grow"], 200)
        self.assertEqual(seen["after"]["name"], "Juniper")
        self.assertEqual(seen["after"]["growth"][0]["text"],
                         "Learned the den is the office.")
        self.assertEqual(seen["bad"], 400)
        self.assertEqual(seen["bad_grow"], 400)
        # A save rewrites the terminal's prompt, so a new window has it.
        self.assertIn("Your name is Juniper.",
                      self.server.TERMINAL_PROMPT_FILE.read_text(encoding="utf-8"))

    def test_the_chat_prompt_carries_it_only_when_set(self):
        plain = self.server._chat_system_prompt(None)
        self.assertNotIn("Your name is", plain)
        personality.save("Juniper", "Warm and brief.", path=self.file)
        said = self.server._chat_system_prompt(None)
        self.assertIn("Your name is Juniper.", said)
        self.assertIn("Your personality: Warm and brief.", said)

    def test_the_settings_payload_carries_the_summary(self):
        personality.save("Juniper", "Warm and brief.", path=self.file)
        out = self.server._settings_payload({})
        self.assertIn("Juniper", out["personality_summary"])


class TestTheVoicePrompt(StoreCase):
    def setUp(self):
        super().setUp()
        sys.path.insert(0, str(SCRIPTS))
        import brain_voice_context
        self.v = brain_voice_context

    def test_the_household_persona_stands_in_for_the_default_style(self):
        none = self.v.system_prompt(household="")
        self.assertIn(self.v.DEFAULT_STYLE, none)
        personality.save("Juniper", "Warm and brief.", path=self.file)
        block = personality.prompt_block(personality.load(self.file))
        said = self.v.system_prompt(household=block)
        self.assertIn("Your name is Juniper.", said)
        self.assertNotIn(self.v.DEFAULT_STYLE, said)
        # An agent's own personality still wins over the household's.
        own = self.v.system_prompt(custom="A pirate.", household=block)
        self.assertIn("A pirate.", own)
        self.assertNotIn("Juniper", own)

    def test_it_reads_the_file_itself(self):
        personality.save("Juniper", "Warm and brief.", path=self.file)
        old = os.environ.get("BRAIN_PERSONALITY_FILE")
        os.environ["BRAIN_PERSONALITY_FILE"] = self.file
        try:
            self.assertIn("Juniper", self.v.household_personality())
        finally:
            if old is None:
                os.environ.pop("BRAIN_PERSONALITY_FILE", None)
            else:
                os.environ["BRAIN_PERSONALITY_FILE"] = old


class TestTheGeneratedClaudeMd(StoreCase):
    def lift(self):
        src = (SCRIPTS / "ha-context-gen.sh").read_text(encoding="utf-8")
        match = re.search(r"^personality_section\(\) \{\n.*?^\}$", src, re.S | re.M)
        self.assertTrue(match, "ha-context-gen.sh no longer defines personality_section")
        self.assertIn("${personality_section}", src)
        return match.group(0)

    def run_section(self):
        harness = self.lift() + "\npersonality_section\n"
        out = subprocess.run(
            ["bash", "-c", harness], capture_output=True, text=True, check=True,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                 "BRAIN_PANEL_DIR": str(PANEL),
                 "BRAIN_PERSONALITY_FILE": self.file})
        return out.stdout

    def test_none_set_is_nothing(self):
        self.assertEqual(self.run_section().strip(), "")

    def test_a_set_personality_is_a_section(self):
        personality.save("Juniper", "Warm and brief.", path=self.file)
        out = self.run_section()
        self.assertIn("## Personality", out)
        self.assertIn("Your name is Juniper.", out)


class TestTheMcpTool(unittest.TestCase):
    TOOL = "note_personality_change"

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(MCP_DIR))
        import ha_mcp_server
        import engine
        import consequence
        cls.mcp, cls.engine, cls.consequence = ha_mcp_server, engine, consequence

    def test_it_is_a_tool_that_writes_through_the_panel(self):
        self.assertIn(self.TOOL, self.mcp.TOOL_IMPLEMENTATIONS)
        sent = []
        old = self.mcp._panel_send
        self.mcp._panel_send = lambda m, p, b=None, timeout=60: (
            sent.append((m, p, b)) or {"ok": True})
        try:
            self.mcp.note_personality_change("Learned the den is the office.")
        finally:
            self.mcp._panel_send = old
        self.assertEqual(sent, [("POST", "/api/personality/growth",
                                 {"text": "Learned the den is the office."})])

    def test_no_unattended_run_and_no_voice_turn_may_call_it(self):
        name = f"{self.engine.MCP}{self.TOOL}"
        self.assertIn(name, self.engine.ANALYST_DENIED)
        self.assertNotIn(name, self.engine.ANALYST_TOOLS)
        self.assertIn(self.TOOL, self.consequence.GATED_MCP)
        self.assertIn(self.TOOL, self.mcp.VOICE_REFUSED_TOOLS)
        self.assertIn(self.TOOL, self.mcp.CONTRACT_REFUSED_TOOLS)
        hook = (ROOT / "brain" / "scripts" / "brain-action-gate.py").read_text(
            encoding="utf-8")
        self.assertIn(f'"{self.TOOL}"', hook)


if __name__ == "__main__":
    unittest.main()
