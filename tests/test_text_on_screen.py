#!/usr/bin/env python3
"""What a card says, read as a person reads it.

A walkthrough of a real house found sentences cut mid-word with no
ellipsis ("…would change the answer to t"), a *Fix it* under a plan that
said brAIn would not make the change, "signal 7" in a reason, a filter chip
reading `#user-1790086614`, "6 presss", and a card foot that read like a
pipeline log. Each is driven here through the function that produces it.
"""

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))

import answers  # noqa: E402
import card_tags  # noqa: E402
import deep_review  # noqa: E402
import findings_store  # noqa: E402
import house  # noqa: E402
import plan_ops  # noqa: E402
import resident  # noqa: E402
import textclip  # noqa: E402
import triage  # noqa: E402


class TestClip(unittest.TestCase):
    def test_a_text_that_fits_is_unchanged(self):
        self.assertEqual(textclip.clip("Battery at 4%.", 40), "Battery at 4%.")

    def test_never_longer_than_the_cap(self):
        text = "word " * 200
        for cap in (5, 20, 61, 120, 300):
            with self.subTest(cap):
                self.assertLessEqual(len(textclip.clip(text, cap)), cap)

    def test_it_ends_on_a_whole_word_with_an_ellipsis(self):
        text = ("The check reads the hourly mean, which would change the "
                "answer to the question asked about the freezer")
        out = textclip.clip(text, 70)
        self.assertTrue(out.endswith("…"), out)
        body = out[:-1]
        # The last word kept is a whole word of the original.
        self.assertTrue(text.startswith(body))
        self.assertEqual(text[len(body)], " ", out)

    def test_it_prefers_a_sentence_end_that_keeps_most_of_the_budget(self):
        text = ("The dehumidifier ran all night as it should. It draws about "
                "730 W while running and almost nothing between cycles.")
        out = textclip.clip(text, 70)
        self.assertEqual(out, "The dehumidifier ran all night as it should.…")

    def test_one_long_token_is_cut_and_says_so(self):
        out = textclip.clip("sensor." + "x" * 100, 30)
        self.assertEqual(len(out), 30)
        self.assertTrue(out.endswith("…"))

    def test_the_old_slice_is_what_the_stores_no_longer_do(self):
        """The stores' caps: a triage reason, a plan step, a deep review's
        detail and a house-book citation all end on a word now."""
        long = ("brAIn looked at this and it is a routine HVAC runtime summary "
                "statistic rather than a fault condition, so nothing needs "
                "doing about it at all, and the screen will still say so ") * 3
        reason = findings_store._clean_triage(
            {"verdict": "held", "reason": long})["reason"]
        self.assertTrue(reason.endswith("…"))
        self.assertLessEqual(len(reason), triage.MAX_REASON)
        plan = findings_store._clean_plan({"summary": long * 3})
        self.assertTrue(plan["summary"].endswith("…"))
        review = deep_review.parse({"summary": long * 2, "observations": []})
        self.assertTrue(review["summary"].endswith("…"))
        self.assertLessEqual(len(review["summary"]), 800)


class TestFixItWaitsForAPlanThatCouldWork(unittest.TestCase):
    def _case(self, plan):
        return {"id": "f:7", "kind": "problem", "status": "open",
                "finding_status": "open", "fixable": True,
                "origin": {"store": "findings", "key": 7},
                "source": "check:sys.entry_failed", "plan": plan}

    def _verbs(self, plan):
        return [a["verb"] for a in answers.answers(self._case(plan))]

    def test_no_plan_offers_fix_it(self):
        self.assertEqual(self._verbs({}),
                         ["fix", "todo", "not_now", "wrong"])

    def test_a_plan_that_refused_takes_fix_it_away(self):
        refused = {"can_fix": False, "needs_you": False, "steps": [],
                   "summary": "brAIn would not make this change itself.",
                   "at": 1_790_000_000}
        self.assertTrue(answers.plan_refused(refused))
        self.assertEqual(self._verbs(refused), ["todo", "not_now", "wrong"])

    def test_a_plan_with_ops_that_was_cancelled_still_offers_it(self):
        ok = {"can_fix": True, "ops": [{"op": "reload", "domain": "light"}],
              "steps": ["Reload"], "at": 1}
        self.assertFalse(answers.plan_refused(ok))
        self.assertIn("fix", self._verbs(ok))

    def test_a_legacy_plan_says_press_fix_it_again_and_gets_it(self):
        self.assertTrue(plan_ops.LEGACY_PLAN.startswith(answers.LEGACY_PLAN_MARK))
        legacy = {"can_fix": False, "ops_refused": plan_ops.LEGACY_PLAN,
                  "summary": "old", "at": 1}
        self.assertFalse(answers.plan_refused(legacy))
        self.assertIn("fix", self._verbs(legacy))


class TestNoInternalNumbers(unittest.TestCase):
    def test_signal_numbers_leave_the_reason(self):
        cases = {
            "Same as signal 7, nothing new.": "Same as another signal, nothing new.",
            "Like signals 2 and 3 (the door).": "Like other signals (the door).",
            "Watching (signal #3) for now.": "Watching for now.",
            "A signal that repeats is fine.": "A signal that repeats is fine.",
        }
        for said, shown in cases.items():
            with self.subTest(said):
                self.assertEqual(resident.strip_signal_refs(said), shown)

    def test_a_first_look_reply_is_stripped(self):
        out = resident.parse_first_look(
            {"verdicts": [{"id": 1, "verdict": "ignore",
                           "why": "Duplicate of signal 2, the hall motion."}]},
            1)
        self.assertNotIn("signal 2", out[1]["why"])

    def test_the_prompt_asks_for_names_not_numbers(self):
        self.assertIn('never says "signal 7"', resident.FIRST_LOOK_SYSTEM)

    def test_a_category_id_is_not_a_tag(self):
        tags = card_tags.base_tags({"category": "user-1790086614",
                                    "category_title": "Lev & Kaz nights",
                                    "tags": ["doors"]})
        self.assertEqual(tags, ["lev-kaz-nights", "doors"])
        self.assertFalse(any(card_tags.id_shaped(t) for t in tags))
        self.assertEqual(card_tags.base_tags({"category": "energy"}), ["energy"])


class TestPlurals(unittest.TestCase):
    def test_a_hiss_takes_es(self):
        self.assertEqual(house.plural(6, "press"), "6 presses")
        self.assertEqual(house.plural(1, "press"), "1 press")
        self.assertEqual(house.plural(3, "day"), "3 days")
        self.assertEqual(house.plural(2, "batch"), "2 batches")


class TestYouBroughtThisBack(unittest.TestCase):
    def test_the_press_is_dated(self):
        record = findings_store._clean_triage(
            {"verdict": "held", "reason": "routine", "elevated_by_person": True,
             "elevated_at": 1_790_000_000})
        self.assertEqual(record["elevated_at"], 1_790_000_000)
        self.assertEqual(findings_store._clean_triage(
            {"verdict": "held"})["elevated_at"], 0)


if __name__ == "__main__":
    unittest.main()
