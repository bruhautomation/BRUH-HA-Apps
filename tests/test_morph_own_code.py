"""Morph can change itself.

Morph is a dashboard brAIn designs, and nothing about it is out of reach:
asked to put a theme switch in Morph's header, brAIn answered that the header
was "Morph's own code" and it could only change the dashboard's files. Now a
module of Morph's own panel can be replaced one file at a time from
/config/morph/frontend/ (``morphcode.py``), and the integration serves the
copy in its place (``static.py``). What is held here, with brAIn played by
the same stand-in ``test_morph_loops`` uses and nothing inside Morph mocked:

* a copy is one commit, recorded with which Morph it was written against,
  and Undo puts Morph's own back;
* an update that changes Morph's own file under a copy PAUSES the copy
  rather than serving last release's module beside this release's others,
  and writing the copy again un-pauses it;
* the integration serves a copy only when the add-on says it is in use,
  never under shipped/, never boot.js, and never a name that is not one;
* a Tell is told it may change Morph itself (never "you cannot"), a Tell
  that did is offered the reload and asked whether to open an issue —
  whether or not brAIn remembered to say so — and the issue carries the
  patch;
* a code suggestion's Do it makes the change rather than only filing it.
"""
import asyncio
import importlib
import json
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path

from morph_env import MorphEnv
from test_morph_loops import DOC, FakeBrain, fast, finish

HAS_GIT = shutil.which("git") is not None
ROOT = Path(__file__).resolve().parent.parent
COMPONENT = ROOT / "morph" / "custom_components" / "morph"


@unittest.skipUnless(HAS_GIT, "git is not installed")
class TestACopyOfMorphsOwnCode(unittest.TestCase):

    def setUp(self):
        self.env = MorphEnv().__enter__()
        self.addCleanup(self.env.__exit__, None, None, None)
        dash, _ = self.env.store.normalize(DOC)
        self.env.store.write(dash)
        self.env.gitrepo.commit("First", "morph")
        self.code = self.env.morph_dir / "frontend"

    def write_copy(self, name="styles.js", extra="/* a theme switch */\n"):
        self.code.mkdir(exist_ok=True)
        (self.code / name).write_text((self.env.shipped / name).read_text() + extra)

    def status(self):
        return {r["name"]: r["status"] for r in self.env.morphcode.status()}

    def test_a_copy_is_one_commit_and_undo_puts_morphs_own_back(self):
        self.write_copy()
        sha = self.env.gitrepo.commit("brAIn: a theme switch", "brain")
        self.assertIn("frontend/styles.js", self.env.gitrepo.changed_files(sha))
        self.assertIn("frontend/.base.json", self.env.gitrepo.changed_files(sha),
                      "the record of which Morph it was written against goes in the same commit")
        self.assertEqual({"styles.js": "active"}, self.status())
        ok, _ = self.env.gitrepo.revert(sha)
        self.assertTrue(ok)
        self.assertFalse((self.code / "styles.js").exists())
        self.assertEqual({}, self.status())

    def test_an_update_under_a_copy_pauses_it_and_writing_it_again_unpauses(self):
        self.write_copy()
        self.env.gitrepo.commit("brAIn: a theme switch", "brain")
        # An update changes Morph's own styles.js.
        own = self.env.shipped / "styles.js"
        own.write_text(own.read_text() + "/* next release */\n")
        self.assertEqual({"styles.js": "paused"}, self.status())
        self.env.morphcode.publish("0.4.0")
        published = json.loads(self.env.paths.CODE_STATE.read_text())
        self.assertEqual([("styles.js", "paused")], [(r["name"], r["status"]) for r in published["files"]])
        # brAIn makes the change again on top of the new file.
        self.write_copy(extra="/* a theme switch, again */\n")
        self.assertEqual({"styles.js": "active"}, self.status(), "a copy written since is not paused")
        self.env.gitrepo.commit("brAIn: made it again", "brain")
        self.assertEqual({"styles.js": "active"}, self.status())

    def test_a_module_morph_does_not_ship_is_in_use_and_boot_is_never_a_copy(self):
        self.code.mkdir()
        (self.code / "theme-switch.js").write_text("export const x = 1;\n")
        (self.code / "boot.js").write_text("// never served\n")
        (self.code / "Not A Module.js").write_text("")
        self.assertEqual({"theme-switch.js": "active"}, self.status())

    def test_putting_morphs_own_back(self):
        self.write_copy()
        self.env.gitrepo.commit("brAIn: a theme switch", "brain")
        self.assertEqual((False, "That is not one of Morph's files."), self.env.morphcode.reset("../secrets.yaml"))
        ok, _ = self.env.morphcode.reset("styles.js")
        self.assertTrue(ok)
        self.assertFalse((self.code / "styles.js").exists())
        self.assertEqual({}, self.status())


