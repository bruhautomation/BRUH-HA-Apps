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
COMPONENT = ROOT / "brain" / "custom_components" / "brain" / "morph"


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

    # Opening Morph quickly: the modules are fetched under s/<stamp>/ and
    # cached for good, so the stamp has to move whenever what a module URL
    # answers with does, and never otherwise.
    def kw(self):
        return {"frontend": self.frontend, "code_dir": self.code, "code_state": self.state}

    def test_the_stamp_names_the_code_being_served(self):
        a = self.static.stamp(**self.kw())
        self.assertRegex(a, r"^[0-9a-f]{12}$")
        self.assertEqual(a, self.static.stamp(**self.kw()), "nothing moved, so the name did not")
        self.say(("styles.js", "active"))
        b = self.static.stamp(**self.kw())
        self.assertNotEqual(a, b, "a copy coming into use is different code")
        (self.frontend / "morph-panel.js").write_text("// Morph's own, updated, and longer\n")
        self.assertNotEqual(b, self.static.stamp(**self.kw()), "an update to Morph's own files is different code")

    def test_boot_is_served_with_the_stamp_and_the_modules(self):
        (self.frontend / "boot.js").write_text("const STAMP = '';\nconst MODULES = [];\n")
        src = self.static.boot_source(**self.kw())
        self.assertIn(f"const STAMP = \"{self.static.stamp(**self.kw())}\";", src)
        self.assertIn('const MODULES = ["morph-panel.js", "styles.js"];', src, "every module but the loader")

    def test_a_stamped_module_is_cached_only_under_the_current_stamp(self):
        self.say(("styles.js", "active"))
        now = self.static.stamp(**self.kw())
        body, current = self.static.stamped("styles.js", now, **self.kw())
        self.assertEqual(b"// this house's\n", body)
        self.assertTrue(current)
        body, current = self.static.stamped("styles.js", "0123456789ab", **self.kw())
        self.assertEqual(b"// this house's\n", body, "an old page still gets today's file")
        self.assertFalse(current, "but not cached for good under a name it does not match")
        self.assertIsNone(self.static.stamped("../const.py", now, **self.kw()))

    def test_the_panel_element_is_the_shell_and_load_carries_the_stamp(self):
        # brAIn's shell is the panel's element since 4.0; it loads Morph's
        # boot.js, which is still the loader that falls back.
        self.assertIn('ELEMENT = "brain-shell"', (COMPONENT / "const.py").read_text())
        shell = (COMPONENT / "frontend" / "shell.js").read_text()
        self.assertIn("customElements.define('brain-shell'", shell)
        self.assertIn("import(here + 'boot.js')", shell)
        boot = (COMPONENT / "frontend" / "boot.js").read_text()
        self.assertIn("customElements.define('morph-boot'", boot)
        self.assertIn("const STAMP = '';", boot)
        self.assertIn("const MODULES = [];", boot)
        ws = (COMPONENT / "websocket.py").read_text()
        self.assertIn('"code": _code_stamp(), "integration": VERSION', ws)


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
        self.env.switch(development_loop=True)

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
        self.assertNotIn(".base/", body, "Morph's own original is not part of the change")

    def test_a_code_suggestions_do_it_makes_the_change(self):
        sugs = self.env.learning.code_suggestions([{"what": "The header has no theme switch", "detail": "Add one"}])
        self.assertIn("brAIn can make it here", sugs[0]["why"])
        src = (ROOT / "brain" / "morph" / "service" / "morphd.py").read_text()
        self.assertNotIn('verb = "send"', src, "Do it on a code suggestion is a Tell, not a filing")


class TestBothHalvesAgree(unittest.TestCase):

    def test_the_fixed_files_and_the_name_rule_are_one_rule(self):
        svc = (ROOT / "brain" / "morph" / "service" / "morphcode.py").read_text()
        static = (COMPONENT / "static.py").read_text()
        for needle in ('NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}\\.js$")', 'FIXED = ("boot.js", "shell.js")'):
            self.assertIn(needle, svc)
        self.assertIn('NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}\\.js$")', static)
        self.assertIn('FIXED = ("boot.js", "shell.js")', static)
        self.assertIn('CODE_STATE = SHARED / "code.json"', (COMPONENT / "const.py").read_text())
        self.assertIn('CODE_STATE = SHARED / "code.json"', (ROOT / "brain" / "morph" / "service" / "paths.py").read_text())

    def test_the_panel_loads_through_boot(self):
        init = (COMPONENT / "__init__.py").read_text()
        self.assertIn('"module_url": f"{STATIC_BASE}/{VERSION}/shell.js"', init)
        boot = (COMPONENT / "frontend" / "boot.js").read_text()
        self.assertIn("shipped/morph-panel.js", boot)
        self.assertIn("__morphFallback", boot)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(HAS_GIT, "git is not installed")
