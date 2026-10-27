#!/usr/bin/env python3
"""A question brAIn asks is a question, never a fault.

On a real house the Findings tab and `get_findings` listed rows reading
"Vesper asks: …" — the assistant's own curiosity questions, "Still open
from an earlier conversation" — among the problems, with Add to To Do and
Ignore under them and nowhere to type the answer.

A row whose text (or claim) starts with the assistant's name and
"asks:" is filed without the prefix as a `question`, marked `asked`:
on Needs you it is read under **Questions for you** (one card at a time,
`measure-today`), answered in a typed box whose words go to the memory
inbox beside the question, and `get_findings` leaves it out. Rows stored
before this are read the same way (the store reads its file through the
same rule). Driven through `findings_store.coerce`, the store's read, the
case read-model, the answer route and the MCP tool.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))
sys.path.insert(0, str(BASE_DIR / "brain" / "ha-mcp-server"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import answers  # noqa: E402
import findings_store  # noqa: E402
from fake_core_ws import drive_app  # noqa: E402

VESPER = "Vesper asks: Why does the porch light come on at 3am on weekdays?"
DEFAULT = "brAIn asks: Is the cellar dehumidifier meant to run all night?"


def named(name="Vesper"):
    return patch("personality.assistant_name", return_value=name)


class TestFiledAsAQuestion(unittest.TestCase):
    def test_the_named_assistant(self):
        with named():
            row = findings_store.coerce({"text": VESPER, "source": "study:x",
                                         "detail": "Still open from an "
                                                   "earlier conversation."})
        self.assertEqual(row["text"],
                         "Why does the porch light come on at 3am on weekdays?")
        self.assertEqual(row["kind"], "question")
        self.assertIs(row["asked"], True)

    def test_brains_own_name_and_a_claim(self):
        with named():
            row = findings_store.coerce({"text": DEFAULT, "claim": DEFAULT})
        self.assertEqual(row["text"],
                         "Is the cellar dehumidifier meant to run all night?")
        self.assertEqual(row["claim"], row["text"])
        self.assertEqual(row["kind"], "question")

    def test_somebody_else_asking_is_not_brains_question(self):
        with named():
            row = findings_store.coerce({
                "text": "The homeowner asks: why is the boiler on?"})
            other = findings_store.coerce({"text": "Hall motion is offline"})
        self.assertNotEqual(row.get("kind"), "question")
        self.assertNotIn("asked", other)


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "inbox").mkdir()
        self._fs = {k: getattr(findings_store, k) for k in
                    ("FINDINGS_FILE", "INBOX_DIR", "SETTLED_FILE", "STATE_FILE")}
        findings_store.FINDINGS_FILE = root / "findings.json"
        findings_store.INBOX_DIR = root / "inbox"
        findings_store.SETTLED_FILE = root / "settled.json"
        findings_store.STATE_FILE = root / "config" / ".brain" / "state.json"
        self.root = root

    def tearDown(self):
        for k, v in self._fs.items():
            setattr(findings_store, k, v)
        self.tmp.cleanup()


class TestRowsStoredBefore(StoreCase):
    def test_are_read_as_questions(self):
        findings_store.FINDINGS_FILE.write_text(json.dumps({"findings": [
            {"ts": 5, "text": VESPER, "status": "open", "severity": "warning",
             "source": "resident", "claim": VESPER, "kind": "problem"},
            {"ts": 6, "text": "Hall motion is offline", "status": "open"}]}))
        with named():
            rows = {r["ts"]: r for r in findings_store.list_all()}
        self.assertEqual(rows[5]["kind"], "question")
        self.assertIs(rows[5]["asked"], True)
        self.assertFalse(rows[5]["text"].startswith("Vesper"))
        self.assertFalse(rows[5]["claim"].startswith("Vesper"))
        self.assertNotIn("asked", rows[6])

    def test_the_case_is_answered_in_words(self):
        findings_store.FINDINGS_FILE.write_text(json.dumps({"findings": [
            {"ts": 7, "text": DEFAULT, "status": "open"}]}))
        import cases
        with named():
            [case] = [c for c in cases.list_cases("open")
                      if c["origin"]["key"] == 7]
        self.assertEqual(answers.situation(case), "gap")
        self.assertEqual(answers.group(case), "questions")
        first = answers.answers(case)[0]
        self.assertEqual(first["verb"], "answer")
        self.assertTrue(first["note"])
        self.assertEqual(first["route"], "/api/question/7/answer")
        self.assertNotIn("house book", first["hint"].lower())
        self.assertNotIn("house book", first.get("ask", "").lower())


class TestTheAnswerGoesToMemory(StoreCase):
    def setUp(self):
        super().setUp()
        import server
        self.server = server
        self._inbox = server.MEMORY_INBOX_DIR
        server.MEMORY_INBOX_DIR = self.root / "memory-inbox"

    def tearDown(self):
        self.server.MEMORY_INBOX_DIR = self._inbox
        super().tearDown()

    def test_typed_answer(self):
        with named():
            [row] = findings_store.add_many([{"text": VESPER,
                                              "source": "resident"}])
            [fault] = findings_store.add_many([{"text": "Hall motion is "
                                                        "offline"}])

            async def go(client):
                empty = await client.post(f"/api/question/{row['ts']}/answer",
                                          json={})
                wrong = await client.post(
                    f"/api/question/{fault['ts']}/answer", json={"note": "x"})
                good = await client.post(
                    f"/api/question/{row['ts']}/answer",
                    json={"note": "The dog goes out then."})
                return empty.status, wrong.status, good.status

            self.assertEqual(drive_app(self.server.make_app, go),
                             (400, 409, 200))
        self.assertIsNone(findings_store.get(row["ts"]))
        inbox = "\n".join(p.read_text() for p in
                          Path(self.server.MEMORY_INBOX_DIR).glob("*"))
        self.assertIn("The dog goes out then.", inbox)
        self.assertIn("porch light", inbox)
        self.assertNotIn("Confirmed by the homeowner", inbox)


class TestGetFindingsLeavesQuestionsOut(unittest.TestCase):
    @patch("ha_mcp_server._panel_get")
    def test_no_question_rows(self, panel):
        import ha_mcp_server
        panel.return_value = {"open": 3, "findings": [
            {"ts": 1, "text": "Hall motion is offline", "status": "open"},
            {"ts": 2, "text": "Why does the porch light come on at 3am?",
             "status": "open", "kind": "question", "asked": True},
            {"ts": 3, "text": "Where is the stopcock?", "status": "open",
             "kind": "question", "source": "house_book"}]}
        for status in ("open", "all"):
            out = ha_mcp_server.get_findings(status=status)
            self.assertEqual([f["ts"] for f in out["findings"]], [1], status)


if __name__ == "__main__":
    unittest.main()
