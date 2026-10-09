#!/usr/bin/env python3
"""Fix opens a box with brAIn's suggestion in it, and what is sent is the
change somebody agreed to.

Reported as: the primary button where brAIn could make the change was
**Plan**, which ran a read-only plan nobody pressed. The press is **Fix**
now. It opens a short box already holding the card's suggested change (the
finding's own `fix` sentence); the person may edit it or write their own,
and what they send rides to the existing plan route as `{change}` — the
same agreed change a discussion's `plan` resolution sends — so the card
then shows exactly what will change, Apply is the one consent, and Undo
follows. The wire action id stays `fix`, because the HA mirror, Repairs
and the notification actions read it. A card brAIn cannot act on offers no
Fix at all.
"""

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))

import answers  # noqa: E402
import cases  # noqa: E402

FIX = "Check the door seal on sensor.garage_freezer, then the compressor relay."


def case(**over) -> dict:
    base = {
        "id": "f:7", "kind": "problem", "status": "open",
        "finding_status": "open", "origin": {"store": "findings", "key": 7},
        "source": "resident", "fixable": True, "plan": {}, "fix": FIX,
        "fix_started": 0, "fix_ended": 0,
    }
    base.update(over)
    return base


def fix_of(rows):
    return [a for a in rows if a["verb"] == "fix"]


class TestFixOpensTheBox(unittest.TestCase):
    def test_the_primary_is_fix_and_carries_the_suggestion(self):
        lead = answers.answers(case())[0]
        self.assertEqual((lead["verb"], lead["label"]), ("fix", "Fix"))
        self.assertTrue(lead["primary"])
        self.assertTrue(lead["instruct"], "Fix must open the instruction box")
        self.assertEqual(lead["prefill"], FIX)
        self.assertEqual(lead["route"], "/api/finding/7/fix")
        # Not the reason box: what is typed is the change, not a note.
        self.assertFalse(lead["note"])
        self.assertTrue(lead["ask"])

    def test_a_card_with_no_suggestion_still_opens_an_empty_box(self):
        lead = answers.answers(case(fix=""))[0]
        self.assertEqual((lead["verb"], lead["label"]), ("fix", "Fix"))
        self.assertTrue(lead["instruct"])
        self.assertEqual(lead["prefill"], "")

    def test_an_out_of_date_plan_offers_fix_with_the_box(self):
        legacy = case(finding_status="planned", plan={
            "can_fix": True, "ops_refused": answers.LEGACY_PLAN_MARK + " …"})
        lead = answers.answers(legacy)[0]
        self.assertEqual((lead["verb"], lead["label"]), ("fix", "Fix"))
        self.assertTrue(lead["instruct"])
        self.assertEqual(lead["prefill"], FIX)

    def test_a_failed_fix_offers_fix_again_behind_the_dots_with_the_box(self):
        failed = case(finding_status="failed")
        more = fix_of(answers.more(failed, answers.answers(failed), []))
        self.assertEqual([(m["label"], m["instruct"], m["prefill"]) for m in more],
                         [("Fix", True, FIX)])


class TestNoFixWhereBrainCannotAct(unittest.TestCase):
    def test_hands_battery_and_refused_plans_offer_no_fix(self):
        shapes = [
            case(fixable=False),
            case(source="check:dev.battery_low"),
            case(finding_status="planned", plan={"can_fix": False,
                                                 "summary": "Needs a person."}),
            case(plan={"summary": "Needs you.", "needs_you": True}),
        ]
        for kase in shapes:
            visible = answers.answers(kase)
            self.assertFalse(fix_of(visible), kase)

    def test_a_house_book_question_offers_no_fix(self):
        gap = case(source="house_book", kind="question", fixable=True)
        rows = answers.answers(gap)
        self.assertFalse(fix_of(rows))

    def test_a_phone_is_never_offered_fix(self):
        row = {"ts": 7, "status": "open", "source": "resident", "fixable": True,
               "fix": FIX, "kind": "problem"}
        self.assertNotIn("fix", [a["action"] for a in answers.request_answers(row)])


class TestTheOverflowSaysFixToo(unittest.TestCase):
    def test_the_rare_verbs_name_the_press_fix(self):
        rows = cases.overflow({"kind": "problem", "status": "open",
                               "origin": {"store": "findings", "key": 7},
                               "source": "resident"})
        fix = [r for r in rows if r["verb"] == "fix"]
        self.assertEqual([r["label"] for r in fix], ["Fix"])


class TestThePanelSendsTheChange(unittest.TestCase):
    """What the box sends is read off app.js: `{change}` to the fix route,
    never `{note}`, so `_run_plan` gets it as the agreed change."""

    def test_the_card_and_the_strip_both_send_change(self):
        app = (PANEL_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn("function instructThenFix(", app)
        self.assertIn("answer.instruct", app)
        body = app.split("function instructThenFix(", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("change", body)
        html = (PANEL_DIR / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="chatFindingFix" class="btn small primary">Fix<', html)
        self.assertNotIn('>Plan</button>', html)


if __name__ == "__main__":
    unittest.main()
