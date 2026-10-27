"""A house-book gap question reads as a question, says what the house book
is, and never promises a box the surface it is on does not have (#502)."""
import re
import sys
import unittest
from pathlib import Path

PANEL_DIR = Path(__file__).resolve().parents[1] / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))

import findings_store  # noqa: E402
import house_book  # noqa: E402
import answers  # noqa: E402


class TestTheQuestionSaysWhatTheBookIs(unittest.TestCase):
    def rows(self):
        return house_book.question_rows(
            [{"question": "Where is the fuse box?", "why": "",
              "subject": "entity:switch.main", "label": "Main"}], [], 0)

    def test_no_row_says_answer_it_here(self):
        for row in self.rows():
            self.assertNotIn("here", row["fix"].lower())
            self.assertIn("house book", row["fix"])
            self.assertIn("guide", row["fix"])

    def test_the_two_spellings_agree(self):
        self.assertEqual(findings_store._HOUSE_BOOK_FIX, house_book.FIX)

    def test_an_old_row_reads_as_the_new_sentence(self):
        old = {"source": "house_book",
               "fix": "Answer it here and the house book will say so."}
        self.assertEqual(findings_store.shown_fix(old), house_book.FIX)
        self.assertIn("Answer it here", old["fix"])  # stored row untouched

    def test_another_producer_keeps_its_own_words(self):
        old = "Answer it here and the house book will say so."
        row = {"source": "resident", "fix": old}
        self.assertEqual(findings_store.shown_fix(row), old)

    def test_the_answer_box_says_what_the_book_is(self):
        case = {"id": "f:1", "kind": "question", "source": "house_book",
                "store": "findings", "finding_status": "open", "ts": 1}
        box = [a for a in answers.answers(case) if a.get("verb") == "answer"]
        self.assertTrue(box)
        self.assertIn("plain-language guide", box[0]["ask"])

    def test_the_why_may_not_cite_unseen_notes(self):
        self.assertIn("the notes say", house_book.SYSTEM)
        why = house_book.SCHEMA["properties"]["questions"]["items"][
            "properties"]["why"]
        self.assertIn("description", why)

    def test_the_group_is_questions_for_you(self):
        self.assertEqual(answers.GROUP_WORDS["questions"], "Questions for you")
        js = (PANEL_DIR / "app.js").read_text()
        self.assertIn('questions: "Questions for you"', js)

    def test_a_loose_gap_row_is_a_question_not_a_tidy_up(self):
        js = (PANEL_DIR / "app.js").read_text()
        self.assertIn('chip: f.source === "house_book" ? "question"', js)
        self.assertTrue(re.search(
            r'group: f\.source === "house_book" \? "questions"', js))


if __name__ == "__main__":
    unittest.main()
