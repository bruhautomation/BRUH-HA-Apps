"""Morph's two loops, driven against a stand-in brAIn.

The stand-in speaks the automation listener's file contract: it CLAIMS a
task by renaming it, does the work, and writes ``task_results/<id>.json``.
Nothing is mocked inside Morph, so what is proved is that a Tell becomes
one commit, Undo reverts exactly that commit, a learning pass files
suggestions without touching the dashboard, and Morph's own faults reach
the outbox brAIn's development loop reads.
"""
import asyncio
import json
import re
import shutil
import threading
import time
import unittest
from pathlib import Path

from morph_env import MorphEnv

HAS_GIT = shutil.which("git") is not None

DOC = {"title": "Home", "floors": [{"title": "Ground", "sections": [{
    "title": "Kitchen", "groups": [{"cards": [{"entity": "light.countertop"}]}]}]}]}


class FakeBrain(threading.Thread):
    """Claims each task, runs ``work(task)`` and answers with what it returns."""

    def __init__(self, env, work, *, claim=True):
        super().__init__(daemon=True)
        self.env, self.work, self.claim = env, work, claim
        self.seen: list[dict] = []
        self.stop = threading.Event()

    def run(self):
        tasks = self.env.brain_shared / "tasks"
        results = self.env.brain_shared / "task_results"
        while not self.stop.is_set():
            for path in sorted(tasks.glob("*.json")):
                if not self.claim:
                    continue
                claimed = path.with_suffix(".claimed")
                path.rename(claimed)
                task = json.loads(claimed.read_text())
                self.seen.append(task)
                answer = self.work(task)
                (results / f"{task['id']}.json").write_text(json.dumps(
                    {"id": task["id"], "status": "completed", "result": "ok", **answer}))
            time.sleep(0.02)


def fast(env):
    env.brain.POLL_S = 0.02
    env.brain.CLAIM_GRACE_S = 0.5


async def finish(env, state, limit=10.0):
    deadline = time.time() + limit
    while time.time() < deadline:
        st = env.tell.read_state(state["id"]) or {}
        if st.get("phase") in ("done", "failed"):
            return st
        await asyncio.sleep(0.02)
    raise AssertionError("the tell never ended")


@unittest.skipUnless(HAS_GIT, "git is not installed")
class TestTell(unittest.TestCase):

    def setUp(self):
        self.env = MorphEnv().__enter__()
        self.addCleanup(self.env.__exit__, None, None, None)
        self.env.brain_on()
        fast(self.env)
        dash, _ = self.env.store.normalize(DOC)
        self.env.store.write(dash)
        self.env.gitrepo.commit("First", "morph")

    def run_brain(self, work, **kw):
        fake = FakeBrain(self.env, work, **kw)
        fake.start()
        self.addCleanup(fake.stop.set)
        return fake

    def test_a_tell_is_one_commit_and_undo_reverts_exactly_it(self):
        env = self.env

        def work(task):
            dash, _, _ = env.store.read()
            dash["title"] = "Our house"
            env.store.write(dash)
            return {"data": {"summary": "Renamed the dashboard", "changed": ["morph dashboard"],
                             "lesson": "They like short titles"}}

        fake = self.run_brain(work)

        async def go():
            st = env.tell.start({"kind": "dashboard"}, "Call it Our house")
            return await finish(env, st)

        st = asyncio.run(go())
        self.assertEqual("done", st["phase"], st.get("say"))
        self.assertEqual("Renamed the dashboard", st["say"])
        task = fake.seen[0]
        self.assertEqual("full", task["tools"], "act at once: a Tell may change the house")
        self.assertEqual("morph", task["source"])
        self.assertIn("Call it Our house", task["prompt"])
        # brAIn's change, then the lesson it taught as a commit of its own.
        log = env.gitrepo.log()
        self.assertEqual(["learning", "brain"], [r["who"] for r in log[:2]])
        self.assertEqual(st["commit"], log[1]["sha"])
        self.assertIn("They like short titles", " ".join(env.learning.read_lessons()))

        out = env.tell.undo(st["id"])
        self.assertTrue(out["ok"], out)
        self.assertEqual("Home", env.store.read()[0]["title"])
        self.assertTrue(env.gitrepo.is_reverted(st["commit"]))

    def test_nothing_listening_is_said_and_the_task_is_taken_back(self):
        env = self.env
        self.run_brain(lambda task: {}, claim=False)

        async def go():
            st = env.tell.start({"kind": "dashboard"}, "Anything")
            return await finish(env, st)

        st = asyncio.run(go())
        self.assertEqual("failed", st["phase"])
        self.assertIn("Automation integration", st["say"])
        self.assertEqual([], list((env.brain_shared / "tasks").glob("*.json")),
                         "an unclaimed task must not run an hour later")

    def test_no_brain_is_refused_before_anything_is_written(self):
        env = self.env
        shutil.rmtree(env.brain_shared / "tasks")
        out = env.tell.start({"kind": "dashboard"}, "Anything")
        self.assertIn("error", out)


