#!/usr/bin/env python3
"""What a case card carries, where it sits, and what its Dismiss does.

Three things the feed got wrong while every store underneath had it right:

* **The evidence was dropped on the way to the card.** The fixer writes a
  `result` and a `changed` list, a proposal carries its replay and its
  trial's grade — and the read model copied none of it, so a failed or
  needs-you fix rendered as an ordinary problem whose first button bought
  another plan run, and *Make the change* sat under no evidence at all.
* **Questions sank.** A guess is `low` stakes and a proposal's id is a
  millisecond, so every question sorted under every warning AND every
  opportunity, whatever their ages.
* **Dismiss on a question killed it.** It snoozed the guess until its own
  expiry, while the button said it would come back, and the sleeping guess
  held one of the queue's three slots for a fortnight.

Every claim is driven through the real stores and the real shell programs
that share the queue, because the queue has three writers and only one of
them is Python.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
SCRIPTS = BASE_DIR / "brain" / "scripts"
sys.path.insert(0, str(PANEL_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import answers  # noqa: E402
import cases  # noqa: E402
import findings_store  # noqa: E402
import hypotheses  # noqa: E402
import proposals  # noqa: E402

# The four real stores in a temporary directory — the harness the case
# tests already use, imported rather than copied.
from test_cases import Recorder, StoresCase  # noqa: E402


def verbs(case: dict) -> list[str]:
    return [a["verb"] for a in answers.answers(case)]


class TestTheFixersReportReachesTheCard(StoresCase):
    """`_from_finding` carries what `_run_fix` wrote, and the first press
    on a card follows what the run concluded."""

    def ran(self, status: str, result: str, changed=()) -> dict:
        row = self.file_problem(source="resident", fixable=True)
        findings_store.set_status(row["ts"], status, result=result,
                                  changed=list(changed))
        return cases.get(f"f:{row['ts']}")

    def test_a_fixed_card_carries_the_report_and_what_changed(self):
        case = self.ran("fixed", "Re-paired it and reloaded ZHA.",
                        ["automations.yaml: hall light condition"])
        self.assertEqual(case["kind"], "change")
        self.assertEqual(case["result"], "Re-paired it and reloaded ZHA.")
        self.assertEqual(case["changed"],
                         ["automations.yaml: hall light condition"])

    def test_needs_you_is_a_pair_of_hands_and_never_another_plan_run(self):
        """The fixer concluded a person has to do this. `fixable` is the
        rule's claim from before anybody looked, and leading with Fix it
        bought another paid plan run to reach the same answer."""
        case = self.ran("needs_you", "Only a person can swap that battery.")
        self.assertTrue(case["fixable"])         # the row still claims it
        self.assertEqual(case["result"], "Only a person can swap that battery.")
        self.assertEqual(answers.situation(case), "hands")
        self.assertNotIn("fix", verbs(case))
        self.assertEqual(verbs(case)[0], "todo")

    def test_a_failed_run_does_not_lead_with_the_same_run_again(self):
        case = self.ran("failed", "The fix run did not complete: timed out")
        self.assertEqual(answers.situation(case), "fix_failed")
        self.assertNotIn("fix", verbs(case))
        # ...and trying again is still there, one press away behind the ⋯.
        behind = [m["verb"] for m in cases.more(case)]
        self.assertIn("fix", behind)

    def test_needs_you_on_a_check_keeps_the_checks_own_reason(self):
        row = self.file_problem(source="check:dev.unavailable", fixable=True)
        findings_store.set_status(row["ts"], "needs_you", result="Plug it in.")
        case = cases.get(f"f:{row['ts']}")
        self.assertEqual(answers.situation(case), "unplugged")
        self.assertIn("on purpose", answers.answers(case)[-1]["prefill"])

    def test_the_mirror_buttons_follow_the_same_rule(self):
        """Repairs and a notification read `request_answers` off a bare
        row; a needs-you row offers no press there that a phone could not
        mean either."""
        row = self.file_problem(source="resident", fixable=True)
        stored = findings_store.set_status(row["ts"], "needs_you",
                                           result="Needs a person.")
        got = [a["action"] for a in answers.request_answers(stored)]
        self.assertEqual(got[0], "todo")


class TestTheProposalsEvidenceReachesTheCard(StoresCase):
    def proposal(self, **extra) -> dict:
        return proposals.add({
            "kind": "routine", "source": "routines",
            "title": "Turn the porch light off at 23:10",
            "why": "You do this by hand most evenings.",
            "config": {"trigger": [{"platform": "time", "at": "23:10"}]},
            "replay": {"would_run": 9, "days": 30, "blocked_by_conditions": 0},
            **extra})

    def test_the_replay_rides_on_the_case(self):
        row = self.proposal()
        case = cases.get(f"p:{row['ts']}")
        self.assertEqual(case["replay"]["would_run"], 9)
        self.assertEqual(case["proposal_status"], "proposed")
        self.assertIsNone(case["trial_result"])

    def test_a_trialled_proposal_carries_its_grade_beside_make_the_change(self):
        row = self.proposal()
        proposals.start_trial(row["ts"])
        proposals.record_trial(row["ts"], {"would_fire": 6, "agreed": 4,
                                           "disagreed": 1, "contradicted": 1,
                                           "days": 3})
        case = cases.get(f"p:{row['ts']}")
        self.assertEqual(case["status"], "watching")
        self.assertEqual(case["proposal_status"], "trialling")
        self.assertEqual(case["trial_result"]["agreed"], 4)
        self.assertGreater(case["trial_ends_at"], case["trial_started_at"])
        # The press it sits beside is still the accept.
        self.assertEqual(verbs(case)[0], "accept")

    def test_a_rule_asked_for_in_words_carries_its_composed_case(self):
        row = self.proposal(spoken={"sentence": "x", "case": "It would have "
                                    "run 9 times; you did the same on 7."})
        case = cases.get(f"p:{row['ts']}")
        self.assertIn("you did the same on 7", case["case_line"])

    def test_a_playbook_says_where_its_evidence_is(self):
        row = self.proposal(kind="playbook", playbook={"class": "smoke"},
                            config={"trigger": [{"platform": "state"}]})
        self.assertTrue(cases.get(f"p:{row['ts']}")["playbook"])


class TestQuestionsHaveTheirOwnBand(StoresCase):
    """Just under the problems that matter a lot, over everything else."""

    def test_a_question_sits_under_a_serious_problem_and_over_a_warning(self):
        serious = self.file_problem(text="Freezer is warming", severity="serious")
        warning = self.file_problem(text="Hall sensor battery low",
                                    severity="warning")
        guess = self.file_question()
        order = [c["id"] for c in cases.list_cases()]
        self.assertEqual(order[:3], [f"f:{serious['ts']}", f"h:{guess['ts']}",
                                     f"f:{warning['ts']}"])

    def test_a_millisecond_id_no_longer_outranks_every_question(self):
        """A proposal filed AFTER the question used to sort above it by a
        factor of a thousand; it is below it now because the band says so,
        and an older proposal is below a newer one because the clock does."""
        guess = self.file_question()
        opp = self.file_opportunity()
        self.assertGreater(opp["ts"], guess["ts"] * 100)   # the old trap
        listed = cases.list_cases()
        ids = [c["id"] for c in listed]
        self.assertLess(ids.index(f"h:{guess['ts']}"),
                        ids.index(f"p:{opp['ts']}"))
        by_id = {c["id"]: c for c in listed}
        self.assertLess(abs(by_id[f"p:{opp['ts']}"]["created_at"]
                            - time.time()), 120)

    def test_created_at_is_seconds_whichever_store(self):
        made = self.one_of_each()
        for case in cases.list_cases(kinds=cases.KINDS):
            self.assertLess(abs(case["created_at"] - time.time()), 600,
                            case["id"])
        self.assertTrue(made)


class TestDismissOnAQuestionBringsItBack(StoresCase):
    def dismiss(self, guess: dict, now: float) -> dict:
        return cases.end(f"h:{guess['ts']}", "not_now",
                         hooks=Recorder().hooks(), now=now)

    def test_a_sleeping_guess_frees_its_slot(self):
        """The gentlest button used to stop brAIn asking anything else."""
        made = [hypotheses.propose(f"Guess number {n} about the house", "t")
                for n in range(hypotheses.MAX_OPEN)]
        self.assertEqual(hypotheses.budget(), 0)
        self.assertIsNone(hypotheses.propose("One more guess", "t"))
        self.dismiss(made[0], time.time())
        self.assertEqual(hypotheses.budget(), 1)
        self.assertIsNotNone(hypotheses.propose("One more guess", "t"))

    def test_it_leaves_every_screen_and_comes_back_on_its_own(self):
        guess = self.file_question()
        now = time.time()
        out = self.dismiss(guess, now)
        until = out["snoozed_until"]
        self.assertEqual(until, int(now + cases.SNOOZE_BY_STAKES["low"]))
        self.assertEqual(cases.list_cases(kinds=["question"], now=now + 60), [])
        self.assertEqual(hypotheses.awake(now + 60), [])
        back = cases.list_cases(kinds=["question"], now=until + 60)
        self.assertEqual([c["id"] for c in back], [f"h:{guess['ts']}"])
        # ...and the guess was never settled in between.
        self.assertEqual(hypotheses.list_all("open")[0]["text"], guess["text"])

    def test_it_does_not_expire_while_it_sleeps(self):
        """Dismissed on day thirteen for a week, it comes back on day
        twenty with a whole fortnight ahead of it — where the old reading
        retired it on day fourteen, mid-sleep, and never said so."""
        guess = self.file_question()
        day13 = guess["ts"] + 13 * 86400
        out = self.dismiss(guess, day13)
        with unittest.mock.patch("time.time", return_value=day13 + 8 * 86400):
            listed = hypotheses.list_all()
        self.assertEqual(listed[0]["status"], "open")
        self.assertGreater(out["snoozed_until"],
                           guess["ts"] + hypotheses.TTL_DAYS * 86400)

    def test_the_findings_payload_does_not_hand_it_back_as_a_loose_card(self):
        """`/api/findings` lists open guesses for anything the case list
        does not cover — and a sleeping one is exactly that, so it came
        straight back onto the feed beside the list that had hidden it."""
        import server  # noqa: PLC0415 — heavy, and only this test needs it
        guess = self.file_question()
        self.dismiss(guess, time.time())
        self.assertEqual(server._findings_payload()["hypotheses"], [])

    def test_the_hint_says_what_the_press_does_now(self):
        got = answers.answers({"id": "h:1", "kind": "question",
                               "origin": {"store": "hypotheses", "key": 1}})
        dismiss = [a for a in got if a["verb"] == "not_now"][0]
        self.assertIn("asks again", dismiss["hint"])
        self.assertIn("asks something else", dismiss["hint"])


def _shell_function(script: Path, name: str) -> str:
    """One function, lifted out of the real script — `consolidator_lock_
    check`'s arrangement in test_memory_learning."""
    text = script.read_text()
    match = re.search(rf"^{re.escape(name)}\(\) \{{\n.*?^\}}\n", text, re.S | re.M)
    assert match, f"{name} is not in {script.name}"
    return match.group(0)


