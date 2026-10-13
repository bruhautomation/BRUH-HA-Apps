"""A Tell is a conversation about what somebody is looking at.

Driven against the same stand-in brAIn as ``test_morph_loops`` (it claims a
task by renaming it and answers in ``task_results``), with nothing inside
Morph mocked. What is held here:

* the picture the panel filed is handed to brAIn FIRST, by path, and an id
  that is not one Morph minted never becomes a path;
* a request from the panel is about the dashboard: Home Assistant itself is
  changed only when the words ask, and a target cannot claim otherwise
  over the wire — only Undo's follow-up carries the house scope;
* brAIn's own tool calls, written by its progress hook, arrive as steps;
* a request that needs Morph's code changed is ASKED about, and only a yes
  reaches the development loop's outbox;
* the learning pass is about the dashboard, carries AGENTS.md's design
  rules in its prompt (it has no file access), and a pass that failed does
  not mark the evidence as read.
"""
import asyncio
import importlib
import json
import shutil
import time
import unittest

from morph_env import MorphEnv
from test_morph_loops import DOC, FakeBrain, fast, finish

HAS_GIT = shutil.which("git") is not None
SHOT = "0123456789abcdef0123456789abcdef"
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32


@unittest.skipUnless(HAS_GIT, "git is not installed")
class TestATellIsAConversation(unittest.TestCase):

    def setUp(self):
        self.env = MorphEnv().__enter__()
        self.addCleanup(self.env.__exit__, None, None, None)
        self.env.brain_on()
        fast(self.env)
        dash, _ = self.env.store.normalize(DOC)
        self.env.store.write(dash)
        self.env.gitrepo.commit("First", "morph")
        self.card = dash["floors"][0]["sections"][0]["groups"][0]["cards"][0]["id"]

    def run_brain(self, work):
        fake = FakeBrain(self.env, work)
        fake.start()
        self.addCleanup(fake.stop.set)
        return fake

    def tell(self, *args, **kw):
        async def go():
            return await finish(self.env, self.env.tell.start(*args, **kw))
        return asyncio.run(go())

    def file_shot(self, shot=SHOT):
        self.env.paths.SHOTS.mkdir(parents=True, exist_ok=True)
        (self.env.paths.SHOTS / f"{shot}.png").write_bytes(PNG)

    def test_the_picture_is_read_first_and_the_text_rides_beside_it(self):
        self.file_shot()
        fake = self.run_brain(lambda task: {"data": {"summary": "Made it wider", "changed": [],
                                                      "reload": False, "saw": "The name is cut off"}})
        st = self.tell({"kind": "card", "id": self.card}, "The name is cut off",
                       shot=SHOT, view={"w": 180, "h": 90, "text": "Countertop · On"})
        prompt = fake.seen[0]["prompt"]
        path = str(self.env.paths.SHOTS / f"{SHOT}.png")
        self.assertIn(f"Read {path}", prompt)
        self.assertLess(prompt.index(path), prompt.index("WHERE THIS LIVES"),
                        "the picture comes before the YAML")
        self.assertIn("Countertop · On", prompt)
        self.assertEqual("The name is cut off", st["saw"])
        self.assertIn("Took a picture of it for brAIn", [x["t"] for x in st["steps"]])

    def test_an_id_morph_did_not_mint_never_becomes_a_path(self):
        fake = self.run_brain(lambda task: {"data": {"summary": "ok", "changed": [], "reload": False}})
        for shot in ("../../secrets", SHOT):  # the second is well-formed but was never filed
            st = self.tell({"kind": "card", "id": self.card}, "Anything", shot=shot,
                           view={"text": "Countertop", "error": "the browser would not draw it"})
            self.assertNotIn("shot", st)
        prompt = fake.seen[-1]["prompt"]
        self.assertNotIn("/shots/", prompt)
        self.assertIn("could not take a picture", prompt)
        self.assertIn("the browser would not draw it", prompt)
        self.assertIn("Countertop", prompt)

    def test_the_panel_asks_for_the_dashboard_and_only_undo_reaches_the_house(self):
        fake = self.run_brain(lambda task: {"data": {"summary": "ok", "changed": [], "reload": False}})
        morphd = importlib.import_module("morphd")

        async def from_the_wire():
            out = await morphd.handle("tell", {"target": {"kind": "dashboard", "scope": "house"},
                                               "text": "Rename it"})
            return await finish(self.env, out)

        st = asyncio.run(from_the_wire())
        self.assertEqual("ui", st["scope"], "a target cannot claim the house scope over the wire")
        prompt = fake.seen[-1]["prompt"]
        self.assertIn("MORPH ONLY — the dashboard and Morph itself", prompt)
        self.assertIn("change the entity ID", prompt)
        self.assertIn("remember_fact", prompt, "a house fact goes to brAIn's memory, not LEARNED.md")

        env = self.env

        def changes_the_house(task):
            dash, _, _ = env.store.read()
            dash["title"] = "Changed"
            env.store.write(dash)
            return {"data": {"summary": "Made a helper", "changed": ["input_boolean.guest"],
                             "reload": True}}

        fake.work = changes_the_house
        st = self.tell({"kind": "dashboard"}, "Add a guest switch and make the helper for it")
        self.assertEqual(["input_boolean.guest"], st["house"])
        fake.work = lambda task: {"data": {"summary": "Put back", "changed": [], "reload": False}}
        async def undo():
            # morphd calls undo inside its loop, which is where the follow-up starts.
            out = env.tell.undo(st["id"])
            return await finish(env, env.tell.read_state(out["follow"]))

        follow = asyncio.run(undo())
        self.assertEqual("house", follow["scope"])
        self.assertIn("this request is about Home Assistant itself", fake.seen[-1]["prompt"])

    def test_what_brain_is_doing_arrives_as_steps(self):
        env = self.env

        def work(task):
            progress = env.paths.BRAIN_PROGRESS / f"{task['id']}.jsonl"
            progress.parent.mkdir(parents=True, exist_ok=True)
            rows = [{"at": time.time(), "tool": "Read", "what": f"{env.paths.SHOTS}/{SHOT}.png"},
                    {"at": time.time(), "tool": "Read", "what": f"{env.paths.MORPH_DIR}/dashboard.yaml"},
                    {"at": time.time(), "tool": "Read", "what": f"{env.paths.MORPH_DIR}/dashboard.yaml"},
                    {"at": time.time(), "tool": "TodoWrite", "what": ""},
                    {"at": time.time(), "tool": "mcp__home-assistant__get_entity_state",
                     "what": "light.countertop"},
                    {"at": time.time(), "tool": "Edit", "what": f"{env.paths.MORPH_DIR}/dashboard.yaml"}]
            progress.write_text("".join(json.dumps(r) + "\n" for r in rows))
            time.sleep(0.15)
            return {"data": {"summary": "ok", "changed": [], "reload": False}}

        self.run_brain(work)
        st = self.tell({"kind": "dashboard"}, "Tidy it")
        said = [x["t"] for x in st["steps"] if x.get("brain")]
        self.assertEqual(["Looking at the screenshot", "Reading dashboard.yaml",
                          "Get entity state · light.countertop", "Editing dashboard.yaml"], said,
                         "a repeat is one line and brAIn's own to-do list is not a step")

    def test_a_tell_that_needs_morphs_code_is_asked_about_before_anything_is_filed(self):
        issue = {"title": "The light card cannot show two colours", "detail": "Needs a split strip"}
        self.run_brain(lambda task: {"data": {"summary": "Did what I could", "changed": [],
                                              "reload": False, "code_issue": issue}})
        st = self.tell({"kind": "card", "id": self.card}, "Show both bulbs' colours")
        self.assertEqual("asked", st["issue"])
        self.assertEqual([], self.env.devloop.rows(), "nothing is filed on the model's say-so")

        self.env.settings.update({"report_code_issues": False})
        refused = self.env.tell.answer_issue(st["id"], "send")
        self.assertFalse(refused["ok"])
        self.assertIn("Report Morph’s own problems", refused["error"])

        self.env.settings.update({"report_code_issues": True})
        self.assertTrue(self.env.tell.answer_issue(st["id"], "send")["ok"])
        rows = self.env.devloop.rows()
        self.assertEqual([issue["title"]], [r["what"] for r in rows])
        self.assertIn("Show both bulbs' colours", rows[0]["body"])
        self.assertIn("card type light", rows[0]["body"], "the issue names the card type to open")
        self.assertEqual("sent", self.env.tell.read_state(st["id"])["issue"])

    def test_no_is_remembered_and_files_nothing(self):
        self.run_brain(lambda task: {"data": {"summary": "x", "changed": [], "reload": False,
                                              "code_issue": {"title": "T", "detail": "D"}}})
        st = self.tell({"kind": "dashboard"}, "Something Morph cannot do")
        self.assertTrue(self.env.tell.answer_issue(st["id"], "no")["ok"])
        self.assertEqual("declined", self.env.tell.read_state(st["id"])["issue"])
        self.assertEqual([], self.env.devloop.rows())

    def test_brains_weather_is_not_a_fault_in_morph(self):
        def failed(task):
            return {"status": "failed", "error": "timeout", "result": "brAIn ran out of time"}

        self.run_brain(failed)
        st = self.tell({"kind": "dashboard"}, "Anything")
        self.assertEqual("failed", st["phase"])
        self.assertEqual([], self.env.devloop.rows(),
                         "a slow or signed-out brAIn is not a bug in Morph's code")

    def test_a_running_tell_is_listed_as_activity(self):
        env = self.env
        gate = {"go": False}

        def slow(task):
            while not gate["go"]:
                time.sleep(0.02)
            return {"data": {"summary": "ok", "changed": [], "reload": False}}

        self.run_brain(slow)

        async def go():
            st = env.tell.start({"kind": "card", "id": self.card, "label": "Countertop"}, "Bigger")
            for _ in range(200):
                acts = env.tell.activity()
                if acts and acts[0]["phase"] == "working":
                    break
                await asyncio.sleep(0.02)
            gate["go"] = True
            await finish(env, st)
            return acts

        acts = asyncio.run(go())
        self.assertEqual(1, len(acts))
        self.assertEqual(("card", self.card, "Bigger"), (acts[0]["kind"], acts[0]["target"], acts[0]["text"]))
        self.assertEqual([], env.tell.activity(), "a finished tell is not activity")


