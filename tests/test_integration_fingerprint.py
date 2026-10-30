"""A restart of Home Assistant only when one is needed, for every BRUH add-on.

Every add-on release bumps its integration's manifest version (CI holds the
versions together), and every add-on asked for a restart of Home Assistant
whenever the version moved — so an update that did not change one byte of
the integration's Python still said "restart Home Assistant". The owner's
words: "If a restart isn't required, don't say it needs one."

The rule now, the same in every add-on: a restart is owed only when the code
Home Assistant LOADED differs from the code deployed. Both sides are one
fingerprint (`fingerprint.py`, copied into every integration, and its shell
twin `integration_fingerprint`, copied into every run.sh): the files Core
reads at load, without the release's version line, never the browser's
files. The integration records the fingerprint of what it imported; run.sh
(or Bambu's panel) compares. A record without one was written by an older
integration, which cannot say what it loaded: a restart, once.

Driven, not grepped: the shell functions are lifted out of the real run.sh
files and run in bash, the integrations' own modules are loaded behind
stubs, and the panel reads what the integration wrote.
"""
from __future__ import annotations

import asyncio
import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
import unittest.mock
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
REPO = TESTS.parent
sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(REPO / "brain" / "panel"))

import brain_ha_env as env  # noqa: E402
import health  # noqa: E402

# add-on folder, integration folder, where its integration records what it loaded
ADDONS = {
    "brain": ("brain", "brain", "/config/.brain/integration_loaded.json"),
    "bruh-bambu-studio": ("bruh-bambu-studio", "bruh_bambu", "/config/.bruh_bambu/integration.json"),
    "bruh-cooking": ("bruh-cooking", "bruh_cooking", "/config/.bruh_cooking/integration.json"),
    "gardenrx": ("gardenrx", "gardenrx", "/config/.gardenrx/integration.json"),
    "bright": ("bright", "bright", "/config/.bright/integration.json"),
    "bruh-print": ("bruh-print", "bruh_print", "/config/.bruh_print/integration.json"),
    "bruh-task-manager": ("bruh-task-manager", "bruh_task_manager",
                          "/config/.bruh_task_manager/integration.json"),
    "bruh-minecraft-server": ("bruh-minecraft-server", "bruh_minecraft",
                              "/config/.bruh_minecraft/integration.json"),
}
BRAIN_INTEGRATION = REPO / "brain" / "custom_components" / "brain"


def integration_dir(key: str) -> Path:
    addon, domain, _ = ADDONS[key]
    return REPO / addon / "custom_components" / domain


