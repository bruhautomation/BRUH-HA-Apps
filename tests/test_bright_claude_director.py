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



class TestTheAnswerIsParsedAsModelsActuallyWriteIt(unittest.TestCase):
    """`Expecting ',' delimiter: line 1 column 222` — the real one.

    It came out of a live install, twice, and every show it touched went
    quietly to the algorithmic floor: the log said a column number about a
    document that had already been thrown away, so the same failure was
    unreadable each time it happened.

    The cause is in the prompt. The schema contract annotates every field
    with a `//` note, so a model matching the shape it was shown writes
    those notes back — and a comment is a syntax error in a format that
    has none. The prompt says so explicitly now; this is the belt to that
    braces, because the next model to imitate an example is not a bug
    anybody gets to fix in advance.
    """

    def test_a_comment_after_a_value_is_the_reported_failure(self):
        """The exact shape, down to the error message."""
        annotated = ('{"version": 2, "scenes": [{"start": 0, "end": 30.5 '
                     '// the first verse\n, "mood": "calm"}]}')
        with self.assertRaises(ValueError) as caught:
            json.loads(annotated)
        self.assertIn("Expecting ',' delimiter", str(caught.exception))
        self.assertEqual(
            {"version": 2,
             "scenes": [{"start": 0, "end": 30.5, "mood": "calm"}]},
            claude_director._extract_json(annotated))

    def test_block_comments_and_trailing_commas_go_too(self):
        self.assertEqual(
            {"a": [1, 2], "b": {"c": 3}},
            claude_director._extract_json(
                '{"a": [1, 2,], /* an aside */ "b": {"c": 3,},}'))

    def test_punctuation_inside_a_string_is_not_punctuation(self):
        """`pop // rock` is a mood somebody could name, and a URL in a
        label is two slashes that have to survive."""
        self.assertEqual(
            {"mood": "pop // rock", "note": "see http://x/y", "n": 1},
            claude_director._extract_json(
                '{"mood": "pop // rock", "note": "see http://x/y", "n": 1}'))

    def test_an_escaped_quote_cannot_end_a_string_early(self):
        """Otherwise the rest of the answer stops being a string and its
        contents start being read as syntax."""
        self.assertEqual(
            {"name": 'a " b // not a comment', "n": 1},
            claude_director._extract_json(
                '{"name": "a \\" b // not a comment", "n": 1}'))

    def test_a_failure_quotes_what_broke(self):
        """A column number is not a diagnosis when the document is gone."""
        with self.assertRaises(ValueError) as caught:
            claude_director._extract_json(
                '{"scenes": [{"start": 0, "end": nonsense-here}]}')
        message = str(caught.exception)
        self.assertIn("near:", message)
        self.assertIn("nonsense", message,
                      "the log has to carry what Claude actually wrote")

    def test_prose_around_the_object_is_still_tolerated(self):
        self.assertEqual(
            {"a": 1},
            claude_director._extract_json(
                'Sure! Here is the show:\n```json\n{"a": 1}\n```\nEnjoy.'))

    def test_the_contract_says_not_to_write_comments(self):
        """The root cause, guarded: the example is annotated, so the
        instruction that the annotation is not part of the answer has to
        travel with it."""
        contract = claude_director._SCHEMA_CONTRACT % "  wash [lifx] — a look"
        self.assertIn("//", contract, "the example is still annotated")
        self.assertIn("strict JSON", contract)
        self.assertIn("trailing comma", contract)


