#!/usr/bin/env python3
"""A report keeps the owner's words and brAIn's findings whole.

The chat's `report_bug` tool put the owner's words and its whole diagnosis
into `what`, and `what` was sliced at 300 characters — so the issue that
reached the reports repository was a fragment ending mid-word, with no full
quote, no evidence and no Done-when. The look stream (`parse_reply`) and its
fallback (`verbatim_rows`) cut the owner's words at 500 the same way.

The owner's words are the requirement: they keep a generous limit and are
never cut mid-word. `what` stays short because it is the title's line, and
anything beyond that is kept in the body rather than dropped. Every cut is
`textclip.clip`'s — a word boundary and an ellipsis — never a bare slice.
"""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_devloop import NAMES, DevloopCase, diagnostics, upstream  # noqa: E402

import devloop.streams as streams  # noqa: E402

FINDING = " ".join(f"finding{i:04d} the card draws its tile twice" for i in range(50))
OWNER = " ".join(f"word{i:04d} please" for i in range(110))
LONG_EVIDENCE = "\n".join(f"log line {i}: the panel answered 500" for i in range(400))


def ends_on_a_word(text: str, source: str) -> bool:
    """Whole, or cut with the ellipsis after a whole word of `source`."""
    text = text.rstrip()
    if source.strip().endswith(text[-12:]) or text == source.strip():
        return True
    if not text.endswith("…"):
        return False
    shown = text[:-1].rstrip()
    i = source.find(shown[-20:]) + len(shown[-20:])
    return i >= len(source) or not source[i].isalnum()


class TestTheChatsReportKeepsEverything(unittest.TestCase):
    def setUp(self):
        import server  # noqa: PLC0415
        self.server = server

    def test_a_long_finding_and_long_owner_words_are_both_in_the_body(self):
        self.assertGreater(len(FINDING), 2000)
        self.assertGreater(len(OWNER), 1500)
        row, why = self.server.report_row({
            "title": "The hall card is drawn twice", "what": FINDING, "asked": OWNER,
            "evidence": "the panel log", "done_when": "one tile per card"})
        self.assertEqual(why, "")
        self.assertIn(FINDING, row["body"])
        self.assertIn(OWNER, row["body"])
        self.assertLessEqual(len(row["what"]), 300)
        self.assertTrue(ends_on_a_word(row["what"], FINDING), row["what"][-40:])

    def test_evidence_is_cut_on_a_line_not_mid_word(self):
        row, _ = self.server.report_row({"title": "t", "what": "w", "evidence": LONG_EVIDENCE})
        fenced = row["body"].split("```")[1].strip("\n")
        self.assertTrue(ends_on_a_word(fenced, LONG_EVIDENCE), fenced[-40:])

    def test_the_tool_says_which_field_is_which(self):
        sys.path.insert(0, str(BASE_DIR / "brain" / "ha-mcp-server"))
        import ha_mcp_server  # noqa: PLC0415
        tool = next(t for t in ha_mcp_server.TOOLS if t["name"] == "report_bug")
        props = tool["inputSchema"]["properties"]
        self.assertRegex(props["asked"]["description"], r"(?i)verbatim|exact words")
        self.assertRegex(props["what"]["description"], r"(?i)short|one.line|summary")
        self.assertRegex(props["evidence"]["description"], r"(?i)diagnosis")


class TestTheLookStreamKeepsEverything(unittest.TestCase):
    def test_the_reply_and_the_owners_words_reach_the_body_whole(self):
        reply = json.dumps({"rows": [{"title": "Tile drawn twice", "what": FINDING,
                                      "why": "because", "done_when": "one tile"}]})
        rows, problem = streams.parse_reply(reply, "look", OWNER)
        self.assertEqual(problem, "")
        self.assertIn(OWNER, rows[0]["body"])
        self.assertIn(FINDING, rows[0]["body"])
        self.assertTrue(ends_on_a_word(rows[0]["what"], FINDING))

    def test_the_fallback_keeps_the_owners_words(self):
        row = streams.verbatim_rows(OWNER)[0]
        self.assertIn(OWNER, row["body"])
        self.assertTrue(ends_on_a_word(row["what"], OWNER))

    def test_the_prompt_carries_the_owners_words(self):
        self.assertIn(OWNER, streams.analyst_prompt("look", "", OWNER))


class TestTheIssueBodyKeepsEverything(DevloopCase):
    def test_a_filed_report_holds_both_whole_and_nothing_ends_mid_word(self):
        import server  # noqa: PLC0415
        self.switch_on()
        row, _ = server.report_row({"title": "The hall card is drawn twice " * 6,
                                    "what": FINDING, "asked": OWNER})
        upstream.ingest("look", [row], diagnostics(), dict(NAMES))
        entry = next(e for e in upstream._load()["items"].values())
        doc = upstream.compose(entry)
        self.assertIn(FINDING, doc["body"])
        self.assertIn(OWNER, doc["body"])
        what = re.search(r"^\*\*What:\*\* (.*)$", doc["body"], re.M).group(1)
        self.assertTrue(what.endswith("…") or not what[-1:].isalnum() or FINDING.endswith(what))
        self.assertTrue(doc["title"].endswith("…") or len(doc["title"]) < 120, doc["title"])
        self.assertLessEqual(len(doc["title"]), 120)


if __name__ == "__main__":
    unittest.main()
