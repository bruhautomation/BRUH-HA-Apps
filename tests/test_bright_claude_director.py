#!/usr/bin/env python3
"""The Claude director tier: the brAIn task round-trip, the JSON
extraction, and the guarantee that a bad answer lands on the algorithmic
floor (or fails honestly in strict mode)."""

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
PANEL_DIR = os.path.join(BASE_DIR, "bright", "panel")
if PANEL_DIR not in sys.path:
    sys.path.append(PANEL_DIR)

from director import claude_director, choreographer  # noqa: E402
from test_bright_director import FIXTURES, analysis_fixture  # noqa: E402


class _FakeBrain(threading.Thread):
    """Plays brAIn's automation listener: consume a task file, answer it."""

    def __init__(self, tasks_dir: Path, results_dir: Path, answer):
        super().__init__(daemon=True)
        self.tasks = tasks_dir
        self.results = results_dir
        self.answer = answer
        self.seen_prompt = None

    def run(self):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            for task_file in self.tasks.glob("*.json"):
                task = json.loads(task_file.read_text())
                task_file.unlink()
                self.seen_prompt = task["prompt"]
                self.results.mkdir(parents=True, exist_ok=True)
                body = (self.answer(task) if callable(self.answer)
                        else self.answer)
                (self.results / f"{task['id']}.json").write_text(
                    json.dumps(body))
                return
            time.sleep(0.02)


class ClaudeDirectorCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self._dirs = (claude_director.TASKS_DIR, claude_director.RESULTS_DIR,
                      claude_director.POLL_S)
        claude_director.TASKS_DIR = base / "tasks"
        claude_director.RESULTS_DIR = base / "task_results"
        claude_director.POLL_S = 0.02
        claude_director.TASKS_DIR.mkdir(parents=True)

    def tearDown(self):
        (claude_director.TASKS_DIR, claude_director.RESULTS_DIR,
         claude_director.POLL_S) = self._dirs
        self.tmp.cleanup()


class TestRoundTrip(ClaudeDirectorCase):
    def test_a_good_answer_becomes_a_valid_script(self):
        analysis = analysis_fixture()
        script_body = choreographer.write_script(analysis, FIXTURES)
        answer = ("Here is your show!\n```json\n"
                  + json.dumps(script_body) + "\n```")
        brain = _FakeBrain(claude_director.TASKS_DIR,
                           claude_director.RESULTS_DIR,
                           lambda task: {"id": task["id"], "status": "completed",
                                         "result": answer})
        brain.start()
        script = claude_director.write_script(analysis, FIXTURES, timeout_s=5)
        brain.join()
        self.assertEqual("claude", script["tier"])
        self.assertEqual(analysis["hash"], script["track_hash"])
        self.assertEqual([], choreographer.validate_script(script))
        # The digest carried what a director needs to know.
        self.assertIn("SECTIONS", brain.seen_prompt)
        self.assertIn("DROPS", brain.seen_prompt)
        self.assertIn("lamp (2)", brain.seen_prompt)
        self.assertIn("laser (1)", brain.seen_prompt)
        # And the part that used to be missing: a director cannot design for
        # a room it cannot see. Every light by id and by name, the zone it
        # is in, and the orders it can travel in.
        self.assertIn("lifx-d073d5000001", brain.seen_prompt)
        self.assertIn("Left lamp", brain.seen_prompt)
        self.assertIn("living", brain.seen_prompt)
        self.assertIn('order:"x"', brain.seen_prompt)
        self.assertIn("no prose", brain.seen_prompt)

    def test_a_failed_task_raises(self):
        brain = _FakeBrain(claude_director.TASKS_DIR,
                           claude_director.RESULTS_DIR,
                           lambda task: {"id": task["id"], "status": "error",
                                         "result": "not authenticated"})
        brain.start()
        with self.assertRaises(RuntimeError):
            claude_director.write_script(analysis_fixture(), FIXTURES,
                                         timeout_s=5)
        brain.join()

    def test_no_answer_times_out_and_cleans_up(self):
        with self.assertRaises(RuntimeError):
            claude_director.write_script(analysis_fixture(), FIXTURES,
                                         timeout_s=0.2)
        self.assertEqual([], list(claude_director.TASKS_DIR.glob("*.json")),
                         "a stale ask must not linger for brAIn to find later")

    def test_availability_is_the_tasks_dir(self):
        self.assertTrue(claude_director.available())
        claude_director.TASKS_DIR = Path(self.tmp.name) / "nonexistent"
        self.assertFalse(claude_director.available())


