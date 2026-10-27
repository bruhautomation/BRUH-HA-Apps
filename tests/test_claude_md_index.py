"""CLAUDE.md is an index, and the notes it points at are all there.

CLAUDE.md is loaded into every Claude Code session and every subagent, on
every turn. It grew to nearly 900 KB (about 223k tokens), one bullet per
lesson, so every turn of a long development-loop run re-read all of it,
and that, not the fixing, was most of what the loop spent. The notes moved
word for word into ``docs/notes/``, one file per area, and CLAUDE.md lists
them. These tests keep that shape:

- CLAUDE.md stays under ``MAX_BYTES``: a new lesson belongs in its area's
  note, and a file nobody holds to a size grows back within weeks.
- Every note is listed in CLAUDE.md, and every note CLAUDE.md names
  exists, so a note nobody can find and a pointer to nothing both fail.
- Every note says what it covers in its first lines, because an agent
  decides from those whether to read the rest.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "CLAUDE.md"
NOTES = ROOT / "docs" / "notes"
MAX_BYTES = 40_000


class TestClaudeMdIsAnIndex(unittest.TestCase):
    def setUp(self):
        self.text = INDEX.read_text(encoding="utf-8")
        self.notes = sorted(p.name for p in NOTES.glob("*.md"))

    def test_it_stays_small(self):
        size = len(self.text.encode("utf-8"))
        self.assertLess(
            size, MAX_BYTES,
            f"CLAUDE.md is {size} bytes, over {MAX_BYTES}. It is loaded on "
            "every turn of every session: put the new lesson in the note "
            "for its area under docs/notes/ instead.")

    def test_there_are_notes(self):
        self.assertGreater(len(self.notes), 10)

    def test_every_note_is_listed(self):
        for name in self.notes:
            self.assertIn(f"`docs/notes/{name}`", self.text,
                          f"docs/notes/{name} is not listed in CLAUDE.md's "
                          "'Where the notes are', so nobody will read it.")

    def test_every_listed_note_exists(self):
        for name in re.findall(r"docs/notes/([\w.-]+\.md)", self.text):
            self.assertIn(name, self.notes,
                          f"CLAUDE.md points at docs/notes/{name}, "
                          "which does not exist.")

    def test_every_note_says_what_it_covers(self):
        for name in self.notes:
            head = (NOTES / name).read_text(encoding="utf-8").split("\n")
            self.assertTrue(head[0].startswith("# "), name)
            self.assertTrue(head[2].strip(), f"{name} has no summary line")


if __name__ == "__main__":
    unittest.main()
