"""The deep review: one press on the top tier, its price shown first.

Three claims, each driven rather than described:

* it is reachable only by a press — `model_plan` refuses the job without
  one, `engine.planned` carries that refusal, and nothing in the panel but
  the one route can start it (an AST walk over every caller);
* the price on the button is read off what earlier reviews on this house
  actually cost, and says when it is only a first guess;
* the run reads and files nothing: what it says is kept in its own capped
  store, and a store that cannot be read says so instead of reading empty.
"""
from __future__ import annotations

import ast
import asyncio
import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PANEL = REPO / "brain" / "panel"
sys.path.insert(0, str(PANEL))

import deep_review  # noqa: E402
import model_plan  # noqa: E402


class TestWhatAReviewIs(unittest.TestCase):
    def test_a_reply_with_nothing_in_it_is_no_review(self):
        self.assertIsNone(deep_review.parse({"summary": "", "observations": []}))
        self.assertIsNone(deep_review.parse("a sentence"))
        self.assertIsNone(deep_review.parse(None))

    def test_observations_are_capped_cleaned_and_kinded(self):
        many = [{"title": f"  t{i}\n", "detail": "d " * 10, "kind": "weird",
                 "entities": ["light.hall", "not an id", 3]}
                for i in range(10)]
        got = deep_review.parse({"summary": "s", "observations": many,
                                 "one_thing": "do it"})
        self.assertEqual(len(got["observations"]), deep_review.MAX_OBSERVATIONS)
        first = got["observations"][0]
        self.assertEqual(first["title"], "t0")
        self.assertEqual(first["kind"], "problem")
        self.assertEqual(first["entities"], ["light.hall"])
        self.assertEqual(got["one_thing"], "do it")

    def test_the_frame_carries_what_is_already_known_and_skips_what_is_empty(self):
        text = deep_review.frame(findings="ALREADY", house="", memory="MEM")
        self.assertIn("ALREADY", text)
        self.assertIn("MEM", text)
        self.assertNotIn("What brAIn has measured", text)


class TestThePriceOnTheButton(unittest.TestCase):
    def test_before_any_review_it_is_a_first_guess_and_says_so(self):
        est = deep_review.estimate([], 300_000)
        self.assertEqual(est["tokens"], deep_review.FIRST_GUESS_TOKENS)
        self.assertIn("first guess", est["basis"])
        self.assertEqual(est["percent"], 50)

    def test_after_reviews_it_is_what_they_cost(self):
        reviews = [{"tokens": 90_000}, {"tokens": 210_000}, {"tokens": 120_000},
                   {"tokens": 999_999}]
        est = deep_review.estimate(reviews, 1_500_000)
        # The newest three, median: 120k, of a Max 5x session's 1.5M.
        self.assertEqual(est["tokens"], 120_000)
        self.assertEqual(est["percent"], 8)
        self.assertIn("last 3 reviews", est["basis"])

    def test_no_plan_allowance_is_no_percentage_rather_than_a_made_up_one(self):
        self.assertIsNone(deep_review.estimate([], None)["percent"])


class TestTheStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = deep_review.STORE
        deep_review.STORE = Path(self.tmp.name) / "deep-review.json"

    def tearDown(self):
        deep_review.STORE = self.old
        self.tmp.cleanup()

    def test_missing_is_an_empty_history_and_unreadable_says_so(self):
        self.assertEqual(deep_review.load(), {"reviews": [], "error": ""})
        deep_review.STORE.write_text("{not json")
        got = deep_review.load()
        self.assertEqual(got["reviews"], [])
        self.assertIn("not valid JSON", got["error"])

    def test_it_keeps_the_newest_few(self):
        for i in range(deep_review.MAX_REVIEWS + 3):
            deep_review.save({"summary": f"r{i}", "observations": []},
                             now=1_700_000_000 + i)
        got = deep_review.load()["reviews"]
        self.assertEqual(len(got), deep_review.MAX_REVIEWS)
        self.assertEqual(got[0]["summary"], f"r{deep_review.MAX_REVIEWS + 2}")

    def test_a_review_saved_over_an_unreadable_file_keeps_the_original_beside_it(self):
        deep_review.STORE.write_text("{not json")
        deep_review.save({"summary": "new", "observations": []})
        self.assertEqual(deep_review.load()["reviews"][0]["summary"], "new")
        self.assertEqual(deep_review.STORE.with_suffix(".unreadable").read_text(),
                         "{not json")