@unittest.skipUnless(HAS_GIT, "git is not installed")
class TestLearning(unittest.TestCase):

    def setUp(self):
        self.env = MorphEnv().__enter__()
        self.addCleanup(self.env.__exit__, None, None, None)
        self.env.brain_on()
        fast(self.env)
        dash, _ = self.env.store.normalize(DOC)
        self.env.store.write(dash)
        self.env.gitrepo.commit("First", "morph")
        self.dash = dash

    def test_a_pass_is_read_only_and_files_suggestions(self):
        env = self.env
        before = env.gitrepo.head()

        def work(task):
            return {"data": {
                "suggestions": [{"title": "Move Kitchen to the top", "why": "Used every evening",
                                 "change": "Move the Kitchen section first", "kind": "dashboard"}],
                "lessons": [{"text": "Kitchen matters most in the evening",
                             "evidence": ["Kitchen opened 40 evenings", "Kitchen moved up twice by hand"]}],
                "code_reports": [{"what": "The fan card cannot show speed", "detail": "x"}]}}

        fake = FakeBrain(env, work)
        fake.start()
        self.addCleanup(fake.stop.set)
        out = asyncio.run(env.learning.run_pass(pressed=True))
        self.assertEqual({"added": 2}, out)
        self.assertEqual("read_only", fake.seen[0]["tools"],
                         "a pass suggests; only a press on Do it changes anything")
        items = env.learning.listing()
        self.assertEqual(["Move Kitchen to the top", "The fan card cannot show speed"],
                         [i["title"] for i in items])
        self.assertEqual(["dashboard", "code"], [i["kind"] for i in items])
        self.assertEqual(["Kitchen matters most in the evening"], env.learning.read_lessons())
        # The lessons file is the one thing a pass writes, and it is its own commit.
        self.assertEqual("learning", env.gitrepo.log()[0]["who"])
        self.assertNotEqual(before, env.gitrepo.head())
        self.assertEqual(self.dash, env.store.read()[0])
        # A model's report about Morph's code is a QUESTION: nothing is filed
        # until somebody presses Send as issue.
        self.assertEqual([], env.devloop.rows())
        self.assertTrue(env.learning.decide(items[1]["id"], "send")["ok"])
        self.assertEqual(["The fan card cannot show speed"], [r["what"] for r in env.devloop.rows()])
        self.assertEqual([], [i for i in env.learning.listing() if i["kind"] == "code"])

    def test_no_is_remembered_and_never_offered_again(self):
        env = self.env
        row = {"title": "Hide the camera", "change": "Hide it"}
        self.assertEqual(1, env.learning.add_suggestions([row], self.dash))
        sid = env.learning.listing()[0]["id"]
        self.assertTrue(env.learning.decide(sid, "no", "We watch it at night")["ok"])
        self.assertEqual([], env.learning.listing())
        self.assertEqual(0, env.learning.add_suggestions([row], self.dash))
        # The reason is evidence for the next pass, not a rule written now.
        self.assertNotIn("We watch it at night", " ".join(env.learning.read_lessons()))
        d = env.learning.digest(self.dash)
        self.assertIn("We watch it at night", env.learning.build_prompt(d, "", [], {}, []))

    def test_not_now_comes_back_later(self):
        env = self.env
        env.learning.add_suggestions([{"title": "A", "change": "B"}], self.dash)
        sid = env.learning.listing()[0]["id"]
        env.learning.decide(sid, "not_now")
        self.assertEqual([], env.learning.listing())
        later = time.time() + env.learning.SNOOZE_S + 1
        self.assertEqual(1, len(env.learning.listing(now=later)))

    def test_a_reworded_suggestion_is_the_same_suggestion(self):
        env = self.env
        self.assertEqual(1, env.learning.add_suggestions(
            [{"title": "Move the porch light card up to the top", "change": "x"}], self.dash))
        self.assertEqual(0, env.learning.add_suggestions(
            [{"title": "Move porch light card to the top", "change": "y"}], self.dash),
            "an open idea reworded must not take another slot")
        self.assertEqual(1, env.learning.add_suggestions(
            [{"title": "Hide the garage camera", "change": "z"}], self.dash))

    def test_a_few_taps_do_not_make_a_pass_worth_running(self):
        env = self.env
        base = {"events": 100, "tells": [], "suggestions": [], "dead": []}
        self.assertEqual(env.learning.fingerprint(base),
                         env.learning.fingerprint({**base, "events": 110}))
        self.assertNotEqual(env.learning.fingerprint(base),
                            env.learning.fingerprint({**base, "events": 100 + 2 * env.learning.EVENT_STEP}))
        self.assertNotEqual(env.learning.fingerprint(base),
                            env.learning.fingerprint({**base, "dead": ["c1"]}))

    def test_the_prompt_lists_what_is_pending_and_leaves_out_idle_cards(self):
        env = self.env
        d = {"days_with_use": 9, "events": 3, "by_kind": {}, "sections": [], "never_used": ["idle1"],
             "dead": [], "tells": [], "suggestions": [],
             "cards": [{"id": "idle1", "section": "s", "type": "t", "entity": "", "uses": 0, "unavailable": False},
                       {"id": "busy1", "section": "s", "type": "t", "entity": "", "uses": 4, "unavailable": False}]}
        items = [{"title": "Waiting idea", "status": "open"}, {"title": "Finished idea", "status": "done"}]
        text = env.learning.build_prompt(d, "floors: []", [], {}, items)
        self.assertIn("busy1", text)
        self.assertNotIn('"id":"idle1"', text)
        self.assertIn("Waiting idea", text)
        self.assertIn("Finished idea", text)

    def test_the_use_log_is_pruned_once_a_day(self):
        env = self.env
        old = time.time() - 90 * 86400
        env.paths.append_jsonl(env.paths.USAGE, {"ts": old, "kind": "open"})
        env.paths.append_jsonl(env.paths.USAGE, {"ts": time.time(), "kind": "open"})
        self.assertTrue(env.learning.prune_due())
        self.assertEqual(1, len(env.learning.usage()))
        self.assertFalse(env.learning.prune_due(), "once a day, not every tick")

    def test_a_suggestion_being_done_is_settled_by_its_tell(self):
        env = self.env
        env.learning.add_suggestions([{"title": "A", "change": "B"}], self.dash)
        sid = env.learning.listing()[0]["id"]
        env.learning.mark_doing(sid, "morph-x")
        env.learning.settle_doing(lambda tid: {"phase": "failed", "say": "nope"})
        item = env.learning.all_items()[0]
        self.assertEqual("open", item["status"], "a failed run says nothing about the idea")
        env.learning.mark_doing(sid, "morph-y")
        env.learning.settle_doing(lambda tid: {"phase": "done", "commit": "abc"})
        self.assertEqual("done", env.learning.all_items()[0]["status"])

    def test_learning_off_means_no_pass_is_due(self):
        env = self.env
        env.settings.update({"learning": False})
        self.assertFalse(env.learning.due(time.time() + 10 * 86400))
        env.settings.update({"learning": True})
        self.assertTrue(env.learning.due(time.time() + 10 * 86400))