@unittest.skipUnless(shutil.which("jq") and shutil.which("bash"), "needs jq")
class TestTheShellWritersAgree(unittest.TestCase):
    """The queue has two shell writers that retire stale guesses and one
    that counts slots, and a dismissed guess must age and count the same
    way in all three — or it comes back on one screen and is gone on the
    other."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.file = Path(self.tmp.name) / "hypotheses.jsonl"
        now = int(time.time())
        old = now - 20 * 86400
        self.file.write_text("\n".join(json.dumps(r) for r in (
            {"ts": old, "text": "slept through it", "status": "open",
             "snoozed_until": now - 86400},
            {"ts": old, "text": "nobody answered", "status": "open"},
            {"ts": now, "text": "asleep now", "status": "open",
             "snoozed_until": now + 3 * 86400},
            {"ts": now, "text": "awake now", "status": "open"},
        )) + "\n")

    def tearDown(self):
        self.tmp.cleanup()

    def run_bash(self, body: str) -> subprocess.CompletedProcess:
        env = {**os.environ, "HYPOTHESES_FILE": str(self.file),
               "HYPOTHESIS_TTL_DAYS": "14"}
        return subprocess.run(["bash", "-c", body], capture_output=True,
                              text=True, env=env, timeout=30)

    def statuses(self) -> dict:
        return {json.loads(line)["text"]: json.loads(line)["status"]
                for line in self.file.read_text().splitlines() if line}

    def test_both_retirers_age_a_guess_from_when_it_came_back(self):
        for script, name in ((SCRIPTS / "brain-memory.sh",
                              "_retire_stale_hypotheses_locked"),
                             (SCRIPTS / "brain-memory-consolidate.sh",
                              "_retire_stale_hypotheses")):
            with self.subTest(script=script.name):
                self.setUp()
                fn = _shell_function(script, name)
                done = self.run_bash(f"{fn}\n{name}")
                self.assertEqual(done.returncode, 0, done.stderr)
                got = self.statuses()
                self.assertEqual(got["slept through it"], "open")
                self.assertEqual(got["nobody answered"], "expired")
                # The panel agrees, on the same file.
                old_file = hypotheses.HYPOTHESES_FILE
                hypotheses.HYPOTHESES_FILE = self.file
                try:
                    self.assertEqual(
                        {e["text"] for e in hypotheses.list_all("open")},
                        {"slept through it", "asleep now", "awake now"})
                finally:
                    hypotheses.HYPOTHESES_FILE = old_file

    def test_a_study_session_counts_the_slots_the_panel_counts(self):
        fn = _shell_function(SCRIPTS / "brain-learn.sh", "open_hypothesis_count")
        done = self.run_bash(f"{fn}\nopen_hypothesis_count")
        self.assertEqual(done.returncode, 0, done.stderr)
        old_file = hypotheses.HYPOTHESES_FILE
        hypotheses.HYPOTHESES_FILE = self.file
        try:
            # Read before anything retires the two old ones: the count is
            # over what is open and awake, which is three here.
            panel = len([e for e in hypotheses._read()
                         if hypotheses._status_of(e) == "open"
                         and not hypotheses.asleep(e)])
        finally:
            hypotheses.HYPOTHESES_FILE = old_file
        self.assertEqual(int(done.stdout.strip()), panel)
        self.assertEqual(panel, 3)


class TestAPhoneDismissIsTheFeedsDismiss(StoresCase):
    """A notification's Dismiss names no hours, and gets the stakes table;
    Repairs' "Remind me tomorrow" names 24 and keeps them."""

    def setUp(self):
        super().setUp()
        import server  # noqa: PLC0415
        self.server = server

    def test_no_hours_is_the_same_quiet_the_feed_buys(self):
        row = self.file_problem(severity="warning")
        before = time.time()
        until = self.server._request_snooze_until(row["ts"], None)
        self.assertAlmostEqual(until, before + cases.SNOOZE_BY_STAKES["medium"],
                               delta=5)

    def test_named_hours_are_kept(self):
        row = self.file_problem(severity="warning")
        before = time.time()
        until = self.server._request_snooze_until(row["ts"], 24)
        self.assertAlmostEqual(until, before + 24 * 3600, delta=5)

    def test_a_finding_that_has_gone_falls_back_to_a_day(self):
        before = time.time()
        until = self.server._request_snooze_until(424242, None)
        self.assertAlmostEqual(until, before + 86400, delta=5)


if __name__ == "__main__":
    unittest.main()
