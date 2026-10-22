"""⚙ › Instructions: every prompt brAIn sends Claude, read and changed in place.

Driven against the real modules: a saved override must reach the attribute
the run reads, a removed placeholder must be refused (a prompt that loses
``{findings}`` silently stops seeing findings), a file edited in the terminal
must be picked up by the scheduler's sync, and Restore must put the shipped
text back.
"""

import os
import sys
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path

PANEL = Path(__file__).resolve().parent.parent / "brain" / "panel"
sys.path.insert(0, str(PANEL))

import brief  # noqa: E402
import instructions  # noqa: E402


class InstructionsCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.patches = [
            unittest.mock.patch.object(instructions, "DIR", self.dir),
            unittest.mock.patch.dict(instructions._APPLIED, {}, clear=True),
            unittest.mock.patch.dict(instructions._ERRORS, {}, clear=True),
        ]
        for p in self.patches:
            p.start()
        self.shipped_brief = instructions.shipped("brief")

    def tearDown(self):
        instructions.reset("brief")
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()


class TestTheCatalogNamesRealPrompts(InstructionsCase):

    def test_every_carrier_exists_and_holds_text(self):
        for key, (_t, group, _w, targets) in instructions.CATALOG.items():
            self.assertIn(group, instructions.GROUPS, key)
            for mod_name, attr in targets:
                if mod_name == "server":
                    continue  # importing the panel's server here costs seconds
                mod = instructions._module(mod_name)
                self.assertIsInstance(getattr(mod, attr), str, f"{key}: {mod_name}.{attr}")


class TestSaveApplyRestore(InstructionsCase):

    def test_a_saved_override_is_what_the_run_reads_and_restore_undoes_it(self):
        text = self.shipped_brief + "\nAlways mention the porch light."
        instructions.save("brief", text)
        self.assertEqual(brief.SYSTEM, text)
        self.assertTrue((self.dir / "brief.md").exists())
        row = next(r for r in instructions.listing() if r["key"] == "brief")
        self.assertTrue(row["overridden"])
        instructions.reset("brief")
        self.assertEqual(brief.SYSTEM, self.shipped_brief)
        self.assertFalse((self.dir / "brief.md").exists())

    def test_an_empty_text_is_refused_and_nothing_changes(self):
        with self.assertRaises(ValueError):
            instructions.save("brief", "   ")
        self.assertEqual(brief.SYSTEM, self.shipped_brief)

    def test_a_dropped_placeholder_is_refused(self):
        base = "Read {findings} and write %(budget)s words."
        with unittest.mock.patch.dict(instructions._SHIPPED, {"brief": base}):
            for gone in ("{findings}", "%(budget)s"):
                with self.assertRaises(ValueError) as ctx:
                    instructions.save("brief", base.replace(gone, ""))
                self.assertIn(gone, str(ctx.exception))
            self.assertIsNone(instructions.check("brief", base + " More."))

    def test_an_edit_made_in_the_terminal_is_picked_up_by_sync(self):
        instructions.save("brief", self.shipped_brief + "\nfirst")
        path = self.dir / "brief.md"
        path.write_text(self.shipped_brief + "\nsecond")
        later = time.time() + 5
        os.utime(path, (later, later))
        self.assertIn("brief", instructions.sync())
        self.assertTrue(brief.SYSTEM.endswith("second"))
        path.unlink()
        self.assertIn("brief", instructions.sync())
        self.assertEqual(brief.SYSTEM, self.shipped_brief)

    def test_a_broken_file_falls_back_to_the_shipped_text_and_says_so(self):
        (self.dir / "brief.md").write_text("")
        instructions.apply("brief")
        self.assertEqual(brief.SYSTEM, self.shipped_brief)
        self.assertTrue(instructions.detail("brief")["error"])


class TestFiles(InstructionsCase):

    def test_the_notes_block_is_the_only_part_of_claude_md_written(self):
        md = self.dir / "CLAUDE.md"
        md.write_text("# generated\n" + instructions.NOTES_START + "\nold\n"
                      + instructions.NOTES_END + "\n# more generated\n")
        entry = instructions.FILES["claude_md_notes"]
        with unittest.mock.patch.dict(instructions.FILES, {
                "claude_md_notes": entry[:3] + (f"{md}#notes", True)}):
            self.assertEqual(instructions.read_file("claude_md_notes")["text"], "old")
            instructions.write_file("claude_md_notes", "the porch light is on a timer")
        text = md.read_text()
        self.assertTrue(text.startswith("# generated\n"))
        self.assertTrue(text.endswith("# more generated\n"))
        self.assertIn("the porch light is on a timer", text)
        self.assertNotIn("old", text)

    def test_a_file_brain_writes_cannot_be_saved_here(self):
        with self.assertRaises(ValueError):
            instructions.write_file("memory", "anything")

    def test_builtins_are_exported_for_claude_to_read(self):
        n = instructions.export_builtins()
        self.assertGreater(n, 0)
        self.assertEqual((self.dir / "builtin" / "brief.md").read_text(), self.shipped_brief)


if __name__ == "__main__":
    unittest.main()
