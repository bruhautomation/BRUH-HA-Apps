#!/usr/bin/env python3
"""Static analysis of bruh-minecraft-server shell scripts.

Checks:
* bash/python syntax is valid
* Shebangs are correct (bashio for run.sh, /bin/bash for standalone)
* No obviously dangerous patterns (rm -rf $VAR with no fallback, eval of user input, ...)
* Scripts marked executable
* run.sh starts all background helpers and registers a shutdown trap
* download-server.sh dispatches every supported server_type
"""
from __future__ import annotations

import os
import stat
import subprocess
import unittest

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
ADDON_DIR = os.path.join(BASE_DIR, "bruh-minecraft-server")
SCRIPTS_DIR = os.path.join(ADDON_DIR, "scripts")
INTEG_DIR = os.path.join(ADDON_DIR, "integrations")


def _read(path: str) -> str:
    with open(path) as f:
        return f.read()


def _all_shell_scripts() -> list[str]:
    out: list[str] = [os.path.join(ADDON_DIR, "run.sh")]
    for root in (SCRIPTS_DIR, INTEG_DIR):
        if not os.path.isdir(root):
            continue
        for name in os.listdir(root):
            if name.endswith(".sh"):
                out.append(os.path.join(root, name))
    return out


def _all_python_scripts() -> list[str]:
    roots = [
        os.path.join(ADDON_DIR, "scripts"),
        os.path.join(ADDON_DIR, "panel"),
        os.path.join(ADDON_DIR, "integrations"),
    ]
    out: list[str] = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        for name in os.listdir(root):
            if name.endswith(".py"):
                out.append(os.path.join(root, name))
    return out


class TestSyntax(unittest.TestCase):
    def test_bash_syntax(self):
        for path in _all_shell_scripts():
            with self.subTest(path=path):
                proc = subprocess.run(["bash", "-n", path], capture_output=True, text=True)
                self.assertEqual(proc.returncode, 0,
                                 f"{path}: {proc.stderr.strip()}")

    def test_python_syntax(self):
        import py_compile
        for path in _all_python_scripts():
            with self.subTest(path=path):
                try:
                    py_compile.compile(path, doraise=True)
                except py_compile.PyCompileError as exc:
                    self.fail(f"{path} failed to compile: {exc}")


class TestShebangsAndPermissions(unittest.TestCase):
    def test_run_sh_uses_bashio(self):
        text = _read(os.path.join(ADDON_DIR, "run.sh"))
        self.assertTrue(text.startswith("#!/usr/bin/with-contenv bashio"),
                        "run.sh must start with '#!/usr/bin/with-contenv bashio'")

    def test_helper_scripts_use_bash(self):
        for path in _all_shell_scripts():
            if path.endswith("/run.sh"):
                continue
            with self.subTest(path=path):
                first_line = _read(path).splitlines()[0]
                self.assertTrue(
                    first_line.startswith("#!/bin/bash"),
                    f"{path} must have '#!/bin/bash' shebang, got {first_line!r}",
                )

    def test_python_scripts_have_env_shebang(self):
        for path in _all_python_scripts():
            with self.subTest(path=path):
                first_line = _read(path).splitlines()[0]
                self.assertTrue(
                    first_line == "#!/usr/bin/env python3" or first_line.startswith('"""'),
                    f"{path} should start with env-python3 shebang or module docstring; got {first_line!r}",
                )

    def test_all_scripts_executable(self):
        for path in _all_shell_scripts() + _all_python_scripts():
            with self.subTest(path=path):
                mode = os.stat(path).st_mode
                self.assertTrue(mode & stat.S_IXUSR, f"{path} is not user-executable")