class TestInventingEffectsFromTheRoom(ClaudeDirectorCase):
    """Effects with nothing typed in.

    The other half of `write_effect`, and the half that matters most to
    somebody who has just drawn their first light map: describing what you
    want assumes you already know what is possible in your own room, which
    is exactly what a new map does not tell you. "What would look good in
    here" is a question about a floor plan — and the floor plan is the one
    thing BRight has.
    """

    def _answer(self, payload):
        brain = _FakeBrain(claude_director.TASKS_DIR,
                           claude_director.RESULTS_DIR,
                           lambda task: {"id": task["id"],
                                         "status": "completed",
                                         "result": json.dumps(payload)})
        brain.start()
        try:
            return claude_director.invent_effects(FIXTURES, 3, timeout_s=10), \
                brain.seen_prompt
        finally:
            brain.join(timeout=5)

    def test_ideas_come_back_validated_and_carry_their_reason(self):
        ideas, prompt = self._answer({"effects": [
            {"type": "theater", "name": "window answer",
             "select": {"ids": ["lifx-d073d5000001", "lifx-d073d5000002"]},
             "params": {"groups": 2},
             "why": "the two window lamps face each other across the bay"},
            {"type": "breathe", "name": "corner calm",
             "select": {"roles": ["candle"]}, "params": {"depth": 0.12},
             "why": "the candles stay soft while everything else moves"},
        ]})
        self.assertEqual(2, len(ideas))
        self.assertEqual("theater", ideas[0]["type"])
        self.assertIn("window lamps", ideas[0]["why"])
        # The room went with the question, or the ideas are about nothing.
        self.assertIn("lifx-d073d5000001", prompt)
        self.assertIn("Left lamp", prompt)

    def test_one_unusable_idea_does_not_sink_the_batch(self):
        """A model asked for six things will occasionally get one wrong.
        Throwing away five good ideas to punish it would make the feature
        useless at the moment it is most useful."""
        ideas, _ = self._answer({"effects": [
            {"type": "not_a_real_effect", "name": "nonsense", "params": {}},
            {"type": "wash", "name": "ground", "params": {"brightness": 0.5},
             "why": "a still ground for the rest to move against"},
        ]})
        self.assertEqual(1, len(ideas))
        self.assertEqual("wash", ideas[0]["type"])

    def test_ideas_that_are_all_unusable_are_reported(self):
        with self.assertRaises(ValueError) as caught:
            self._answer({"effects": [{"type": "nope", "params": {}}]})
        self.assertIn("cannot use", str(caught.exception))

    def test_an_answer_with_no_effects_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            self._answer({"effects": []})
        self.assertIn("no effects", str(caught.exception))

    def test_why_never_reaches_the_compiler(self):
        """`why` is ours, not the catalog's. It is lifted out before the
        validator sees the effect and put back after, so a generated effect
        cannot smuggle a field the compiler will later trip over."""
        ideas, _ = self._answer({"effects": [
            {"type": "wash", "name": "g", "params": {}, "why": "because",
             "smuggled": {"anything": True}},
        ]})
        self.assertNotIn("smuggled", ideas[0])
        self.assertEqual("because", ideas[0]["why"])

    def test_a_room_with_no_lights_is_refused_before_claude_is_asked(self):
        with self.assertRaises(ValueError) as caught:
            claude_director.invent_effects([], 3, timeout_s=10)
        self.assertIn("Light Map", str(caught.exception))

    def test_the_brief_asks_for_variety_and_for_this_room(self):
        """The two failure modes of asking a model for a list: six
        variations on one idea, and ideas that could have been written
        without ever seeing the room."""
        _, prompt = self._answer({"effects": [
            {"type": "wash", "name": "g", "params": {}, "why": "w"}]})
        self.assertIn("DIFFERENT from each other", prompt)
        self.assertIn("Read the map", prompt)


class TestTheDirectorRunsOnTheAskedModel(ClaudeDirectorCase):
    """The host asked for Opus by name; the task file is where that
    request either rides to brAIn or silently doesn't."""

    def _task_written(self):
        analysis = analysis_fixture()
        script = choreographer.write_script(analysis, FIXTURES)
        seen = {}

        def answer(task):
            seen.update(task)
            return {"id": task["id"], "status": "completed",
                    "result": json.dumps(script)}

        brain = _FakeBrain(claude_director.TASKS_DIR,
                           claude_director.RESULTS_DIR, answer)
        brain.start()
        claude_director.write_script(analysis, FIXTURES, timeout_s=5)
        brain.join()
        return seen

    def test_the_task_asks_for_opus_by_default(self):
        old = os.environ.pop("BRIGHT_DIRECTOR_MODEL", None)
        try:
            self.assertEqual("opus", self._task_written().get("model"))
        finally:
            if old is not None:
                os.environ["BRIGHT_DIRECTOR_MODEL"] = old

    def test_the_option_overrides_the_default(self):
        old = os.environ.get("BRIGHT_DIRECTOR_MODEL")
        os.environ["BRIGHT_DIRECTOR_MODEL"] = "sonnet"
        try:
            self.assertEqual("sonnet", self._task_written().get("model"))
        finally:
            if old is None:
                os.environ.pop("BRIGHT_DIRECTOR_MODEL", None)
            else:
                os.environ["BRIGHT_DIRECTOR_MODEL"] = old


