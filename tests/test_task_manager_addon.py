"""BRUH Task Manager's manifest, profile and integration mirror reader.

The Level 2 promise is made in three places — config.yaml asks for the host's
process list, apparmor.txt says what it may never read, and the panel's
option defaults say it starts off — and each is checked here against the
others, because a promise that holds in two of three places does not hold.
"""
import json
import os
import tempfile
import time
import unittest

import yaml

import task_manager_env

ROOT = os.path.join(os.path.dirname(__file__), "..", "bruh-task-manager")
INTEGRATION = os.path.join(ROOT, "custom_components", "bruh_task_manager")

(settings,) = task_manager_env.load("settings")


def read(*parts):
    with open(os.path.join(ROOT, *parts)) as handle:
        return handle.read()


def config():
    return yaml.safe_load(read("config.yaml"))


class TestManifest(unittest.TestCase):
    def test_level_two_is_asked_for_and_starts_off(self):
        cfg = config()
        self.assertTrue(cfg["host_pid"])
        self.assertFalse(cfg["options"]["process_view"])
        self.assertFalse(cfg["options"]["allow_ending_processes"])
        self.assertNotIn("full_access", cfg)
        self.assertNotIn("docker_api", cfg)
        self.assertNotIn("privileged", cfg)

    def test_no_port_is_published(self):
        self.assertFalse(config().get("ports"))
        self.assertTrue(config()["ingress"])
        self.assertTrue(config()["panel_admin"])

    def test_the_panels_defaults_are_the_manifests(self):
        cfg = config()
        self.assertEqual(set(cfg["options"]), set(settings.DEFAULTS))
        for key, value in cfg["options"].items():
            with self.subTest(option=key):
                self.assertEqual(value, settings.DEFAULTS[key])
        for key, (low, high) in settings.BOUNDS.items():
            with self.subTest(bound=key):
                self.assertEqual(f"int({low},{high})", cfg["schema"][key])

    def test_the_panel_can_change_only_what_takes_effect_live(self):
        self.assertNotIn("log_level", settings.EDITABLE)
        self.assertNotIn("enable_ha_integration", settings.EDITABLE)
        self.assertLessEqual(set(settings.EDITABLE), set(config()["options"]))

    def test_versions_agree(self):
        with open(os.path.join(INTEGRATION, "manifest.json")) as handle:
            manifest = json.load(handle)
        self.assertEqual(config()["version"], manifest["version"])
        self.assertIn(f"## {config()['version']}", read("CHANGELOG.md"))


class TestProfile(unittest.TestCase):
    def test_other_processes_secrets_are_denied(self):
        body = read("apparmor.txt")
        for rule in ("deny @{PROC}/*/environ", "deny @{PROC}/*/mem",
                     "deny @{PROC}/*/root/**", "deny capability sys_ptrace"):
            with self.subTest(rule=rule):
                self.assertIn(rule, body)

    def test_it_may_signal_and_read_proc(self):
        body = read("apparmor.txt")
        self.assertIn("capability kill,", body)
        self.assertIn("signal (send),", body)
        self.assertIn("@{PROC}/** r,", body)


class TestRunScript(unittest.TestCase):
    def test_it_deploys_the_integration_and_names_the_level(self):
        body = read("run.sh")
        self.assertIn("custom_components/bruh_task_manager", body)
        self.assertIn("protection_mode", body)
        self.assertIn('python3 -u "${PANEL_DIR}/server.py"', body)


class TestItStartsWithProtectionModeOff(unittest.TestCase):
    """Level 2 means the HOST's PID namespace, where this container is not PID 1.

    s6-overlay (the base image's /init) refuses to run anywhere but PID 1, so
    an add-on started through it dies the moment Protection mode is turned
    off: "s6-overlay-suexec: fatal: can only run as pid 1", seen on a real
    install. run.sh is the entrypoint, and nothing in it may need s6.
    """

    def test_the_entrypoint_is_run_sh_not_s6(self):
        lines = [line.strip() for line in read("Dockerfile").splitlines()
                 if line.strip() and not line.strip().startswith("#")]
        self.assertIn('ENTRYPOINT ["/run.sh"]', lines)
        self.assertEqual(False, config()["init"])

    def test_run_sh_does_not_need_s6s_environment(self):
        first = read("run.sh").splitlines()[0]
        self.assertEqual("#!/usr/bin/env bashio", first)
        self.assertNotIn("with-contenv", read("run.sh"))

    def _protection(self, *, new_name: bool, answer: str) -> str:
        import re
        import subprocess
        body = read("run.sh")
        fn = re.search(r"^protection_mode\(\) \{.*?^\}", body, re.S | re.M).group(0)
        name = "bashio::app.protected" if new_name else "bashio::addon.protected"
        script = f"{name}() {{ echo {answer}; }}\n{fn}\nprotection_mode\n"
        return subprocess.run(["bash", "-c", script], capture_output=True,
                              text=True, check=True).stdout.strip()

    def test_protection_is_read_by_the_new_name_where_bashio_has_it(self):
        self.assertEqual("false", self._protection(new_name=True, answer="false"))

    def test_an_older_bashio_is_asked_by_the_old_name(self):
        self.assertEqual("true", self._protection(new_name=False, answer="true"))


class TestTheMirrorReader(unittest.TestCase):
    """custom_components/bruh_task_manager/mirror.py imports nothing from HA."""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "bruh_task_manager_mirror", os.path.join(INTEGRATION, "mirror.py"))
        cls.mirror = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mirror)

    def write(self, data, age=0):
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump(data, handle)
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        when = time.time() - age
        os.utime(handle.name, (when, when))
        return handle.name

    def test_a_fresh_file_is_available(self):
        path = self.write({"stale_after_s": 60, "busiest": {"name": "X"}})
        self.assertTrue(self.mirror.read(path)["available"])

    def test_staleness_is_the_files_age_against_its_own_window(self):
        path = self.write({"stale_after_s": 60, "generated_at": time.time() + 99999}, age=120)
        result = self.mirror.read(path)
        self.assertFalse(result["available"])
        self.assertIn("may be stopped", result["reason"])

    def test_missing_and_garbage_say_why(self):
        self.assertIn("not started", self.mirror.read("/nonexistent/state.json")["reason"])
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        handle.write("{not json")
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        self.assertFalse(self.mirror.read(handle.name)["available"])


if __name__ == "__main__":
    unittest.main()
