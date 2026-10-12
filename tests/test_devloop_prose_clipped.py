"""What the development loop shows a model or a person ends on a word.

The devloop's "already reported" list cut each report's sentence at 200
characters with a bare slice, so the run deciding whether a new report is
a rewording of an old one was shown "…the same problem is filed twice by
differ". `textclip.clip` is the repo's one rule for prose (it is never
stored ending mid-word); these drive the real builders with long sentences
and check every cut lands on a boundary and says it shortened.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import devloop.streams as streams  # noqa: E402
from textclip import ELLIPSIS  # noqa: E402

WORDS = ("findings are not merged across sources so the same problem is "
         "filed twice by different cards and somebody answers it twice ")


def long(n: int) -> str:
    return (WORDS * (n // len(WORDS) + 1))[:n].strip()


def ends_on_a_word(text: str) -> bool:
    if not text.endswith(ELLIPSIS):
        return False
    body = text[:-len(ELLIPSIS)]
    return any(body.endswith(w) for w in WORDS.split())


class TestTheReportedList(unittest.TestCase):
    def test_a_long_report_is_cut_on_a_word_and_kept_longer(self):
        what = long(700)
        block = streams.reported_block([
            {"stream": "look", "where": "Look: Findings", "what": what,
             "state": "sent", "last_seen": 1}])
        shown = block[len("- Look: Findings: "):]
        self.assertTrue(ends_on_a_word(shown), shown[-40:])
        self.assertLessEqual(len(shown), streams.REPORTED_WHAT_CHARS)
        # More than the old 200 characters of the sentence survive.
        self.assertGreater(len(shown), 300)

    def test_a_short_report_is_untouched(self):
        block = streams.reported_block([
            {"stream": "gaps", "where": "Gap: A", "what": "no image analysis",
             "state": "sent", "last_seen": 1}])
        self.assertEqual(block, "- Gap: A: no image analysis")

    def test_the_block_is_bounded_in_whole_lines(self):
        rows = [{"stream": "look", "where": f"Look: {i}", "what": long(700),
                 "state": "sent", "last_seen": 1000 - i}
                for i in range(streams.MAX_REPORTED)]
        block = streams.reported_block(rows)
        self.assertLessEqual(len(block), streams.REPORTED_CHARS)
        for row in block.splitlines():
            self.assertTrue(row.startswith("- Look: "), row[:30])
            self.assertTrue(ends_on_a_word(row), row[-30:])
        # Newest first, and the newest is never the one dropped.
        self.assertTrue(block.startswith("- Look: 0: "))


class TestTheOtherCuts(unittest.TestCase):
    def test_a_wrong_reason_ends_on_a_word(self):
        rows = streams.wrongs(
            [{"source": "check:x", "title": "X", "wrong": 3, "total": 3}],
            [{"kind": "ignored", "source": "check:x", "note": long(500)}])
        said = [x for x in rows[0]["body"].splitlines() if x.startswith("> ")]
        self.assertTrue(said and ends_on_a_word(said[0][2:]), said)

    def test_the_design_context_cuts_on_words(self):
        ctx = streams.design_context(
            [{"title": long(300), "summary": long(900)}],
            [{"text": long(500), "detail": "short", "fix": long(500),
              "triage": {"reason": long(500)}}])
        card = [x for x in ctx.splitlines() if x.startswith("- ")]
        title, summary = card[0][2:].split(" — ", 1)
        self.assertTrue(ends_on_a_word(title), title[-30:])
        self.assertTrue(ends_on_a_word(summary), summary[-30:])
        bits = card[1][2:].split(" | ")
        self.assertEqual(bits[1], "short")
        for bit in (bits[0], bits[2], bits[3]):
            self.assertTrue(ends_on_a_word(bit), bit[-30:])

    def test_a_long_capability_ends_on_a_word_and_keeps_its_key(self):
        said = "I cannot " + long(400) + "."
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("a", "b"):
                Path(tmp, f"{name}.json").write_text(json.dumps({"events": [
                    {"type": "user", "text": "do it"},
                    {"type": "text", "text": said}]}))
            rows = streams.unmet(Path(tmp))
        self.assertEqual(len(rows), 1)
        self.assertTrue(ends_on_a_word(rows[0]["what"]), rows[0]["what"][-30:])
        self.assertLessEqual(len(rows[0]["what"]), streams.CAPABILITY_CHARS)
        # The key is what the old raw cut produced, so a stored verdict
        # still finds it.
        self.assertEqual(rows[0]["key"], streams.capability_key(
            " ".join(said[:-1].split())[:200]))

    def test_a_morph_row_morph_wrote_is_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as tmp:
            outbox = Path(tmp, "outbox.json")
            what = "Morph: a card threw TypeError while opening"
            outbox.write_text(json.dumps({"rows": [
                {"where": "Morph · card", "what": what, "detail": "d"}]}))
            rows = streams.morph(outbox)
        self.assertEqual(rows[0]["what"], what)


if __name__ == "__main__":
    unittest.main()