class TestRevision(ClaudeDirectorCase):
    """Feedback on a show somebody watched, applied by the director."""

    def _revise(self, feedback, answer_script=None):
        analysis = analysis_fixture()
        current = choreographer.write_script(analysis, FIXTURES)
        revised_body = answer_script or dict(current)
        brain = _FakeBrain(claude_director.TASKS_DIR,
                           claude_director.RESULTS_DIR,
                           lambda task: {"id": task["id"],
                                         "status": "completed",
                                         "result": json.dumps(revised_body)})
        brain.start()
        revised = claude_director.revise_script(current, feedback, analysis,
                                                FIXTURES, timeout_s=5)
        brain.join()
        return revised, brain.seen_prompt, current

    def test_the_notes_and_the_current_script_ride_the_prompt(self):
        _, prompt, current = self._revise("the chorus needs more movement")
        self.assertIn("THE HOST'S NOTES", prompt)
        self.assertIn("the chorus needs more movement", prompt)
        self.assertIn("THE CURRENT SCRIPT", prompt)
        # The show itself is in there — a scene the notes are about has to
        # be visible to the director revising it.
        self.assertIn('"scenes"', prompt)
        # And the room and the song, same as a first draft.
        self.assertIn("THE ROOM", prompt)
        self.assertIn("SECTIONS", prompt)

    def test_the_answer_is_stamped_like_any_claude_script(self):
        revised, _, _ = self._revise("more candles")
        self.assertEqual("claude", revised["tier"])
        self.assertEqual(analysis_fixture()["hash"], revised["track_hash"])

    def test_empty_feedback_never_reaches_claude(self):
        with self.assertRaises(ValueError):
            claude_director.revise_script({}, "   ", analysis_fixture(),
                                          FIXTURES, timeout_s=5)

    def test_a_failed_revision_leaves_the_show_on_disk_alone(self):
        """revise_show writes NOTHING unless the revised script validates
        and compiles — a revision must never cost the show it criticized."""
        from unittest import mock

        from director import build

        analysis = analysis_fixture()
        current = choreographer.write_script(analysis, FIXTURES)

        def broken_reviser(script, feedback, ana, fixtures):
            return {"scenes": "not even a list"}

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(build.library, "load_analysis",
                                  return_value=analysis), \
                mock.patch.object(build, "fixtures_for_show",
                                  return_value=FIXTURES), \
                mock.patch.object(build.library, "script_path",
                                  return_value=Path(tmp) / "script.json"), \
                mock.patch.object(build, "compile_and_save") as compiled:
            (Path(tmp) / "script.json").write_text(json.dumps(current))
            with self.assertRaises(ValueError):
                build.revise_show("ab" * 20, {}, 7, "more!", broken_reviser)
            compiled.assert_not_called()

    def test_a_good_revision_compiles_and_records_its_report(self):
        from unittest import mock

        from director import build

        analysis = analysis_fixture()
        current = choreographer.write_script(analysis, FIXTURES)

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(build.library, "load_analysis",
                                  return_value=analysis), \
                mock.patch.object(build, "fixtures_for_show",
                                  return_value=FIXTURES), \
                mock.patch.object(build.library, "script_path",
                                  return_value=Path(tmp) / "script.json"), \
                mock.patch.object(build, "compile_and_save",
                                  return_value={"stats": {"cues": 1}}), \
                mock.patch.object(build, "save_report") as reported:
            (Path(tmp) / "script.json").write_text(json.dumps(current))
            show = build.revise_show("ab" * 20, {}, 7, "warmer verses",
                                     lambda s, f, a, x: dict(current))
            self.assertEqual("revise", show["director"]["asked"])
            self.assertEqual("warmer verses", show["director"]["feedback"])
            reported.assert_called_once()

    def test_a_missing_show_is_a_clear_refusal(self):
        from unittest import mock

        from director import build

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(build.library, "load_analysis",
                                  return_value=analysis_fixture()), \
                mock.patch.object(build, "fixtures_for_show",
                                  return_value=FIXTURES), \
                mock.patch.object(build.library, "script_path",
                                  return_value=Path(tmp) / "missing.json"):
            with self.assertRaises(ValueError) as caught:
                build.revise_show("ab" * 20, {}, 7, "notes",
                                  lambda *a: {})
            self.assertIn("compile one first", str(caught.exception))


