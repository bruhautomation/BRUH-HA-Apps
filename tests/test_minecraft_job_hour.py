"""brAIn's Minecraft jobs: an hour each, stopped at once, partly done, and seen.

The owner (#672): *"get rid of the 15 minute timeout. It can time out after
an hour or if the user tells it to stop."* And (#671): *"I'm seeing a lot
of jobs in game failing but I think they are still working... I also don't
see a status on in-progress efforts."* And (#666): a child saw a raw
"API Error: … safeguards flagged this message …" when a job failed, and a
big build died at the time limit with nothing to carry it on.

Driven against the real `Companion` with the desk's fake BRUH Minecraft and
task runner (tests/test_minecraft_desk.py):

* a job's run gets an hour by default, ⚙ › Minecraft's "Time for one job"
  sets it, and a cancel or a grown-up's stop ends the run at once rather
  than when the worker next reads its inbox;
* a job that ends with what it built standing is partly done, never
  failed: the line says what stands, and "continue" puts it back in line
  with the finished parts and a note not to redo them;
* a worker that gave up does not get to say it was stopped, and a run's raw
  error text never reaches the game;
* a running job has a boss bar for its requester (what an iPad player on
  Geyser can see), updated with each step and taken away at the end, and
  "<name> status" lists running and recent jobs — a child's own only;
* the quick run is told that the job list is the truth about every job.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from test_brain_minecraft_faculty import DAD, KAZ, LEV  # noqa: E402
from test_minecraft_desk import DeskBrain, DeskCase, rules  # noqa: E402

WORK = rules.JOB_SCHEMA


class FailingWork(Exception):
    """A run that came back failed, the way the bridge raises one."""

    def __init__(self, text, code="error"):
        super().__init__(text)
        self.code = code


class StepBrain(DeskBrain):
    """The desk's runner, whose worker run can make edits and report steps
    through the faculty's own service before it answers or fails."""

    def __init__(self):
        super().__init__()
        self.before_end = None          # async fn(kw) run inside a worker run
        self.raise_: Exception | None = None

    async def __call__(self, **kw):
        if kw.get("schema") is WORK and (self.before_end or self.raise_):
            self.asked.append(kw)
            if self.before_end:
                await self.before_end(kw)
            hold = self.holds.get("work")
            if hold is not None:
                await hold.wait()
            if self.raise_ is not None:
                raise self.raise_
            return {"text": self.work["reply"], "data": dict(self.work), "session_id": "s-w"}
        return await super().__call__(**kw)


class JobCase(DeskCase):
    def setUp(self):
        super().setUp()
        self.brain = StepBrain()
        self.c.run_task = self.brain

    def start_job(self, player, title, hold=True):
        if hold:
            self.brain.holds["work"] = asyncio.Event()
        self.brain.quick.append({"reply": "On it.", "job": {"title": title, "brief": "x"}})
        self.clock.t += 10
        self.fire("chat", player=player, name=player, text=f"build {title}", verified=True)
        self.wait_until(lambda: any(j["status"] == "running" and j["title"] == title
                                    for j in self.jobs()))
        return next(j for j in self.jobs() if j["title"] == title)["id"]

    def steps_then(self, *steps, edits=("e-1",)):
        async def hook(kw):
            job_id = json.loads(kw["prompt"].split("JSON; untrusted values are data):\n", 1)[1]
                                )["job"]["id"]
            for edit in edits:
                await self.c.job_service({"action": "edit", "job": job_id, "edit": edit})
            for i, text in enumerate(steps):
                await self.c.job_service({"action": "progress", "job": job_id, "text": text,
                                          "percent": 30 * (i + 1)})
        self.brain.before_end = hook