class TestDevloopOutbox(unittest.TestCase):

    def test_faults_reach_the_outbox_and_switching_off_empties_it(self):
        with MorphEnv() as env:
            for _ in range(3):
                env.devloop.note_fault("Cards", "A fan card failed to draw: x is undefined", "trace")
            out = env.devloop.publish("0.1.0")
            self.assertEqual(1, len(out["rows"]), "one fault, one row, however often")
            row = out["rows"][0]
            self.assertTrue(row["where"].startswith("Morph"),
                            "brAIn's stream keeps only rows whose where starts with Morph")
            self.assertEqual(3, row["impact"]["times"])
            env.settings.update({"report_code_issues": False})
            self.assertEqual([], env.devloop.publish("0.1.0")["rows"])

    def test_every_issue_points_at_files_that_exist(self):
        # The body sent the developer to `morph/AGENTS.md`, which is not in
        # the repository; every path it names now has to be.
        repo = Path(__file__).resolve().parent.parent
        with MorphEnv() as env:
            env.devloop.note_fault("Cards", "A fan card failed to draw", "trace")
            env.devloop.note_request("The header is too tall", ui=True)
            rows = env.devloop.rows()
        self.assertEqual(2, len(rows))
        for row in rows:
            named = re.findall(r"(?:morph|docs|tests)/[\w./-]+\.(?:md|mjs)", row["body"])
            self.assertIn("morph/defaults/AGENTS.md", named)
            for path in named:
                self.assertTrue((repo / path).is_file(), path)
            self.assertNotIn("see morph/AGENTS.md", row["body"])

    def test_panel_errors_are_folded_in_and_the_file_emptied(self):
        with MorphEnv() as env:
            env.paths.append_jsonl(env.paths.ERRORS, {
                "kind": "card", "card_type": "climate", "message": "boom", "ts": time.time()})
            self.assertEqual(1, env.devloop.ingest_errors())
            self.assertEqual([], env.paths.read_jsonl(env.paths.ERRORS))
            self.assertIn("climate card", env.devloop.rows()[0]["what"])

    def test_a_debug_trace_is_not_a_fault(self):
        # Four issues titled "DEBUG …" were filed from traces left in while
        # chasing a layout bug; a person's own words are never dropped.
        with MorphEnv() as env:
            env.paths.append_jsonl(env.paths.ERRORS, {
                "kind": "panel", "message": "DEBUG wide tile went small #1", "ts": time.time()})
            env.devloop.ingest_errors()
            env.devloop.note_fault("Panel", "DEBUG loaded 2026-10-14", "")
            env.devloop.note_request("Debug view should be hidden", ui=False)
            whats = [r["what"] for r in env.devloop.rows()]
        self.assertEqual(["Debug view should be hidden"], whats)

    def test_a_row_says_when_morph_last_saw_it(self):
        # brAIn's stream reads this as the sighting, so a row republished
        # for a fortnight is not "still happening" on every update.
        with MorphEnv() as env:
            env.devloop.note_fault("Cards", "A fan card failed", "", now=1_700_000_000.0)
            row = env.devloop.rows(now=1_700_000_100.0)[0]
        self.assertEqual(1_700_000_000.0, row["last"])


if __name__ == "__main__":
    unittest.main()