class TestExtraction(unittest.TestCase):
    def test_json_amid_prose_and_fences(self):
        script = {"version": 1, "scenes": []}
        for wrapper in (
            json.dumps(script),
            "```json\n" + json.dumps(script) + "\n```",
            "Sure! Here's the show:\n" + json.dumps(script) + "\nEnjoy!",
        ):
            with self.subTest(wrapper=wrapper[:20]):
                self.assertEqual(script,
                                 claude_director._extract_json(wrapper))

    def test_no_json_is_an_error(self):
        with self.assertRaises(ValueError):
            claude_director._extract_json("a poem about lights")


class TestLyricsInDigest(unittest.TestCase):
    def test_synced_lyrics_ride_along_capped(self):
        analysis = analysis_fixture()
        analysis["lyrics"] = {
            "synced": True,
            "lines": [{"t": float(i), "text": f"line {i}"}
                      for i in range(100)],
        }
        digest = claude_director._digest(analysis, FIXTURES)
        self.assertIn("SYNCED LYRICS", digest)
        self.assertIn("[0.0] line 0", digest)
        self.assertNotIn("line 99", digest)
        self.assertIn("40 more lines", digest)

    def test_instrumentals_carry_no_lyrics_block(self):
        digest = claude_director._digest(analysis_fixture(), FIXTURES)
        self.assertNotIn("SYNCED LYRICS", digest)


if __name__ == "__main__":
    unittest.main()

class TestOneEffectFromASentence(ClaudeDirectorCase):
    """A show is four minutes of decisions; an effect is one idea, and
    people have ideas in sentences."""

    def test_a_described_effect_comes_back_validated(self):
        effect = {"type": "chase", "name": "window bounce",
                  "select": {"ids": ["lifx-d073d5000001",
                                     "lifx-d073d5000002"]},
                  "order": "listed",
                  "params": {"step_beats": 0.5, "bounce": True}}
        brain = _FakeBrain(claude_director.TASKS_DIR,
                           claude_director.RESULTS_DIR,
                           lambda task: {"id": task["id"],
                                         "status": "completed",
                                         "result": json.dumps(effect)})
        brain.start()
        try:
            written = claude_director.write_effect(
                "bounce between the two window lamps", FIXTURES, timeout_s=10)
        finally:
            brain.join(timeout=5)
        self.assertEqual("chase", written["type"])
        self.assertEqual(True, written["params"]["bounce"])
        # The room went with the question: an effect written for a room the
        # model cannot see is an effect about nothing.
        self.assertIn("lifx-d073d5000001", brain.seen_prompt)
        self.assertIn("Left lamp", brain.seen_prompt)
        self.assertIn("bounce between the two window lamps", brain.seen_prompt)

    def test_an_unusable_effect_is_refused_not_stored(self):
        """The validator is the same one a hand-typed effect goes through.
        A generated effect gets no privileges, and an unknown type is caught
        here rather than at compile time in the middle of an evening."""
        brain = _FakeBrain(claude_director.TASKS_DIR,
                           claude_director.RESULTS_DIR,
                           lambda task: {"id": task["id"],
                                         "status": "completed",
                                         "result": json.dumps(
                                             {"type": "disco_inferno"})})
        brain.start()
        try:
            with self.assertRaises(ValueError) as caught:
                claude_director.write_effect("go wild", FIXTURES, timeout_s=10)
        finally:
            brain.join(timeout=5)
        self.assertIn("disco_inferno", str(caught.exception))

    def test_an_empty_description_never_reaches_claude(self):
        with self.assertRaises(ValueError):
            claude_director.write_effect("   ", FIXTURES, timeout_s=10)

    def test_the_effect_prompt_carries_the_whole_catalog(self):
        """The types and their parameters are generated from the catalog,
        so an effect gaining a parameter cannot leave the prompt behind."""
        prompt = claude_director._effect_prompt("something", FIXTURES)
        for name in ("chase", "strobe", "breathe", "aux"):
            self.assertIn(name, prompt)
        self.assertIn("BEATS", prompt)

