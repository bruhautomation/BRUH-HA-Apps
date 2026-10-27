"""brAIn 4.0: Morph is part of brAIn (docs/design/brain-morph-merge.md).

The four switches (⚙ › Features, panel/features.py) and the one file they
are published in; Personality as a name everywhere and nothing when it is
off; the shell's sidebar entry and brAIn's own ingress entry, of which there
is always exactly one; Morph's service reading the switches; and the wiring
between the shell, brAIn's page and Morph.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
import tempfile
import time
import unittest
import unittest.mock as mock
from pathlib import Path

from morph_env import MorphEnv

ROOT = Path(__file__).resolve().parent.parent
PANEL = ROOT / "brain" / "panel"
INTEGRATION = ROOT / "brain" / "custom_components" / "brain" / "morph"
FRONTEND = INTEGRATION / "frontend"

sys.path.insert(0, str(PANEL))


def _fresh(name, case=None):
    """A fresh import that reads this test's environment, with the module
    the rest of the suite holds put back afterwards (another file patches
    attributes on that one, and a stray copy left behind is read instead)."""
    saved = sys.modules.pop(name, None)
    if case is not None:
        case.addCleanup(lambda: sys.modules.__setitem__(name, saved) if saved is not None
                        else sys.modules.pop(name, None))
    return importlib.import_module(name)


class _Tmp(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / ".brain").mkdir()
        self.features_file = self.root / ".brain" / "features.json"
        self.persona_file = self.root / ".brain" / "personality.json"
        self.dashboard = self.root / "morph" / "dashboard.yaml"
        env = {"BRAIN_FEATURES_FILE": str(self.features_file),
               "BRAIN_PERSONALITY_FILE": str(self.persona_file),
               "BRAIN_MORPH_DASHBOARD": str(self.dashboard)}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.personality = _fresh("personality", self)
        self.features = _fresh("features", self)
        self.dev = mock.patch.object(self.features, "_development", return_value=False)
        self.dev.start()
        self.addCleanup(self.dev.stop)

    def stored(self):
        return json.loads(self.features_file.read_text())


class TestTheSwitches(_Tmp):

    def test_a_house_that_never_chose_keeps_what_it_had(self):
        self.assertEqual({"morph": False, "personality": False, "learning_loop": True,
                          "development_loop": False}, self.features.load())
        self.dashboard.parent.mkdir()
        self.dashboard.write_text("floors: []\n")
        self.persona_file.write_text(json.dumps({"name": "Vesper"}))
        self.assertEqual(True, self.features.load()["morph"], "it had the Morph add-on")
        self.assertEqual(True, self.features.load()["personality"], "it had named brAIn")

    def test_the_first_publish_decides_the_defaults_once(self):
        self.dashboard.parent.mkdir()
        self.dashboard.write_text("floors: []\n")
        self.features.ensure()
        self.assertTrue(self.stored()["morph"])
        self.dashboard.unlink()
        self.assertTrue(self.features.load()["morph"],
                        "a dashboard file going away does not turn a switch off")

    def test_a_refusal_is_a_sentence_before_anything_is_saved(self):
        self.assertEqual("", self.features.refusal({"morph": True}))
        self.assertIn("unknown switch", self.features.refusal({"telemetry": True}))
        self.assertIn("true or false", self.features.refusal({"morph": 1}))
        self.assertTrue(self.features.refusal({}))
        self.assertFalse(self.features_file.exists())

    def test_save_takes_only_switches_and_only_true_or_false(self):
        with self.assertRaises(ValueError):
            self.features.save({"telemetry": True})
        with self.assertRaises(ValueError):
            self.features.save({"morph": "yes"})
        out = self.features.save({"morph": True, "learning_loop": False})
        self.assertTrue(out["morph"])
        self.assertFalse(out["learning_loop"])
        self.assertEqual(False, self.stored()["learning_loop"])

    def test_the_development_switch_is_the_devloops_own(self):
        fake = mock.Mock()
        with mock.patch.object(self.features, "_devloop", return_value=fake):
            self.features.save({"development_loop": True})
        fake.save_settings.assert_called_once_with({"enabled": True})
        self.assertNotIn("development_loop", {k for k in self.features.OWN})

    def test_the_file_carries_the_name_only_while_personality_is_on(self):
        self.persona_file.write_text(json.dumps({"name": "Vesper"}))
        self.assertEqual("Vesper", self.features.save({"personality": True})["name"])
        self.assertEqual("Vesper", self.stored()["name"])
        self.assertEqual("brAIn", self.features.save({"personality": False})["name"])
        self.assertEqual("brAIn", self.stored()["name"])

    def test_publish_never_creates_its_own_folder(self):
        with mock.patch.object(self.features, "FILE", str(self.root / "nowhere" / "features.json")):
            self.features.publish()
        self.assertFalse((self.root / "nowhere").exists())


class TestPersonalityIsOneSwitch(_Tmp):

    def setUp(self):
        super().setUp()
        self.persona_file.write_text(json.dumps({"name": "Vesper", "persona": "Warm and brief."}))

    def test_on_it_is_the_name_everywhere(self):
        self.features.save({"personality": True})
        p = self.personality
        self.assertEqual("Vesper", p.assistant_name())
        self.assertIn("Your name is Vesper.", p.prompt_block())
        self.assertEqual("Vesper can fix this. Run `brain undo`.",
                         p.speak("brAIn can fix this. Run `brain undo`."))

    def test_off_the_stored_one_is_kept_and_nothing_reads_it(self):
        self.features.save({"personality": False})
        p = self.personality
        self.assertEqual("brAIn", p.assistant_name())
        self.assertEqual("", p.prompt_block())
        self.assertEqual("", p.section())
        self.assertEqual("brAIn can fix this.", p.speak("brAIn can fix this."))
        self.assertEqual("Vesper", p.load()["name"], "kept for when it is switched back on")

    def test_no_switches_written_is_on(self):
        self.assertTrue(self.personality.enabled())

    def test_a_notification_says_the_name(self):
        self.features.save({"personality": True})
        router = _fresh("notify_router", self)
        title, body = router.compose([{"severity": "warning", "text": "brAIn saw the door open."}])
        self.assertTrue(title.startswith("Vesper"))
        self.assertIn("Vesper saw the door open.", body)


class TestOneSidebarEntryNeverNone(unittest.TestCase):

    def setUp(self):
        self.link = _fresh("shell_link", self)

    def test_decide(self):
        d = self.link.decide
        self.assertEqual(False, d(True, True, False), "the shell is there: hide ours")
        self.assertEqual(True, d(False, False, True), "the shell is gone: put back what we hid")
        self.assertIsNone(d(False, False, False), "a hide that was the person's stays")
        self.assertIsNone(d(None, True, False), "the Supervisor did not say")
        self.assertIsNone(d(False, True, True))

    def test_the_mark_goes_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            mark = Path(tmp) / "shell.json"
            self.assertFalse(self.link.shell_fresh(path=str(mark)))
            mark.write_text(json.dumps({"at": int(time.time())}))
            self.assertTrue(self.link.shell_fresh(path=str(mark)))
            later = time.time() + self.link.SHELL_STALE_S + 1
            self.assertFalse(self.link.shell_fresh(now=later, path=str(mark)))

    def test_sync_hides_then_shows_and_records_whose_hide_it_was(self):
        with tempfile.TemporaryDirectory() as tmp:
            hidden = os.path.join(tmp, "hidden.json")
            mark = os.path.join(tmp, "shell.json")
            info = {"ingress_url": "/api/hassio_ingress/abcdefghijkl/", "slug": "x_brain",
                    "ingress_panel": True}
            calls = []

            class Opts:
                OptionsError = RuntimeError

                @staticmethod
                def available():
                    return True

                @staticmethod
                async def refresh():
                    return {}

                @staticmethod
                def ingress():
                    return dict(info)

                @staticmethod
                async def set_ingress_panel(on):
                    calls.append(on)
                    info["ingress_panel"] = on

            with mock.patch.object(self.link, "HIDDEN_FILE", hidden), \
                    mock.patch.object(self.link, "SHELL_FILE", mark), \
                    mock.patch.object(self.link, "INGRESS_FILE", os.path.join(tmp, "ingress.json")):
                Path(mark).write_text(json.dumps({"at": int(time.time())}))
                self.assertEqual("hidden", asyncio.run(self.link.sync(Opts)))
                self.assertTrue(self.link.we_hid(hidden))
                self.assertEqual("/api/hassio_ingress/abcdefghijkl/",
                                 json.loads(Path(tmp, "ingress.json").read_text())["ingress_url"])
                os.unlink(mark)
                self.assertEqual("shown", asyncio.run(self.link.sync(Opts)))
                self.assertFalse(self.link.we_hid(hidden))
                self.assertEqual([False, True], calls)


class TestTheIntegrationReadsTheSwitches(unittest.TestCase):

    def _switches(self):
        sys.path.insert(0, str(INTEGRATION.parent.parent))
        try:
            sys.modules.pop("brain.morph.switches", None)
            import types
            pkg = types.ModuleType("brainpkg")
            pkg.__path__ = [str(INTEGRATION)]
            sys.modules["brainpkg"] = pkg
            sys.modules.pop("brainpkg.const", None)
            sys.modules.pop("brainpkg.switches", None)
            return importlib.import_module("brainpkg.switches")
        finally:
            sys.path.remove(str(INTEGRATION.parent.parent))

    def test_read_features_and_the_panel_they_give(self):
        sw = self._switches()
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "features.json"
            self.assertEqual("brAIn", sw.read_features(f)["name"])
            self.assertFalse(sw.read_features(f)["morph"])
            f.write_text(json.dumps({"morph": True, "personality": True, "name": "Vesper"}))
            self.assertEqual("Vesper", sw.read_features(f)["name"])
            f.write_text(json.dumps({"morph": True, "personality": False, "name": "Vesper"}))
            self.assertEqual("brAIn", sw.read_features(f)["name"], "off is brAIn, whatever the file says")

    def test_the_panel_is_administrators_only_without_the_dashboard(self):
        src = (INTEGRATION / "__init__.py").read_text()
        self.assertIn('"require_admin": not features.get("morph")', src)
        self.assertIn('"title": features.get("name") or PANEL_TITLE', src)


class TestMorphsServiceReadsTheSwitches(unittest.TestCase):

    def test_the_two_loops_are_brains_switches_and_a_stored_value_is_ignored(self):
        with MorphEnv() as env:
            env.switch(learning_loop=False, development_loop=False)
            s = env.settings.update({"learning": True, "report_code_issues": True, "theme": "dark"})
            self.assertFalse(s["learning"])
            self.assertFalse(s["report_code_issues"])
            self.assertEqual("dark", s["theme"])
            env.switch(learning_loop=True, development_loop=True)
            s = env.settings.load()
            self.assertTrue(s["learning"])
            self.assertTrue(s["report_code_issues"])

    def test_switched_off_the_service_waits(self):
        with MorphEnv() as env:
            self.assertTrue(env.settings.morph_on())
            env.switch(morph=False)
            self.assertFalse(env.settings.morph_on())
        src = (ROOT / "brain" / "morph" / "service" / "morphd.py").read_text()
        self.assertIn("while not settings.morph_on():", src)
        self.assertIn("OFF_ERROR", src)


class TestDashboardSettingsGoThroughTheServicesFolder(unittest.TestCase):

    def test_only_the_dashboards_presses_are_let_through(self):
        svc = _fresh("morph_service", self)
        self.assertFalse(svc.request("tell", {})["ok"])
        self.assertFalse(svc.request("save", {})["ok"])
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(svc, "SHARED", Path(tmp)):
            got = svc.request("history", {"limit": 1}, timeout=0.3)
            self.assertFalse(got["ok"])
            self.assertEqual([], list((Path(tmp) / "requests").glob("*.json")),
                             "a request nobody answered is withdrawn")


class TestTheWiring(unittest.TestCase):

    def test_the_shell_and_the_page_speak_one_protocol(self):
        shell = (FRONTEND / "shell.js").read_text()
        app = (PANEL / "app.js").read_text()
        html = (PANEL / "index.html").read_text()
        for word in ("bars", "show", "raise", "menu", "features", "ready"):
            self.assertIn(word, shell)
            self.assertIn(f"{word}:", app)
        self.assertIn("ev.source !== this.frame.contentWindow", shell)
        self.assertIn("ev.source !== window.parent", app)
        self.assertIn("/ingress/session", shell)
        self.assertIn("/ingress/validate_session", shell)
        self.assertIn('id="homeTab"', html)
        self.assertIn('id="viewHome"', html)
        # The shell is declared before any view switch can read it.
        self.assertLess(app.index("const SHELL ="), app.index("function switchView("))

    def test_morph_has_no_settings_page_and_opens_brains(self):
        js = (FRONTEND / "morph-panel.js").read_text()
        self.assertNotIn("settingsHtml", js)
        self.assertNotIn("data-v=\"settings\"", js)
        self.assertIn("'brain-open'", js)
        self.assertIn("speak(html)", js)

    def test_features_is_the_first_section_and_warns_about_morph(self):
        html = (PANEL / "index.html").read_text()
        nav = html[html.index('id="setNav"'):]
        self.assertLess(nav.index('data-sec="features"'), nav.index('data-sec="account"'))
        sec = html[html.index('id="setsecFeatures"'):html.index('id="setsecDashboard"')]
        for needle in ('data-feature="morph"', 'data-feature="personality"',
                       'data-feature="learning_loop"', 'id="setDevloop"',
                       "actively", "may be unstable", "Leaves this house", "Stays in this house"):
            self.assertIn(needle, sec)
        self.assertEqual(1, html.count('id="setDevloop"'), "one development switch, not two")


if __name__ == "__main__":
    unittest.main()
