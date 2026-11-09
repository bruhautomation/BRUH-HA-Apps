"""A quick run that runs out of time hands on to a job, and never holds the desk.

The house's report (2026-11-09): a player asked in game chat to "teleport
along the builds" — many steps, one after another — and it ran as a quick
run, which the listener stops at TALK_TIMEOUT less its margin (45 s), with
some teleports done. The listener wrote `failed`/`timeout`, the bridge
raised BrainRunError(code="timeout"), and `_quick` read every failure that
was not the bridge's own TimeoutError as brAIn being down: status "down",
and BRAIN_RETRY (five minutes) during which every next line was "down",
reply "", nothing attempted — the player typed into silence. The line that
timed out said nothing either, because it had not named the companion.

Now:
  - a quick run the listener stopped at its limit becomes a job for what
    was asked (the job route the desk already has), and the player is told;
  - only a failure that says brAIn cannot be asked (signed out, paused, out
    of budget, or no closed word at all) holds the desk, and a line skipped
    while it does is said once to that player, named or not;
  - the handed-on job keeps the quick run's scope: a child's stays the game
    scope, so the job route is no new power;
  - the quick prompt names a run of actions (a teleport tour) as a job.
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_brain_minecraft_faculty import DAD, FAMILY, KAZ  # noqa: E402
from test_minecraft_desk import DeskBrain, DeskCase, rules  # noqa: E402

TOUR = "teleport me along the list of builds"


class RunFailed(Exception):
    """A run that came back failed, the way the bridge raises one
    (BrainRunError: the listener's sentence and its closed word)."""

    def __init__(self, text, code="error"):
        super().__init__(text)
        self.code = code


class FailingQuick(DeskBrain):
    """The desk's runner, whose next quick runs fail as listed."""

    def __init__(self):
        super().__init__()
        self.quick_fails: list[BaseException] = []

    async def __call__(self, **kw):
        if kw.get("schema") is rules.TALK_SCHEMA and self.quick_fails:
            self.asked.append(kw)
            raise self.quick_fails.pop(0)
        return await super().__call__(**kw)


class TimeoutCase(DeskCase):
    def setUp(self):
        super().setUp()
        self.brain = FailingQuick()
        self.c.run_task = self.brain

    def timed_out(self):
        return RunFailed("Claude timed out after 45s", code="timeout")


class TestATimedOutQuickRunBecomesAJob(TimeoutCase):
    def test_the_request_carries_on_as_a_job_and_the_player_is_told(self):
        self.join(DAD)
        self.brain.quick_fails = [self.timed_out()]
        self.chat(DAD, TOUR)                    # no name: every line is for it
        self.settle()
        jobs = self.jobs()
        self.assertEqual(len(jobs), 1, jobs)
        job = jobs[0]
        self.assertEqual(job["brief"], TOUR)
        self.assertTrue(job["from_talk"])
        self.assertEqual(job["status"], "done")
        said = self.lines_to(DAD)
        self.assertIn(rules.CANNED["handoff"].format(title=job["title"]), said)
        talk = [t for t in self.talks() if t.get("kind") == "chat"][-1]
        self.assertEqual(talk["status"], "timed_out")
        self.assertIn("timed out", talk["note"])
        # The worker is told it began as a quick answer, outside the brief.
        work = self.brain.of("work")[0]["prompt"]
        self.assertIn("began as a quick answer", work)
        self.assertIn("a run of actions one after another", work)

    def test_the_next_line_is_asked_and_answered_never_down(self):
        self.join(DAD)
        self.brain.quick_fails = [self.timed_out()]
        self.chat(DAD, TOUR)
        self.settle()
        self.chat(DAD, "thanks, where is the farm?")
        self.chat(DAD, "and the mill?")
        self.settle()
        self.assertEqual(len(self.brain.of("quick")), 3)
        statuses = [t["status"] for t in self.talks() if t.get("kind") == "chat"]
        self.assertNotIn("down", statuses)
        self.assertEqual(self.lines_to(DAD)[-1], "Sure!")
        self.assertEqual(self.c.brain_down_until, 0.0)

    def test_a_childs_handed_on_job_keeps_the_game_scope(self):
        self.join(KAZ)
        self.brain.quick_fails = [self.timed_out()]
        self.chat(KAZ, "take me to every house one by one")
        self.settle()
        job = self.jobs()[0]
        self.assertEqual(job["scope"], "minecraft")
        self.assertEqual(job["role"], "child")
        self.assertEqual(self.brain.of("work")[0]["tools"], "minecraft")

    def test_a_trusted_grown_ups_job_is_no_wider_than_their_quick_run(self):
        people = [dict(p, trusted=True) if p["person"] == "Dad" else p for p in FAMILY]
        self.write_settings(**{**self.settings, "people": people})
        self.join(DAD)
        self.brain.quick_fails = [self.timed_out()]
        self.chat(DAD, TOUR)
        self.settle()
        quick_tools = self.brain.of("quick")[0]["tools"]
        self.assertEqual(self.jobs()[0]["scope"], quick_tools)

    def test_the_same_words_timing_out_again_do_not_open_a_second_job(self):
        self.join(DAD)
        self.brain.holds["work"] = asyncio.Event()
        self.brain.quick_fails = [self.timed_out(), self.timed_out()]
        self.fire("chat", player=DAD, name=DAD, text=TOUR, verified=True)
        self.wait_until(lambda: self.jobs() and self.jobs()[0]["status"] == "running")
        self.wait_until(lambda: not self.c.talking)
        self.clock.t += 10
        self.fire("chat", player=DAD, name=DAD, text=TOUR, verified=True)
        self.wait_until(lambda: not self.c.talking)
        self.assertEqual(len(self.jobs()), 1)
        self.assertIn(rules.CANNED["handoff_again"].format(title=self.jobs()[0]["title"]),
                      self.lines_to(DAD))
        self.brain.holds["work"].set()
        self.settle()

    def test_the_bridge_giving_up_is_said_and_holds_nothing(self):
        self.join(DAD)
        self.brain.quick_fails = [TimeoutError("No response within 60s")]
        self.chat(DAD, TOUR)
        self.settle()
        self.assertEqual(self.lines_to(DAD)[-1], rules.CANNED["timeout"])
        self.assertEqual(self.jobs(), [])
        self.chat(DAD, "hello?")
        self.assertEqual(len(self.brain.of("quick")), 2)


class TestOnlyBrainBeingDownHoldsTheDesk(TimeoutCase):
    def test_one_runs_own_failure_does_not_hold_the_next_line(self):
        for code in ("safeguard", "max_turns", "empty", "error"):
            self.assertFalse(rules.brain_is_down(RunFailed("x", code=code)), code)
        for code in ("auth", "paused", "budget", "rate_limited"):
            self.assertTrue(rules.brain_is_down(RunFailed("x", code=code)), code)
        self.assertFalse(rules.brain_is_down(TimeoutError("nothing came back")))
        self.assertTrue(rules.brain_is_down(RuntimeError("service went away")))

    def test_a_safety_refusal_is_said_and_the_next_line_runs(self):
        self.join(DAD)
        self.brain.quick_fails = [RunFailed("API Error: safeguards", code="safeguard")]
        self.chat(DAD, "make a dragon")
        self.assertEqual(self.lines_to(DAD)[-1], rules.CANNED["down"])
        self.chat(DAD, "make a horse")
        self.assertEqual(len(self.brain.of("quick")), 2)
        self.assertEqual(self.lines_to(DAD)[-1], "Sure!")

    def test_signed_out_holds_the_desk_and_a_skipped_line_is_told_once(self):
        self.join(DAD)
        self.brain.quick_fails = [RunFailed("Claude's saved login has expired", code="auth")]
        self.chat(DAD, "build a tower")
        self.assertEqual(self.lines_to(DAD)[-1], rules.CANNED["down"])
        before = len(self.lines_to(DAD))
        self.chat(DAD, "hello?")                 # not named: told anyway, once
        self.chat(DAD, "anyone?")
        self.assertEqual(len(self.brain.of("quick")), 1)
        self.assertEqual(self.lines_to(DAD)[before:], [rules.CANNED["down"]])
        downs = [t for t in self.talks() if t["status"] == "down"]
        self.assertEqual(len(downs), 3)
        self.assertEqual([t["reply"] for t in downs[:2]], ["", rules.CANNED["down"]])


class TestTheDeskIsToldARunOfActionsIsAJob(TimeoutCase):
    def test_the_quick_prompt_names_a_teleport_tour_and_the_time(self):
        self.join(DAD)
        self.chat(DAD, "hi")
        prompt = self.brain.of("quick")[0]["prompt"]
        self.assertIn("a teleport tour along the builds", prompt)
        self.assertIn("well under a minute", prompt)


if __name__ == "__main__":
    unittest.main()
