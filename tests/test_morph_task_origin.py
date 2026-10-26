"""Every task Morph hands brAIn says Morph sent it (#427).

brAIn lists the conversations a face started under that face's name, and
the one thing it can read without guessing from a prompt's wording is a
field on the task. So every kind Morph writes — a Tell, Ask's
conversation, a learning pass, the request that makes a paused change to
Morph's own code again — carries ``"origin": "morph"``, and nothing in
Morph writes into brAIn's task folder except ``brain.submit``.
"""
import asyncio
import importlib
import re
import shutil
import time
import unittest
from pathlib import Path

from morph_env import MorphEnv
from test_morph_loops import DOC, FakeBrain, fast

HAS_GIT = shutil.which("git") is not None
SERVICE = Path(__file__).resolve().parent.parent / "morph" / "service"


def _answer(task):
    return {"data": {"summary": "Done.", "files": [], "home_assistant": [], "suggestions": [],
                     "lessons": [], "code_reports": []}}


@unittest.skipUnless(HAS_GIT, "git is not installed")
class TestEveryTaskSaysItCameFromMorph(unittest.TestCase):

    def setUp(self):
        self.env = MorphEnv().__enter__()
        self.addCleanup(self.env.__exit__, None, None, None)
        self.env.brain_on()
        fast(self.env)
        dash, _ = self.env.store.normalize(DOC)
        self.env.store.write(dash)
        self.env.gitrepo.commit("First", "morph")
        self.brain = FakeBrain(self.env, _answer)
        self.brain.start()
        self.addCleanup(self.brain.stop.set)
        self.morphd = importlib.import_module("morphd")

    def _wait_for(self, n: int, limit: float = 10.0) -> dict:
        async def go():
            deadline = time.time() + limit
            while len(self.brain.seen) < n and time.time() < deadline:
                await asyncio.sleep(0.02)
        return go()

    def _run(self, coro_fn, n: int = 1) -> dict:
        async def go():
            await coro_fn()
            await self._wait_for(n)
            for running in (self.env.tell._RUNNING, self.env.converse._RUNNING):
                for t in list(running.values()):
                    t.cancel()
            await asyncio.sleep(0)
        asyncio.run(go())
        self.assertGreaterEqual(len(self.brain.seen), n, "brAIn was handed nothing")
        return self.brain.seen[n - 1]

    def test_a_tell(self):
        task = self._run(lambda: self.morphd.handle(
            "tell", {"target": {"kind": "dashboard"}, "text": "Put the kitchen first."}))
        self.assertEqual(task["origin"], "morph")

    def test_a_conversation(self):
        task = self._run(lambda: self.morphd.handle("converse", {"text": "Is the porch light on?"}))
        self.assertEqual(task.get("kind"), "conversation")
        self.assertEqual(task["origin"], "morph")

    def test_a_learning_pass(self):
        async def go():
            asyncio.get_running_loop().create_task(self.env.learning.run_pass(pressed=True))
        task = self._run(go)
        self.assertEqual(task["origin"], "morph")

    def test_a_redo_of_a_paused_change_to_morphs_own_code(self):
        code = self.env.morph_dir / "frontend"
        code.mkdir()
        before = (self.env.shipped / "styles.js").read_text()
        (code / "styles.js").write_text(before + "/* a theme switch */\n")
        self.env.gitrepo.commit("brAIn: a theme switch", "brain")
        (self.env.shipped / "styles.js").write_text(before + "/* next release */\n")
        task = self._run(lambda: self.morphd.handle("code_redo", {"name": "styles.js"}))
        self.assertEqual(task["origin"], "morph")

    def test_the_writer_itself(self):
        self.env.brain.submit("morph-x1", "hello")
        self.env.brain.submit("conv-x1", "hello", kind="conversation")
        # The fake claims tasks as they land; read what it was handed.
        asyncio.run(self._wait_for(1 + len(self.brain.seen)))
        for task in self.brain.seen:
            self.assertEqual(task["origin"], "morph", task.get("id"))


class TestNothingElseWritesATask(unittest.TestCase):

    def test_only_brain_submit_writes_into_the_task_folder(self):
        for path in SERVICE.glob("*.py"):
            text = path.read_text()
            for m in re.finditer(r"tasks_dir\(\)", text):
                line = text[:m.start()].count("\n") + 1
                if path.name == "brain.py":
                    continue
                self.fail(f"{path.name}:{line} reaches brAIn's task folder outside brain.submit")


if __name__ == "__main__":
    unittest.main()
