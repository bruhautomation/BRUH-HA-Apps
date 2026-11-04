"""The eval harness with no model: every grader against hand-written good
and bad outputs, every case against the schema, and the runner end to end
through a stand-in CLI.

This is the half of tests/evals/ that rides ordinary CI. A grader that
passes a bad output is a gate that opens by itself, so each one is shown
at least one output it must fail.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).resolve().parent
TESTS = HERE.parent
REPO = TESTS.parent
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from evals import jobs, run, schema  # noqa: E402
from evals import select as selector  # noqa: E402
from evals.graders import GRADERS, grade  # noqa: E402
from evals.graders import judge as judge_mod  # noqa: E402
from evals.graders.common import dated, matches, mentions, similar  # noqa: E402

FAKE = HERE / "fake_claude.py"
ALL = schema.load_cases()
BY_ID = {c["id"]: c for c in ALL}


def case(cid: str) -> dict:
    return BY_ID[cid]


def verdict(cid: str, output: dict) -> str:
    return grade(case(cid), output)["verdict"]


# ---------------------------------------------------------------- the cases

class TestTheCases(unittest.TestCase):
    def test_every_case_file_validates(self):
        problems = []
        for path in schema.case_files():
            problems += schema.validate(json.loads(path.read_text(encoding="utf-8")), path)
        self.assertEqual(problems, [])

    def test_every_regression_case_names_a_real_origin(self):
        for c in ALL:
            with self.subTest(c["id"]):
                self.assertTrue(c["origin"].strip())
                if c["kind"] == "regression":
                    self.assertNotEqual(c["origin"].strip(), schema.SYNTHETIC)

    def test_every_job_has_a_grader_and_cases_and_a_regression_suite(self):
        self.assertEqual(set(GRADERS), set(schema.JOBS))
        self.assertEqual(set(jobs.BUILDERS), set(schema.JOBS))
        for job in schema.JOBS:
            with self.subTest(job):
                mine = [c for c in ALL if c["job"] == job]
                self.assertTrue(mine)
                self.assertTrue(any(c["kind"] == "regression" for c in mine))

    def test_the_validator_refuses_what_it_should(self):
        good = {"id": "x", "job": "extractor", "kind": "capability", "input": {},
                "expect": {}, "origin": "synthetic"}
        self.assertEqual(schema.validate(good), [])
        bad = {
            "no origin": {**good, "origin": ""},
            "synthetic regression": {**good, "kind": "regression"},
            "unknown job": {**good, "job": "nope"},
            "unknown kind": {**good, "kind": "maybe"},
            "unknown key": {**good, "extra": 1},
            "input not object": {**good, "input": []},
            "bad trials": {**good, "trials": 0},
        }
        for why, c in bad.items():
            with self.subTest(why):
                self.assertTrue(schema.validate(c))
        missing = dict(good)
        del missing["expect"]
        self.assertTrue(schema.validate(missing))


# ------------------------------------------------------------- the selector

class TestTheSelector(unittest.TestCase):
    def test_the_workflow_paths_are_the_selectors(self):
        doc = yaml.safe_load((REPO / ".github" / "workflows" / "evals.yml")
                             .read_text(encoding="utf-8"))
        on = doc.get("on") or doc.get(True)
        self.assertEqual(on["pull_request"]["paths"], selector.workflow_paths())

    def test_every_named_builder_exists(self):
        for pattern in selector.PROMPT_FILES:
            if "*" not in pattern:
                with self.subTest(pattern):
                    self.assertTrue((REPO / pattern).exists(), pattern)

    def test_paths_map_to_jobs(self):
        self.assertEqual(selector.jobs_for("brain/panel/outcomes.py"),
                         ("reflect", "first_look"))
        self.assertTrue(selector.is_prompt_path("brain/panel/devloop/streams.py"))
        self.assertFalse(selector.is_prompt_path("brain/panel/server.py"))
        self.assertEqual(selector.selected_jobs(["tests/evals/run.py"], schema.JOBS),
                         list(schema.JOBS))
        self.assertEqual(selector.selected_jobs(
            ["tests/evals/cases/reflect/refl-hall-cat.json", "README.md"], schema.JOBS),
            ["reflect"])


# ----------------------------------------------------------------- matching

class TestMatching(unittest.TestCase):
    def test_words_not_substrings(self):
        self.assertTrue(mentions("The Beacon is on", "beacon"))
        self.assertFalse(mentions("it will do", "ill"))
        self.assertTrue(matches("garage freezer plug", {"all": ["freezer"], "any": ["plug"]}))
        self.assertFalse(matches("garage freezer", {"all": ["freezer"], "any": ["plug"]}))
        self.assertFalse(matches("anything", {}))
        self.assertTrue(similar("Move the Garden section to the top",
                                "Move Garden section to the top"))

    def test_dates_are_relative(self):
        import datetime
        today = datetime.date(2026, 11, 4)
        self.assertEqual(dated("(observed {days_ago:3})", today), "(observed 2026-11-01)")
        self.assertEqual(dated({"a": ["{days_ago:0}"]}, today), {"a": ["2026-11-04"]})


# ------------------------------------------------------------------ graders

class TestExtractorGrader(unittest.TestCase):
    def test_good_and_bad(self):
        good = {"facts": [{"fact": "The garage freezer is on switch.garage_plug; never turn "
                                   "that plug off", "kind": "fact", "subject": "switch.garage_plug"}]}
        self.assertEqual(verdict("ext-earlier-is-context-only", good), "pass")
        leaked = {"facts": good["facts"] + [{"fact": "The office lamp is the beacon",
                                             "kind": "fact", "subject": "light.office_lamp"}]}
        self.assertEqual(verdict("ext-earlier-is-context-only", leaked), "fail")
        self.assertEqual(verdict("ext-earlier-is-context-only", {"facts": []}), "fail")
        self.assertEqual(verdict("ext-earlier-is-context-only", {}), "fail")

    def test_from_tool_output_fails(self):
        bad = {"facts": [{"fact": "The boiler is a Worcester Greenstar 30i", "kind": "fact",
                          "subject": "house"},
                         {"fact": "Check the boiler filter monthly", "kind": "intent",
                          "subject": "house"}]}
        self.assertEqual(verdict("ext-tool-output-is-not-a-fact", bad), "fail")
        good = {"facts": [bad["facts"][1]]}
        self.assertEqual(verdict("ext-tool-output-is-not-a-fact", good), "pass")

    def test_kind_and_none(self):
        as_fact = {"facts": [{"fact": "The porch motion sensor is wired to the light circuit",
                              "kind": "fact", "subject": "binary_sensor.porch_motion"}]}
        self.assertEqual(verdict("ext-correction-is-a-correction", as_fact), "fail")
        as_fact["facts"][0]["kind"] = "correction"
        self.assertEqual(verdict("ext-correction-is-a-correction", as_fact), "pass")
        self.assertEqual(verdict("ext-ok-is-not-teaching", {"facts": []}), "pass")
        self.assertEqual(verdict("ext-ok-is-not-teaching",
                                 {"facts": [{"fact": "likes the porch light"}]}), "fail")
        four = {"facts": [{"fact": f"fact {i} about the beacon"} for i in range(4)]}
        self.assertEqual(verdict("ext-nickname", four), "fail")


class TestConsolidatorGrader(unittest.TestCase):
    def out(self, memory, rc=0, before="old", voice="- v"):
        return {"rc": rc, "memory": dated(memory), "voice": voice, "memory_before": before}

    def test_erasure_fails_and_a_merge_passes(self):
        c = case("cons-no-erasure")
        merged = c["input"]["memory"] + "- The utility room light is called 'the shed'\n"
        self.assertEqual(grade(c, self.out(merged))["verdict"], "pass")
        template = "# Home Memory\n\n## Preferences\n\n## Device notes\n"
        self.assertEqual(grade(c, self.out(template))["verdict"], "fail")
        refused = self.out(dated(c["input"]["memory"]), rc=1,
                           before=dated(c["input"]["memory"]))
        self.assertEqual(grade(c, refused)["verdict"], "fail")

    def test_verbatim_lines_and_newer_wins(self):
        c = case("cons-person-lines-verbatim")
        kept = c["input"]["memory"] + "- Guests sleep in the loft (observed {days_ago:0})\n"
        self.assertEqual(grade(c, self.out(kept))["verdict"], "pass")
        reworded = kept.replace("hallway lights off by midnight", "hall lights off at 12")
        self.assertEqual(grade(c, self.out(reworded))["verdict"], "fail")
        c = case("cons-correction-wins")
        fixed = c["input"]["memory"].replace(
            "The porch motion sensor is stuck on — fault",
            "The porch motion sensor is wired to the porch light circuit, so it reads on "
            "with the light")
        self.assertEqual(grade(c, self.out(fixed))["verdict"], "pass")
        self.assertEqual(grade(c, self.out(c["input"]["memory"]))["verdict"], "fail")

    def test_caps(self):
        c = case("cons-size-cap")
        self.assertEqual(grade(c, self.out("## Device notes\n- garage freezer\n"))["verdict"],
                         "pass")
        self.assertEqual(grade(c, self.out("- garage freezer " + "x" * 3000))["verdict"],
                         "fail")
        self.assertEqual(grade(c, self.out("- garage freezer", voice="v" * 3000))["verdict"],
                         "fail")
        self.assertEqual(grade(c, {"rc": 1})["verdict"], "fail")


class TestReflectGrader(unittest.TestCase):
    def out(self, cid, lessons):
        return {"candidates": jobs.reflect_candidates(case(cid)),
                "reply": {"lessons": lessons}}

    def test_the_code_half(self):
        self.assertEqual(jobs.reflect_candidates(case("refl-safety-never-quieter")),
                         jobs.reflect_candidates(case("refl-hall-cat")))
        for cid in ("refl-protected-never-quieter", "refl-safety-check-never-quieter",
                    "refl-person-never-a-scope"):
            with self.subTest(cid):
                self.assertEqual(jobs.reflect_candidates(case(cid)), [])
                self.assertEqual(verdict(cid, self.out(cid, [])), "pass")
        cheat = {"candidates": [{"scope": "entity", "subject": "binary_sensor.kitchen_leak",
                                 "direction": "quieter", "counts": "", "whys": [],
                                 "notes": []}],
                 "reply": {"lessons": []}}
        self.assertEqual(verdict("refl-safety-never-quieter", cheat), "fail")

    def test_the_model_half(self):
        cid = "refl-hall-cat"
        self.assertEqual(verdict(cid, self.out(cid, [{"id": 1, "lesson":
                                                      "Night motion on the landing is the cat"}])),
                         "pass")
        bad = {
            "counts": [{"id": 1, "lesson": "The cat, 4 of 4 times"}],
            "no such pattern": [{"id": 2, "lesson": "the cat"}],
            "says nothing of the cat": [{"id": 1, "lesson": "The hall sensor is sensitive"}],
            "unreadable": "nope",
        }
        for why, lessons in bad.items():
            with self.subTest(why):
                self.assertEqual(verdict(cid, self.out(cid, lessons)), "fail")
        cid = "refl-no-evidence-no-lesson"
        self.assertEqual(verdict(cid, self.out(cid, [{"id": 1, "lesson": ""}])), "pass")
        self.assertEqual(verdict(cid, self.out(cid, [{"id": 1, "lesson":
                                                      "The sensor is broken"}])), "fail")
        cid = "refl-louder-safety-not-dismissed"
        self.assertEqual(verdict(cid, self.out(cid, [{"id": 1, "lesson":
                                                      "Leaks under the sink here are real"}])),
                         "pass")
        self.assertEqual(verdict(cid, self.out(cid, [{"id": 1, "lesson":
                                                      "Basement leak alerts are harmless"}])),
                         "fail")


class TestFirstLookGrader(unittest.TestCase):
    @staticmethod
    def reply(*words):
        return {"reply": {"verdicts": [{"id": i, "verdict": w, "why": "x"}
                                       for i, w in enumerate(words, 1)]}}

    def test_good_and_bad(self):
        cid = "fl-rehearsal"
        self.assertEqual(verdict(cid, self.reply("watch", "watch", "act", "investigate",
                                                 "ignore")), "pass")
        self.assertEqual(verdict(cid, self.reply("ignore", "watch", "act", "investigate",
                                                 "ignore")), "fail")
        self.assertEqual(verdict(cid, {"reply": None}), "fail")
        cid = "fl-routine-noise"
        self.assertEqual(verdict(cid, self.reply("ignore", "ignore")), "pass")
        self.assertEqual(verdict(cid, self.reply("act", "ignore")), "fail")


class TestMorphGrader(unittest.TestCase):
    def test_lessons_survive(self):
        c = case("morph-household-lessons-kept")
        mine = [r for r in c["input"]["lessons"] if r["source"] == "you"]
        ok = {"reply": {"suggestions": [], "lessons": []}, "merged_lessons": mine}
        self.assertEqual(grade(c, ok)["verdict"], "pass")
        lost = {"reply": {"suggestions": [], "lessons": []}, "merged_lessons": mine[:1]}
        self.assertEqual(grade(c, lost)["verdict"], "fail")
        c = case("morph-tell-lessons-kept")
        reply = {"suggestions": [], "lessons": [{"text": "Keep the Kitchen section first"}]}
        self.assertEqual(grade(c, {"reply": reply})["verdict"], "fail")
        reply["lessons"].append({"text": "Show temperatures in Celsius with no decimals"})
        self.assertEqual(grade(c, {"reply": reply})["verdict"], "pass")
        self.assertEqual(grade(c, {"reply": "nope"})["verdict"], "fail")

    def test_declined_is_not_made_again(self):
        c = case("morph-declined-not-reworded")

        def out(title):
            return {"reply": {"suggestions": [{"title": title, "why": "w", "change": "c"}],
                              "lessons": []}}
        self.assertEqual(grade(c, out("Move Garden section to the top"))["verdict"], "fail")
        self.assertEqual(grade(c, out("Put the Garden section first in summer"))["verdict"],
                         "fail")
        self.assertEqual(grade(c, out("Add the porch light to Kitchen"))["verdict"], "pass")
        c = case("morph-dashboard-only")
        self.assertEqual(grade(c, out("Automate the porch light at sunset"))["verdict"], "fail")


class TestDevloopGrader(unittest.TestCase):
    @staticmethod
    def rows(*rows, **extra):
        full = [{"title": t, "what": w, "why": "evidence", "done_when": "checked",
                 "impact": "daily", **extra} for t, w in rows]
        return {"reply": {"rows": full}}

    def test_precision_against_labels(self):
        cid = "dl-vague-ideas-declined"
        self.assertEqual(verdict(cid, self.rows(("Weekly report: room heating share",
                                                 "Name the room that used the most heating"))),
                         "pass")
        self.assertEqual(verdict(cid, self.rows(("AI energy optimisation",
                                                 "Use machine learning to optimise energy"))),
                         "fail")
        self.assertEqual(verdict(cid, self.rows(("Brief: shorter", "The brief is long"))),
                         "unknown")
        self.assertEqual(verdict(cid, {"reply": {}}), "fail")
        missing = self.rows(("Weekly report: room heating", "Name the room by heating"))
        del missing["reply"]["rows"][0]["done_when"]
        self.assertEqual(verdict(cid, missing), "fail")

    def test_refiling_a_decline_fails(self):
        cid = "dl-yolo-self-edit-declined"
        self.assertEqual(verdict(cid, self.rows(("Self-edit: let brAIn change house.js",
                                                 "brAIn cannot edit its own files"))), "fail")
        cid = "dl-duplicate-not-refiled"
        self.assertEqual(verdict(cid, self.rows(("Findings: one leak shows twice",
                                                 "The same leak appears as two findings"))),
                         "fail")

    def test_empty_addon_and_still(self):
        self.assertEqual(verdict("dl-healthy-house-empty", {"reply": {"rows": []}}), "pass")
        self.assertEqual(verdict("dl-healthy-house-empty", self.rows(("x", "y"))), "fail")
        cid = "dl-look-routes-to-addon"
        self.assertEqual(verdict(cid, self.rows(("Blank screen on phones",
                                                 "GardenRX does not load"), addon="brAIn")),
                         "fail")
        cid = "dl-look-still-a-problem"
        self.assertEqual(verdict(cid, self.rows(("Settings", "Still a problem: crowded"))),
                         "unknown")
        self.assertEqual(verdict(cid, self.rows(("Settings", "It is crowded"))), "fail")


class TestAGraderNeverPassesByAccident(unittest.TestCase):
    def test_a_crash_or_nonsense_is_a_fail(self):
        for c in ALL:
            with self.subTest(c["id"]):
                self.assertIn(grade(c, None)["verdict"], ("fail",))


class TestTheJudge(unittest.TestCase):
    def test_pinned_and_unknown_is_kept(self):
        self.assertTrue(judge_mod.JUDGE_MODEL.startswith("claude-"))
        self.assertEqual(judge_mod.parse_judgement({"verdict": "maybe"})["verdict"], "unknown")
        self.assertEqual(judge_mod.parse_judgement("x")["verdict"], "unknown")
        self.assertEqual(judge_mod.parse_judgement({"verdict": "pass", "reason": "r"})
                         ["verdict"], "pass")

    def test_it_is_asked_only_with_a_rubric(self):
        asked = []

        def ask(prompt, system, model, schema=None):
            asked.append(model)
            return {"ok": True, "data": {"verdict": "fail", "reason": "no"}, "tokens": 5}
        got, cost = judge_mod.judge({"expect": {}}, {}, ask)
        self.assertEqual((got["verdict"], cost, asked), ("unknown", 0, []))
        got, cost = judge_mod.judge({"expect": {"judge": "ok?"}}, {}, ask)
        self.assertEqual((got["verdict"], cost, asked), ("fail", 5, [judge_mod.JUDGE_MODEL]))


# ------------------------------------------------------------------- runner

class TestTheArithmetic(unittest.TestCase):
    def test_case_verdicts_and_rates(self):
        p, f, u = {"verdict": "pass"}, {"verdict": "fail"}, {"verdict": "unknown"}
        self.assertEqual(run.case_verdict([p, p, p]), "pass")
        self.assertEqual(run.case_verdict([p, f, p]), "fail")
        self.assertEqual(run.case_verdict([p, u, p]), "unknown")
        rows = [{"verdict": "pass", "trials": [p, p, p]},
                {"verdict": "fail", "trials": [p, p, f]},
                {"verdict": "unknown", "trials": [p, {**u, "error": "x"}, p]}]
        s = run.summarise(rows)
        self.assertEqual(s["pass_at_1"], round(7 / 8, 3))
        self.assertEqual(s["pass_pow_k"], 0.5)
        self.assertEqual((s["errors"], s["decided_cases"]), (1, 2))

    def test_the_gate(self):
        def suite(pk, errors=0, trials=3, cases=1, incomplete=0):
            return {"regression": {"cases": cases, "trials": trials, "errors": errors,
                                   "pass_pow_k": pk, "incomplete": incomplete}}
        self.assertEqual(run.gate({"reflect": suite(1.0)}, 0.95), [])
        self.assertTrue(run.gate({"reflect": suite(0.9)}, 0.95))
        self.assertTrue(run.gate({"reflect": suite(None, errors=3)}, 0.95))
        self.assertTrue(run.gate({"reflect": suite(1.0, errors=2)}, 0.95))
        self.assertEqual(run.gate({"reflect": suite(None, incomplete=1)}, 0.95), [])
        self.assertEqual(run.gate({"reflect": {"capability": {"pass_pow_k": 0.0}}}, 0.95), [])


def _env(tmp: Path, replies: dict) -> dict:
    path = tmp / "replies.json"
    path.write_text(json.dumps(replies), encoding="utf-8")
    env = dict(os.environ)
    for name in run.CREDENTIAL_VARS:
        env.pop(name, None)
    env.update({"EVALS_CLAUDE_BIN": f"{sys.executable} {FAKE}",
                "EVALS_FAKE_REPLIES": str(path), "EVALS_FAKE_LOG": str(tmp / "calls.jsonl")})
    return env


@pytest.mark.slow
class TestTheRunnerEndToEnd(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def runner(self, env, *args):
        return subprocess.run([sys.executable, str(HERE / "run.py"), *args], env=env,
                              capture_output=True, text=True, timeout=120, check=False,
                              cwd=str(REPO))

    def test_no_token_is_a_skip_and_exit_zero(self):
        env = dict(os.environ)
        for name in run.CREDENTIAL_VARS + ("EVALS_CLAUDE_BIN",):
            env.pop(name, None)
        out = self.runner(env, "--jobs", "reflect", "--out", str(self.tmp / "r.json"))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("skipped: no token", out.stdout)
        self.assertEqual(json.loads((self.tmp / "r.json").read_text())["skipped"], "no token")

    def test_a_good_model_passes_and_the_report_carries_models_and_machine(self):
        env = _env(self.tmp, {"PATTERN": {"lessons": [
            {"id": 1, "lesson": "Night motion on the hall landing is the cat"}]}})
        report = self.tmp / "r.json"
        out = self.runner(env, "--only", "refl-hall-cat", "--trials", "2",
                          "--out", str(report))
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        data = json.loads(report.read_text())
        self.assertEqual(data["models_asked"], {"reflect": "claude-haiku-5-5"})
        self.assertEqual(data["models_reported"], ["claude-haiku-5-5"])
        self.assertEqual(data["judge_model"], judge_mod.JUDGE_MODEL)
        self.assertIn("cpus", data["environment"])
        self.assertEqual(data["by_job"]["reflect"]["regression"]["pass_pow_k"], 1.0)
        calls = [json.loads(line) for line in (self.tmp / "calls.jsonl").read_text().splitlines()
                 if "--version" not in json.loads(line)["argv"]]
        self.assertEqual(len(calls), 2)
        argv = calls[0]["argv"]
        for flag in ("--json-schema", "--strict-mcp-config", "--tools"):
            self.assertIn(flag, argv)
        self.assertEqual(argv[argv.index("--model") + 1], "claude-haiku-5-5")

    def test_a_regression_under_threshold_exits_one(self):
        env = _env(self.tmp, {"*": {"lessons": [{"id": 1, "lesson": "4 of 4 were wrong"}]}})
        out = self.runner(env, "--jobs", "reflect", "--kind", "regression", "--trials", "1")
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
        self.assertIn("FAILED: reflect", out.stdout)

    def test_every_job_but_the_shell_one_runs_through_its_adapter(self):
        replies = {
            "Conversation:": '{"fact": "The garage freezer is on switch.garage_plug and the '
                             'plug must stay on", "confidence": "high", "subject": '
                             '"switch.garage_plug", "kind": "fact"}',
            "learning pass": {"suggestions": [], "lessons": [
                {"text": "Keep the Kitchen section first"},
                {"text": "Never hide the alarm card"}]},
            "You watch one home": {"verdicts": [{"id": 1, "verdict": "act", "why": "leak"}]},
            "*": {"rows": []},
        }
        env = _env(self.tmp, replies)
        report = self.tmp / "r.json"
        for only in ("ext-earlier-is-context-only", "morph-household-lessons-kept",
                     "fl-leak-alone", "dl-healthy-house-empty"):
            with self.subTest(only):
                out = self.runner(env, "--only", only, "--trials", "1", "--out", str(report))
                self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
                row = json.loads(report.read_text())["results"][0]
                self.assertEqual(row["verdict"], "pass", row)

    def test_the_consolidator_runs_the_real_script(self):
        c = case("cons-no-erasure")
        merged = dated(c["input"]["memory"]) + "- The utility room light is called 'the shed'\n"
        env = _env(self.tmp, {"*": merged + "-----VOICE-----\n- 'the shed' = utility light\n"})
        report = self.tmp / "r.json"
        out = self.runner(env, "--only", "cons-no-erasure", "--trials", "1", "--out", str(report))
        row = json.loads(report.read_text())["results"][0]
        self.assertEqual(row["verdict"], "pass", row)
        self.assertEqual(out.returncode, 0)
        self.assertGreater(row["trials"][0]["tokens"], 0)
        self.assertEqual(row["trials"][0]["models"], ["claude-haiku-5-5"])


@pytest.mark.slow
class TestEveryPromptBuilds(unittest.TestCase):
    def test_dry_run(self):
        rc, text = run.dry_run(ALL)
        self.assertEqual(rc, 0, text)


if __name__ == "__main__":
    unittest.main()
