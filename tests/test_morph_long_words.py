"""A person's words reach brAIn whole, whatever a card sent with them.

A custom card sent its ~2000-character context first and "What <who> said:
<question>" last as one `text`, and Morph's conversation sliced `text[:2000]`:
the person's question was the part cut, and brAIn answered "your message got
cut off". The bound is sized for a context and a message now, a card can send
the two apart, and when anything gives it is the context.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import re
import sys
import unittest
from pathlib import Path

from morph_env import MorphEnv

ROOT = Path(__file__).resolve().parent.parent
INTEGRATION = ROOT / "morph" / "custom_components" / "morph"
QUESTION = "What Sam said: is the back door locked, and did the dryer finish?"


def _context(n: int) -> str:
    row = "kitchen 21.4 C; hall motion 3 min ago; dryer 2 W; "
    return (row * (n // len(row) + 1))[:n]


class _Converse:
    """Drive morphd's real `converse` request and read the task brAIn gets."""

    def converse(self, env, payload: dict) -> tuple[dict, dict]:
        env.brain_on()
        morphd = importlib.import_module("morphd")

        async def go():
            st = await morphd.handle("converse", payload)
            task_file = None
            for _ in range(200):
                found = list((env.brain_shared / "tasks").glob("*.json"))
                if found:
                    task_file = found[0]
                    break
                await asyncio.sleep(0.02)
            for t in list(env.converse._RUNNING.values()):
                t.cancel()
            await asyncio.sleep(0)
            return st, json.loads(task_file.read_text()) if task_file else {}
        return asyncio.run(go())


class TestAConversationKeepsThePersonsWords(unittest.TestCase, _Converse):

    def test_a_message_after_a_long_context_reaches_brain_whole(self):
        # The house's card: context first, the person's words last, one text.
        text = _context(2100) + "\n\n" + QUESTION
        with MorphEnv() as env:
            st, task = self.converse(env, {"text": text})
        self.assertTrue(st["ok"], st)
        self.assertTrue(st["text"].endswith(QUESTION))
        self.assertTrue(task["prompt"].endswith(QUESTION), task["prompt"][-200:])
        self.assertTrue(task["person_words"].endswith(QUESTION))

    def test_context_sent_apart_rides_beside_the_words(self):
        with MorphEnv() as env:
            st, task = self.converse(env, {"text": QUESTION, "context": _context(2500)})
        self.assertEqual(st["text"], QUESTION)
        self.assertEqual(task["person_words"], QUESTION)
        self.assertTrue(task["prompt"].endswith(QUESTION))
        self.assertIn(_context(2500).strip(), task["prompt"])
        self.assertLess(task["prompt"].index("kitchen"), task["prompt"].index(QUESTION))

    def test_when_something_must_give_it_is_the_context(self):
        huge = _context(40000)
        with MorphEnv() as env:
            st, task = self.converse(env, {"text": QUESTION, "context": huge})
            cap = env.converse.MAX_TEXT
            cut = env.wording.CONTEXT_CUT
        self.assertEqual(task["person_words"], QUESTION)
        self.assertTrue(task["prompt"].endswith(QUESTION))
        self.assertIn(cut.strip(), task["prompt"])
        self.assertLessEqual(len(st["context"]) + len(st["text"]), cap)
        self.assertEqual(st["cut"], "context")

    def test_one_text_too_long_still_reaches_brain_whole(self):
        # A person's words are never cut from the front (#428): the start of
        # what they typed is where the request usually is.
        text = _context(40000) + QUESTION
        with MorphEnv() as env:
            st, task = self.converse(env, {"text": text})
        self.assertTrue(task["prompt"].endswith(QUESTION))
        self.assertIn(text, task["prompt"])
        self.assertEqual(st["text"], text)


class TestATellKeepsThePersonsWords(unittest.TestCase):

    def test_a_long_request_reaches_the_tell_whole(self):
        long_words = ("Make the climate card show the week, " * 150) + "and put it first."
        self.assertGreater(len(long_words), 4000)
        with MorphEnv() as env:
            env.brain_on()
            morphd = importlib.import_module("morphd")

            async def go():
                st = await morphd.handle("tell", {"target": {"kind": "dashboard"}, "text": long_words,
                                                  "context": _context(3000)})
                for t in list(env.tell._RUNNING.values()):
                    t.cancel()
                await asyncio.sleep(0)
                return st
            st = asyncio.run(go())
            prompt = env.tell.build_prompt({"kind": "dashboard"}, st["text"], "", context=st["context"])
        self.assertTrue(st["ok"], st)
        self.assertEqual(st["text"], long_words.strip())
        self.assertEqual(st["person_words"], long_words.strip())
        self.assertIn("“" + long_words.strip() + "”", prompt)
        self.assertLess(prompt.index("kitchen"), prompt.index("THE REQUEST"))


class TestTheIntegrationCutsNothingSilently(unittest.TestCase):

    def setUp(self):
        sys.path.insert(0, str(INTEGRATION))
        sys.modules.pop("words", None)
        self.words = importlib.import_module("words")

    def tearDown(self):
        sys.modules.pop("words", None)
        sys.path.remove(str(INTEGRATION))

    def test_the_limit_is_brains_own(self):
        for path, name in ((ROOT / "brain" / "panel" / "morph_bridge.py", "ASK_TEXT_MAX"),
                           (ROOT / "brain" / "panel" / "finding_requests.py", "MORPH_TEXT_MAX")):
            m = re.search(rf"^{name} = (\d+)", path.read_text(), re.M)
            self.assertEqual(int(m.group(1)), self.words.BRAIN_TEXT_MAX, path.name)

    def test_a_long_reply_is_refused_in_words_and_a_short_one_is_not(self):
        self.assertEqual(self.words.reply_refusal("yes, it is off on purpose"), "")
        said = self.words.reply_refusal("x" * 1500)
        self.assertIn("1500", said)
        self.assertIn("Ask", said)

    def test_no_route_slices_text_any_more(self):
        src = (INTEGRATION / "websocket.py").read_text()
        self.assertNotIn('["text"].strip()[:', src)
        self.assertIn("words.reply_refusal(text)", src)
        self.assertIn("words.too_long(text)", src)


if __name__ == "__main__":
    unittest.main()