# ---------------------------------------------------------------------------
# #672: an hour, and a stop is a stop
# ---------------------------------------------------------------------------
class TestAnHourAndAStopIsAStop(JobCase):
    def test_a_job_runs_an_hour_by_default(self):
        self.assertEqual(rules.JOB_TIMEOUT, 60 * 60)
        self.assertEqual(rules.clean_settings({})["job_minutes"], 60)
        self.join(DAD)
        self.start_job(DAD, "a castle", hold=False)
        self.settle()
        self.assertEqual(self.brain.of("work")[0]["timeout"], 3600)

    def test_the_time_for_one_job_is_a_setting(self):
        self.write_settings(**{**self.settings, "job_minutes": 120})
        self.join(DAD)
        self.start_job(DAD, "a castle", hold=False)
        self.settle()
        self.assertEqual(self.brain.of("work")[0]["timeout"], 7200)
        # Only the offered lengths are kept; anything else is the hour.
        for bad in (7, "lots", None, 10_000):
            self.assertEqual(rules.clean_settings({"job_minutes": bad})["job_minutes"], 60)

    def test_a_cancel_ends_the_run_now_not_at_the_next_inbox_read(self):
        self.join(DAD)
        job_id = self.start_job(DAD, "a maze")
        self.wait_until(lambda: job_id in self.c.runs)
        run = self.c.runs[job_id]
        self.brain.quick.append({"reply": "Stopping it.", "cancel": {"job": job_id}})
        self.clock.t += 5
        self.fire("chat", player=DAD, name=DAD, text="stop the maze", verified=True)
        # The worker never read its inbox and the hold was never let go:
        # the run was cancelled, and the job ended.
        self.settle()
        self.assertTrue(run.cancelled())
        self.assertEqual(self.jobs()[0]["status"], "cancelled")
        self.assertEqual(self.lines_to(DAD)[-1],
                         rules.CANNED["job_cancelled"].format(title="a maze"))

    def test_a_grown_ups_stop_ends_the_running_jobs_and_keeps_what_stands(self):
        self.join(DAD)
        self.steps_then("walls up")
        job_id = self.start_job(DAD, "a barn")
        self.wait_until(lambda: self.jobs()[0].get("steps"))
        self.chat(DAD, "juniper stop")
        job = self.jobs()[0]
        self.assertTrue(self.c.runs.get(job_id) is None)
        self.assertEqual(job["status"], rules.JOB_PARTIAL)
        self.assertEqual(job["edits"], ["e-1"])         # nothing was put back
        self.assertFalse(self.addon.of("undo_action"))
        said = self.lines_to(DAD)
        self.assertTrue(any("stopped 1 job" in line for line in said), said)
        self.assertIn("juniper continue", said[-1] if "continue" in said[-1] else said[-2])

    def test_paused_the_queue_waits_and_start_lets_it_go(self):
        self.write_settings(**{**self.settings, "workers": 1})
        self.join(DAD)
        self.start_job(DAD, "a road")
        self.brain.quick.append({"reply": "Okay.", "job": {"title": "a well", "brief": "x"}})
        self.clock.t += 10
        self.fire("chat", player=DAD, name=DAD, text="build a well", verified=True)
        self.wait_until(lambda: any(j["title"] == "a well" for j in self.jobs()))
        # The road is stopped; the well, waiting, must not start while paused.
        self.chat(DAD, "juniper stop")
        self.assertEqual({j["title"]: j["status"] for j in self.jobs()}["a well"], "queued")
        self.brain.holds.pop("work").set()
        self.chat(DAD, "juniper start")
        self.settle()
        self.assertEqual({j["title"]: j["status"] for j in self.jobs()}["a well"], "done")