class TestTheIntegrationServesTheCopy(unittest.TestCase):
    """``static.pick`` decides what a module URL answers with."""

    @classmethod
    def setUpClass(cls):
        # static.py imports aiohttp and Home Assistant's view base; neither is
        # what is being tested, so they are stand-ins for the import only.
        saved = {k: sys.modules.get(k) for k in ("homeassistant", "homeassistant.components",
                                                 "homeassistant.components.http", "aiohttp")}
        ha = types.ModuleType("homeassistant")
        comps = types.ModuleType("homeassistant.components")
        http = types.ModuleType("homeassistant.components.http")
        http.HomeAssistantView = object
        aio = sys.modules.get("aiohttp") or types.ModuleType("aiohttp")
        if not hasattr(aio, "web"):
            aio.web = types.SimpleNamespace(Request=object, StreamResponse=object)
        sys.modules.update({"homeassistant": saved["homeassistant"] or ha,
                            "homeassistant.components": saved["homeassistant.components"] or comps,
                            "homeassistant.components.http": saved["homeassistant.components.http"] or http,
                            "aiohttp": aio})
        pkg = types.ModuleType("morph_component")
        pkg.__path__ = [str(COMPONENT)]
        sys.modules["morph_component"] = pkg
        for sub in ("const", "static"):
            spec = importlib.util.spec_from_file_location(f"morph_component.{sub}", COMPONENT / f"{sub}.py")
            mod = importlib.util.module_from_spec(spec)
            sys.modules[f"morph_component.{sub}"] = mod
            spec.loader.exec_module(mod)
        cls.static = sys.modules["morph_component.static"]
        for k in ("morph_component", "morph_component.const", "morph_component.static"):
            sys.modules.pop(k, None)
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.frontend, self.code, self.state = root / "frontend", root / "copies", root / "code.json"
        self.frontend.mkdir()
        self.code.mkdir()
        for name in ("morph-panel.js", "styles.js", "boot.js"):
            (self.frontend / name).write_text("// Morph's own\n")
            (self.code / name).write_text("// this house's\n")

    def pick(self, name, shipped=False):
        p = self.static.pick(name, shipped, frontend=self.frontend, code_dir=self.code, code_state=self.state)
        return None if p is None else p.parent.name

    def say(self, *rows):
        self.state.write_text(json.dumps({"files": [{"name": n, "status": s} for n, s in rows]}))

    def test_a_copy_in_use_is_served_and_morphs_own_is_always_under_shipped(self):
        self.say(("styles.js", "active"))
        self.assertEqual("copies", self.pick("styles.js"))
        self.assertEqual("frontend", self.pick("styles.js", shipped=True))
        self.assertEqual("frontend", self.pick("morph-panel.js"), "a copy nobody listed is not served")

    def test_paused_unreadable_and_boot_serve_morphs_own(self):
        self.say(("styles.js", "paused"), ("boot.js", "active"))
        self.assertEqual("frontend", self.pick("styles.js"))
        self.assertEqual("frontend", self.pick("boot.js"), "the loader that falls back is never replaced")
        self.state.write_text("{not json")
        self.assertEqual("frontend", self.pick("styles.js"), "an unreadable verdict serves Morph's own")

    def test_a_name_that_is_not_one_is_a_404(self):
        self.say(("styles.js", "active"))
        for bad in ("../const.py", "styles.css", ".base.json", "STYLES.js", ""):
            self.assertIsNone(self.pick(bad), bad)