@unittest.skipUnless(HAS_GIT, "git is not installed")
class TestTheLearningPassIsAboutTheDashboard(unittest.TestCase):

    def setUp(self):
        self.env = MorphEnv().__enter__()
        self.addCleanup(self.env.__exit__, None, None, None)
        self.env.brain_on()
        fast(self.env)
        dash, _ = self.env.store.normalize(DOC)
        self.env.store.write(dash)
        self.env.gitrepo.commit("First", "morph")
        # AGENTS.md as Morph installs it.
        text = (self.env.paths.DEFAULTS / "AGENTS.md").read_text(encoding="utf-8")
        self.env.paths.AGENTS.write_text(text, encoding="utf-8")

    def test_the_prompt_carries_the_design_rules_and_asks_for_no_files(self):
        fake = FakeBrain(self.env, lambda task: {"data": {"suggestions": [], "lessons": [],
                                                          "code_reports": []}})
        fake.start()
        self.addCleanup(fake.stop.set)
        asyncio.run(self.env.learning.run_pass(pressed=True))
        prompt = fake.seen[0]["prompt"]
        self.assertIn("Nothing floats over anything", prompt)
        self.assertNotIn("read AGENTS.md", prompt, "a read-only task has no Read tool")
        self.assertIn("do not suggest automations", prompt)
        self.assertEqual(["dashboard"],
                         self.env.learning.SCHEMA["properties"]["suggestions"]["items"]
                         ["properties"]["kind"]["enum"])

    def test_a_suggestion_marked_house_is_still_a_dashboard_suggestion(self):
        row = {"title": "Make an automation", "change": "x", "kind": "house"}
        fake = FakeBrain(self.env, lambda task: {"data": {"suggestions": [row], "lessons": []}})
        fake.start()
        self.addCleanup(fake.stop.set)
        asyncio.run(self.env.learning.run_pass(pressed=True))
        self.assertEqual(["dashboard"], [i["kind"] for i in self.env.learning.listing()])

    def test_a_pass_that_failed_does_not_mark_the_evidence_read(self):
        env = self.env
        env.paths.append_jsonl(env.paths.USAGE, {"ts": time.time(), "kind": "open", "hour": 9})
        fake = FakeBrain(env, lambda task: {"status": "failed", "error": "auth", "result": "signed out"})
        fake.start()
        self.addCleanup(fake.stop.set)
        out = asyncio.run(env.learning.run_pass())
        self.assertEqual({"error": "auth"}, out)
        self.assertNotIn("fingerprint", env.learning.state())
        self.assertEqual([], env.devloop.rows(), "signed out is not a fault in Morph's code")
        fake.work = lambda task: {"data": {"suggestions": [], "lessons": []}}
        out = asyncio.run(env.learning.run_pass())
        self.assertEqual({"added": 0}, out, "the next pass runs rather than skipping as unchanged")
        self.assertIn("fingerprint", env.learning.state())


if __name__ == "__main__":
    unittest.main()