class TestNobodyListeningIsItsOwnFailure(ClaudeDirectorCase):
    """`available()` only says the tasks FOLDER exists, and that folder
    outlives the listener that made it. A brAIn whose Automation
    integration is off looks exactly like a working one — until the wait
    expires, which used to cost ten minutes and then a message blaming a
    timeout. The listener claims a task by renaming it, so an un-renamed
    file is a definitive answer.
    """

    def setUp(self):
        super().setUp()
        self._grace = claude_director.CLAIM_GRACE_S
        claude_director.CLAIM_GRACE_S = 0.2

    def tearDown(self):
        claude_director.CLAIM_GRACE_S = self._grace
        super().tearDown()

    def test_an_unclaimed_task_says_nothing_is_reading_the_folder(self):
        with self.assertRaises(RuntimeError) as caught:
            claude_director._run_task("hello", timeout_s=30)
        message = str(caught.exception)
        self.assertIn("never picked this up", message)
        self.assertIn("Automation", message,
                      "the message has to name the switch to turn on")

    def test_it_fails_in_the_grace_window_not_the_timeout(self):
        """The whole point: a dead listener is answered in seconds, not
        after the director's ten-minute budget."""
        elapsed = []
        started = time.monotonic()
        with self.assertRaises(RuntimeError):
            claude_director._run_task("hello", timeout_s=600)
        elapsed.append(time.monotonic() - started)
        self.assertLess(elapsed[0], 10,
                        f"waited {elapsed[0]:.1f}s for a dead listener")

    def test_an_unclaimed_task_is_not_left_behind(self):
        with self.assertRaises(RuntimeError):
            claude_director._run_task("hello", timeout_s=30)
        self.assertEqual([], list(claude_director.TASKS_DIR.glob("*.json")))

    def test_a_claimed_task_that_never_answers_blames_the_right_thing(self):
        """Claimed and silent is a different failure with a different
        remedy: brAIn has it, and brAIn's log is where the reason is."""
        def claim_it():
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                for task in claude_director.TASKS_DIR.glob("*.json"):
                    task.rename(task.with_suffix(".work.1"))
                    return
                time.sleep(0.01)

        claimer = threading.Thread(target=claim_it, daemon=True)
        claimer.start()
        with self.assertRaises(RuntimeError) as caught:
            claude_director._run_task("hello", timeout_s=1.5)
        claimer.join()
        message = str(caught.exception)
        self.assertIn("did not answer", message)
        self.assertNotIn("never picked this up", message)

    def test_a_fast_claim_is_never_mistaken_for_a_dead_listener(self):
        """The claim is checked before the grace expires, so a listener
        that takes most of the window is still a listener."""
        answer = {"scenes": [], "moments": []}

        brain = _FakeBrain(claude_director.TASKS_DIR,
                           claude_director.RESULTS_DIR,
                           lambda task: {"id": task["id"],
                                         "status": "completed",
                                         "result": json.dumps(answer)})
        brain.start()
        text = claude_director._run_task("hello", timeout_s=5)
        brain.join()
        self.assertIn("scenes", text)