class TestMakingAPausedChangeAgain(unittest.TestCase):
    """"Make it again" (house report: "I click make it again and nothing
    happens"): the request has to give brAIn what it needs for a real
    redo, and a second press must not start a second one."""

    def setUp(self):
        self.env = MorphEnv().__enter__()
        self.addCleanup(self.env.__exit__, None, None, None)
        self.env.brain_on()
        fast(self.env)
        dash, _ = self.env.store.normalize(DOC)
        self.env.store.write(dash)
        self.env.gitrepo.commit("First", "morph")
        self.code = self.env.morph_dir / "frontend"
        self.code.mkdir()
        self.before = (self.env.shipped / "styles.js").read_text()
        (self.code / "styles.js").write_text(self.before + "/* a theme switch */\n")
        self.env.gitrepo.commit("brAIn: Put a light/dark switch in the header", "brain")
        (self.env.shipped / "styles.js").write_text(self.before + "/* next release */\n")

    def test_morphs_own_file_the_change_was_written_against_is_kept(self):
        kept = self.env.morphcode.kept_base("styles.js")
        self.assertIsNotNone(kept)
        self.assertEqual(self.before, kept.read_text(), "the ORIGINAL, not the new release")
        self.assertIn("frontend/.base/styles.js",
                      self.env.gitrepo.changed_files(self.env.gitrepo.head()),
                      "committed with the copy, so Undo takes both")
        self.assertEqual({"styles.js": "paused"},
                         {r["name"]: r["status"] for r in self.env.morphcode.status()},
                         "the kept original is not itself a copy")

    def test_the_request_is_a_three_way_merge_with_the_history(self):
        history = [c["message"] for c in self.env.gitrepo.log(12, "frontend/styles.js")]
        words = self.env.morphcode.redo_words("styles.js", "0.5.2", history)
        self.assertTrue(words.startswith("Make my change to Morph's styles.js again on the new Morph (0.5.2)."))
        self.assertIn(str(self.env.morphcode.kept_base("styles.js")), words)
        self.assertIn(str(self.env.shipped / "styles.js"), words)
        self.assertIn("three-way merge", words)
        self.assertIn("brAIn: Put a light/dark switch in the header", words)
        self.assertNotIn("First", words, "only commits that touched the file")

    def test_the_merge_never_swaps_a_house_component_for_morphs_own_silently(self):
        # #541: a merge swapped an import of a house module for upstream's.
        for words in (self.env.morphcode.redo_words("styles.js", "0.5.2", []),
                      self.env.morphcode.redo_all_words(["styles.js"], "0.5.2")):
            self.assertIn("Never replace a component of this house's with Morph's own equivalent", words)
            self.assertIn("swapping an import of a house module for a built-in one", words)
            self.assertIn("unless your summary says so", words)

    def test_without_a_kept_original_brain_is_told_not_to_copy_the_old_file_over(self):
        (self.code / ".base" / "styles.js").unlink()
        self.assertIsNone(self.env.morphcode.kept_base("styles.js"))
        words = self.env.morphcode.redo_words("styles.js", "0.5.2", [])
        self.assertIn("was not kept", words)
        self.assertIn("Never copy the old file over the new one", words)

    def test_putting_morphs_own_back_drops_the_kept_original(self):
        ok, _ = self.env.morphcode.reset("styles.js")
        self.assertTrue(ok)
        self.assertFalse((self.code / ".base" / "styles.js").exists())

    def test_a_second_press_shows_the_running_redo(self):
        morphd = importlib.import_module("morphd")

        async def go():
            first = await morphd.handle("code_redo", {"name": "styles.js"})
            second = await morphd.handle("code_redo", {"name": "styles.js"})
            for t in list(self.env.tell._RUNNING.values()):
                t.cancel()
            return first, second
        first, second = asyncio.run(go())
        self.assertTrue(first["ok"], first)
        self.assertEqual("code", first["target"]["kind"])
        self.assertEqual(first["id"], second["id"], "one redo per file")
        self.assertTrue(second.get("already"))

    def test_a_tell_hands_what_it_learned_about_the_house_to_brains_memory(self):
        """A Tell is a task run; brAIn's action gate refuses remember_fact
        there (house report: "A system gate blocked the save"). The facts
        ride in the answer and Morph queues them in brAIn's inbox."""
        (self.env.brain_shared / "memory").mkdir(parents=True)
        fake = FakeBrain(self.env, lambda task: {"data": {
            "summary": "Added an Upstairs HVAC card", "changed": ["cards/morph-hvac-flow.js"], "reload": True,
            "facts": [{"fact": "Govee 1 measures the upstairs HVAC return air.", "subject": "sensor.govee_1_temperature"},
                      {"fact": "  ", "subject": "house"},
                      {"fact": "Govee 2 measures supply air.", "subject": "not a subject; rm -rf"}]}})
        fake.start()
        self.addCleanup(fake.stop.set)

        async def go():
            return await finish(self.env, self.env.tell.start({"kind": "dashboard"}, "Add an HVAC card"))
        st = asyncio.run(go())
        self.assertNotIn("remember_fact. LEARNED", fake.seen[0]["prompt"])
        self.assertIn("put it in `facts`", fake.seen[0]["prompt"])
        files = list((self.env.brain_shared / "memory" / "inbox").glob("*.jsonl"))
        self.assertEqual(1, len(files))
        rows = [json.loads(x) for x in files[0].read_text().splitlines()]
        self.assertEqual(["Govee 1 measures the upstairs HVAC return air.", "Govee 2 measures supply air."],
                         [r["fact"] for r in rows])
        self.assertEqual({"morph"}, {r["source"] for r in rows})
        self.assertEqual("sensor.govee_1_temperature", rows[0]["subject"])
        self.assertNotIn("subject", rows[1], "a subject that is not one is dropped, the fact kept")
        self.assertTrue(any("Queued 2 facts" in x["t"] for x in st["steps"]))

    def test_no_brain_memory_folder_means_nothing_is_written(self):
        self.assertEqual(0, self.env.tell.queue_facts([{"fact": "x"}], "morph-abc"))
        self.assertFalse((self.env.brain_shared / "memory").exists())


