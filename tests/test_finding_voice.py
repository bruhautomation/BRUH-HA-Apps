#!/usr/bin/env python3
"""What a finding owes its reader, held where a second example would hit it.

Findings arrived as headlines withdrawn by their own text ("nothing is
needed"), with no step at all, with a count and no usual rate, handing the
household a lookup brAIn could make, and quoting an event's code name. The
shared half is `prompt_kit.FINDING_VOICE` (every finding-writing prompt), the
deterministic half is `resident.unfinished` (a reply that broke the last two
is not filed), `triage.says_nothing_to_do` (a look that withdraws its row),
`house_words.technical` (a code name leaves the sentence) and `textclip.shorten`
(a step is never cut mid-sentence). Every fixture here is invented.
"""
import asyncio
import json
import sys
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import categories  # noqa: E402
import findings_store  # noqa: E402
import house_words  # noqa: E402
import notify_router  # noqa: E402
import prompt_kit  # noqa: E402
import resident  # noqa: E402
import triage  # noqa: E402
from test_resident_loop import LoopCase  # noqa: E402


def case(**kw):
    base = {"claim": "The shed heater stopped", "detail": "It went off at 14:10.",
            "kind": "problem", "confidence": 0.8, "stakes": "low",
            "fix": "Replace the shed heater's plug.", "evidence": [],
            "actions": [], "todo_text": ""}
    base.update(kw)
    return resident.parse_case(base)


class TestThePromptsSayIt(unittest.TestCase):
    def test_every_finding_writing_prompt_carries_the_block(self):
        for system in (resident.INVESTIGATE_SYSTEM,
                       resident.investigate_system({"text": "a row"})):
            self.assertIn(prompt_kit.FINDING_VOICE, system)

    def test_the_block_names_each_rule(self):
        rule = prompt_kit.FINDING_VOICE.lower()
        for words in ("what is affected or at risk now", "look up what you can read",
                      "usual rate", "make the call yourself",
                      "make no claim"):
            self.assertIn(words, rule)

    def test_the_card_contract_asks_for_a_stranger_to_follow_it(self):
        self.assertIn("saw no earlier card", categories._CARD_CONTRACT)
        self.assertIn("chains of sensor names", categories._CARD_CONTRACT)


class TestAReplyThatIsNotAFinding(unittest.TestCase):
    def test_a_step_that_says_nothing_is_needed_is_not_filed(self):
        for fix in ("Nothing is needed: the heater was switched off on purpose.",
                    "No action is needed, it came back at 14:12.",
                    "Nothing needs doing; the plug is fine."):
            self.assertEqual(resident.unfinished(case(fix=fix))[0],
                             "nothing_needed", fix)

    def test_a_detail_that_withdraws_the_claim_is_not_filed(self):
        got = resident.unfinished(case(
            fix="", detail="It was off for ten minutes. Nothing needs doing."))
        self.assertEqual(got[0], "nothing_needed")
        self.assertIn("Nothing needs doing", got[1])

    def test_a_problem_with_no_step_is_not_filed(self):
        self.assertEqual(resident.unfinished(case(fix=""))[0], "no_step")

    def test_a_real_step_a_question_and_a_high_stake_stay(self):
        self.assertEqual(resident.unfinished(case()), ("", ""))
        self.assertEqual(resident.unfinished(
            case(kind="question", fix="")), ("", ""))
        self.assertEqual(resident.unfinished(
            case(stakes="high", fix="")), ("", ""))
        self.assertEqual(resident.unfinished(case(
            fix="Replace the plug. Nothing else is needed.")), ("", ""))

    def test_a_todo_or_an_action_is_a_step(self):
        self.assertEqual(resident.unfinished(
            case(fix="", todo_text="Replace the plug."))[0], "")


class TestALookThatWithdrawsItsRow(unittest.TestCase):
    def verdict(self, verdict, why):
        return resident.parse_first_look(
            {"verdicts": [{"id": 1, "verdict": verdict, "why": why}]}, 1)[1]

    def test_watch_with_a_nothing_needed_reason_is_set_aside(self):
        for why in ("This doesn't need asking.", "There's no need to ask.",
                    "Nothing is left open and nothing needs doing."):
            got = self.verdict("watch", why)
            self.assertEqual(got["verdict"], "ignore", why)
            self.assertEqual(got["already"], "explained", why)

    def test_an_investigation_or_a_plain_watch_is_left(self):
        self.assertEqual(self.verdict(
            "investigate", "Nothing needs doing yet, but read the log")["verdict"],
            "investigate")
        self.assertEqual(self.verdict(
            "watch", "It dropped twice; the third would matter.")["verdict"],
            "watch")
        self.assertFalse(triage.says_nothing_to_do("Nothing to do with the hub."))


class TestACodeNameLeavesTheSentence(unittest.TestCase):
    def test_a_snake_case_name_goes_to_the_technical_line(self):
        for name in ("shed_heater_moment", "note_a_change", "zha_event_x2"):
            text, found = house_words.technical(f"Nothing answers {name} today.")
            self.assertNotIn(name, text)
            self.assertEqual(found, [name])

    def test_an_entity_a_word_and_a_version_stay(self):
        said = "The sensor.hall_motion reads 1.2 in the hall and works."
        self.assertEqual(house_words.technical(said), (said, []))


class TestAStepIsNotCutMidSentence(unittest.TestCase):
    LONG = ("Open the heater's app and re-add the plug. " * 12
            + "Then reboot the hub and wait for the light to turn green again.")

    def test_an_action_detail_ends_on_a_whole_sentence(self):
        [row] = findings_store._clean_actions([{
            "label": "Fix", "shape": "notify", "consent": True,
            "detail": self.LONG}])
        self.assertTrue(row["detail"].endswith("."), row["detail"][-20:])
        self.assertNotIn("…", row["detail"])

    def test_a_notification_body_ends_on_a_whole_sentence(self):
        _, body = notify_router.compose_brief(self.LONG * 4)
        self.assertNotIn(".…", body)


class TestTheInvestigationDoesNotFileIt(LoopCase):
    def run_it(self, **kw):
        reply = {"claim": "The shed heater stopped",
                 "detail": "It went off at 14:10.", "kind": "problem",
                 "confidence": 0.8, "stakes": "low",
                 "fix": "Replace the shed heater's plug.", "evidence": [],
                 "actions": [], "escalate": False}
        reply.update(kw)
        self.investigations.append({"ok": True, "error": "",
                                    "meta": {"session_id": "inv-v"},
                                    "text": json.dumps(reply)})
        signal = {"kind": "state", "subject": "switch.shed", "salience": 0.5,
                  "text": "x", "evidence": []}
        asyncio.run(self.server._resident_investigate(
            signal, time.time(), "normal"))
        return [r for r in self.server.findings_store._load()
                if r.get("source") == "resident"]

    def test_a_withdrawn_claim_is_not_filed(self):
        self.assertEqual(self.run_it(fix="Nothing is needed; it was off on purpose."), [])

    def test_a_claim_with_no_step_is_not_filed(self):
        self.assertEqual(self.run_it(fix=""), [])

    def test_a_claim_with_a_step_is_filed(self):
        self.assertEqual(len(self.run_it()), 1)


if __name__ == "__main__":
    unittest.main()
