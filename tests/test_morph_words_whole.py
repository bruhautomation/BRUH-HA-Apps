"""A long Morph request reaches brAIn with the person's words whole (#428).

What a person types is never the part that is cut, however long: Morph used
to keep the END of words over its bound behind "(the start of this message
was cut to fit)", so a long change request reached brAIn — and brAIn's chat —
missing its opening, cut mid-word. Only the context sent beside the words
gives way, and it is cut on a line break (or between words) and says so.
The same rule holds for the other text Morph writes into a request: a
suggestion's change and an answer's request are cut between words, marked.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import unittest

from morph_env import MorphEnv


def _typed(n: int) -> str:
    """What somebody typed: distinct words, so a missing piece shows."""
    out, i = [], 0
    while len(" ".join(out)) < n:
        out.append(f"step{i} move the climate card")
        i += 1
    return " ".join(out)[:n].rstrip()


def _context(n: int) -> str:
    rows, i = [], 0
    while sum(len(r) + 1 for r in rows) < n:
        rows.append(f"reading {i}: kitchen 21.4 C, hall motion 3 min ago")
        i += 1
    return "\n".join(rows)


def _drive(env, kind: str, payload: dict) -> tuple[dict, dict]:
    env.brain_on()
    morphd = importlib.import_module("morphd")

    async def go():
        st = await morphd.handle(kind, payload)
        task = {}
        for _ in range(300):
            found = list((env.brain_shared / "tasks").glob("*.json"))
            if found:
                task = json.loads(found[0].read_text())
                break
            await asyncio.sleep(0.02)
        for running in (env.tell._RUNNING, env.converse._RUNNING):
            for t in list(running.values()):
                t.cancel()
        await asyncio.sleep(0)
        return st, task
    return asyncio.run(go())


class TestTheWordsArriveWhole(unittest.TestCase):

    def _check_context(self, sent: str, context: str, cut_marker: str):
        self.assertTrue(sent.endswith(cut_marker), sent[-120:])
        kept = sent[: -len(cut_marker)]
        self.assertTrue(context.startswith(kept))
        # Cut on a line: what follows the kept part in the original is a line break.
        self.assertEqual(context[len(kept)], "\n")

    def test_a_conversation_with_6000_typed_and_40000_of_context(self):
        typed, context = _typed(6000), _context(40000)
        with MorphEnv() as env:
            st, task = _drive(env, "converse", {"text": typed, "context": context})
            marker = env.wording.CONTEXT_CUT
        self.assertEqual(task["person_words"], typed)
        self.assertIn(typed, task["prompt"])
        self._check_context(st["context"], context, marker)

    def test_a_tell_with_6000_typed_and_40000_of_context(self):
        typed, context = _typed(6000), _context(40000)
        with MorphEnv() as env:
            st, _ = _drive(env, "tell", {"target": {"kind": "dashboard"}, "text": typed,
                                         "context": context})
            marker = env.wording.CONTEXT_CUT
            prompt = env.tell.build_prompt({"kind": "dashboard"}, st["text"], "",
                                           context=st["context"])
        self.assertEqual(st["text"], typed)
        self.assertEqual(st["person_words"], typed)
        self.assertIn("“" + typed + "”", prompt)
        self._check_context(st["context"], context, marker)

    def test_words_alone_over_the_bound_keep_their_first_character(self):
        typed = _typed(20000)
        with MorphEnv() as env:
            st, task = _drive(env, "converse", {"text": typed})
            self.assertGreater(len(typed), env.wording.MAX_TEXT)
        self.assertEqual(st["text"], typed)
        self.assertEqual(task["person_words"], typed)
        self.assertTrue(task["prompt"].endswith(typed))
        self.assertNotIn("cut to fit", task["prompt"])

    def test_a_context_with_no_lines_is_cut_between_words(self):
        with MorphEnv() as env:
            ctx = ("kitchen twentyone point four " * 2000).strip()
            out = env.wording.fit("hello", ctx, cap=1000)
            marker = env.wording.CONTEXT_CUT
        kept = out["context"][: -len(marker)]
        self.assertTrue(ctx.startswith(kept))
        self.assertEqual(ctx[len(kept)], " ")

    def test_no_room_left_says_the_context_was_left_out(self):
        with MorphEnv() as env:
            out = env.wording.fit("x" * 999, _context(500), cap=1000)
        self.assertTrue(out["context_cut"])
        self.assertIn("left out", out["context"])


class TestWhatMorphWritesIsCutBetweenWords(unittest.TestCase):

    def test_a_suggestions_change(self):
        change = _typed(3000)
        with MorphEnv() as env:
            env.learning.add_suggestions([{"title": "Move the climate card", "change": change}], {})
            item = env.learning.all_items()[-1]
        self.assertTrue(item["change"].endswith("…"))
        kept = item["change"][:-1]
        self.assertTrue(change.startswith(kept))
        self.assertEqual(change[len(kept)], " ")

    def test_an_answers_request(self):
        request = _typed(3000)
        with MorphEnv() as env:
            q = env.tell.clean_question({"text": "Which way?", "options": [
                {"label": "This", "request": request}, {"label": "That", "request": "Use Morph's own."}]})
        got = q["options"][0]["request"]
        self.assertTrue(got.endswith("…"))
        self.assertEqual(request[len(got) - 1], " ")


if __name__ == "__main__":
    unittest.main()