@unittest.skipUnless(HAS_GIT, "git is not installed")
class TestAnUpdateToAnotherModulePausesTheCopy(unittest.TestCase):
    """A copy of morph-panel.js imports engine.js, cards.js and the rest:
    an update that changes engine.js and not morph-panel.js still leaves
    last release's panel beside this release's engine. The copy pauses
    whenever any of Morph's modules moved, and a redo brAIn answered puts it
    back in use whether or not brAIn had to edit it."""

    def setUp(self):
        self.env = MorphEnv().__enter__()
        self.addCleanup(self.env.__exit__, None, None, None)
        self.env.brain_on()
        fast(self.env)
        dash, _ = self.env.store.normalize(DOC)
        self.env.store.write(dash)
        self.env.gitrepo.commit("First", "morph")
        self.code = self.env.morph_dir / "frontend"
        self.code.mkdir()
        (self.code / "styles.js").write_text((self.env.shipped / "styles.js").read_text() + "/* a theme switch */\n")
        self.env.gitrepo.commit("brAIn: a theme switch", "brain")

    def rows(self):
        return {r["name"]: r for r in self.env.morphcode.status()}

    def test_a_change_to_another_module_pauses_and_names_it(self):
        self.assertEqual("active", self.rows()["styles.js"]["status"])
        engine = self.env.shipped / "engine.js"
        engine.write_text(engine.read_text() + "/* next release */\n")
        row = self.rows()["styles.js"]
        self.assertEqual("paused", row["status"])
        self.assertEqual("others", row["why"])
        self.assertEqual(["engine.js"], row["moved"])
        words = self.env.morphcode.redo_words("styles.js", "0.5.4", [])
        self.assertTrue(words.startswith("Make my change to Morph's styles.js work on the new Morph (0.5.4)."))
        self.assertIn("engine.js", words)
        self.assertIn("If it already fits, leave it", words)

    def test_a_record_from_before_others_were_kept_is_filled_in_on_the_next_commit(self):
        base = self.code / ".base.json"
        data = json.loads(base.read_text())
        data["styles.js"].pop("others")
        base.write_text(json.dumps(data))
        engine = self.env.shipped / "engine.js"
        engine.write_text(engine.read_text() + "/* an update nobody recorded */\n")
        self.assertEqual("active", self.rows()["styles.js"]["status"], "nothing to compare with: not guessed")
        self.env.morphcode.record_bases()
        engine.write_text(engine.read_text() + "/* the next one */\n")
        self.assertEqual("paused", self.rows()["styles.js"]["status"])

    def test_a_redo_brain_answers_without_editing_puts_the_copy_back_in_use(self):
        engine = self.env.shipped / "engine.js"
        engine.write_text(engine.read_text() + "/* next release */\n")
        fake = FakeBrain(self.env, lambda task: {"data": {"summary": "It still fits the new engine.js.",
                                                           "changed": [], "reload": False}})
        fake.start()
        self.addCleanup(fake.stop.set)

        async def go():
            st = self.env.tell.start({"kind": "code", "id": "styles.js", "label": "styles.js"},
                                     self.env.morphcode.redo_words("styles.js", "0.5.4", []))
            return await finish(self.env, st)
        st = asyncio.run(go())
        self.assertEqual("done", st["phase"])
        self.assertEqual("active", self.rows()["styles.js"]["status"])
        self.assertIn("frontend/.base.json", self.env.gitrepo.changed_files(st["commit"]),
                      "the record goes in the tell's commit, so Undo pauses it again")
        ok, _ = self.env.gitrepo.revert(st["commit"])
        self.assertTrue(ok)
        self.assertEqual("paused", self.rows()["styles.js"]["status"])

    def test_a_merge_brain_will_not_guess_at_asks_and_stays_paused_until_answered(self):
        engine = self.env.shipped / "engine.js"
        engine.write_text(engine.read_text() + "/* next release */\n")
        words = self.env.morphcode.redo_words("styles.js", "0.5.5", [])
        self.assertIn("do not guess", words)
        self.assertIn("one that uses Morph's own", words)

        def work(task):
            if len(fake.seen) == 1:
                return {"data": {"summary": "The update rewrote the header.", "changed": [], "reload": False,
                                 "question": {"text": "Where should the switch go?", "options": [
                                     {"label": "Beside the menu", "request": "Put it beside the menu in styles.js."},
                                     {"label": "Use Morph's own", "request": "Delete /config/morph/frontend/styles.js."}]}}}
            return {"data": {"summary": "Put it beside the menu.", "changed": [], "reload": True}}
        fake = FakeBrain(self.env, work)
        fake.start()
        self.addCleanup(fake.stop.set)

        async def go():
            first = await finish(self.env, self.env.tell.start(
                {"kind": "code", "id": "styles.js", "label": "styles.js"}, words))
            paused = self.rows()["styles.js"]["status"]
            second = await finish(self.env, self.env.tell.answer_question(first["id"], 0))
            return first, paused, second
        first, paused, second = asyncio.run(go())
        self.assertEqual("done", first["phase"])
        self.assertEqual(2, len(first["question"]["options"]))
        self.assertEqual("paused", paused, "a question is not a merge: the copy stays paused")
        self.assertEqual("code", second["target"]["kind"])
        self.assertEqual("active", self.rows()["styles.js"]["status"], "the answered merge puts it back in use")

    def test_a_redo_that_failed_leaves_it_paused(self):
        engine = self.env.shipped / "engine.js"
        engine.write_text(engine.read_text() + "/* next release */\n")
        fake = FakeBrain(self.env, lambda task: {"status": "failed", "error": "auth", "result": "signed out"})
        fake.start()
        self.addCleanup(fake.stop.set)

        async def go():
            st = self.env.tell.start({"kind": "code", "id": "styles.js", "label": "styles.js"}, "redo")
            return await finish(self.env, st)
        asyncio.run(go())
        self.assertEqual("paused", self.rows()["styles.js"]["status"])


