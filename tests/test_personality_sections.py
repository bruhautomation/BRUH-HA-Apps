"""⚙ › Personality reads as the outline a house wrote, and says when it was cut.

The owner: *"the personality in brAIn settings still looks clipped; fix
that; and bring back the rich formatting / sections that used to exist in
that menu in Morph."* A persona moved over from Morph's old PERSONA object
is an outline of labelled parts (`line: …`, `born: …`, `who_i_am:` with
its items under it). The ⚙ list row showed the outline's raw first line —
"Juniper · line: The evening star…" — where the tagline belongs, and a
persona an older 4,000-character cap had already cut was stored ending in
"…" and shown as if whole. `summary` now leads with the tagline, and the
payload says when a persona looks cut at that old limit so the page can
say so once (the page draws the sections; `measure-settings` holds that).
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain" / "panel"))

import personality  # noqa: E402
import textclip  # noqa: E402

OUTLINE = "\n".join([
    "line: The evening star of the house, steady and a little wry.",
    "born: 2026-03-14",
    "who_i_am:",
    "  - a keeper of small routines",
    "  - plain-spoken",
    "how_i_am: Calm first, quick second.",
    "voice:",
    "  rules:",
    "    - one sentence for what changed",
    "  tone: warm",
    "never:",
    "  - lecture",
    "name_why: Named for the star that comes out first.",
    "still_working_out: when to speak up at night",
])


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        (Path(self.tmp.name) / ".brain").mkdir()
        self.file = str(Path(self.tmp.name) / ".brain" / "personality.json")

    def tearDown(self):
        self.tmp.cleanup()


class TestTheRowLeadsWithTheTagline(Case):
    def test_an_outline_row_is_the_name_and_the_tagline_without_its_label(self):
        out = personality.summary({"name": "Juniper", "persona": OUTLINE})
        self.assertEqual(out, "Juniper · The evening star of the house, steady and a little wry.")
        self.assertNotIn("line:", out)

    def test_a_tagline_key_reads_the_same(self):
        out = personality.tagline("tagline: Quietly useful.\nborn: 2026-01-01")
        self.assertEqual(out, "Quietly useful.")

    def test_an_outline_without_a_tagline_leads_with_its_first_words_not_a_label(self):
        out = personality.tagline("who_i_am:\n  - a keeper of small routines\nborn: 2026")
        self.assertEqual(out, "a keeper of small routines")

    def test_plain_prose_is_unchanged(self):
        self.assertEqual(personality.summary({"name": "Wren", "persona": "Warm and brief.\n\nNever lectures."}),
                         "Wren · Warm and brief.")

    def test_the_payload_carries_the_row_so_a_save_shows_the_same_words(self):
        personality.save("Juniper", OUTLINE, path=self.file)
        out = personality.payload(self.file)
        self.assertEqual(out["summary"], "Juniper · The evening star of the house, steady and a little wry.")


class TestACutPersonaIsSaid(Case):
    def cut_at_the_old_cap(self):
        long = " ".join(f"Sentence {i} about how the house is kept." for i in range(200))
        cut = textclip.clip(long, personality.OLD_PERSONA_MAX)
        self.assertTrue(cut.endswith("…"))
        return cut

    def test_a_persona_cut_by_the_old_cap_is_flagged(self):
        personality.save("Juniper", self.cut_at_the_old_cap(), path=self.file)
        self.assertTrue(personality.payload(self.file)["cut_at_old_limit"])

    def test_the_bare_slice_the_cap_once_was_is_flagged_too(self):
        cut = ("x" * 5000)[:3999] + "…"
        self.assertTrue(personality.looks_cut(cut))

    def test_a_whole_persona_is_not(self):
        self.assertFalse(personality.looks_cut(OUTLINE))
        self.assertFalse(personality.looks_cut("Short, and trails off…"))
        # longer than the old cap could ever have left it
        self.assertFalse(personality.looks_cut("y" * 4500 + "…"))

    def test_nothing_is_invented_the_text_is_kept_as_stored(self):
        cut = self.cut_at_the_old_cap()
        personality.save("Juniper", cut, path=self.file)
        self.assertEqual(personality.payload(self.file)["persona"], cut)


if __name__ == "__main__":
    unittest.main()