@unittest.skipUnless(HAS_GIT, "git is not installed")
class TestATellMayChangeMorphItself(unittest.TestCase):

    def setUp(self):
        self.env = MorphEnv().__enter__()
        self.addCleanup(self.env.__exit__, None, None, None)
        self.env.brain_on()
        fast(self.env)
        dash, _ = self.env.store.normalize(DOC)
        self.env.store.write(dash)
        self.env.gitrepo.commit("First", "morph")
        self.env.settings.update({"report_code_issues": True})

    def run_brain(self, work):
        fake = FakeBrain(self.env, work)
        fake.start()
        self.addCleanup(fake.stop.set)
        return fake

    def tell(self, *args, **kw):
        async def go():
            return await finish(self.env, self.env.tell.start(*args, **kw))
        return asyncio.run(go())

    def test_the_prompt_says_morph_is_in_reach_and_where_its_code_is(self):
        fake = self.run_brain(lambda task: {"data": {"summary": "ok", "changed": [], "reload": False}})
        self.tell({"kind": "dashboard"}, "Put a light/dark switch in the header")
        prompt = fake.seen[0]["prompt"]
        self.assertIn("Nothing about Morph is out of reach", prompt)
        self.assertIn(str(self.env.shipped), prompt)
        self.assertIn("/config/morph/frontend/", prompt)
        self.assertIn("Never say you cannot change Morph's code", prompt)
        self.assertNotIn("THE DASHBOARD ONLY", prompt)

    def test_a_tell_that_changed_morph_offers_the_reload_and_asks_with_the_patch(self):
        def work(task):
            code = self.env.morph_dir / "frontend"
            code.mkdir(exist_ok=True)
            own = (self.env.shipped / "morph-panel.js").read_text()
            (code / "morph-panel.js").write_text(own.replace("Back to the dashboard", "Back to the house"))
            # brAIn forgot code_issue: Morph asks anyway.
            return {"data": {"summary": "Renamed the Settings back link", "changed": ["frontend/morph-panel.js"],
                             "reload": True}}
        self.run_brain(work)
        st = self.tell({"kind": "dashboard"}, "Call it Back to the house")
        self.assertEqual(["morph-panel.js"], st["code"])
        self.assertEqual("asked", st["issue"])
        self.assertEqual("Renamed the Settings back link", st["code_issue"]["title"])
        self.assertTrue(self.env.tell.answer_issue(st["id"], "send")["ok"])
        body = self.env.devloop.rows()[0]["body"]
        self.assertIn("```diff", body, "the change goes with the issue")
        self.assertIn("+", body)
        self.assertIn("Back to the house", body)
        self.assertNotIn("```\n```diff", body, "the patch is not wrapped in a second fence")

    def test_a_code_suggestions_do_it_makes_the_change(self):
        sugs = self.env.learning.code_suggestions([{"what": "The header has no theme switch", "detail": "Add one"}])
        self.assertIn("brAIn can make it here", sugs[0]["why"])
        src = (ROOT / "morph" / "service" / "morphd.py").read_text()
        self.assertNotIn('verb = "send"', src, "Do it on a code suggestion is a Tell, not a filing")


class TestBothHalvesAgree(unittest.TestCase):

    def test_the_fixed_files_and_the_name_rule_are_one_rule(self):
        svc = (ROOT / "morph" / "service" / "morphcode.py").read_text()
        static = (COMPONENT / "static.py").read_text()
        for needle in ('NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}\\.js$")', 'FIXED = ("boot.js",)'):
            self.assertIn(needle, svc)
        self.assertIn('NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}\\.js$")', static)
        self.assertIn('FIXED = ("boot.js",)', static)
        self.assertIn('CODE_STATE = SHARED / "code.json"', (COMPONENT / "const.py").read_text())
        self.assertIn('CODE_STATE = SHARED / "code.json"', (ROOT / "morph" / "service" / "paths.py").read_text())

    def test_the_panel_loads_through_boot(self):
        init = (COMPONENT / "__init__.py").read_text()
        self.assertIn('module_url=f"{STATIC_BASE}/{VERSION}/boot.js"', init)
        boot = (COMPONENT / "frontend" / "boot.js").read_text()
        self.assertIn("shipped/morph-panel.js", boot)
        self.assertIn("__morphFallback", boot)


if __name__ == "__main__":
    unittest.main()
