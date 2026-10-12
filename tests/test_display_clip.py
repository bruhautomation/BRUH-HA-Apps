#!/usr/bin/env python3
"""A long tool input or result is shortened FOR THE SCREEN, and says so.

The owner's words: "in the brain conversation … there is a … (truncated)
line. You still see the full context and stuff right? You're not cutting
off your own context while trying to answer these?"

No: `chat_session._clip` and `conversations._clip` shorten the copy the
panel DRAWS — the CLI already holds the whole text, and nothing clipped
here is ever sent back to it. But a bare "… (truncated)" cut mid-word
said none of that. So the copy is cut on a line or word boundary, and the
line under it says how much is shown, that it is the display only, and
that Claude has the full text.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import chat_session  # noqa: E402
import conversations  # noqa: E402
import textclip  # noqa: E402

WORDS = " ".join(f"reading{i:04d}" for i in range(2000))   # ~24,000 chars
NOTE_RE = re.compile(
    r"\n… display truncated: ([\d,]+) of ([\d,]+) characters shown here"
    r" — Claude has the full text\.$")


class Shape:
    def check(self, out: str, original: str, limit: int):
        m = NOTE_RE.search(out)
        self.assertIsNotNone(m, out[-200:])
        shown = out[:m.start()]
        self.assertNotIn("(truncated)", out)
        # The counts are the real ones, with thousands separators.
        self.assertEqual(int(m.group(1).replace(",", "")), len(shown))
        self.assertEqual(int(m.group(2).replace(",", "")), len(original))
        self.assertIn(",", m.group(2))
        # Cut on a boundary: what is shown is a prefix of the original and
        # the next character of the original is whitespace — never half a
        # word.
        self.assertTrue(original.startswith(shown))
        self.assertTrue(original[len(shown)].isspace(), repr(original[len(shown) - 5:len(shown) + 5]))
        self.assertLessEqual(len(shown), limit)
        self.assertGreater(len(shown), limit // 2)


class TestTheChatsClip(Shape, unittest.TestCase):
    def test_a_long_result_is_cut_on_a_word_and_says_claude_has_it(self):
        out = chat_session._clip(WORDS, chat_session.MAX_RESULT_CHARS)
        self.check(out, WORDS, chat_session.MAX_RESULT_CHARS)

    def test_a_long_tool_input_is_cut_on_a_line(self):
        lines = "\n".join(f'  "key_{i}": "value number {i}",' for i in range(3000))
        out = chat_session._clip(lines, chat_session.MAX_RESULT_CHARS)
        self.check(out, lines, chat_session.MAX_RESULT_CHARS)
        shown = out[:NOTE_RE.search(out).start()]
        self.assertTrue(lines[len(shown)] == "\n", "not cut at the end of a line")

    def test_text_that_fits_is_untouched(self):
        self.assertEqual(chat_session._clip("short and sweet", 200), "short and sweet")

    def test_a_one_line_label_ends_in_an_ellipsis_and_no_note(self):
        out = chat_session._clip(WORDS, 200)
        self.assertNotIn("\n", out)
        self.assertTrue(out.endswith("…"))
        self.assertLessEqual(len(out), 200)
        self.assertTrue(WORDS[len(out) - 1].isspace())


class TestTheReplaysClip(Shape, unittest.TestCase):
    def test_a_long_message_is_cut_on_a_word_and_says_claude_has_it(self):
        out = conversations._clip(WORDS)
        self.check(out, WORDS, conversations.MAX_TEXT)

    def test_text_that_fits_is_untouched(self):
        self.assertEqual(conversations._clip("fine"), "fine")


class TestOneImplementation(unittest.TestCase):
    def test_both_clips_go_through_textclip(self):
        self.assertEqual(chat_session._clip(WORDS, 4000),
                         textclip.shown(WORDS, 4000))
        self.assertEqual(conversations._clip(WORDS),
                         textclip.shown(WORDS, conversations.MAX_TEXT))


if __name__ == "__main__":
    unittest.main()