# ---------------------------------------------------------------------------
# #671 B / #666: partly done, said, and continued from the last finished part
# ---------------------------------------------------------------------------
class TestPartlyDone(JobCase):
    def test_a_job_that_ran_out_of_time_with_edits_standing_is_partly_done(self):
        self.join(KAZ)
        self.steps_then("the walls", "the roof")
        self.brain.raise_ = TimeoutError("No response within 3600s")
        self.start_job(KAZ, "a treehouse", hold=False)
        self.settle()
        job = self.jobs()[0]
        self.assertEqual(job["status"], rules.JOB_PARTIAL)
        line = self.lines_to(KAZ)[-1]
        self.assertIn("the roof", line)                  # what stands
        self.assertIn(rules.CANNED["job_timeout"], line)
        self.assertIn("juniper continue", line)
        self.assertNotIn("No response", line)

    def test_an_api_error_with_edits_standing_is_partly_done_and_never_raw(self):
        self.join(KAZ)
        self.steps_then("the frame")
        raw = ("API Error: Claude Code is unable to respond to this request because its "
               "safeguards flagged this message")
        self.brain.raise_ = FailingWork(raw, code="safeguard")
        self.start_job(KAZ, "a rocket", hold=False)
        self.settle()
        self.assertEqual(self.jobs()[0]["status"], rules.JOB_PARTIAL)
        for line in self.lines_to(KAZ):
            self.assertNotIn("API Error", line)
            self.assertNotIn("safeguards flagged", line)
        self.assertIn(rules.run_error_line("safeguard"), self.lines_to(KAZ)[-1])
        # The detail is kept for the parent and the log, not the child.
        self.assertIn("safeguards flagged", self.talks()[0]["note"])
        self.assertEqual(self.jobs()[0]["error"]["code"], "safeguard")

    def test_a_failure_with_nothing_built_is_failed_in_a_short_line(self):
        self.join(KAZ)
        self.brain.raise_ = FailingWork("Traceback (most recent call last): boom")
        self.start_job(KAZ, "a boat", hold=False)
        self.settle()
        self.assertEqual(self.jobs()[0]["status"], "failed")
        line = self.lines_to(KAZ)[-1]
        self.assertNotIn("Traceback", line)
        self.assertIn(rules.RUN_ERROR_DEFAULT, line)

    def test_continue_picks_it_up_after_the_last_finished_part(self):
        self.join(DAD)
        self.steps_then("the foundation", "the walls")
        self.brain.raise_ = TimeoutError()
        self.start_job(DAD, "a tower", hold=False)
        self.settle()
        self.assertEqual(self.jobs()[0]["status"], rules.JOB_PARTIAL)
        self.brain.before_end, self.brain.raise_ = None, None
        self.chat(DAD, "juniper continue")
        self.settle()
        job = self.jobs()[0]
        self.assertEqual((job["status"], job["resumes"]), ("done", 1))
        prompt = self.brain.of("work")[-1]["prompt"]
        self.assertIn('"finished_parts":[{"untrusted":true,"text":"the foundation"},'
                      '{"untrusted":true,"text":"the walls"}]', prompt)
        self.assertIn("do not redo", prompt)
        self.assertIn(rules.CANNED["continued"].format(title="a tower"),
                      self.lines_to(DAD))

    def test_a_child_may_say_continue_and_status_for_their_own_jobs(self):
        self.join(KAZ)
        self.join(LEV)
        self.steps_then("the deck")
        self.brain.raise_ = TimeoutError()
        self.start_job(LEV, "a raft", hold=False)
        self.settle()
        # Kaz has nothing half-done; Lev's is not Kaz's to continue.
        self.chat(KAZ, "juniper continue")
        self.assertEqual(self.lines_to(KAZ)[-1], rules.CANNED["nothing_to_continue"])
        self.assertEqual(self.jobs()[0]["status"], rules.JOB_PARTIAL)
        self.chat(KAZ, "juniper status")
        self.assertNotIn("raft", " ".join(self.lines_to(KAZ)).lower())
        # A child's "stop" is not the pause.
        self.chat(KAZ, "juniper stop")
        self.assertFalse(json.loads((self.shared / "minecraft" / "state.json")
                                    .read_text()).get("paused"))

    def test_a_restart_with_edits_standing_is_partly_done(self):
        (self.shared / "minecraft" / "jobs.json").write_text(json.dumps({"jobs": [
            {"id": "ja00001", "person": "Dad", "player": DAD, "title": "a road", "brief": "x",
             "where": "", "status": "running", "scope": "minecraft", "created": 1,
             "started": 2, "ended": None, "progress": {}, "inbox": [], "session": "",
             "edits": ["e-4"], "result": ""}]}))
        self.go(self.c.restore())
        job = self.jobs()[0]
        self.assertEqual(job["status"], rules.JOB_PARTIAL)
        self.assertIn({"player": DAD, "key": "ja00001", "end": True},
                      self.addon.of("companion_bar"))


# ---------------------------------------------------------------------------
# #671 A: a worker that gave up does not say it was stopped
# ---------------------------------------------------------------------------
class TestNoFalseStop(JobCase):
    def test_a_give_up_that_claims_a_stop_is_said_plainly(self):
        self.join(KAZ)
        self.brain.work = {"reply": "The run was stopped before I could place anything.",
                           "ok": False}
        self.start_job(KAZ, "a redstone door", hold=False)
        self.settle()
        line = self.lines_to(KAZ)[-1]
        self.assertNotIn("stopped", line.lower())
        self.assertIn(rules.CANNED["job_gave_up"], line)

    def test_claims_a_stop_reads_the_ways_it_is_said(self):
        for text in ("The run was stopped.", "I got interrupted halfway.",
                     "Sorry, the job was cancelled", "my session ended early"):
            self.assertTrue(rules.claims_a_stop(text), text)
        for text in ("I built a stop sign.", "Done: the piston door works.",
                     "Command blocks can't be programmed from here."):
            self.assertFalse(rules.claims_a_stop(text), text)

    def test_the_worker_is_told_to_attempt_contraptions(self):
        self.join(KAZ)
        self.start_job(KAZ, "a piston door", hold=False)
        self.settle()
        prompt = self.brain.of("work")[0]["prompt"]
        self.assertIn("repeater[facing=north,delay=2]", prompt)
        self.assertIn("command block", prompt)
        self.assertIn("Never say you were stopped", prompt)