def load_fingerprint(path: Path):
    spec = importlib.util.spec_from_file_location(f"fp_{abs(hash(str(path)))}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FP = load_fingerprint(BRAIN_INTEGRATION / "fingerprint.py")


def shell_function(run_sh: Path, name: str) -> str:
    """One function, lifted out of a run.sh exactly as written."""
    text = run_sh.read_text()
    match = re.search(rf"^{re.escape(name)}\(\) \{{\n.*?^\}}\n", text, re.M | re.S)
    assert match, f"{run_sh} has no {name}()"
    return match.group(0)


def shell(script: str, *args: str, cwd: str | None = None) -> str:
    done = subprocess.run(["bash", "-c", script, "bash", *args], capture_output=True,
                          text=True, timeout=30, cwd=cwd)
    assert done.returncode == 0, done.stderr
    return done.stdout


def shell_fingerprint(directory: Path, run_sh: Path | None = None) -> str:
    fn = shell_function(run_sh or REPO / "brain" / "run.sh", "integration_fingerprint")
    return shell(fn + '\nintegration_fingerprint "$1"', str(directory)).strip()


class TestOneFingerprintEverywhere(unittest.TestCase):
    """One rule, so one file and one shell function, copied and identical."""

    def test_every_integration_carries_the_same_fingerprint_py(self):
        brain = (BRAIN_INTEGRATION / "fingerprint.py").read_text()
        copies = [integration_dir(k) / "fingerprint.py" for k in ADDONS]
        copies.append(REPO / "bruh-bambu-studio" / "panel" / "integration_fingerprint.py")
        for path in copies:
            with self.subTest(copy=str(path.relative_to(REPO))):
                self.assertEqual(brain, path.read_text(), "a copy drifted from brAIn's")

    def test_every_run_sh_carries_the_same_shell_twin(self):
        brain = REPO / "brain" / "run.sh"
        for name in ("integration_fingerprint", "integration_restart_verdict"):
            want = shell_function(brain, name)
            for key in ADDONS:
                with self.subTest(addon=key, function=name):
                    self.assertEqual(want, shell_function(REPO / ADDONS[key][0] / "run.sh", name))

    def test_shell_and_python_agree_on_every_real_integration(self):
        for key in ADDONS:
            with self.subTest(addon=key):
                directory = integration_dir(key)
                py = FP.fingerprint(str(directory))
                self.assertRegex(py, r"^f1-[0-9a-f]{16}$")
                self.assertEqual(py, shell_fingerprint(directory, REPO / ADDONS[key][0] / "run.sh"))

    def test_every_integration_records_where_its_add_on_reads(self):
        """The record the integration writes is the one its add-on reads."""
        for key, (addon, _domain, record) in ADDONS.items():
            if key in ("brain", "bruh-bambu-studio"):
                continue  # driven below, through their own readers
            with self.subTest(addon=key):
                rel = record.removeprefix("/config/")
                source = (integration_dir(key) / "__init__.py").read_text()
                self.assertIn(rel, source)
                run_sh = (REPO / addon / "run.sh").read_text()
                run_sh = re.sub(r'"\$\{(GARDENRX|COOKING)_SHARED\}/', '"' + str(Path(record).parent) + "/", run_sh)
                self.assertIn(f'"{record}")" = "needed"', run_sh)


class TestWhatMovesTheFingerprint(unittest.TestCase):
    """What a restart would load moves it; the version and the browser's
    files do not. Each case is asked of Python and of the shell twin."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.dir = self.tmp / "brain"
        shutil.copytree(BRAIN_INTEGRATION, self.dir,
                        ignore=shutil.ignore_patterns("__pycache__"))
        self.before = FP.fingerprint(str(self.dir))

    def after(self) -> str:
        py = FP.fingerprint(str(self.dir))
        self.assertEqual(py, shell_fingerprint(self.dir), "the shell twin disagreed")
        return py

    def test_a_version_only_release_owes_no_restart(self):
        manifest = self.dir / "manifest.json"
        manifest.write_text(re.sub(r'"version": "[^"]+"', '"version": "99.1.2"', manifest.read_text()))
        # GardenRX's const.py carries the release in step with the manifest.
        (self.dir / "const.py").write_text((self.dir / "const.py").read_text() + 'VERSION = "99.1.2"\n')
        before = FP.fingerprint(str(self.dir))
        (self.dir / "const.py").write_text(
            (self.dir / "const.py").read_text().replace('VERSION = "99.1.2"', 'VERSION = "99.1.3"'))
        self.assertEqual(before, self.after())

    def test_a_manifest_version_bump_alone_leaves_it(self):
        manifest = self.dir / "manifest.json"
        manifest.write_text(re.sub(r'"version": "[^"]+"', '"version": "99.1.2"', manifest.read_text()))
        self.assertEqual(self.before, self.after())

    def test_a_changed_python_module_moves_it(self):
        (self.dir / "const.py").write_text((self.dir / "const.py").read_text() + "\nNEW = 1\n")
        self.assertNotEqual(self.before, self.after())

    def test_a_new_platform_moves_it(self):
        (self.dir / "light.py").write_text('"""A new platform."""\n')
        self.assertNotEqual(self.before, self.after())

    def test_what_core_reads_at_load_moves_it(self):
        for name, edit in (("services.yaml", "\n# changed\n"),
                           ("strings.json", " "),
                           ("translations/en.json", " ")):
            with self.subTest(file=name):
                path = self.dir / name
                original = path.read_text()
                path.write_text(original + edit)
                self.assertNotEqual(self.before, self.after())
                path.write_text(original)

    def test_a_manifest_field_core_reads_moves_it(self):
        manifest = self.dir / "manifest.json"
        manifest.write_text(manifest.read_text().replace('"recorder"', '"recorder",\n    "zone"'))
        self.assertNotEqual(self.before, self.after())

    def test_the_browsers_files_and_caches_leave_it(self):
        frontend = self.dir / "morph" / "frontend"
        (frontend / "shell.js").write_text((frontend / "shell.js").read_text() + "\n// changed\n")
        (frontend / "new-module.js").write_text("export {};\n")
        (self.dir / "brand" / "icon.png").write_bytes(b"\x89PNG not really")
        (self.dir / "__pycache__").mkdir(exist_ok=True)
        (self.dir / "__pycache__" / "const.cpython-313.pyc").write_bytes(b"\0")
        (self.dir / ".DS_Store.json").write_text("{}")
        self.assertEqual(self.before, self.after())

    def test_an_unreadable_folder_is_no_fingerprint(self):
        self.assertIsNone(FP.fingerprint(str(self.tmp / "nowhere")))


class TestTheVerdict(unittest.TestCase):
    """`integration_restart_verdict`, as every run.sh carries it."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.record = self.tmp / "integration.json"
        self.fn = shell_function(REPO / "brain" / "run.sh", "integration_restart_verdict")

    def verdict(self, src_fp: str) -> str:
        return shell(self.fn + '\nintegration_restart_verdict "$1" "$2"', src_fp, str(self.record)).strip()

    def test_the_same_code_loaded_is_no_restart(self):
        self.record.write_text(json.dumps({"version": "1.0.0", "fingerprint": "f1-aaaa"}))
        self.assertEqual("no", self.verdict("f1-aaaa"))

    def test_different_code_loaded_is_a_restart(self):
        self.record.write_text(json.dumps({"version": "1.0.0", "fingerprint": "f1-aaaa"}))
        self.assertEqual("needed", self.verdict("f1-bbbb"))

    def test_a_record_from_an_older_integration_is_a_restart_once(self):
        self.record.write_text(json.dumps({"version": "1.0.0"}))
        self.assertEqual("needed", self.verdict("f1-aaaa"))

    def test_nothing_recorded_is_a_restart(self):
        self.assertEqual("needed", self.verdict("f1-aaaa"))

    def test_an_unreadable_deploy_is_never_waved_through(self):
        self.record.write_text(json.dumps({"fingerprint": ""}))
        self.assertEqual("needed", self.verdict(""))


BASHIO_STUBS = r"""
bashio::log.info() { echo "INFO $*"; }
bashio::log.debug() { echo "DEBUG $*"; }
bashio::log.warning() { echo "WARN $*"; }
bashio::log.error() { echo "ERROR $*"; }
bashio::addon.version() { echo "9.9.9"; }
send_discovery_message() { :; }
curl() { printf '%s\n' "$*" >> "$CURL_LOG"; }
"""


@pytest.mark.slow
class TestBrainDeploy(unittest.TestCase):
    """brAIn's run.sh deploy, driven with its paths moved into a scratch
    folder: what it says, and the marker the integration and the panel
    read."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.src = self.tmp / "opt" / "brain"
        shutil.copytree(BRAIN_INTEGRATION, self.src, ignore=shutil.ignore_patterns("__pycache__"))
        self.config = self.tmp / "config"
        (self.config / ".brain").mkdir(parents=True)
        self.dest = self.config / "custom_components" / "brain"
        self.curl_log = self.tmp / "curl.log"
        run_sh = (REPO / "brain" / "run.sh").read_text()
        loaded_line = re.search(r"^INTEGRATION_LOADED_FILE=.*$", run_sh, re.M).group(0)
        parts = [BASHIO_STUBS, loaded_line] + [shell_function(REPO / "brain" / "run.sh", n) for n in (
            "integration_fingerprint", "integration_restart_verdict", "deploy_custom_integration",
            "notify_restart_required", "no_restart_needed")]
        script = "\n".join(parts).replace("/opt/custom_components/brain", str(self.src))
        self.script = script.replace("/config/", f"{self.config}/") + "\ndeploy_custom_integration\n"

    def deploy(self) -> str:
        done = subprocess.run(["bash", "-c", "set -e\nset -o pipefail\n" + self.script],
                              capture_output=True, text=True, timeout=60,
                              env={**os.environ, "CURL_LOG": str(self.curl_log),
                                   "SUPERVISOR_TOKEN": "t"})
        self.assertEqual(0, done.returncode, done.stderr + done.stdout)
        return done.stdout

    def install_running(self, version: str, fingerprint: str | None):
        """The integration already deployed at `version` and loaded by Core."""
        shutil.copytree(self.src, self.dest)
        manifest = self.dest / "manifest.json"
        manifest.write_text(re.sub(r'"version": "[^"]+"', f'"version": "{version}"', manifest.read_text()))
        record = {"version": version, "at": 1}
        if fingerprint:
            record["fingerprint"] = fingerprint
        (self.config / ".brain" / "integration_loaded.json").write_text(json.dumps(record))

    def marker(self) -> dict | None:
        path = self.config / ".brain" / "restart_required"
        return json.loads(path.read_text()) if path.exists() else None

    def src_version(self) -> str:
        return json.loads((self.src / "manifest.json").read_text())["version"]

    def test_a_version_only_update_asks_for_nothing(self):
        self.install_running("0.0.1", FP.fingerprint(str(self.src)))
        (self.config / ".brain" / "restart_required").write_text('{"required_version": "0.0.0"}')
        out = self.deploy()
        self.assertIn("no restart is needed", out)
        self.assertNotIn("needs a restart", out)
        self.assertIsNone(self.marker(), "a marker an earlier update left is stale and goes")
        record = json.loads((self.config / ".brain" / "integration_loaded.json").read_text())
        self.assertEqual(self.src_version(), record["version"], "the record takes the new version")
        self.assertEqual(self.src_version(), json.loads((self.dest / "manifest.json").read_text())["version"])
        # The running integration is told to take down a Repairs issue.
        self.assertIn("brain_restart_required", self.curl_log.read_text())

    def test_changed_python_asks_for_a_restart_with_its_fingerprint(self):
        self.install_running("0.0.1", "f1-0000000000000000")
        out = self.deploy()
        self.assertIn("Home Assistant needs a restart to load", out)
        marker = self.marker()
        self.assertEqual(self.src_version(), marker["required_version"])
        self.assertEqual(FP.fingerprint(str(self.src)), marker["fingerprint"])

    def test_an_older_integration_with_no_fingerprint_asks_once(self):
        self.install_running("0.0.1", None)
        out = self.deploy()
        self.assertIn("Home Assistant needs a restart to load", out)
        self.assertIsNotNone(self.marker())

    def test_a_fresh_install_asks_and_notifies(self):
        out = self.deploy()
        self.assertIn("First install", out)
        self.assertIsNotNone(self.marker())
        self.assertIn("persistent_notification/create", self.curl_log.read_text())

    def test_the_same_files_again_say_nothing(self):
        self.install_running(self.src_version(), FP.fingerprint(str(self.src)))
        out = self.deploy()
        self.assertIn("up to date", out)
        self.assertIsNone(self.marker())


class _Hass:
    def __init__(self, base: Path):
        self.calls: list = []
        outer = self

        class _Services:
            async def async_call(self, domain, service, data=None, **kw):
                outer.calls.append((domain, service, dict(data or {})))

        self.services = _Services()
        self.config = types.SimpleNamespace(path=lambda *parts: str(base.joinpath(*parts)))

    async def async_add_executor_job(self, fn, *args):
        return fn(*args)


class TestBrainIntegrationAndPanelAgree(unittest.TestCase):
    """The integration clears or raises the Repairs issue, the panel's
    verdict and Morph's banner read the same two files, by fingerprint."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / ".brain").mkdir()
        self.pkg = env.load_integration()
        self.pkg.ir = unittest.mock.MagicMock(name="issue_registry")
        self.pkg._LOADED_VERSION = "4.0.20"
        self.pkg._LOADED_FINGERPRINT = "f1-aaaaaaaaaaaaaaaa"
        self.hass = _Hass(self.tmp)

    def check(self):
        asyncio.run(self.pkg._check_restart_required(self.hass))

    def marker(self, **fields):
        (self.tmp / ".brain" / "restart_required").write_text(json.dumps(fields))

    def panel(self) -> dict:
        server = importlib.import_module("server")
        with unittest.mock.patch.object(server, "INTEGRATION_LOADED_FILE", self.tmp / ".brain" / "integration_loaded.json"), \
                unittest.mock.patch.object(server, "RESTART_MARKER_FILE", self.tmp / ".brain" / "restart_required"):
            return server._integration_versions()

    def morph_restart(self) -> bool:
        from test_morph_usage_and_names import _load_websocket
        return _load_websocket().restart_owed(self.tmp / ".brain")

    def test_the_same_code_under_a_newer_version_is_no_restart_anywhere(self):
        self.marker(required_version="4.0.21", fingerprint="f1-aaaaaaaaaaaaaaaa")
        self.check()
        self.pkg.ir.async_delete_issue.assert_called()
        self.pkg.ir.async_create_issue.assert_not_called()
        self.assertFalse((self.tmp / ".brain" / "restart_required").exists())
        versions = self.panel()
        self.assertFalse(versions["restart_pending"])
        self.assertEqual([], health._restart_owed({"versions": {"addon": "4.0.21", "integration": versions}}))
        self.assertFalse(self.morph_restart())

    def test_different_code_is_one_restart_everywhere(self):
        self.marker(required_version="4.0.21", fingerprint="f1-bbbbbbbbbbbbbbbb")
        self.check()
        self.pkg.ir.async_create_issue.assert_called_once()
        versions = self.panel()
        self.assertTrue(versions["restart_pending"])
        problems = health._restart_owed({"versions": {"addon": "4.0.21", "integration": versions}})
        self.assertEqual(["restart"], [p["id"] for p in problems])
        self.assertIn("needs a restart", problems[0]["what"])
        self.assertTrue(self.morph_restart())

    def test_a_marker_from_an_older_run_sh_falls_back_to_the_version(self):
        self.marker(required_version="4.0.21")
        self.check()
        self.pkg.ir.async_create_issue.assert_called_once()
        self.assertTrue(self.panel()["restart_pending"])
        self.assertTrue(self.morph_restart())

    def test_the_integration_records_its_fingerprint(self):
        self.check()
        record = json.loads((self.tmp / ".brain" / "integration_loaded.json").read_text())
        self.assertEqual("f1-aaaaaaaaaaaaaaaa", record["fingerprint"])
        self.assertEqual("4.0.20", record["version"])
        self.assertFalse(self.morph_restart(), "no marker is no restart")

    def test_the_version_run_sh_moved_on_is_kept_while_the_code_is_the_same(self):
        (self.tmp / ".brain" / "integration_loaded.json").write_text(
            json.dumps({"version": "4.0.21", "fingerprint": "f1-aaaaaaaaaaaaaaaa"}))
        self.check()
        record = json.loads((self.tmp / ".brain" / "integration_loaded.json").read_text())
        self.assertEqual("4.0.21", record["version"])

    def test_the_real_import_took_a_real_fingerprint(self):
        pkg = env.load_integration()
        self.assertEqual(FP.fingerprint(str(BRAIN_INTEGRATION)), pkg._LOADED_FINGERPRINT)

    def test_morphs_banner_follows_the_answer_not_the_add_on_version(self):
        js = (BRAIN_INTEGRATION / "morph" / "frontend" / "morph-panel.js").read_text()
        update = js[js.index("  updateHtml() {"):js.index("  region(name, html) {")]
        # The integration's answer when it sends one; the version only for an
        # integration from before it did (which is a release behind).
        self.assertIn("typeof d.restart === 'boolean' ? d.restart", update)


# ---------------------------------------------------------------- Bambu ----

def _bambu_panel():
    from bambu_env import load
    return load("ha_setup")[0]


class TestBambuPanelFollowsTheCode(unittest.TestCase):
    """BRUH Bambu Studio's panel is its one voice about a restart (the
    Printers tab, the banner, the notification): by fingerprint."""

    def setUp(self):
        self.ha_setup = _bambu_panel()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.deployed = self.tmp / "cc"
        shutil.copytree(integration_dir("bruh-bambu-studio"), self.deployed,
                        ignore=shutil.ignore_patterns("__pycache__"))
        manifest = self.deployed / "manifest.json"
        manifest.write_text(re.sub(r'"version": "[^"]+"', '"version": "0.5.0"', manifest.read_text()))
        (self.tmp / "shared").mkdir()
        for name, value in (("DEPLOYED", self.deployed), ("SHARED", self.tmp / "shared"),
                            ("NOTIFIED", self.tmp / "notified")):
            p = unittest.mock.patch.object(self.ha_setup, name, value)
            p.start()
            self.addCleanup(p.stop)
        e = unittest.mock.patch.dict(os.environ, {"SUPERVISOR_TOKEN": "t", "ENABLE_HA_INTEGRATION": "true"})
        e.start()
        self.addCleanup(e.stop)
        self.calls = []

        def call(method, path, body=None):
            self.calls.append((method, path, body))
            if path.startswith("/core/api/config/config_entries/entry"):
                return 200, [{"domain": "bruh_bambu", "state": "loaded", "entry_id": "e"}]
            return 200, []
        p = unittest.mock.patch.object(self.ha_setup, "_call", side_effect=call)
        p.start()
        self.addCleanup(p.stop)

    def running(self, **record):
        (self.tmp / "shared" / "integration.json").write_text(json.dumps(record))

    def test_a_version_only_update_owes_no_restart(self):
        self.running(version="0.4.9", fingerprint=FP.fingerprint(str(self.deployed)))
        state = self.ha_setup.check(force=True)
        self.assertFalse(state["restart_needed"])
        self.assertEqual("0.5.0", state["running"], "the same code is the deployed copy running")
        self.assertFalse([c for c in self.calls if "persistent_notification" in c[1]])

    def test_changed_code_is_a_restart_and_one_notification(self):
        self.running(version="0.4.9", fingerprint="f1-0000000000000000")
        state = self.ha_setup.check(force=True)
        self.assertTrue(state["restart_needed"])
        self.assertEqual("update", state["reason"])
        self.assertEqual(1, len([c for c in self.calls if "persistent_notification" in c[1]]))

    def test_a_record_from_an_older_integration_is_a_restart_once(self):
        self.running(version="0.4.9")
        self.assertTrue(self.ha_setup.check(force=True)["restart_needed"])


# ------------------------------------------------- the cards follow ----

class _StubFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Every `homeassistant…` and `voluptuous…` import answers with a module
    whose every attribute exists — enough to import an integration's
    package and drive one coroutine."""

    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in ("homeassistant", "voluptuous", "aiohttp"):
            return importlib.machinery.ModuleSpec(name, self, is_package=True)
        return None

    def create_module(self, spec):
        return _AutoModule(spec.name)

    def exec_module(self, module):
        module.__path__ = []


# The names an integration subclasses or raises: real classes, because a
# MagicMock can be neither.
_BASES = ("Coordinator", "Entity", "View", "Flow", "Error", "Exception", "Handler")


class _AutoModule(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        if name == "callback":
            return lambda func: func
        stub = type(name, (), {"__init__": lambda self, *a, **k: None,
                               "__class_getitem__": classmethod(lambda cls, item: cls)}) \
            if name.endswith(_BASES) else unittest.mock.MagicMock(name=f"{self.__name__}.{name}")
        setattr(self, name, stub)
        return stub


def load_stubbed(key: str):
    saved = dict(sys.modules)
    finder = _StubFinder()
    sys.meta_path.insert(0, finder)
    try:
        for name in [n for n in sys.modules if n.split(".")[0] in ("homeassistant", "voluptuous")]:
            del sys.modules[name]
        name = f"stubbed_{key.replace('-', '_')}"
        spec = importlib.util.spec_from_file_location(
            name, integration_dir(key) / "__init__.py",
            submodule_search_locations=[str(integration_dir(key))])
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.meta_path.remove(finder)
        sys.modules.clear()
        sys.modules.update(saved)


class _Frontend(types.ModuleType):
    def __init__(self):
        super().__init__("homeassistant.components.frontend")
        self.urls: list[str] = []
        self.add_extra_js_url = lambda hass, url: self.urls.append(url)
        self.remove_extra_js_url = lambda hass, url: self.urls.remove(url)


class _CardHass:
    async def async_add_executor_job(self, fn, *args):
        return fn(*args)


class TestCardsFollowTheirFile(unittest.TestCase):
    """A card-only update owes no restart, so its URL has to move without
    one: the registered URL follows the file's hash, and a page reload
    loads the new card."""

    def drive(self, key: str):
        module = load_stubbed(key)
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        card = tmp / "card.js"
        card.write_text("const CARD = 1;\n")
        frontend = _Frontend()
        hass = _CardHass()
        with unittest.mock.patch.object(module, "CARD_FILE", card), \
                unittest.mock.patch.dict(sys.modules, {"homeassistant.components.frontend": frontend}):
            module._CARD["url"] = None
            asyncio.run(module._follow_card(hass))
            self.assertEqual([], frontend.urls, "nothing registered is nothing to follow")
            module._CARD["url"] = module.card_url(card)
            frontend.urls.append(module._CARD["url"])
            asyncio.run(module._follow_card(hass))
            self.assertEqual([module.card_url(card)], frontend.urls, "an unchanged card stays")
            card.write_text("const CARD = 2;\n")
            asyncio.run(module._follow_card(hass))
        self.assertEqual([module.card_url(card)], frontend.urls)
        self.assertIn("?v=", frontend.urls[0])

    def test_bruh_print(self):
        self.drive("bruh-print")

    def test_bruh_bambu_studio(self):
        self.drive("bruh-bambu-studio")

    def test_gardenrx_puts_the_files_hash_on_its_url(self):
        module = load_stubbed("gardenrx")
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        card = tmp / "gardenrx-cards.js"
        card.write_text("one")
        first = module._cards_url(card, "/gardenrx_static/0.1.3")
        card.write_text("two")
        self.assertNotEqual(first, module._cards_url(card, "/gardenrx_static/0.1.3"))
        self.assertTrue(first.startswith("/gardenrx_static/0.1.3/gardenrx-cards.js?v="))
        self.assertIsNone(module._cards_url(tmp / "missing.js", "/x"))


class TestBambuCardRetryRunsOnTheLoop(unittest.TestCase):
    """The card retry handed `async_call_later` a plain lambda that called
    `hass.async_create_task`. Core runs a plain function in the executor, so
    that was a call off the event loop. The retry is a coroutine function
    now (Core awaits it on the loop), cancelled on shutdown."""

    def test_the_retry_is_awaited_on_the_loop_and_cancelled_on_shutdown(self):
        import inspect
        import threading

        module = load_stubbed("bruh-bambu-studio")
        scheduled = []

        class _Job:
            def __init__(self, target, name=None, *, cancel_on_shutdown=None):
                self.target, self.cancel_on_shutdown = target, cancel_on_shutdown

        seen = []

        async def register(hass, tries=0):
            seen.append((tries, threading.current_thread() is threading.main_thread()))

        with unittest.mock.patch.object(module, "HassJob", _Job), \
                unittest.mock.patch.object(module, "async_call_later",
                                  side_effect=lambda hass, delay, job: scheduled.append((delay, job))), \
                unittest.mock.patch.object(module, "_register_card", register):
            module._schedule_card_retry(_CardHass(), 2)
            self.assertEqual(1, len(scheduled))
            delay, job = scheduled[0]
            self.assertEqual(module.CARD_RETRY_SECONDS, delay)
            self.assertIsInstance(job, _Job, "a HassJob, so it can carry cancel_on_shutdown")
            self.assertTrue(job.cancel_on_shutdown)
            self.assertTrue(inspect.iscoroutinefunction(job.target),
                            "a plain function would be run in the executor")
            asyncio.run(job.target(None))
        self.assertEqual([(3, True)], seen, "the next try, awaited on the loop's thread")

    def test_a_missing_card_schedules_the_retry_this_way(self):
        module = load_stubbed("bruh-bambu-studio")
        with unittest.mock.patch.object(module, "CARD_FILE", Path(tempfile.gettempdir()) / "bruh-bambu-no-such-card.js"), \
                unittest.mock.patch.object(module, "_schedule_card_retry") as retry:
            asyncio.run(module._register_card(_CardHass()))
        retry.assert_called_once()
        source = (integration_dir("bruh-bambu-studio") / "__init__.py").read_text()
        self.assertNotIn("lambda _now: hass.async_create_task", source)


# ------------------------------------------- the siblings' run.sh ----

@pytest.mark.slow
class TestSiblingDeploysSayWhatIsTrue(unittest.TestCase):
    """Every sibling's deploy, driven: the log line says a restart only when
    the code Home Assistant loaded differs from the code deployed."""

    SIBLINGS = {
        "gardenrx": {"GARDENRX_HOME": "home", "GARDENRX_SHARED": "config/.gardenrx"},
        "bruh-cooking": {"COOKING_HOME": "home", "INTEGRATION": "bruh_cooking",
                         "COOKING_SHARED": "config/.bruh_cooking"},
        "bright": {"BRIGHT_HOME": "home"},
        "bruh-print": {"BRUH_PRINT_HOME": "home"},
        "bruh-task-manager": {"TASK_MANAGER_HOME": "home"},
        "bruh-minecraft-server": {},
    }

    def deploy(self, key: str, record: dict | None, *, bump: bool, edit: bool) -> str:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        domain = ADDONS[key][1]
        src = tmp / "home" / "custom_components" / domain
        shutil.copytree(integration_dir(key), src, ignore=shutil.ignore_patterns("__pycache__"))
        dst = tmp / "config" / "custom_components" / domain
        shutil.copytree(src, dst)
        loaded_fp = FP.fingerprint(str(dst))
        manifest = src / "manifest.json"
        if bump:
            manifest.write_text(re.sub(r'"version":\s*"[^"]+"', '"version": "99.0.0"', manifest.read_text()))
        if edit:
            (src / "const.py").write_text((src / "const.py").read_text() + "\nNEW = 1\n")
        shared = Path(ADDONS[key][2]).parent.name
        if record is not None:
            (tmp / "config" / shared).mkdir(parents=True, exist_ok=True)
            record = {k: (loaded_fp if v == "LOADED" else v) for k, v in record.items()}
            (tmp / "config" / shared / "integration.json").write_text(json.dumps(record))
        run_sh = REPO / ADDONS[key][0] / "run.sh"
        body = "\n".join(shell_function(run_sh, n) for n in (
            "integration_fingerprint", "integration_restart_verdict", "deploy_custom_integration"))
        body = body.replace("/opt/bruh-mc/", f"{tmp}/home/").replace("/config/", f"{tmp}/config/")
        exports = "".join(f'{k}="{tmp}/{v}"\n' if "/" in v or v == "home" else f'{k}="{v}"\n'
                          for k, v in self.SIBLINGS[key].items())
        script = BASHIO_STUBS + 'ENABLE_HA_INTEGRATION=true\n' + exports + body + "\ndeploy_custom_integration\n"
        done = subprocess.run(["bash", "-c", "set -o pipefail\n" + script], capture_output=True,
                              text=True, timeout=60, env={**os.environ, "CURL_LOG": str(tmp / "curl")})
        self.assertEqual(0, done.returncode, done.stderr)
        return done.stdout

    def test_a_version_only_update_says_no_restart(self):
        for key in self.SIBLINGS:
            with self.subTest(addon=key):
                out = self.deploy(key, {"fingerprint": "LOADED"}, bump=True, edit=False)
                self.assertIn("no restart is needed", out)
                self.assertNotIn("restart Home Assistant to load it", out)

    def test_changed_code_says_restart(self):
        for key in self.SIBLINGS:
            with self.subTest(addon=key):
                out = self.deploy(key, {"fingerprint": "LOADED"}, bump=True, edit=True)
                self.assertIn("restart Home Assistant to load it", out)

    def test_an_older_record_says_restart_once(self):
        for key in self.SIBLINGS:
            with self.subTest(addon=key):
                out = self.deploy(key, {"version": "0.0.1"}, bump=True, edit=False)
                self.assertIn("restart Home Assistant to load it", out)

    def test_nothing_changed_copies_nothing(self):
        for key in self.SIBLINGS:
            with self.subTest(addon=key):
                out = self.deploy(key, {"fingerprint": "LOADED"}, bump=False, edit=False)
                self.assertNotIn("Deployed", out)


if __name__ == "__main__":
    unittest.main()
