#!/usr/bin/env python3
"""A report's ``brain-devloop`` block is valid JSON whatever the add-on log
carried (house filer bug, found 2026-11-07).

A report's block would not parse ("Invalid \\escape") after an add-on log
excerpt with raw escape characters — terminal colour codes, shown as
^[[33m — went into it. Every string in a report now loses its control
characters and ANSI sequences before it goes anywhere, and the block is
held to parsing back to the object it sealed. Driven with an excerpt full
of ESC sequences and backslashes through the real compose.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

from devloop import blocks, streams, upstream  # noqa: E402

LOG = (
    "\x1b[33m2026-11-07 03:12:01 WARNING (MainThread) [brain] a look timed out\x1b[0m\n"
    "\x1b[31mERROR\x1b[0m path C:\\temp\\new \\d+ \\x1b \\u00zz \\\" \\\\ ` ``` \r\n"
    "^[[32mINFO^[[0m ok\n"
    "\x1b]0;title\x07Traceback (most recent call last): \x00\x07\x08 failed\n"
)


class _Plain:
    def apply(self, text: str) -> str:
        return text


def independent_digest(obj: dict) -> str:
    body = {k: v for k, v in obj.items() if k != "digest"}
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class TestTheBlockAlwaysParses(unittest.TestCase):

    def compose(self):
        excerpt = streams.log_excerpt(LOG)
        entry = {
            "fp": "f" * 16, "stream": "faults", "version": "4.2.6",
            "where": "Run (task)", "what": "ended error \x1b[33m(3 times)\x1b[0m",
            "detail": "a detail with \x1b[1mbold\x1b[0m and C:\\path",
            "body": ("<details><summary>Add-on log, the trouble lines (redacted)"
                     "</summary>\n\n```\n" + excerpt + "\n```\n</details>"),
            "log_excerpt": LOG,
            "done_when": "Done when: the block parses \\ always",
        }
        return upstream.compose(entry, _Plain())

    def test_the_block_parses_and_its_digest_verifies(self):
        body = self.compose()["body"]
        m = re.search(r"^```json brain-devloop\n(.*?)\n```$", body, re.S | re.M)
        self.assertIsNotNone(m)
        obj = json.loads(m.group(1))
        self.assertEqual(obj["digest"], independent_digest(obj))
        self.assertEqual(blocks.parse_block("devloop", body), obj)
        self.assertIn("C:\\temp\\new", obj["log_excerpt"])
        self.assertNotIn("\x1b", obj["log_excerpt"])
        self.assertNotIn("^[[", obj["log_excerpt"])

    def test_no_control_character_reaches_the_report(self):
        out = self.compose()
        for text in (out["title"], out["body"]):
            self.assertIsNone(re.search(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]", text),
                              repr(text[:200]))
            self.assertNotIn("[33m", text)

    def test_the_excerpt_keeps_its_words(self):
        excerpt = streams.log_excerpt(LOG)
        self.assertIn("WARNING (MainThread) [brain] a look timed out", excerpt)
        self.assertIn("Traceback (most recent call last):  failed", excerpt)
        self.assertNotIn("\x1b", excerpt)

    def test_a_block_that_would_not_parse_back_is_written_ascii(self):
        text = blocks.make_block("devloop", {"what": "a\u2028b \x1b x"})
        obj = blocks.parse_block("devloop", text)
        self.assertIsNotNone(obj)
        self.assertEqual(obj["what"], "a\u2028b \x1b x")


if __name__ == "__main__":
    unittest.main()
