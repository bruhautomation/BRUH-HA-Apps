#!/usr/bin/env python3
"""`ha-context-gen.sh`'s learned-memory excerpt, driven rather than read.

The block that splices `memory.md` into `/config/CLAUDE.md` used to be
`head -c 4096`: a raw byte cut. Three things follow from that and all three
are reproduced below before the fix is asserted.

  * it cuts mid-fact, so the terminal reads half a sentence as a whole one;
  * it can cut mid-UTF-8-character, leaving bytes nothing can decode;
  * on a sectioned document it never reaches the last section, so
    `## Device notes` was invisible to the most knowledgeable reader brAIn
    has — while `categories.memory_excerpt` has cut on a line boundary for
    exactly this reason since it was written.

The function is lifted out of the real script by name and run, rather than
reimplemented here: a copy of the cut in the test would agree with itself
forever, which is the shape of bug this repo keeps finding.
"""
from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPT = BASE_DIR / "brain" / "scripts" / "ha-context-gen.sh"

NOTE = "memory excerpt trimmed to fit"

SECTIONS = ("Preferences", "Entity nicknames", "Household patterns",
            "Device notes")

# A multibyte character sits at the head of every section's first line, so
# a byte cut anywhere near a boundary lands inside one.
FACT = "- {sec} fact {i}: café con señor Müller — " + "x" * 40


def a_real_shaped_document(per_section: int = 20) -> str:
    lines = ["<!-- brAIn learned memory -->", "# Home memory", ""]
    for sec in SECTIONS:
        lines.append(f"## {sec}")
        for i in range(per_section):
            lines.append(FACT.format(sec=sec, i=i))
        lines.append("")
    return "\n".join(lines) + "\n"


def lift(name: str) -> str:
    """The named function, out of the real script."""
    src = SCRIPT.read_text(encoding="utf-8")
    match = re.search(rf"^{name}\(\) \{{\n.*?^\}}$", src, re.S | re.M)
    assert match, f"ha-context-gen.sh no longer defines {name}"
    return match.group(0)