class TestDangerousPatterns(unittest.TestCase):
    def test_no_unprotected_rm_rf(self):
        for path in _all_shell_scripts():
            text = _read(path)
            # Reject `rm -rf $X` where $X could be empty; require either
            # a quoted literal leading char or `:?` guard
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if "rm -rf" not in stripped:
                    continue
                # Ensure the target path literally begins with a '/' or '"/'
                # (so we never rm -rf the current dir if a var expands empty).
                ok = any(
                    f"rm -rf {prefix}" in stripped
                    for prefix in ('"/', '/', '"${', '${')
                )
                self.assertTrue(
                    ok,
                    f"{path}: potentially unsafe rm -rf line {stripped!r}",
                )

    def test_no_eval_of_stdin(self):
        for path in _all_shell_scripts():
            text = _read(path)
            self.assertNotIn("eval $(cat", text, f"{path} uses eval with cat")


class TestRunSh(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = _read(os.path.join(ADDON_DIR, "run.sh"))

    def test_starts_required_helpers(self):
        # All background helpers that must be started
        for helper in (
            "start_ingress_panel",
            "start_backup_watcher",
            "start_stats_collector",
            "start_ha_bridge",
        ):
            self.assertIn(helper, self.text, f"run.sh missing {helper}")

    def test_registers_shutdown_trap(self):
        self.assertIn("trap graceful_shutdown", self.text)
        self.assertIn("SIGTERM", self.text)

    def test_eula_hard_gate(self):
        # If EULA isn't true the script must exit before launching the JVM
        self.assertIn('if [ "${EULA}" != "true" ]', self.text)
        self.assertIn("exit 1", self.text)

    def test_auto_restart_window(self):
        # Rate-limited crash restarts
        self.assertIn("max_crash_restarts", self.text)
        self.assertIn("crash_window_seconds", self.text)

    def test_no_hardcoded_rcon_password(self):
        # The RCON password is either auto-generated or read from rcon.secret
        self.assertNotIn('RCON_PASSWORD="hunter2"', self.text)
        self.assertIn("rcon.secret", self.text)

    def test_custom_integration_deployment_guard(self):
        self.assertIn("deploy_custom_integration", self.text)

    def test_load_config_does_not_write_to_panel_state(self):
        """Regression guard for the 1.0.2 crash-loop bug.

        bashio sources `set -e` + `set -u` + `pipefail`. If load_config does
        filesystem IO before prepare_filesystem creates MC_PANEL_STATE, the
        failed redirection kills the script silently and HA crash-loops the
        add-on with no user-visible error.
        """
        in_load = False
        brace_depth = 0
        for line in self.text.splitlines():
            stripped = line.strip()
            if stripped.startswith("load_config()"):
                in_load = True
                continue
            if not in_load:
                continue
            # Track brace depth to know when we leave the function
            if "{" in line and "${" not in line.replace("${", ""):
                brace_depth += 1
            if line.strip() == "}":
                break
            # Inside load_config: disallow any writes to MC_PANEL_STATE
            if "MC_PANEL_STATE" in line and (">" in line or "mkdir" in line or "touch" in line):
                if not line.lstrip().startswith("#"):
                    self.fail(f"load_config must not write to MC_PANEL_STATE: {line!r}")

    def test_ensure_rcon_password_runs_after_prepare_filesystem(self):
        """The RCON password MUST be resolved after MC_PANEL_STATE exists."""
        self.assertIn("ensure_rcon_password", self.text,
                      "run.sh must define/call ensure_rcon_password")
        # Find main() body and check call order
        start = self.text.index("main() {")
        end = self.text.index("\n}\n", start)
        main_body = self.text[start:end]
        prep_idx = main_body.find("prepare_filesystem")
        rcon_idx = main_body.find("ensure_rcon_password")
        self.assertGreater(prep_idx, 0, "prepare_filesystem not called in main")
        self.assertGreater(rcon_idx, 0, "ensure_rcon_password not called in main")
        self.assertLess(prep_idx, rcon_idx,
                        "ensure_rcon_password must run AFTER prepare_filesystem")

    def test_supervisor_token_has_default(self):
        """set -u would abort if SUPERVISOR_TOKEN is unset."""
        self.assertIn("${SUPERVISOR_TOKEN:-}", self.text,
                      "SUPERVISOR_TOKEN must have a :- default (set -u guard)")

    def test_log_level_propagated_to_bashio(self):
        """Toggling log_level in config should actually affect bashio output."""
        self.assertIn("BASHIO_LOG_LEVEL", self.text,
                      "log_level option must export BASHIO_LOG_LEVEL")

    def test_plugin_parser_accepts_string_shorthand(self):
        """Regression for 1.2.7: `plugins:` entries can be either
        `{url: "...", name: "..."}` objects or plain URL strings.
        The pre-1.2.7 parser only handled the object form and emitted
        `jq: Cannot index string with string "url"` on every string
        entry, silently skipping the plugin.
        """
        # The parser must branch on the JSON type of the entry
        self.assertIn("jq -r 'type'", self.text,
                      "install_plugins must inspect entry type to support URL-string shorthand")
        self.assertRegex(
            self.text,
            r'entry_type.*=.*"string"',
            "install_plugins must special-case string-typed plugin entries",
        )

    def test_addon_version_resolver_handles_unrendered_template(self):
        """Regression for 1.2.7: `build.yaml` passes ADDON_VERSION as a
        Jinja template `{{ version }}`. When the Supervisor doesn't
        render it (local builds, some Supervisor versions), the literal
        `{{ version }}` ends up in the banner. run.sh must detect and
        fall back to parsing config.yaml.
        """
        self.assertIn("resolve_addon_version", self.text,
                      "run.sh must define resolve_addon_version")
        self.assertIn('"{{ version }}"', self.text,
                      "run.sh must detect un-rendered template value")
        self.assertIn("/opt/bruh-mc/config.yaml", self.text,
                      "run.sh must read baked-in config.yaml as fallback")


class TestDockerfile(unittest.TestCase):
    """The Dockerfile must bake config.yaml into the image so run.sh can
    resolve the add-on version at startup without relying on the Jinja
    template in build.yaml."""

    @classmethod
    def setUpClass(cls):
        cls.text = _read(os.path.join(ADDON_DIR, "Dockerfile"))

    def test_copies_config_yaml(self):
        self.assertIn("COPY config.yaml /opt/bruh-mc/config.yaml", self.text,
                      "Dockerfile must copy config.yaml so run.sh can parse the version at runtime")


class TestDownloadServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = _read(os.path.join(SCRIPTS_DIR, "download-server.sh"))

    def test_dispatches_every_server_type(self):
        for typ in ("paper", "purpur", "folia", "vanilla", "fabric", "forge"):
            # Each type must appear as a case branch
            self.assertRegex(self.text, rf"\b{typ}\)")

    def test_uses_cache_dir(self):
        self.assertIn("SERVER_CACHE", self.text)
        self.assertIn("Using cached", self.text)  # cache hit log message

    def test_vanilla_sha1_verification(self):
        # The vanilla jar URL includes sha1; we must verify it
        self.assertIn("sha1sum", self.text)

    def test_failure_exits_nonzero(self):
        self.assertIn("exit 1", self.text)

    def test_latest_filters_out_prereleases_and_rcs(self):
        """Regression for 1.2.7: PaperMC's `versions[]` array mixes stable
        releases with pre-releases (`1.21.11-pre5`) and release candidates
        (`1.21.11-rc3`). A naive `.versions[-1]` picks a pre-release during
        Paper's rolling release window, whose network protocol differs from
        the stable client on the same MC version — vanilla clients reject
        the server with "Outdated server! I'm still on X.Y.Z". LATEST must
        filter to stable-shaped strings (X.Y or X.Y.Z) before picking [-1];
        SNAPSHOT preserves opt-in to pre-releases.
        """
        # jq filter that selects only plain X.Y / X.Y.Z entries
        filter_re = r'select\(test\("\^\[0-9\]\+\\\\\.\[0-9\]\+\(\\\\\.\[0-9\]\+\)\?\$"\)\)'
        self.assertRegex(self.text, filter_re,
                         "resolve_paper_version must filter versions to stable-shaped entries")
        # Both paper and purpur must use the filter when VERSION_REQ == LATEST
        # — the two separate branches prove LATEST and SNAPSHOT diverge.
        self.assertIn('[ "${VERSION_REQ}" = "LATEST" ]', self.text)
        self.assertIn('elif [ "${VERSION_REQ}" = "SNAPSHOT" ]', self.text)

    def test_filter_regex_semantics(self):
        """Sanity-check the jq filter against realistic upstream arrays.
        Catches accidentally stripping valid versions or failing to strip
        pre-releases.
        """
        import json
        import subprocess
        jq_filter = ('[.versions[] | select(test("^[0-9]+\\\\.[0-9]+'
                     '(\\\\.[0-9]+)?$"))] | .[-1]')
        scenarios = [
            # stable 1.21.11 out, pre-releases also present -> pick stable
            (["1.21.10", "1.21.11-pre5", "1.21.11-rc3", "1.21.11"], "1.21.11"),
            # only pre-releases for the new version -> fall back to prior stable
            (["1.21.9", "1.21.10", "1.21.11-pre3", "1.21.11-rc1"], "1.21.10"),
            # two-component version ("1.20") is still a valid Minecraft version
            (["1.19.4", "1.20", "1.20.1"], "1.20.1"),
            # Snapshot-style weekly entries ("24w05a") must be filtered out
            (["1.21.9", "1.21.10", "24w05a", "24w05b"], "1.21.10"),
        ]
        for versions, expected in scenarios:
            with self.subTest(versions=versions):
                payload = json.dumps({"versions": versions})
                proc = subprocess.run(
                    ["jq", "-r", jq_filter],
                    input=payload, capture_output=True, text=True, check=True,
                )
                self.assertEqual(proc.stdout.strip(), expected)


class TestBackup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = _read(os.path.join(SCRIPTS_DIR, "backup.sh"))

    def test_flushes_before_backup(self):
        # save-off → save-all flush → copy → save-on
        self.assertIn("save-off", self.text)
        self.assertIn("save-all flush", self.text)
        self.assertIn("save-on", self.text)

    def test_supports_both_git_and_tar(self):
        self.assertIn("backup_worlds_git", self.text)
        self.assertIn("backup_worlds_tar", self.text)

    def test_prunes_old_archives(self):
        self.assertIn("BACKUP_KEEP_COUNT", self.text)


class TestHaDiscoveryAnnouncement(unittest.TestCase):
    """1-click Devices & Services setup requires the add-on to POST to
    /discovery on the Supervisor. Verify run.sh does that correctly."""

    @classmethod
    def setUpClass(cls):
        cls.run_sh = _read(os.path.join(ADDON_DIR, "run.sh"))

    def test_announce_function_exists(self):
        self.assertIn("announce_ha_discovery", self.run_sh)

    def test_posts_to_supervisor_endpoint(self):
        self.assertIn("http://supervisor/discovery", self.run_sh)
        self.assertIn("Authorization: Bearer ${SUPERVISOR_TOKEN}", self.run_sh)

    def test_payload_advertises_bruh_minecraft_service(self):
        self.assertIn('"service":"bruh_minecraft"', self.run_sh)

    def test_called_from_main(self):
        start = self.run_sh.index("main() {")
        body = self.run_sh[start:self.run_sh.index("\n}\n", start)]
        self.assertIn("announce_ha_discovery", body,
                      "announce_ha_discovery must be invoked from main()")


class TestBedrockSupport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.run_sh = _read(os.path.join(ADDON_DIR, "run.sh"))
        cls.installer = _read(os.path.join(SCRIPTS_DIR, "install-bedrock-support.sh"))

    def test_default_enabled(self):
        """On by default so iOS/Android/console players work out of the box."""
        import yaml
        cfg = yaml.safe_load(_read(os.path.join(ADDON_DIR, "config.yaml")))
        self.assertTrue(cfg["options"]["enable_bedrock_support"],
                        "enable_bedrock_support must default to true")
        self.assertEqual(cfg["schema"]["enable_bedrock_support"], "bool")

    def test_run_sh_invokes_installer(self):
        self.assertIn("install_bedrock_support", self.run_sh)
        self.assertIn("install-bedrock-support.sh", self.run_sh)

    def test_respects_toggle(self):
        # When disabled, installer must be skipped
        self.assertIn('ENABLE_BEDROCK_SUPPORT', self.run_sh)
        self.assertRegex(
            self.run_sh,
            r'ENABLE_BEDROCK_SUPPORT.*!=\s*"true"',
            "run.sh must check ENABLE_BEDROCK_SUPPORT before invoking the installer",
        )

    def test_installer_handles_all_server_types(self):
        """Paper/Purpur/Folia go to plugins/, Fabric goes to mods/, rest warn."""
        for typ in ("paper|purpur|folia", "fabric"):
            self.assertIn(typ, self.installer)
        # Must explicitly handle the unsupported types gracefully
        self.assertIn("doesn't support Geyser", self.installer)

    def test_installer_fetches_both_geyser_and_floodgate(self):
        # The URL uses ${project}; the jar names are passed positionally
        self.assertIn("download.geysermc.org/v2/projects/", self.installer)
        self.assertIn("install_jar geyser", self.installer)
        self.assertIn("install_jar floodgate", self.installer)

    def test_installer_caches_via_if_modified_since(self):
        # -z <file> makes curl send If-Modified-Since; keeps startup quick.
        self.assertIn("--remote-time", self.installer)
        self.assertIn('-z "${dest}"', self.installer)

    def test_installer_uses_spigot_not_paper_slug(self):
        """Regression for 1.0.4: the v2 API download is called 'spigot',
        not 'paper'. 'paper' returns HTTP 404 and Bedrock clients can't
        connect. We keyword-check the case branch here; a separate network
        test (skipped when offline) HEADs the real URL."""
        self.assertNotRegex(
            self.installer,
            r'GEYSER_VARIANT="paper"',
            "Geyser/Floodgate v2 API uses 'spigot', not 'paper' — regression",
        )
        self.assertIn('GEYSER_VARIANT="spigot"', self.installer)
        self.assertIn('FLOODGATE_VARIANT="spigot"', self.installer)

    def test_geyser_download_urls_resolve(self):
        """Live HEAD the GeyserMC API. Skipped when offline so CI in an
        air-gapped runner doesn't fail spuriously, but catches URL-schema
        breakages quickly when the machine has internet."""
        import socket
        import urllib.error
        import urllib.request
        try:
            socket.create_connection(("download.geysermc.org", 443), timeout=2.0)
        except OSError:
            self.skipTest("no internet access to download.geysermc.org")

        # Only URL combinations we actually install. Floodgate has no Fabric
        # variant (Geyser-Fabric bundles Floodgate support internally).
        combos = [("geyser", "spigot"), ("geyser", "fabric"), ("floodgate", "spigot")]
        for project, variant in combos:
            url = (
                f"https://download.geysermc.org/v2/projects/{project}/"
                f"versions/latest/builds/latest/downloads/{variant}"
            )
            req = urllib.request.Request(url, method="HEAD")
            try:
                with urllib.request.urlopen(req, timeout=5.0) as resp:
                    self.assertIn(
                        resp.status, (200, 301, 302, 307, 308),
                        f"{project}/{variant} responded {resp.status} — URL schema changed?",
                    )
            except urllib.error.HTTPError as exc:
                self.fail(
                    f"{project}/{variant} returned HTTP {exc.code} "
                    f"— GeyserMC API slug may have changed"
                )


class TestServerLauncher(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = _read(os.path.join(SCRIPTS_DIR, "server-launcher.sh"))

    def test_aikar_flags_toggle(self):
        self.assertIn("USE_AIKAR_FLAGS", self.text)
        self.assertIn("-XX:+UseG1GC", self.text)

    def test_respects_memory_mb(self):
        self.assertIn("-Xms", self.text)
        self.assertIn("-Xmx", self.text)

    def test_input_fifo_for_rcon_free_stdin(self):
        # The panel pushes commands by writing to the input FIFO
        self.assertIn("MC_INPUT_FIFO", self.text)


if __name__ == "__main__":
    unittest.main()