class TestOnlyAPressReachesIt(unittest.TestCase):
    def test_the_plan_refuses_it_without_a_press(self):
        with self.assertRaises(ValueError):
            model_plan.resolve("deep_review")
        self.assertEqual(model_plan.resolve("deep_review", pressed=True)[0], "fable")

    def test_engine_planned_carries_the_refusal(self):
        engine = importlib.import_module("engine")
        with self.assertRaises(ValueError):
            engine.planned("deep_review")
        self.assertTrue(engine.planned("deep_review", pressed=True)[0])

    def test_nothing_but_the_route_starts_a_review(self):
        tree = ast.parse((PANEL / "server.py").read_text(encoding="utf-8"))
        callers: dict[str, set[str]] = {}
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(fn):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id in ("_start_deep_review", "_run_deep_review")):
                    callers.setdefault(node.func.id, set()).add(fn.name)
        self.assertEqual(callers.get("_start_deep_review"), {"h_deep_review_run"})
        # `go` is the task body `_start_deep_review` itself schedules.
        self.assertEqual(callers.get("_run_deep_review"), {"_start_deep_review", "go"})

    def test_only_the_deep_review_plumbing_plans_a_pressed_job(self):
        # A scheduler that reached for `pressed=True` would be the attention
        # loop spending the top tier. Every call carrying it, panel-wide:
        allowed = {"_deep_review_payload", "_run_deep_review"}
        found = set()
        for path in PANEL.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for fn in ast.walk(tree):
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for node in ast.walk(fn):
                    if not isinstance(node, ast.Call):
                        continue
                    name = getattr(node.func, "attr", getattr(node.func, "id", ""))
                    if name != "planned":
                        continue
                    if any(k.arg == "pressed" for k in node.keywords):
                        found.add(f"{path.name}:{fn.name}")
        self.assertEqual({f.split(":")[1] for f in found}, allowed)
        self.assertTrue(all(f.startswith("server.py:") for f in found))