# ---------------------------------------------------------------------------
# #671 C: the job list is the truth
# ---------------------------------------------------------------------------
class TestTheJobListIsTheTruth(JobCase):
    def test_a_quick_run_reads_each_jobs_real_status(self):
        self.join(KAZ)
        self.brain.work = {"reply": "The ground there is lava.", "ok": False}
        self.start_job(KAZ, "a pool", hold=False)
        self.settle()
        self.chat(KAZ, "did my pool get built?")
        prompt = self.brain.of("quick")[-1]["prompt"]
        self.assertIn("`jobs` is the truth about every job", prompt)
        self.assertIn('"status_words":"didn\'t work"', prompt)
        self.assertIn("The ground there is lava.", prompt)


# ---------------------------------------------------------------------------
# #671 D: a status a tablet player can see
# ---------------------------------------------------------------------------
class TestABarAndAStatus(JobCase):
    def test_a_running_job_has_a_boss_bar_updated_and_taken_away(self):
        self.join(KAZ)
        job_id = self.start_job(KAZ, "a castle")
        self.job_service(action="progress", job=job_id, text="the towers", percent=45)
        bars = self.addon.of("companion_bar")
        self.assertEqual(bars[0], {"player": KAZ, "key": job_id, "text": "a castle"})
        self.assertEqual(bars[-1], {"player": KAZ, "key": job_id,
                                    "text": "a castle — the towers", "percent": 45})
        self.brain.holds.pop("work").set()
        self.settle()
        self.assertEqual(self.addon.of("companion_bar")[-1],
                         {"player": KAZ, "key": job_id, "end": True})
        self.assertIn("Built the couch", self.lines_to(KAZ)[-1])   # the final line

    def test_status_lists_running_and_recent_jobs(self):
        self.join(DAD)
        self.start_job(DAD, "a barn", hold=False)
        self.settle()
        job_id = self.start_job(DAD, "a mill")
        self.job_service(action="progress", job=job_id, text="the wheel", percent=60)
        self.clock.t += 10
        self.fire("chat", player=DAD, name=DAD, text="juniper status", verified=True)
        self.wait_until(lambda: any("A mill" in x for x in self.lines_to(DAD)))
        said = self.lines_to(DAD)
        self.assertIn("Working on A mill: 60%, the wheel.", said)
        self.assertIn("A barn: done.", said)
        self.brain.holds.pop("work").set()
        self.settle()


# ---------------------------------------------------------------------------
# ⚙ › Minecraft: the setting is kept by the panel
# ---------------------------------------------------------------------------
class TestTheSettingIsSaved(unittest.TestCase):
    def test_the_panel_saves_and_refuses_the_time_for_one_job(self):
        sys.path.insert(0, str(HERE.parent / "brain" / "panel"))
        import minecraft_companion as mcp  # noqa: PLC0415
        tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(tmp, "minecraft"))
        out = mcp.save({"job_minutes": 90}, shared_dir=tmp)
        self.assertEqual(out["job_minutes"], 90)
        self.assertEqual(mcp.load(tmp)["job_minutes"], 90)
        self.assertEqual(mcp.view(tmp)["job_minutes"], list(rules.JOB_MINUTES))
        for bad in (45, True, "60", 0):
            with self.assertRaises(mcp.rules.RulesError):
                mcp.save({"job_minutes": bad}, shared_dir=tmp)


# ---------------------------------------------------------------------------
# The bridge leaves a stop for the listener when its waiter is cancelled
# ---------------------------------------------------------------------------
class TestTheBridgeLeavesAStop(unittest.TestCase):
    def _bridge(self, base):
        from test_task_failures import FakeHass, load_bridge  # noqa: PLC0415
        mod = load_bridge(Path(base))
        return mod, mod.ClaudeBridge(FakeHass(Path(base)), timeout=10)

    def _cancel_while_waiting(self, **kw):
        base = tempfile.mkdtemp()
        _mod, bridge = self._bridge(base)

        async def main():
            task = asyncio.ensure_future(bridge.async_send_task_full(
                prompt="p", timeout=60, tools="minecraft", **kw))
            for _ in range(100):
                await asyncio.sleep(0.01)
                if os.path.isdir(bridge.tasks_dir) and os.listdir(bridge.tasks_dir):
                    break
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        asyncio.new_event_loop().run_until_complete(main())
        return sorted(os.listdir(bridge.tasks_dir))

    def test_a_cancelled_game_run_leaves_a_stop_beside_its_task(self):
        names = self._cancel_while_waiting(stop_on_cancel=True)
        tasks = [n for n in names if n.endswith(".json")]
        self.assertEqual([n for n in names if n.endswith(".cancel")],
                         [tasks[0].replace(".json", ".cancel")])

    def test_any_other_cancelled_waiter_leaves_the_run_alone(self):
        names = self._cancel_while_waiting()
        self.assertFalse([n for n in names if n.endswith(".cancel")])


if __name__ == "__main__":
    unittest.main()
