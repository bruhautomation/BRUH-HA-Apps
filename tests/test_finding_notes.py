#!/usr/bin/env python3
"""A note brAIn files about itself is news to read, not a problem to judge.

The owner asked that brAIn's personality keep developing and that each
change show up on the list ("you can have that show up as findings about
how you're updating your personality"). The only door from a conversation
is a line in the findings inbox, and a line there landed as `triaging`
like a house fault: the first look could hold it, the stale sweep showed
it as "Unchecked", and its buttons were a problem's.

One rule (`triage.is_note`): a row from a note source (`personality`) or
one that says `kind: note` is a NOTE. `triage.gate` — still the one door —
files it open, as information, with nothing for a look to judge; its card
has one press, the acknowledgement (Done, the action vocabulary's
word for it); and nothing about it ever reaches a phone.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "brain"
                       / "panel"))

import answers  # noqa: E402
import cases  # noqa: E402
import findings_store  # noqa: E402
import notify_router  # noqa: E402
import triage  # noqa: E402
from test_subject_fold import FoldCase  # noqa: E402

LINE = {"text": "brAIn now answers more briefly in the morning",
        "detail": "You asked for shorter replies before nine.",
        "source": "personality", "severity": "warning"}


class TestTheRule(unittest.TestCase):
    def test_a_note_source_or_kind_is_a_note(self):
        self.assertTrue(triage.is_note({"source": "personality"}))
        self.assertTrue(triage.is_note({"source": "chat", "kind": "note"}))
        self.assertFalse(triage.is_note({"source": "chat", "kind": "problem"}))
        self.assertFalse(triage.is_note({"source": "check:dev.frozen"}))

    def test_a_safety_row_can_never_be_a_note(self):
        self.assertFalse(triage.is_note({"source": "safety", "kind": "note"}))
        self.assertFalse(triage.is_note({"source": "security",
                                         "kind": "note"}))

    def test_the_gate_files_it_open_as_information(self):
        [row] = triage.gate([dict(LINE)])
        self.assertEqual(row["status"], "open")
        self.assertEqual(row["severity"], "info")
        self.assertIs(row["informational"], True)
        [fault] = triage.gate([{"text": "x", "source": "check:dev.frozen"}])
        self.assertEqual(fault["status"], "triaging")


class TestAnInboxNoteLandsOpen(FoldCase):
    def setUp(self):
        super().setUp()
        self._inbox = findings_store.INBOX_DIR
        findings_store.INBOX_DIR = Path(self.tmp.name) / "inbox"
        findings_store.INBOX_DIR.mkdir()

    def tearDown(self):
        findings_store.INBOX_DIR = self._inbox
        super().tearDown()

    def sweep(self, *lines) -> list[dict]:
        (findings_store.INBOX_DIR / "a.jsonl").write_text(
            "\n".join(json.dumps(x) for x in lines) + "\n")
        return findings_store.sweep_inbox(triage.gate)

    def test_it_is_open_and_never_waits_for_a_look(self):
        [row] = self.sweep(LINE)
        stored = findings_store.get(row["ts"])
        self.assertEqual(stored["status"], "open")
        self.assertNotIn(row["ts"], [r["ts"] for r in
                                     findings_store.awaiting_triage()])

    def test_its_card_has_one_press_an_acknowledgement(self):
        [row] = self.sweep(LINE)
        case = cases.get(f"f:{row['ts']}")
        self.assertEqual(answers.situation(case), "acknowledge")
        pressed = answers.answers(case)
        self.assertEqual([a["label"] for a in pressed], ["Done"])
        self.assertEqual(pressed[0]["verb"], "ack")
        self.assertEqual(pressed[0]["request"], "ack")
        self.assertEqual([a["action"] for a in
                          answers.request_answers(findings_store.get(
                              row["ts"]))], ["ack"])

    def test_it_is_never_notified(self):
        [row] = self.sweep(LINE)
        for floor in ("info", "warning", "critical"):
            self.assertEqual(notify_router.tier_of(row, floor), "quiet")
            self.assertEqual(notify_router.worth_sending([row], floor), [])

    def test_a_note_from_a_conversation_lands_the_same_way(self):
        [row] = self.sweep({"text": "brAIn learned the boiler's quirks",
                            "source": "chat", "kind": "note"})
        self.assertEqual(findings_store.get(row["ts"])["status"], "open")
        self.assertEqual(answers.situation(cases.get(f"f:{row['ts']}")),
                         "acknowledge")


if __name__ == "__main__":
    unittest.main()
