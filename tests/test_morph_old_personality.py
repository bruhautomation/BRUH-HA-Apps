"""A house still running an older copy that reads personality.js (#391).

Morph's Settings › Personality reads brAIn's personality. A house that
customised Morph before that had its personality in a module of its own,
/config/morph/frontend/personality.js, read by its own copy of
morph-panel.js — and a copy that is in use is what the page runs, so the
house went on reading the old file whatever Morph shipped. A copy that
reads personality.js, and personality.js itself, are paused (Morph's own
runs) and Settings says so in one sentence; making the copy again tells
brAIn to leave the old file behind; nothing Morph ships reads it.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from morph_env import MorphEnv
from test_morph_loops import DOC

ROOT = Path(__file__).resolve().parent.parent
MORPH = ROOT / "brain" / "morph"
FRONTEND_DIR = ROOT / "brain" / "custom_components" / "brain" / "morph" / "frontend"
PANEL_JS = FRONTEND_DIR / "morph-panel.js"

OLD_LOADER = """
  async loadPersona() {
    const mod = await import('./personality.js?v=' + Date.now());
    this.s.persona = { brain: true, personality: { name: mod.PERSONA.name, persona: mod.PERSONA.text, growth: mod.GROWTH } };
  }
"""


class TestACopyThatReadsTheOldFileIsPaused(unittest.TestCase):

    def setUp(self):
        self.env = MorphEnv().__enter__()
        self.addCleanup(self.env.__exit__, None, None, None)
        dash, _ = self.env.store.normalize(DOC)
        self.env.store.write(dash)
        self.env.gitrepo.commit("First", "morph")
        self.code = self.env.morph_dir / "frontend"
        self.code.mkdir()

    def rows(self):
        return {r["name"]: r for r in self.env.morphcode.status()}

    def test_a_copy_of_the_panel_that_imports_it(self):
        (self.code / "morph-panel.js").write_text(PANEL_JS.read_text() + OLD_LOADER)
        self.env.gitrepo.commit("brAIn: a personality section", "brain")
        # Written against the Morph installed now (brAIn merged it), so
        # nothing else would pause it.
        self.env.morphcode.accept("morph-panel.js")
        row = self.rows()["morph-panel.js"]
        self.assertEqual("paused", row["status"])
        self.assertEqual("personality", row["why"])

    def test_the_old_file_itself(self):
        (self.code / "personality.js").write_text("export const PERSONA = {name: 'Wren'};\nexport const GROWTH = [];\n")
        self.env.gitrepo.commit("brAIn: a personality", "brain")
        row = self.rows()["personality.js"]
        self.assertEqual("paused", row["status"])
        self.assertEqual("personality", row["why"])

    def test_a_copy_that_does_not_read_it_is_left_alone(self):
        (self.code / "styles.js").write_text((self.env.shipped / "styles.js").read_text() + "/* a theme */\n")
        self.env.gitrepo.commit("brAIn: a theme", "brain")
        self.assertEqual("active", self.rows()["styles.js"]["status"])

    def test_making_it_again_tells_brain_to_leave_the_old_file_behind(self):
        (self.code / "morph-panel.js").write_text(PANEL_JS.read_text() + OLD_LOADER)
        self.env.gitrepo.commit("brAIn: a personality section", "brain")
        words = self.env.morphcode.redo_words("morph-panel.js", "1.1.3", [])
        self.assertIn("/config/.brain/personality.json", words)
        self.assertIn("personality.js", words)
        self.assertRegex(words, r"(?i)never .*personality\.js|do not .*personality\.js")
        old = self.env.morphcode.redo_words("personality.js", "1.1.3", [])
        self.assertIn("delete /config/morph/frontend/personality.js", old)

    def test_the_served_list_leaves_them_out(self):
        (self.code / "morph-panel.js").write_text(PANEL_JS.read_text() + OLD_LOADER)
        (self.code / "personality.js").write_text("export const PERSONA = {};\n")
        self.env.gitrepo.commit("brAIn: a personality", "brain")
        rows = self.env.morphcode.publish("1.1.3")
        self.assertFalse([r["name"] for r in rows if r["status"] == "active"])


class TestNothingMorphShipsReadsIt(unittest.TestCase):

    def test_no_shipped_module_or_prompt_reads_or_writes_it(self):
        for path in list((FRONTEND_DIR).glob("*.js")) \
                + list((MORPH / "service").glob("*.py")):
            text = path.read_text()
            for m in re.finditer(r"personality\.js\b", text):
                line = text[text.rfind("\n", 0, m.start()) + 1: text.find("\n", m.end())]
                # Only the rule that leaves it behind may name it.
                self.assertRegex(line, r"(?i)retired|never|leave|old|delete|paus|RETIRED",
                                 f"{path.name}: {line.strip()}")

    def test_agents_md_says_never_to_read_or_write_it(self):
        text = (MORPH / "defaults" / "AGENTS.md").read_text()
        self.assertIn("frontend/personality.js", text)

    def test_settings_says_what_to_do(self):
        js = PANEL_JS.read_text()
        self.assertIn("why === 'personality'", js)


if __name__ == "__main__":
    unittest.main()
