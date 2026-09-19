"""The model plan: which model does which job, and how the engine carries it.

Haiku looks, Sonnet thinks, Opus acts, Fable is a press. Every scheduled
and pressed Claude run used to call one global setting; these tests pin
that the plan tiers them, that a typed global model still overrides
everything (the pre-2.0 behaviour kept on purpose), that the top tier
can never be reached from a loop, and that the engine turns a job into
`--model`/`--effort`/`--json-schema` on the argv — and drops a flag the
installed CLI does not know rather than failing the run over it.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PANEL = Path(__file__).resolve().parent.parent / "brain" / "panel"
sys.path.insert(0, str(PANEL))

import categories  # noqa: E402
import engine  # noqa: E402
import model_plan  # noqa: E402
import settings_store  # noqa: E402


class TestTheTable(unittest.TestCase):
    def test_every_job_names_a_known_tier_and_effort(self):
        for job, (tier, effort, _down, _up) in model_plan.JOBS.items():
            self.assertIn(tier, model_plan.TIERS, job)
            self.assertIn(effort, model_plan.EFFORTS, job)

    def test_the_tiers_are_what_the_page_says(self):
        self.assertEqual(model_plan.resolve("triage"), ("haiku", "low"))
        self.assertEqual(model_plan.resolve("card")[0], "sonnet")
        self.assertEqual(model_plan.resolve("fix_apply"), ("opus", "xhigh"))
        self.assertEqual(model_plan.resolve("consolidate")[0], "haiku")

    def test_fable_is_a_press_and_never_a_timer(self):
        with self.assertRaises(ValueError):
            model_plan.resolve("deep_review")
        self.assertEqual(model_plan.resolve("deep_review", pressed=True)[0], "fable")
        # And nothing a scheduler could name is on the top tier.
        for job, (tier, *_rest) in model_plan.JOBS.items():
            if tier == "fable":
                self.assertIn(job, model_plan.PRESS_ONLY, job)

    def test_a_typed_global_model_overrides_every_job(self):
        """What the `model` option did before 2.0, kept on purpose."""
        for job in model_plan.JOBS:
            pressed = job in model_plan.PRESS_ONLY
            self.assertEqual(
                model_plan.resolve(job, "normal", "claude-sonnet-5", pressed=pressed)[0],
                "claude-sonnet-5", job)

    def test_light_steps_down_only_where_being_wrong_is_cheap(self):
        self.assertEqual(model_plan.resolve("card", "light")[0], "haiku")
        # An apply run changes a house: light may not demote it.
        self.assertEqual(model_plan.resolve("fix_apply", "light")[0], "opus")
        self.assertEqual(model_plan.resolve("fix_plan", "light")[0], "sonnet")

    def test_generous_steps_up_only_the_reasoning_jobs(self):
        self.assertEqual(model_plan.resolve("investigate", "generous")[0], "opus")
        self.assertEqual(model_plan.resolve("card", "generous")[0], "opus")
        # A naming call is never promoted to Opus.
        self.assertEqual(model_plan.resolve("scene_names", "generous")[0], "haiku")

    def test_an_unknown_job_lands_in_the_middle(self):
        self.assertEqual(model_plan.resolve("never-heard-of-it"), ("sonnet", "medium"))

    def test_env_exports_follow_the_override(self):
        plain = model_plan.env_exports()
        self.assertEqual(plain["BRAIN_MODEL_MEMORY"], "haiku")
        self.assertEqual(plain["BRAIN_MODEL_OPUS"], "opus")
        pinned = model_plan.env_exports("claude-opus-5")
        self.assertTrue(all(v == "claude-opus-5" for k, v in pinned.items()
                            if k.startswith("BRAIN_MODEL_")), pinned)
        self.assertEqual(pinned["BRAIN_THINKING"], "normal")


class TestTheShellHalfReadsTheSameTable(unittest.TestCase):
    """The consolidator, study and both listeners run as separate
    processes and cannot import the plan, so run.sh prints it into
    /data/.brain_env off `model_plan.py` itself — one table, two readers.
    """

    ADDON = PANEL.parent

    def test_the_cli_prints_the_exports_and_reads_the_dial_off_disk(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            settings = os.path.join(tmp, "settings.json")
            Path(settings).write_text(json.dumps({"thinking": "light"}))
            env = dict(os.environ, BRAIN_SETTINGS_FILE=settings)
            out = subprocess.run([sys.executable, str(PANEL / "model_plan.py")],
                                 env=env, capture_output=True, text=True,
                                 check=True).stdout
            lines = dict(line[len("export "):].split("=", 1)
                         for line in out.splitlines())
            self.assertEqual(lines["BRAIN_THINKING"], '"light"')
            # Light steps the card tier down, and the shell sees the same.
            self.assertEqual(lines["BRAIN_MODEL_SONNET"], '"haiku"')
            self.assertEqual(lines["BRAIN_MODEL_OPUS"], '"opus"')
            # A typed override wins for every export, as it does in the panel.
            out = subprocess.run([sys.executable, str(PANEL / "model_plan.py"),
                                  "claude-opus-5"], env=env,
                                 capture_output=True, text=True, check=True).stdout
            for line in out.splitlines():
                if line.startswith("export BRAIN_MODEL_"):
                    self.assertTrue(line.endswith('="claude-opus-5"'), line)
            # An unreadable settings file is the default dial, never a crash.
            env["BRAIN_SETTINGS_FILE"] = os.path.join(tmp, "missing.json")
            out = subprocess.run([sys.executable, str(PANEL / "model_plan.py")],
                                 env=env, capture_output=True, text=True,
                                 check=True).stdout
            self.assertIn('export BRAIN_THINKING="normal"', out)

    def test_run_sh_writes_the_plan_into_the_env_file(self):
        run_sh = (self.ADDON / "run.sh").read_text()
        self.assertIn("python3 /opt/panel/model_plan.py", run_sh)
        # After the heredoc that creates the file, never before it.
        self.assertLess(run_sh.index("ENVEOF\n"), run_sh.index("model_plan.py"))

    def test_each_shell_reader_takes_its_own_tier(self):
        """Naming an env var in a script is the one claim a grep can make."""
        readers = {
            "scripts/brain-memory-consolidate.sh": "BRAIN_MODEL_MEMORY",
            "scripts/brain-learn.sh": "BRAIN_MODEL_STUDY",
            "integrations/automation-listener.sh": "BRAIN_MODEL_TASK",
            "integrations/assist-listener.sh": "BRAIN_MODEL_VOICE",
        }
        for rel, var in readers.items():
            self.assertIn(var, (self.ADDON / rel).read_text(), rel)
            self.assertIn(var, model_plan.env_exports(), var)


class TestEveryPanelJobIsInTheTable(unittest.TestCase):
    """A job the table does not know runs at the fallback tier, which is
    safe and is also silent: this reads every `job="…"` the panel passes
    and asserts each is planned on purpose."""

    def test_jobs_named_in_the_panel_are_planned(self):
        import re
        named: set[str] = set()
        for path in PANEL.glob("*.py"):
            if path.name == "model_plan.py":
                continue
            for match in re.finditer(r'job=["\']([a-z_]+)["\']', path.read_text()):
                named.add(match.group(1))
        self.assertTrue(named, "no call site passes a job yet")
        self.assertEqual(sorted(named - set(model_plan.JOBS)), [],
                         "jobs passed by the panel but missing from the plan")


class TestTheSetting(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "settings.json")
        self.patch = mock.patch.object(settings_store, "SETTINGS_FILE", self.path)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_default_is_normal_and_the_dial_has_three_positions(self):
        self.assertEqual(settings_store.load()["thinking"], "normal")
        settings_store.save({"thinking": "light"})
        self.assertEqual(settings_store.load()["thinking"], "light")
        with self.assertRaises(ValueError):
            settings_store.save({"thinking": "maximum"})

    def test_the_engine_reads_the_dial_and_the_override_at_call_time(self):
        with mock.patch.dict(os.environ, {"BRAIN_MODEL": ""}):
            self.assertEqual(engine.planned("card")[0], "sonnet")
            settings_store.save({"thinking": "light"})
            self.assertEqual(engine.planned("card")[0], "haiku")
            settings_store.save({"model": "claude-opus-4-8"})
            self.assertEqual(engine.planned("card")[0], "claude-opus-4-8")


def _fake_cli(behaviour: str) -> str:
    """A stand-in `claude` that records its argv and answers per behaviour.

    `reject:<flag>` dies naming the flag the way the real CLI does for an
    unknown option; `structured` answers a json envelope carrying
    `structured_output`; anything else answers a plain result.
    """
    script = f"""#!/usr/bin/env python3
