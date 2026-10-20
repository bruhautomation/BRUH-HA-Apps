#!/usr/bin/env python3
"""A Morph suggestion is a yes/no question, and its card offers the yes.

Morph files its dashboard suggestions into brAIn as cases, and the case was
filed as an `opportunity` with `fixable: False` and the question ("Should I
make this change to the dashboard?") stored as its `fix`. `answers` read
that as a pair of hands — Add to To Do · Snooze · Ignore — so the only way
to say yes was missing, and Add to To Do told Morph `todo` rather than
`accepted`. A suggestion is a question only the person can answer, so it is
filed and read as a findings-store question: Yes · No · Snooze · Doesn't
apply, the chip Question, the question as the card's own words and no
`fix` line. A row already stored the old way reads the same (`answers.
as_morph_question`), and Repairs and a notification offer the Yes too.

Driven through the real `_apply_morph_case` and the real case endings
(`cases.end` with the panel's `CASE_HOOKS`, what `/api/case/<id>/<verb>`
runs), into `_end_morph_case` and `morph_bridge.ended`.
"""
from __future__ import annotations

import asyncio
import sys
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import answers  # noqa: E402
import findings_store  # noqa: E402
from test_morph_contracts_drain import MorphCase  # noqa: E402

ASK = "Should I make this change to the dashboard?"


class TestAMorphSuggestionAsksYesOrNo(MorphCase):

    def file(self, key="sug-abc", claim="Move Kitchen above Dining.",
             ask=ASK, case_kind="opportunity"):
        self.request({"kind": "morph_case", "action": "file", "key": key,
                      "case_kind": case_kind, "claim": claim,
                      "detail": "You open it first every morning.",
                      "ask": ask, "via": "morph"})
        got = self.drain()
        self.assertTrue(got[0]["ok"], got)
        return got[0]["case"]

    def press(self, case_id: str, verb: str, note: str = "") -> dict | None:
        s = self.server

        async def go():
            now = time.time()
            ended = await asyncio.to_thread(
                s.cases.end, case_id, verb, note, hooks=s.CASE_HOOKS, now=now)
            if ended is None:
                return None
            work = ended.pop("result", None)
            if callable(work):
                await work()
            return ended
        return asyncio.run(go())

    def endings(self) -> list[tuple[str, str]]:
        return [(e["key"], e["how"]) for e in self.server.morph_bridge.ended()]

    def test_the_card_offers_yes_no_snooze_and_doesnt_apply(self):
        case_id = self.file()
        case = self.server.cases.get(case_id)
        self.assertEqual(case["kind"], "question")
        verbs = [a["verb"] for a in self.server.cases.answers(case)]
        self.assertEqual(verbs, ["yes", "no", "not_now", "not_applicable"])
        self.assertEqual(answers.chip(case), "question")

    def test_the_question_is_the_cards_words_and_no_fix_line(self):
        case_id = self.file()
        case = self.server.cases.get(case_id)
        self.assertIn("Move Kitchen above Dining", case["claim"])
        self.assertTrue(case["claim"].endswith("?"), case["claim"])
        self.assertIn("dashboard", case["claim"])
        self.assertEqual(case["fix"], "")
        row = findings_store.get(int(case_id.split(":")[1]))
        # The suggestion's own sentence stays the key Morph and the store
        # dedupe it under.
        self.assertEqual(row["text"], "Move Kitchen above Dining.")
        self.assertEqual(row["morph_key"], "sug-abc")

    def test_yes_reaches_morph_as_accepted(self):
        case_id = self.file()
        self.assertIsNotNone(self.press(case_id, "do"))
        self.assertIsNone(findings_store.get(int(case_id.split(":")[1])))
        self.assertEqual(self.endings(), [("sug-abc", "accepted")])
        # A layout preference is Morph's to learn, never brAIn's memory.
        self.assertEqual(self.queued_memory(), [])

    def test_no_reaches_morph_as_declined(self):
        case_id = self.file()
        self.assertIsNotNone(self.press(case_id, "wrong", "I like it there"))
        self.assertEqual(self.endings(), [("sug-abc", "declined")])
        self.assertEqual(self.queued_memory(), [])

    def test_morphs_own_code_question_gets_the_same_yes(self):
        case_id = self.file(key="sug-code", claim="Show the week on the clock.",
                            ask="Should brAIn change Morph itself for this?")
        case = self.server.cases.get(case_id)
        self.assertEqual([a["verb"] for a in self.server.cases.answers(case)][:2],
                         ["yes", "no"])
        self.assertIn("Morph itself", case["claim"])
        self.press(case_id, "do")
        self.assertEqual(self.endings(), [("sug-code", "accepted")])

    def test_a_row_stored_the_old_way_gets_the_yes_too(self):
        # What 3.x stored: an opportunity, no hands, the ask as its fix.
        filed = findings_store.add_case({
            "text": "Fold the garage at night.",
            "claim": "Fold the garage at night.",
            "detail": "Nobody opens it after 22:00.", "kind": "opportunity",
            "fix": ASK, "fixable": False, "severity": "info",
            "stakes": "low", "source": "morph", "morph_key": "sug-old",
            "source_title": "Morph, your dashboard"})
        case_id = f"f:{filed['ts']}"
        case = self.server.cases.get(case_id)
        self.assertEqual(case["kind"], "question")
        self.assertEqual([a["verb"] for a in self.server.cases.answers(case)][:2],
                         ["yes", "no"])
        self.assertEqual(case["fix"], "")
        self.press(case_id, "do")
        self.assertEqual(self.endings(), [("sug-old", "accepted")])

    def test_no_open_morph_finding_carries_a_question_with_no_yes(self):
        self.file()
        findings_store.add_case({
            "text": "Fold the garage at night.",
            "claim": "Fold the garage at night.", "kind": "opportunity",
            "fix": ASK, "fixable": False, "source": "morph",
            "morph_key": "sug-old"})
        morph = [c for c in self.server.cases.list_cases()
                 if c.get("source") == "morph"]
        self.assertEqual(len(morph), 2)
        for case in morph:
            verbs = [a["verb"] for a in self.server.cases.answers(case)]
            self.assertIn("yes", verbs, case)
            self.assertFalse(str(case.get("fix") or "").endswith("?"), case)