class TestThePressDriven(unittest.TestCase):
    """The route, over real stores, with the CLI stubbed at `run_analyst`."""

    @classmethod
    def setUpClass(cls):
        cls.server = importlib.import_module("server")

    def setUp(self):
        import engine
        import settings_store
        import usage_store
        srv = self.server
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self._restore = []

        def point(mod, **attrs):
            for k, v in attrs.items():
                self._restore.append((mod, k, getattr(mod, k)))
                setattr(mod, k, v)

        point(srv.deep_review, STORE=root / "deep-review.json")
        for mod in {id(m): m for m in (srv.findings_store, sys.modules.get("findings_store"))
                    if m is not None}.values():
            point(mod, FINDINGS_FILE=root / "findings.json", INBOX_DIR=root / "inbox",
                  SETTLED_FILE=root / "settled.json",
                  STATE_FILE=root / "config" / ".brain" / "state.json")
        point(settings_store, SETTINGS_FILE=str(root / "settings.json"))
        point(usage_store, USAGE_FILE=str(root / "usage.json"),
              LIMITS_FILE=str(root / "limits.json"))
        self.calls: list[dict] = []
        self.reply = {"ok": True, "meta": {"usage": {"input_tokens": 140_000,
                                                     "output_tokens": 6_000}},
                      "data": {"summary": "The house is mostly well set up.",
                               "observations": [{
                                   "title": "Three plugs share one hub",
                                   "detail": "They drop out together.",
                                   "kind": "problem",
                                   "entities": ["switch.kettle"]}],
                               "one_thing": "Move the hub off the microwave."}}

        def run_analyst(prompt, system, *a, **k):
            self.calls.append({"prompt": prompt, "system": system, "args": a, **k})
            return self.reply

        def run_claude(*a, **k):
            raise AssertionError("a review reads with tools; it never runs tool-less")

        point(engine, run_analyst=run_analyst, run_claude=run_claude,
              get_auth=lambda: {"type": "oauth", "value": "x"})

        async def house(now=None):
            return "MEASURED"

        point(srv, _house_prompt_block=house, _memory_block=lambda **k: "REMEMBERED")
        os.environ.pop("BRAIN_MODEL", None)
        settings_store.save({"onboarded": True, "auto_enabled": False,
                             "plan": "pro"})
        srv.DEEP_REVIEW_STATE.update({"running": False, "starting": False,
                                      "last_error": ""})

    def tearDown(self):
        for mod, k, v in reversed(self._restore):
            setattr(mod, k, v)
        self.server.DEEP_REVIEW_STATE.update({"running": False, "starting": False,
                                              "last_error": ""})
        self.tmp.cleanup()

    def press(self):
        srv = self.server

        async def go():
            resp = await srv.h_deep_review_run(None)
            while srv._DEEP_REVIEW_TASKS:
                await asyncio.gather(*list(srv._DEEP_REVIEW_TASKS))
            return resp

        return asyncio.run(go())

    def test_a_press_runs_the_top_tier_with_read_only_tools_and_keeps_what_it_said(self):
        before = json.loads(asyncio.run(self.server.h_deep_review(None)).body)
        self.assertIn("first guess", before["estimate"]["basis"])
        self.assertEqual(before["estimate"]["percent"], 50)
        self.assertIsNone(before["latest"])

        resp = self.press()
        self.assertEqual(resp.status, 200)
        [call] = self.calls
        self.assertEqual(call["job"], "deep_review")
        self.assertEqual(call["schema"], deep_review.SCHEMA)
        self.assertEqual(call["args"][0], "fable")
        self.assertIn("MEASURED", call["prompt"])
        self.assertIn("REMEMBERED", call["prompt"])

        after = json.loads(asyncio.run(self.server.h_deep_review(None)).body)
        latest = after["latest"]
        self.assertEqual(latest["one_thing"], "Move the hub off the microwave.")
        self.assertEqual(latest["tokens"], 146_000)
        # The next button is priced off what this one cost.
        self.assertEqual(after["estimate"]["tokens"], 146_000)
        self.assertIn("last 1 review", after["estimate"]["basis"])
        self.assertFalse(after["running"])
        diag = self.server._deep_review_diagnostics()
        self.assertEqual((diag["kept"], diag["last_tokens"]), (1, 146_000))

    def test_it_files_nothing_anywhere_else(self):
        srv = self.server
        before = srv.findings_store.list_all()
        self.press()
        self.assertEqual(srv.findings_store.list_all(), before)

    def test_a_paused_house_still_runs_a_press_and_no_credential_refuses_it(self):
        import engine
        self.press()
        self.assertEqual(len(self.calls), 1)
        engine.get_auth = lambda: None
        resp = asyncio.run(self.server.h_deep_review_run(None))
        self.assertEqual(resp.status, 400)
        self.assertEqual(len(self.calls), 1)

    def test_a_second_press_while_one_runs_is_refused(self):
        srv = self.server
        srv.DEEP_REVIEW_STATE["running"] = True
        resp = asyncio.run(srv.h_deep_review_run(None))
        self.assertEqual(resp.status, 409)
        self.assertEqual(self.calls, [])

    def test_a_failed_or_unreadable_run_says_why_and_keeps_the_last_review(self):
        self.press()
        self.reply = {"ok": False, "error": "529 Overloaded", "meta": {}}
        self.press()
        self.reply = {"ok": True, "data": {"summary": "", "observations": []}, "meta": {}}
        self.press()
        got = json.loads(asyncio.run(self.server.h_deep_review(None)).body)
        self.assertIn("could be read", got["last_error"])
        self.assertEqual(got["latest"]["summary"], "The house is mostly well set up.")
        self.assertEqual(got["history"], [])

    def test_the_routes_are_mounted(self):
        paths = set()
        for route in self.server.make_app().router.routes():
            info = route.resource.get_info() if route.resource else {}
            paths.add((route.method, info.get("path")))
        self.assertIn(("GET", "/api/deep-review"), paths)
        self.assertIn(("POST", "/api/deep-review/run"), paths)


if __name__ == "__main__":
    unittest.main()