@unittest.skipUnless(HAS_GIT, "git is not installed")
class TestBrainAsksWhenTheChoiceIsTheirs(unittest.TestCase):
    """A card that works a number out from other sensors has no history
    unless Home Assistant holds it as an entity. brAIn asks; the answer is
    the next request, started from the option stored with the tell, and
    only the button that said it changes Home Assistant may."""

    def setUp(self):
        self.env = MorphEnv().__enter__()
        self.addCleanup(self.env.__exit__, None, None, None)
        self.env.brain_on()
        fast(self.env)
        dash, _ = self.env.store.normalize(DOC)
        self.env.store.write(dash)
        self.env.gitrepo.commit("First", "morph")

    def answer(self, task):
        if len(self.fake.seen) > 1:
            return {"data": {"summary": "Made the sensor.", "changed": ["sensor.hvac_delta"], "reload": False}}
        return {"data": {"summary": "Added the card.", "changed": [], "reload": True,
                         "question": {"text": "Keep a history of the supply/return difference?",
                                      "options": [{"label": "Calculate it in the card", "request": "Keep it in the card."},
                                                  {"label": "Make a sensor", "home_assistant": True,
                                                   "request": "Make a template sensor sensor.hvac_delta and use it."},
                                                  {"label": "", "request": "dropped"}]}}}

    def test_the_prompt_asks_about_history_and_the_answer_reaches_the_house_only_when_it_says_so(self):
        self.fake = FakeBrain(self.env, self.answer)
        self.fake.start()
        self.addCleanup(self.fake.stop.set)
        morphd = importlib.import_module("morphd")

        async def go():
            first = await finish(self.env, self.env.tell.start({"kind": "dashboard"}, "Add an HVAC card"))
            wrong = await morphd.handle("tell_answer", {"id": first["id"], "choice": 7})
            out = await morphd.handle("tell_answer", {"id": first["id"], "choice": 1})
            again = await morphd.handle("tell_answer", {"id": first["id"], "choice": 0})
            second = await finish(self.env, out)
            return first, wrong, out, again, second
        first, wrong, out, again, second = asyncio.run(go())
        # The calculated-sensor rule lives in AGENTS.md's "when to ask"
        # list; the prompt points there rather than carrying a second copy.
        self.assertIn("When to ask", self.fake.seen[0]["prompt"])
        self.assertNotIn("has no history", self.fake.seen[0]["prompt"])
        agents = (self.env.paths.DEFAULTS / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("has no history", agents)
        self.assertEqual(2, len(first["question"]["options"]), "an option with no label is not a button")
        self.assertFalse(wrong["ok"])
        self.assertTrue(out["ok"], out)
        self.assertEqual("Make a template sensor sensor.hvac_delta and use it.", out["text"])
        self.assertEqual("house", out["scope"])
        self.assertIn("Scope: this request is about Home Assistant itself", self.fake.seen[1]["prompt"])
        self.assertFalse(again["ok"], "one answer per question")
        self.assertEqual(1, self.env.tell.read_state(first["id"])["answered"])
        self.assertEqual(["sensor.hvac_delta"], second["house"])

    def test_the_card_only_answer_stays_on_the_dashboard(self):
        self.fake = FakeBrain(self.env, self.answer)
        self.fake.start()
        self.addCleanup(self.fake.stop.set)

        async def go():
            first = await finish(self.env, self.env.tell.start({"kind": "dashboard"}, "Add an HVAC card"))
            out = self.env.tell.answer_question(first["id"], 0)
            return await finish(self.env, out)
        second = asyncio.run(go())
        self.assertEqual("ui", second["scope"])
        self.assertIn("Scope: everything the request needs", self.fake.seen[1]["prompt"])

    def test_a_question_that_is_not_one_is_dropped(self):
        clean = self.env.tell.clean_question
        self.assertIsNone(clean("yes?"))
        self.assertIsNone(clean({"text": "One option?", "options": [{"label": "a", "request": "b"}]}))
        self.assertIsNone(clean({"text": "", "options": [{"label": "a", "request": "b"}] * 2}))
        q = clean({"text": "Pick", "options": [{"label": "a", "request": "b", "home_assistant": "yes"}] * 2})
        self.assertFalse(q["options"][0]["home_assistant"], "only a literal true changes Home Assistant")