class TestHomeAssistantOffersTheYes(unittest.TestCase):
    """Repairs and a notification read `request_answers` off a bare row."""

    def test_a_morph_row_offers_confirm_and_wrong(self):
        for row in (
                {"ts": 7, "status": "open", "kind": "question",
                 "source": "morph", "fixable": False},
                {"ts": 8, "status": "open", "kind": "opportunity",
                 "source": "morph", "fixable": False, "fix": ASK}):
            actions = [a["action"] for a in answers.request_answers(row)]
            self.assertEqual(actions[:2], ["confirm", "wrong"], row)
            self.assertNotIn("todo", actions)

    def test_confirm_is_a_request_both_halves_carry(self):
        import finding_requests
        self.assertIn("confirm", finding_requests.ACTIONS)
        self.assertEqual(finding_requests.verb_for("confirm"), "confirm")
        src = (BASE_DIR / "brain" / "custom_components" / "brain"
               / "requests.py").read_text(encoding="utf-8")
        line = [ln for ln in src.splitlines()
                if ln.startswith("ACTIONS = ")][0]
        self.assertIn('"confirm"', line + src[src.index(line):][:200])


class TestOneWordForMorph(unittest.TestCase):
    def test_the_leaf_spells_the_stores_source(self):
        self.assertEqual(answers.MORPH_SOURCE, findings_store.MORPH_SOURCE)


class TestAYesFromAPhoneReachesMorph(TestAMorphSuggestionAsksYesOrNo):
    """The drain applies `confirm` through `_end_finding`, as a press does."""

    def test_confirm_request_is_accepted_for_morph(self):
        case_id = self.file()
        self.request({"ts": int(case_id.split(":")[1]), "action": "confirm",
                      "via": "notification"})
        got = self.drain()
        self.assertTrue(got[0]["ok"], got)
        self.assertEqual(self.endings(), [("sug-abc", "accepted")])

    def test_confirm_is_refused_on_a_problem(self):
        row = self.check_row()
        self.request({"ts": int(row["ts"]), "action": "confirm",
                      "via": "notification"})
        got = self.drain()
        self.assertFalse(got[0]["ok"], got)
        self.assertIsNotNone(findings_store.get(int(row["ts"])))


if __name__ == "__main__":
    unittest.main()