import json, os, sys
argv = sys.argv[1:]
with open(os.environ["FAKE_ARGV_LOG"], "a") as fh:
    fh.write(json.dumps(argv) + "\\n")
behaviour = {behaviour!r}
if behaviour.startswith("reject:"):
    flag = behaviour.split(":", 1)[1]
    if "--" + flag in argv:
        sys.stderr.write("error: unknown option '--" + flag + "'\\n")
        sys.exit(1)
sys.stdin.read()
env = {{"type": "result", "subtype": "success", "is_error": False,
       "result": '{{"a": 1}}', "session_id": "s-1", "num_turns": 1}}
if behaviour == "structured" and "--json-schema" in argv:
    env["structured_output"] = {{"a": 1, "validated": True}}
print(json.dumps(env))
"""
    fd, path = tempfile.mkstemp(prefix="fake-claude-", suffix=".py")
    with os.fdopen(fd, "w") as fh:
        fh.write(script)
    os.chmod(path, 0o755)
    return path


class TestTheEngineCarriesTheJob(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.log = os.path.join(self.tmp.name, "argv.jsonl")
        self.env = mock.patch.dict(os.environ, {
            "FAKE_ARGV_LOG": self.log, "BRAIN_MODEL": "",
            "BRAIN_SETTINGS_FILE": os.path.join(self.tmp.name, "settings.json"),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        mock.patch.object(settings_store, "SETTINGS_FILE",
                          os.environ["BRAIN_SETTINGS_FILE"]).start()
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(engine, "get_auth", lambda: None).start()
        mock.patch.object(engine.run_sources, "record", lambda *a, **k: None).start()
        mock.patch.object(engine.journal, "record", lambda *a, **k: None).start()

    def _use(self, behaviour: str):
        path = _fake_cli(behaviour)
        self.addCleanup(os.unlink, path)
        mock.patch.object(engine, "_claude_argv", lambda: [sys.executable, path]).start()

    def _argvs(self) -> list[list[str]]:
        return [json.loads(line) for line in Path(self.log).read_text().splitlines()]

    def test_a_job_becomes_model_and_effort_on_the_argv(self):
        self._use("plain")
        result = engine.run_claude("hi", "sys", job="triage")
        self.assertTrue(result["ok"], result)
        argv = self._argvs()[0]
        self.assertIn("--model", argv)
        self.assertEqual(argv[argv.index("--model") + 1], "haiku")
        self.assertEqual(argv[argv.index("--effort") + 1], "low")

    def test_an_explicit_model_still_wins_over_the_job(self):
        self._use("plain")
        engine.run_claude("hi", "sys", model="claude-opus-5", job="triage")
        argv = self._argvs()[0]
        self.assertEqual(argv[argv.index("--model") + 1], "claude-opus-5")

    def test_a_schema_is_sent_and_the_object_comes_back_as_data(self):
        self._use("structured")
        result = engine.run_claude("hi", "sys", schema={"type": "object"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"], {"a": 1, "validated": True})
        argv = self._argvs()[0]
        self.assertEqual(json.loads(argv[argv.index("--json-schema") + 1]),
                         {"type": "object"})

    def test_a_cli_that_rejects_effort_runs_without_it(self):
        """The request is optional; the run is not."""
        self._use("reject:effort")
        result = engine.run_claude("hi", "sys", job="card")
        self.assertTrue(result["ok"], result)
        argvs = self._argvs()
        self.assertEqual(len(argvs), 2)
        self.assertIn("--effort", argvs[0])
        self.assertNotIn("--effort", argvs[1])
        # And the session id is kept on the retry: only the rejected flag goes.
        self.assertIn("--session-id", argvs[1])

    def test_a_cli_that_rejects_the_schema_falls_back_to_the_text(self):
        self._use("reject:json-schema")
        result = engine.run_claude("hi", "sys", schema={"type": "object"})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["data"], {"a": 1})
        self.assertNotIn("--json-schema", self._argvs()[1])


class TestTheCardStylesheet(unittest.TestCase):
    def test_the_palette_left_the_prompt_for_the_stylesheet(self):
        """The design system used to be ~1.5 KB of hex values re-sent
        per run; it is CSS now and the prompt names the variables."""
        self.assertIn("--c1:#2a78d6", categories.CARD_STYLES)
        self.assertIn("var(--c1)", categories._CARD_CONTRACT)
        for hexcode in ("#e87ba4", "#cde2fb", "#0d366b", "#ec835a"):
            self.assertIn(hexcode, categories.CARD_STYLES)
            self.assertNotIn(hexcode, categories._CARD_CONTRACT, hexcode)
        self.assertLess(len(categories._CARD_CONTRACT), 8000)

    def test_inject_styles_is_placed_in_head_and_is_idempotent(self):
        html = "<!DOCTYPE html><html><head><title>t</title></head><body></body></html>"
        out = categories.inject_styles(html)
        self.assertTrue(out.index("card-styles") < out.index("<title>"))
        self.assertEqual(categories.inject_styles(out), out)
        self.assertTrue(categories.inject_styles("<p>bare</p>").startswith("<style"))
        self.assertEqual(categories.inject_styles(""), "")

    def test_the_schema_matches_the_contract(self):
        for key in ("title", "summary", "highlights", "html"):
            self.assertIn(key, categories.CARD_SCHEMA["required"])
        sev = categories.CARD_SCHEMA["properties"]["findings"]["items"]["properties"]["severity"]
        self.assertEqual(sev["enum"], ["info", "warning", "serious", "critical"])


if __name__ == "__main__":
    unittest.main()
