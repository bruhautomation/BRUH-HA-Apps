#!/usr/bin/env python3
"""What the Claude director is told, and the schema its answer is held to.

Every assertion here is about the prompt the real builders produce or the
schema the real task carries — not a copy of either kept in the test, which
would only ever agree with itself.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
PANEL_DIR = os.path.join(BASE_DIR, "bright", "panel")
if PANEL_DIR not in sys.path:
    sys.path.append(PANEL_DIR)

from director import choreographer, claude_director, compiler  # noqa: E402
from director import effects as fx  # noqa: E402
from stores import effect_presets  # noqa: E402
from test_bright_claude_director import ClaudeDirectorCase, _FakeBrain  # noqa: E402
from test_bright_director import FIXTURES, analysis_fixture  # noqa: E402


# ---------------------------------------------------------------------------
# A JSON Schema check for the keywords these schemas use. jsonschema is not
# a test dependency of this repository, so the subset is checked here, and
# where the library happens to be installed it checks the same answers too.
# ---------------------------------------------------------------------------
_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool,
          "integer": int, "number": (int, float)}


def _is(value, kind: str) -> bool:
    if kind in ("integer", "number") and isinstance(value, bool):
        return False
    return isinstance(value, _TYPES[kind])


def problems(schema: dict, value, where: str = "$") -> list[str]:
    out: list[str] = []
    kind = schema.get("type")
    if kind is not None:
        kinds = kind if isinstance(kind, list) else [kind]
        if not any(_is(value, k) for k in kinds):
            return [f"{where}: not {kind}"]
    if "enum" in schema and value not in schema["enum"]:
        out.append(f"{where}: {value!r} not in enum")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            out.append(f"{where}: below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            out.append(f"{where}: above maximum")
    if isinstance(value, str) and len(value) < schema.get("minLength", 0):
        out.append(f"{where}: too short")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            out.append(f"{where}: too few items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            out.append(f"{where}: too many items")
        for index, item in enumerate(value):
            out += problems(schema.get("items", {}), item, f"{where}[{index}]")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                out.append(f"{where}: missing {key}")
        extra = schema.get("additionalProperties", True)
        for key, item in value.items():
            if key in props:
                out += problems(props[key], item, f"{where}.{key}")
            elif extra is False:
                out.append(f"{where}: unexpected {key}")
            elif isinstance(extra, dict):
                out += problems(extra, item, f"{where}.{key}")
    if "anyOf" in schema and not any(
            not problems(branch, value, where) for branch in schema["anyOf"]):
        out.append(f"{where}: matches no anyOf branch")
    return out


def _library_check(schema, value) -> bool | None:
    try:
        import jsonschema
    except ImportError:
        return None
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema).is_valid(value)


def flat(text: str) -> str:
    """A prompt with its line wrapping undone, so a phrase is found
    whichever line it was wrapped across."""
    return " ".join(text.split())


def _answerable(script: dict) -> dict:
    """A director's script as the model would answer it: without the fields
    BRight stamps on afterwards and the version 1 lists it no longer
    writes."""
    return json.loads(json.dumps(
        {k: v for k, v in script.items()
         if k in ("version", "scenes", "moments")}))


class TestTheBriefReadsInOneVoice(unittest.TestCase):
    def setUp(self):
        self.analysis = analysis_fixture()
        self.brief = flat(claude_director.digest(
            self.analysis, FIXTURES, vibe="slow and moody, no strobes"))

    def test_the_vibe_comes_first_and_says_what_it_outranks(self):
        vibe_at = self.brief.index("slow and moody, no strobes")
        self.assertLess(vibe_at, self.brief.index("HOW THE SONG IS LABELLED"))
        self.assertLess(vibe_at, self.brief.index("THE ANSWER:"))
        self.assertLess(vibe_at, self.brief.index("BUILD THE SHOW OUT OF"))
        self.assertTrue(self.brief.startswith("You are the lighting director"))
        self.assertIn("outranks the default energy curve and the house "
                      "principles", self.brief)

    def test_no_vibe_is_no_brief_line(self):
        brief = claude_director.digest(self.analysis, FIXTURES)
        self.assertNotIn("THIS SHOW'S BRIEF", brief)

    def test_every_section_kind_the_analyzer_writes_is_explained(self):
        """The brief said chorus and verse; the analysis says peak and
        quiet. Each kind is named, with the song part it stands for."""
        for kind in ("intro", "quiet", "mid", "peak", "outro"):
            with self.subTest(kind=kind):
                self.assertIn(f"`{kind}`", self.brief)
        self.assertIn("`peak` is chorus, hook and drop territory", self.brief)
        self.assertIn("energy", self.brief)
        self.assertIn("0 to 1", self.brief)

    def test_the_contradictions_are_gone(self):
        for stale in ("soft pulse underneath",
                      "one intentional motif per scene",
                      "lyric_moment",
                      "the host watched it run",
                      "a chorus should look different from its verse"):
            with self.subTest(stale=stale):
                self.assertNotIn(stale, self.brief)
        self.assertIn("a soft `hit` underneath", self.brief)
        self.assertIn("One idea per layer", self.brief)

    def test_it_says_how_much_to_write(self):
        self.assertIn("one scene per section", self.brief)
        self.assertIn("2 to 4 effects per scene", self.brief)
        self.assertIn("4 to 8 moments", self.brief)

    def test_coverage_and_names_are_stated(self):
        self.assertIn("no gaps and no overlaps", self.brief)
        self.assertIn("what the host sees on every cue", self.brief)

    def test_snap_is_documented_where_the_shape_is(self):
        contract = flat(claude_director.schema_contract())
        self.assertIn('"snap": "beat"', contract)

    def test_the_budget_and_the_layering_rule_are_said_once(self):
        self.assertEqual(1, self.brief.count("THE ONE HARD LIMIT"))
        self.assertEqual(1, self.brief.count(claude_director._routine_names()))
        self.assertEqual(1, self.brief.count("A bulb runs exactly one of them"))
        self.assertIn(str(int(compiler.MAX_RATE_HZ)), self.brief)

    def test_one_effect_shape_everywhere(self):
        """`select` with `exclude`, `order` with `listed`: the show contract
        and the one-effect contract describe the same object, word for
        word, because they were two shapes and one of them was short."""
        shape = claude_director._effect_shape()
        self.assertIn('"exclude"', shape)
        self.assertIn("listed", shape)
        for order in fx.ORDERS:
            self.assertIn(order, shape)
        self.assertIn(shape, claude_director.schema_contract())
        self.assertIn(shape, claude_director._effect_prompt("a chase",
                                                            FIXTURES))
        self.assertIn(shape, claude_director._invent_prompt(FIXTURES, 2))


class TestTheRevisionKnowsTheShow(ClaudeDirectorCase):
    def _revise(self, vibe=None):
        analysis = analysis_fixture()
        analysis["lyrics"] = {"synced": True, "lines": [
            {"t": 12.0, "text": "here comes the hook"}]}
        current = {"version": 2, "scenes": [{
            "start": 0.0, "end": 180.0, "mood": "calm",
            "palette": [[30, 0.5], [200, 0.6]], "brightness": 0.5,
            "effects": [{"type": "chase", "name": "run"}]}], "moments": []}
        brain = _FakeBrain(claude_director.TASKS_DIR,
                           claude_director.RESULTS_DIR,
                           lambda task: {"id": task["id"],
                                         "status": "completed",
                                         "result": json.dumps(current)})
        brain.start()
        claude_director.revise_script(current, "more movement", analysis,
                                      FIXTURES, timeout_s=5, vibe=vibe)
        brain.join()
        return brain.seen_prompt, brain.seen_task

    def test_the_vibe_and_the_lyrics_ride_the_revision(self):
        prompt, _ = self._revise(vibe="keep it gentle")
        prompt = flat(prompt)
        self.assertIn("keep it gentle", prompt)
        self.assertLess(prompt.index("keep it gentle"),
                        prompt.index("THE ANSWER:"))
        self.assertIn("here comes the hook", prompt)
        self.assertNotIn("watched", prompt)

    def test_the_catalog_is_full_only_for_the_types_in_use(self):
        prompt, _ = self._revise()
        chase = fx.CATALOG["chase"]["blurb"]
        strobe = fx.CATALOG["strobe"]["blurb"]
        self.assertIn(chase, prompt, "a type the script uses is in full")
        self.assertNotIn(strobe, prompt, "an unused type is one line")
        self.assertIn("  strobe [light]: " + ", ".join(
            fx.CATALOG["strobe"]["params"]), prompt)
        self.assertLess(len(prompt), len(claude_director.digest(
            analysis_fixture(), FIXTURES)) + 2000)

    def test_the_revision_asks_for_the_same_schema(self):
        _, task = self._revise()
        self.assertEqual(claude_director.script_schema(), task["schema"])

    def test_the_vibe_is_carried_from_the_report_into_the_revision(self):
        from director import build

        analysis = analysis_fixture()
        current = choreographer.write_script(analysis, FIXTURES)
        seen = {}

        def reviser(script, feedback, ana, fixtures, vibe=None):
            seen["vibe"] = vibe
            return dict(current)

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(build.library, "load_analysis",
                                  return_value=analysis), \
                mock.patch.object(build, "fixtures_for_show",
                                  return_value=FIXTURES), \
                mock.patch.object(build.library, "script_path",
                                  return_value=Path(tmp) / "script.json"), \
                mock.patch.object(build, "load_report",
                                  return_value={"vibe": "late night"}), \
                mock.patch.object(build, "compile_and_save",
                                  return_value={"stats": {"cues": 1}}), \
                mock.patch.object(build, "save_report"):
            (Path(tmp) / "script.json").write_text(json.dumps(current))
            show = build.revise_show("ab" * 20, {}, 7, "warmer", reviser)
        self.assertEqual("late night", seen["vibe"])
        self.assertEqual("late night", show["director"]["vibe"])


class TestOneEffectPrompts(unittest.TestCase):
    def test_a_described_effect_gets_full_detail_for_what_it_names(self):
        prompt = claude_director._effect_prompt(
            "a slow chase across the lamps", FIXTURES)
        self.assertIn(fx.CATALOG["chase"]["blurb"], prompt)
        self.assertNotIn(fx.CATALOG["rainbow"]["blurb"], prompt)
        self.assertIn("  rainbow [light]: ", prompt)

    def test_variety_is_only_asked_of_two_or_more(self):
        one = flat(claude_director._invent_prompt(FIXTURES, 1))
        three = flat(claude_director._invent_prompt(FIXTURES, 3))
        self.assertNotIn("at least one should be quiet enough", one)
        self.assertIn("Propose one effect", one)
        self.assertIn("at least one should be quiet enough", three)
        self.assertIn("3 effects", three)


class TestTheSchemaIsWhatTheValidatorAccepts(unittest.TestCase):
    def test_the_automatic_directors_script_fits_the_schema(self):
        script = _answerable(choreographer.write_script(analysis_fixture(),
                                                        FIXTURES))
        script["version"] = 2
        self.assertEqual([], choreographer.validate_script(script))
        self.assertEqual([], problems(claude_director.script_schema(), script))
        self.assertIn(_library_check(claude_director.script_schema(), script),
                      (None, True))

    def test_the_worked_example_fits_the_schema(self):
        brief = claude_director.digest(analysis_fixture(), FIXTURES)
        block = brief[brief.index("ONE SCENE, WRITTEN WELL"):]
        opening = block.index("{")
        depth = 0
        for index in range(opening, len(block)):
            depth += {"{": 1, "}": -1}.get(block[index], 0)
            if depth == 0:
                scene = json.loads(block[opening:index + 1])
                break
        script = {"version": 2, "scenes": [scene], "moments": []}
        self.assertEqual([], problems(claude_director.script_schema(), script))

    def test_the_schema_and_the_validator_refuse_the_same_mistakes(self):
        good = {"version": 2, "scenes": [{
            "start": 0, "end": 30, "mood": "calm",
            "palette": [[30, 0.5]], "brightness": 0.5,
            "effects": [{"type": "wash"}]}],
            "moments": [{"t": 4.0, "snap": "beat",
                         "effect": {"type": "stab"}}]}
        self.assertEqual([], choreographer.validate_script(good))
        self.assertEqual([], problems(claude_director.script_schema(), good))

        def broken(change):
            script = json.loads(json.dumps(good))
            change(script)
            return script

        mistakes = {
            "unknown type": lambda s: s["scenes"][0]["effects"][0].update(
                type="disco_inferno"),
            "brightness past 1": lambda s: s["scenes"][0].update(
                brightness=1.5),
            "palette of hues": lambda s: s["scenes"][0].update(
                palette=[30, 200]),
            "no scenes": lambda s: s.update(scenes=[]),
            "scene with no end": lambda s: s["scenes"][0].pop("end"),
            "moment with no time": lambda s: s["moments"][0].pop("t"),
        }
        for name, change in mistakes.items():
            with self.subTest(mistake=name):
                script = broken(change)
                self.assertTrue(choreographer.validate_script(script))
                self.assertTrue(problems(claude_director.script_schema(),
                                         script))

    def test_the_vocabularies_are_the_catalogs(self):
        effect = claude_director.effect_schema()["properties"]
        self.assertEqual(list(fx.CATALOG), effect["type"]["enum"])
        self.assertEqual(list(fx.ORDERS), effect["order"]["enum"])
        self.assertEqual(list(fx.ALIGNMENTS), effect["align"]["enum"])

    def test_a_saved_effect_by_name_fits(self):
        script = {"version": 2, "scenes": [{
            "start": 0, "end": 30, "palette": [[30, 0.5]], "brightness": 0.5,
            "effects": [{"use": "kitchen chase",
                         "params": {"step_beats": 1}}]}]}
        self.assertEqual([], problems(claude_director.script_schema(), script))

    def test_an_invented_idea_carries_its_why(self):
        answer = {"effects": [{"type": "chase", "why": "the lamps answer"}]}
        self.assertEqual([], problems(claude_director.invent_schema(), answer))
        self.assertTrue(problems(claude_director.invent_schema(),
                                 {"effects": [{"type": "chase", "x": 1}]}))


class TestTheValidatedAnswerIsTheOneRead(ClaudeDirectorCase):
    def test_the_task_carries_the_schema_and_data_wins_over_text(self):
        analysis = analysis_fixture()
        script = _answerable(choreographer.write_script(analysis, FIXTURES))
        brain = _FakeBrain(claude_director.TASKS_DIR,
                           claude_director.RESULTS_DIR,
                           lambda task: {"id": task["id"],
                                         "status": "completed",
                                         "result": "Here is the show.",
                                         "data": script})
        brain.start()
        written = claude_director.write_script(analysis, FIXTURES, timeout_s=5)
        brain.join()
        self.assertEqual(claude_director.script_schema(),
                         brain.seen_task["schema"])
        self.assertEqual("read_only", brain.seen_task["tools"])
        self.assertEqual(script["scenes"], written["scenes"])
        self.assertEqual([], choreographer.validate_script(written))

    def test_an_effect_task_carries_the_effect_schema(self):
        brain = _FakeBrain(claude_director.TASKS_DIR,
                           claude_director.RESULTS_DIR,
                           lambda task: {"id": task["id"],
                                         "status": "completed", "result": "",
                                         "data": {"type": "breathe"}})
        brain.start()
        effect = claude_director.write_effect("a slow breathe", FIXTURES,
                                              timeout_s=5)
        brain.join()
        self.assertEqual("breathe", effect["type"])
        self.assertEqual(claude_director.effect_schema(root=True),
                         brain.seen_task["schema"])

    def test_a_saved_effect_named_by_the_director_is_expanded_not_refused(self):
        """`{"use": ...}` reached the validator unexpanded, which reads an
        effect by its type — so every show that took the brief's invitation
        to reuse the library fell back to the algorithmic director."""
        analysis = analysis_fixture()
        script = _answerable(choreographer.write_script(analysis, FIXTURES))
        script["scenes"][0]["effects"].append(
            {"use": "lamp chase", "params": {"step_beats": 1}})
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(effect_presets, "PRESETS_FILE",
                                  Path(tmp) / "presets.json"):
            effect_presets.save("lamp chase", {
                "type": "chase", "select": {"roles": ["lamp"]},
                "params": {"step_beats": 0.5, "bounce": True}})
            brain = _FakeBrain(claude_director.TASKS_DIR,
                               claude_director.RESULTS_DIR,
                               lambda task: {"id": task["id"],
                                             "status": "completed",
                                             "result": "", "data": script})
            brain.start()
            written = claude_director.write_script(analysis, FIXTURES,
                                                   timeout_s=5)
            brain.join()
        self.assertEqual([], choreographer.validate_script(written))
        expanded = written["scenes"][0]["effects"][-1]
        self.assertEqual("chase", expanded["type"])
        self.assertEqual({"step_beats": 1, "bounce": True},
                         expanded["params"])


if __name__ == "__main__":
    unittest.main()