def run_excerpt(path: Path, budget: str | int | None = None,
                env: dict | None = None) -> bytes:
    """Drive `memory_excerpt` and hand back the raw bytes it emitted."""
    call = f'memory_excerpt "{path}"'
    if budget is not None:
        call += f" {budget}"
    harness = lift("memory_excerpt") + "\n" + call + "\n"
    result = subprocess.run(
        ["bash", "-c", harness], capture_output=True, check=False,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", **(env or {})},
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    return result.stdout


class TestTheOldCutIsWhatWentWrong(unittest.TestCase):
    """The failure, demonstrated on the same fixture, before the fix."""

    def setUp(self):
        self.doc = a_real_shaped_document()

    def test_a_byte_cut_never_reaches_the_last_section(self):
        head = self.doc.encode("utf-8")[:4096]
        self.assertIn(b"## Preferences", head)
        self.assertNotIn("## Device notes".encode(), head)

    def test_a_byte_cut_can_land_inside_a_character(self):
        """Not a theoretical edge: every fact in the fixture carries one."""
        raw = self.doc.encode("utf-8")
        broke = []
        for n in range(1, min(len(raw), 4200)):
            try:
                raw[:n].decode("utf-8")
            except UnicodeDecodeError:
                broke.append(n)
        self.assertTrue(broke, "the fixture has no multibyte character in it")


class TestTheExcerptIsCutBetweenLines(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(__file__).resolve().parent / "_memfixture.md"
        self.addCleanup(lambda: self.tmp.unlink(missing_ok=True))
        self.doc = a_real_shaped_document()
        self.tmp.write_text(self.doc, encoding="utf-8")

    def _excerpt(self, budget=None, env=None) -> str:
        return run_excerpt(self.tmp, budget, env).decode("utf-8")

    def test_a_document_inside_the_budget_arrives_whole(self):
        self.assertEqual(self._excerpt(100_000), self.doc)
        self.assertNotIn(NOTE, self._excerpt(100_000))

    def test_every_line_it_emits_is_a_whole_line_of_the_document(self):
        lines = set(self.doc.splitlines())
        for line in self._excerpt(2_000).splitlines():
            if NOTE in line:
                continue
            self.assertIn(line, lines, f"half a line survived the cut: {line!r}")

    def test_the_output_is_always_decodable(self):
        """The byte cut could split a UTF-8 sequence; a line cut cannot,
        because a newline never occurs inside one."""
        for budget in (80, 200, 900, 2_000, 5_000, 100_000):
            raw = run_excerpt(self.tmp, budget)
            raw.decode("utf-8")  # raises if a character was split

    def test_it_stays_inside_the_budget(self):
        for budget in (200, 900, 2_000, 5_000):
            raw = run_excerpt(self.tmp, budget)
            self.assertLessEqual(len(raw), budget, f"budget {budget}")

    def test_every_section_survives_a_tight_budget(self):
        """The bug: a short excerpt from every section beats a long one from
        the first, and `head -c` could only ever do the second."""
        out = self._excerpt(900)
        for sec in SECTIONS:
            self.assertIn(f"## {sec}", out)
            self.assertIn(f"- {sec} fact 0", out)

    def test_the_head_gets_what_is_left_over(self):
        """The floors are a floor, not a ration: the top of the document
        still gets the rest of the budget."""
        small = self._excerpt(900)
        large = self._excerpt(3_000)
        self.assertGreater(large.count("Preferences fact"),
                           small.count("Preferences fact"))
        for sec in SECTIONS:
            self.assertIn(f"## {sec}", large)

    def test_a_trimmed_excerpt_says_it_was_trimmed(self):
        """A document quietly missing its tail reads as a document that
        never had one."""
        self.assertIn(NOTE, self._excerpt(2_000))

    def test_a_budget_too_small_for_the_floors_still_cuts_on_a_line(self):
        out = self._excerpt(300)
        lines = set(self.doc.splitlines())
        for line in out.splitlines():
            if NOTE not in line:
                self.assertIn(line, lines)

    def test_a_document_with_no_sections_is_still_cut_on_a_line(self):
        plain = "\n".join(f"fact {i}: café {i}" for i in range(400)) + "\n"
        self.tmp.write_text(plain, encoding="utf-8")
        out = run_excerpt(self.tmp, 500).decode("utf-8")
        self.assertLessEqual(len(out.encode()), 500)
        self.assertIn("fact 0:", out)
        for line in out.splitlines():
            if NOTE not in line:
                self.assertIn(line, set(plain.splitlines()))

    def test_an_empty_or_missing_document_emits_nothing(self):
        self.tmp.write_text("", encoding="utf-8")
        self.assertEqual(run_excerpt(self.tmp), b"")
        self.tmp.unlink()
        self.assertEqual(run_excerpt(self.tmp), b"")


class TestTheBudget(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(__file__).resolve().parent / "_membudget.md"
        self.addCleanup(lambda: self.tmp.unlink(missing_ok=True))
        self.tmp.write_text(a_real_shaped_document(400), encoding="utf-8")

    def test_the_default_is_sixteen_kilobytes(self):
        raw = run_excerpt(self.tmp)
        self.assertLessEqual(len(raw), 16_384)
        self.assertGreater(len(raw), 8_192, "the default is no longer 4 KB")

    def test_the_environment_raises_it(self):
        raw = run_excerpt(self.tmp, env={"BRAIN_CONTEXT_MEMORY_BYTES": "32768"})
        self.assertGreater(len(raw), 16_384)
        self.assertLessEqual(len(raw), 32_768)

    def test_a_nonsense_budget_falls_back_to_the_default(self):
        raw = run_excerpt(self.tmp, env={"BRAIN_CONTEXT_MEMORY_BYTES": "lots"})
        self.assertLessEqual(len(raw), 16_384)
        self.assertGreater(len(raw), 8_192)


class TestTheScriptUsesIt(unittest.TestCase):

    def test_the_raw_byte_cut_is_gone(self):
        """Comment lines are stripped first: the paragraph above the fix
        names the old `head -c` on purpose, and a grep that matched it would
        be the one claim a grep cannot honestly make."""
        code = "\n".join(
            line for line in SCRIPT.read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("#")
        )
        self.assertNotIn("head -c", code)
        self.assertIn('memory_excerpt "$memory_file"', code)


if __name__ == "__main__":
    unittest.main()
