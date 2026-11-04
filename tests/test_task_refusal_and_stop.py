"""A run a safety check refused is tried once on another model, a run nobody
wants any more is stopped, and a long one gets turns for its window.

#680: a brAIn task run (source "task") ended twice on the API's own
"API Error: … safeguards flagged this message …" — a false positive on one
model's classifier, handed back raw. #666: the same text reached a child in
Minecraft. #672: a game job may run an hour, and still stops within seconds
when the player says stop.

Driven through the REAL `process_task` against the fake CLI
(tests/test_task_failures.ListenerCase), and the REAL `engine._run_cli`
(tests/test_engine_landing.LandingCase).
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Modules, not their classes: a base class imported by name is collected
# here and its tests run twice.
import test_engine_landing  # noqa: E402
import test_task_failures  # noqa: E402

engine = test_engine_landing.engine

import model_plan  # noqa: E402  (the panel's, on the path through test_engine_landing)


def argvs(log: Path) -> list[list[str]]:
    if not log.exists():
        return []
    return [json.loads(ln) for ln in log.read_text().splitlines() if ln.startswith("[")]


def after(argv: list[str], flag: str) -> str | None:
    return argv[argv.index(flag) + 1] if flag in argv else None


class TestTheListenerRetriesARefusalOnAnotherModel(test_task_failures.ListenerCase):
    def setUp(self):
        super().setUp()
        extra = {"FAKE_ONCE_FILE": str(self.tmp / "once"),
                 # What run.sh writes into /data/.brain_env off model_plan.
                 "BRAIN_REFUSAL_FALLBACK":
                     model_plan.env_exports()["BRAIN_REFUSAL_FALLBACK"]}
        real = test_task_failures.subprocess.run

        def run(*args, env=None, **kw):
            return real(*args, env={**(env or {}), **extra}, **kw)
        patch = unittest.mock.patch.object(test_task_failures.subprocess, "run", run)
        patch.start()
        self.addCleanup(patch.stop)

    def run_json(self, mode, **task):
        # An envelope the way the CLI writes one under --output-format json.
        return self.run_task({"model": "sonnet", **task}, fake_mode=mode)

    def test_a_refused_task_is_answered_by_the_second_model(self):
        result = self.run_json("refused_then_ok")
        self.assertEqual(result["status"], "completed", result)
        runs = argvs(self.argv_log)
        self.assertEqual([after(a, "--model") for a in runs], ["sonnet", "opus"])
        rows = self.journal_rows()
        self.assertIn("safety check", rows[0].get("error") or json.dumps(rows[0]))

    def test_an_opus_run_falls_back_to_sonnet(self):
        self.run_task({"model": "claude-opus-5-5"}, fake_mode="refused_then_ok")
        self.assertEqual([after(a, "--model") for a in argvs(self.argv_log)],
                         ["claude-opus-5-5", "sonnet"])

    def test_refused_twice_is_a_sentence_never_the_raw_text(self):
        result = self.run_json("refused")
        self.assertEqual((result["status"], result["error"]), ("failed", "safeguard"))
        self.assertNotIn("API Error", result["result"])
        self.assertNotIn("safeguards flagged", result["result"])
        self.assertIn("safety check", result["result"])
        self.assertEqual(len(argvs(self.argv_log)), 2)


class TestTheListenerStopsARunNobodyWants(test_task_failures.ListenerCase):
    def test_a_cancel_beside_the_task_stops_the_run_within_seconds(self):
        marker = self.tmp / "tasks" / "t1.cancel"

        def stop_when_running():
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if self.argv_log.exists() and self.argv_log.read_text().strip():
                    marker.write_text("{}")
                    return
                time.sleep(0.05)
        helper = threading.Thread(target=stop_when_running)
        helper.start()
        started = time.monotonic()
        result = self.run_task({"timeout": 300}, fake_mode="hang")   # hangs 60 s
        helper.join()
        self.assertLess(time.monotonic() - started, 20)
        self.assertEqual((result["status"], result["error"]), ("failed", "stopped"))
        self.assertFalse(marker.exists())
        self.assertEqual(len(argvs(self.argv_log)), 1)             # no retry, no landing

    def test_stopped_before_it_started_runs_nothing(self):
        (self.tmp / "tasks" / "t1.cancel").write_text("{}")
        result = self.run_task({})
        self.assertEqual(result["error"], "stopped")
        self.assertFalse(self.claude_ran())

    def test_an_hour_long_window_gets_turns_in_proportion(self):
        self.run_task({"timeout": 3600})
        self.assertEqual(after(argvs(self.argv_log)[0], "--max-turns"), "800")
        self.run_task({"timeout": 300})
        self.assertEqual(after(argvs(self.argv_log)[-1], "--max-turns"), "200")


class TestTheEngineRetriesARefusalOnAnotherModel(test_engine_landing.LandingCase):
    def setUp(self):
        super().setUp()
        self.once = Path(self.tmp.name) / "once"
        os.environ["FAKE_ONCE_FILE"] = str(self.once)

    def tearDown(self):
        os.environ.pop("FAKE_ONCE_FILE", None)
        super().tearDown()

    def test_the_run_is_tried_on_the_fallback_model_and_the_journal_says_so(self):
        os.environ["FAKE_MODE"] = "refused_then_ok"
        result = engine.run_claude("p", "s", timeout=60, source="card", model="opus")
        self.assertTrue(result["ok"], result)
        self.assertEqual([self._after(a, "--model") for a in self._argvs()], ["opus", "sonnet"])
        row = self._rows()[-1]
        self.assertEqual(row["extra"]["retried"], "refused")
        self.assertEqual(row["extra"]["refused_on"], "opus")

    def test_refused_twice_is_said_in_words(self):
        os.environ["FAKE_MODE"] = "refused"
        result = engine.run_claude("p", "s", timeout=60, model="sonnet")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], engine.REFUSED_MESSAGE)
        self.assertEqual(len(self._argvs()), 2)

    def test_refused_reads_the_error_and_nothing_else(self):
        self.assertTrue(engine.refused({"ok": False, "error": "API Error: its safeguards "
                                                              "flagged this message"}))
        self.assertTrue(engine.refused({"ok": False, "error": "This request appears to "
                                                              "violate our Usage Policy"}))
        self.assertFalse(engine.refused({"ok": True, "text": "the safeguards flagged it"}))
        self.assertFalse(engine.refused({"ok": False, "error": "API Error: 529 Overloaded"}))

    def test_the_fallback_table(self):
        self.assertEqual(model_plan.refusal_fallback("claude-fable-1"), "opus")
        self.assertEqual(model_plan.refusal_fallback("opus"), "sonnet")
        self.assertEqual(model_plan.refusal_fallback("sonnet"), "opus")
        self.assertEqual(model_plan.refusal_fallback(""), "sonnet")


if __name__ == "__main__":
    unittest.main()
